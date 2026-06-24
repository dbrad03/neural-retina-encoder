#!/usr/bin/env python3
"""
first_light.py - Phase 3 hardware bringup for the Science Eye retina on PYNQ.

Goal: prove the full datapath on real silicon with ZERO camera variables.
  file/synthetic image -> PL pixel RAM -> trigger frame -> POLL done
  -> drain spike FIFO -> stream stimulus + spikes over UDP to bci_visualizer.

This deliberately uses POLLING (not UIO interrupts) so first light does not
depend on a device-tree UIO node (that comes in Phase 4 / uio_retina.dts).

Register map (from hdl/axi_retina_wrapper.sv, verified against system.hwh):
  Retina IP base 0x40000000, 0x20000 span
    0x00000 : pixel RAM, 32-bit words, low 18 bits = Q8.10 (one word per neuron)
    0x10000 : control/status
              write: bit0=start_frame, bit1=clear frame_done, bit2=clear overflow
              read : bit0=start, bit1=frame_done, bit2=overflow_seen
  AXI-Stream FIFO base 0x43C00000 (Xilinx axi_fifo_mm_s)
    0x1C RDFO : receive occupancy IN WORDS  (NOT bytes -> do not /4)
    0x20 RDFD : receive data
    0x24 RLR  : receive length in bytes (valid once a TLAST packet is present).
                The stream asserts one TLAST per frame, so we drain by reading
                RLR for the packet's byte length -- but ONLY when RDFO>0, since
                RLR on an empty FIFO returns SLVERR/SIGBUS.

Usage:
    sudo python3 first_light.py <host_ip> [image.png]
"""
import sys
import time
import socket
import struct

import numpy as np

try:
    from pynq import Overlay, MMIO
except ImportError:
    print("This script must run on the PYNQ board (pynq package not found).")
    sys.exit(1)

# ---- Address map -----------------------------------------------------------
RETINA_BASE = 0x40000000
RETINA_SPAN = 0x20000
FIFO_BASE   = 0x43C00000
FIFO_SPAN   = 0x10000

OFF_PIXEL_RAM = 0x00000
OFF_CONTROL   = 0x10000

CTRL_START      = 0x1
CTRL_CLEAR_DONE = 0x2
CTRL_CLEAR_OVF  = 0x4
STAT_DONE       = 0x2
STAT_OVERFLOW   = 0x4

FIFO_RDFR = 0x18   # receive reset
FIFO_RDFO = 0x1C   # receive occupancy (words)
FIFO_RDFD = 0x20   # receive data
FIFO_RLR  = 0x24   # receive length (bytes)

GRID = 128
NUM_NEURONS = GRID * GRID

UDP_PORT = 8080
PKT_IMAGE = 2
PKT_SPIKE = 1


def make_stimulus(path=None):
    """Return a 128x128 uint8 grayscale frame."""
    if path:
        try:
            from PIL import Image
            img = Image.open(path).convert("L").resize((GRID, GRID))
            return np.asarray(img, dtype=np.uint8)
        except Exception as e:
            print(f"Could not load {path} ({e}); using synthetic pattern.")
    # Synthetic: bright diamond on the fovea + radial gradient. Exercises both
    # the foveal (midget) center and peripheral (parasol) regions.
    yy, xx = np.mgrid[0:GRID, 0:GRID]
    diamond = (np.abs(xx - 64) + np.abs(yy - 64)) < 45
    grad = (255 * (1 - (np.hypot(xx - 64, yy - 64) / 90))).clip(0, 255)
    frame = grad.astype(np.uint8)
    frame[diamond] = 255
    return frame


def to_q8_10(frame):
    """Match the driver's intensity mapping: (val/10.0)*1024 = val*102.4."""
    return (frame.astype(np.float32) * 102.4).astype(np.uint32)


def main():
    if len(sys.argv) < 2:
        print(f"Usage: sudo python3 {sys.argv[0]} <host_ip> [image.png]")
        sys.exit(1)
    host_ip = sys.argv[1]
    img_path = sys.argv[2] if len(sys.argv) > 2 else None

    print("Loading overlay retina.bit ...")
    Overlay("retina.bit")  # configures PL + clocks from retina.hwh (cwd-relative)

    retina = MMIO(RETINA_BASE, RETINA_SPAN)
    fifo = MMIO(FIFO_BASE, FIFO_SPAN)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    addr = (host_ip, UDP_PORT)

    frame = make_stimulus(img_path)
    q = to_q8_10(frame)

    # 1. Write pixels to PL BRAM (one 32-bit word per neuron).
    print("Writing 16384 pixels to PL pixel RAM ...")
    for i in range(NUM_NEURONS):
        retina.write(OFF_PIXEL_RAM + i * 4, int(q.flat[i]))

    # 2. Send the stimulus image to the visualizer (type 2 packet).
    sock.sendto(bytes([PKT_IMAGE]) + frame.tobytes(), addr)

    # 3. Reset the FIFO receive side so we start clean.
    fifo.write(FIFO_RDFR, 0x000000A5)

    # 4. Run MANY frames. Each frame advances every neuron by ONE Izhikevich
    #    timestep; v/u state persists in BRAM between frames, so neurons integrate
    #    over successive frames and only cross threshold after a warm-up. A single
    #    frame never spikes -- that is physics, not a bug.
    n_frames = int(sys.argv[3]) if len(sys.argv) > 3 else 500
    print(f"Running {n_frames} frames (each = one Izhikevich timestep) ...")
    total_spikes = 0
    first_spike_frame = None
    t_start = time.perf_counter()

    for f in range(n_frames):
        # Trigger a frame: bit0 start (re-pulses), bit1 clears previous done.
        retina.write(OFF_CONTROL, CTRL_START | CTRL_CLEAR_DONE)

        # Poll for frame_done.
        timeout = time.perf_counter() + 1.0
        while not (retina.read(OFF_CONTROL) & STAT_DONE):
            if time.perf_counter() > timeout:
                print(f"TIMEOUT waiting for frame_done at frame {f}.")
                return

        # The closing TLAST fires a few us AFTER frame_done (last spikes still
        # draining), so the packet commits slightly late. Wait briefly for it
        # before draining -- and crucially before the next trigger, which would
        # clear frame_complete and cut off a pending TLAST.
        occ = fifo.read(FIFO_RDFO)
        commit_deadline = time.perf_counter() + 0.003
        while occ == 0 and time.perf_counter() < commit_deadline:
            occ = fifo.read(FIFO_RDFO)

        # Drain this frame's spike packet (one TLAST packet/frame).
        if occ:
            nwords = fifo.read(FIFO_RLR) // 4   # RLR safe only when RDFO>0
            if first_spike_frame is None:
                first_spike_frame = f
            for _ in range(nwords):
                addr16 = fifo.read(FIFO_RDFD) & 0xFFFF
                sock.sendto(struct.pack("BBB", PKT_SPIKE,
                                        (addr16 >> 8) & 0xFF, addr16 & 0xFF), addr)
            total_spikes += nwords

        if f % 50 == 0:
            print(f"  frame {f:4d}: total spikes so far = {total_spikes}")

    dt = time.perf_counter() - t_start
    fps = n_frames / dt if dt else 0
    print(f"Done. {n_frames} frames in {dt:.2f}s ({fps:.0f} fps), "
          f"{total_spikes} spikes total; first spike at frame {first_spike_frame}.")
    if total_spikes == 0:
        print("Still zero spikes after warm-up -> investigate (TLAST / state init).")


if __name__ == "__main__":
    main()
