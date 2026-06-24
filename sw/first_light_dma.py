#!/usr/bin/env python3
"""
first_light_dma.py - DMA stimulus-input bringup for the Science Eye retina.

Same proof as first_light.py, but the per-pixel AXI-Lite write loop (16,384
single-beat /dev/mem stores per frame) is replaced by ONE AXI DMA MM2S burst:

  file/synthetic image -> PYNQ contiguous buffer -> AXI DMA MM2S ->
  axis_pixel_ingress -> PL pixel BRAM -> trigger frame -> POLL done ->
  drain spike FIFO -> stream stimulus + spikes over UDP to bci_visualizer.

Requires the DMA-enabled overlay (vivado/build_bd.tcl with the axi_dma_0 block
+ S_AXI_HP0; axi_retina_wrapper built with USE_DMA_INGRESS=1). The legacy
AXI-Lite pixel-write path still works on this overlay (DMA just has priority on
the shared BRAM port), so first_light.py remains a valid fallback.

Status register (read at control offset 0x10000):
  bit0 start, bit1 frame_done, bit2 overflow,
  bit3 dma_frame_loaded, bit4 dma_err_short, bit5 dma_err_long

Usage:
    sudo python3 first_light_dma.py <host_ip> [image.png] [n_frames]
"""
import sys
import time
import socket
import struct

import numpy as np

try:
    from pynq import Overlay, MMIO, allocate
except ImportError:
    print("This script must run on the PYNQ board (pynq package not found).")
    sys.exit(1)

# ---- Address map (control/FIFO via MMIO; pixels go through the DMA) ---------
RETINA_BASE = 0x40000000
RETINA_SPAN = 0x20000
FIFO_BASE   = 0x43C00000
FIFO_SPAN   = 0x10000

OFF_CONTROL = 0x10000

CTRL_START      = 0x1
CTRL_CLEAR_DONE = 0x2
CTRL_CLEAR_OVF  = 0x4
STAT_DONE        = 0x2
STAT_DMA_LOADED  = 0x8
STAT_DMA_SHORT   = 0x10
STAT_DMA_LONG    = 0x20

FIFO_RDFR = 0x18
FIFO_RDFO = 0x1C   # receive occupancy (words)
FIFO_RDFD = 0x20   # receive data
FIFO_RLR  = 0x24   # receive length (bytes), valid only when RDFO>0

GRID = 128
NUM_NEURONS = GRID * GRID

UDP_PORT = 8080
PKT_IMAGE = 2
PKT_SPIKE = 1

BIT_PATH = "retina.bit"


def make_stimulus(path=None):
    """Return a 128x128 uint8 grayscale frame (diamond on fovea + gradient)."""
    if path:
        try:
            from PIL import Image
            img = Image.open(path).convert("L").resize((GRID, GRID))
            return np.asarray(img, dtype=np.uint8)
        except Exception as e:
            print(f"Could not load {path} ({e}); using synthetic pattern.")
    yy, xx = np.mgrid[0:GRID, 0:GRID]
    diamond = (np.abs(xx - 64) + np.abs(yy - 64)) < 45
    grad = (255 * (1 - (np.hypot(xx - 64, yy - 64) / 90))).clip(0, 255)
    frame = grad.astype(np.uint8)
    frame[diamond] = 255
    return frame


def to_q8_10(frame):
    """Match the driver's intensity mapping: (val/10.0)*1024 = val*102.4."""
    return (frame.astype(np.float32) * 102.4).astype(np.int32)


def main():
    if len(sys.argv) < 2:
        print(f"Usage: sudo python3 {sys.argv[0]} <host_ip> [image.png] [n_frames]")
        sys.exit(1)
    host_ip = sys.argv[1]
    img_path = sys.argv[2] if len(sys.argv) > 2 else None
    n_frames = int(sys.argv[3]) if len(sys.argv) > 3 else 500

    print(f"Loading DMA-enabled overlay {BIT_PATH} ...")
    ol = Overlay(BIT_PATH)  # configures PL + clocks from retina.hwh (cwd-relative)

    # The DMA IP is named axi_dma_0 in build_bd.tcl. PYNQ binds it to its DMA
    # driver; sendchannel is the MM2S (PS DDR -> PL stream) direction.
    try:
        dma = ol.axi_dma_0
    except AttributeError:
        names = list(ol.ip_dict.keys())
        print(f"axi_dma_0 not found in overlay. IPs: {names}")
        print("This script needs the DMA-enabled overlay (rebuild build_bd.tcl).")
        sys.exit(1)

    retina = MMIO(RETINA_BASE, RETINA_SPAN)
    fifo = MMIO(FIFO_BASE, FIFO_SPAN)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    addr = (host_ip, UDP_PORT)

    frame = make_stimulus(img_path)
    q = to_q8_10(frame).reshape(-1)

    # Contiguous DMA-safe buffer; fill once, re-send each frame (static stimulus).
    in_buf = allocate(shape=(NUM_NEURONS,), dtype=np.int32)
    np.copyto(in_buf, q)

    def dma_load_frame():
        """Burst the stimulus buffer into PL pixel BRAM via AXI DMA MM2S."""
        dma.sendchannel.transfer(in_buf)
        dma.sendchannel.wait()

    print("Priming pixel RAM via DMA ...")
    dma_load_frame()
    status = retina.read(OFF_CONTROL)
    if not (status & STAT_DMA_LOADED):
        print(f"WARNING: dma_frame_loaded not set (status={status:#x}). "
              f"short={bool(status & STAT_DMA_SHORT)} long={bool(status & STAT_DMA_LONG)}")
    else:
        print("DMA frame load confirmed (status bit3 set).")

    # Send the stimulus image to the visualizer (type 2 packet).
    sock.sendto(bytes([PKT_IMAGE]) + frame.tobytes(), addr)

    # Reset the FIFO receive side so we start clean.
    fifo.write(FIFO_RDFR, 0x000000A5)

    print(f"Running {n_frames} frames (each = one Izhikevich timestep) ...")
    total_spikes = 0
    first_spike_frame = None
    t_start = time.perf_counter()

    for f in range(n_frames):
        # Trigger a frame: bit0 start (re-pulses), bit1 clears previous done
        # (and the latched DMA status bits).
        retina.write(OFF_CONTROL, CTRL_START | CTRL_CLEAR_DONE)

        timeout = time.perf_counter() + 1.0
        while not (retina.read(OFF_CONTROL) & STAT_DONE):
            if time.perf_counter() > timeout:
                print(f"TIMEOUT waiting for frame_done at frame {f}.")
                return

        # Wait briefly for the closing TLAST to commit the spike packet.
        occ = fifo.read(FIFO_RDFO)
        commit_deadline = time.perf_counter() + 0.003
        while occ == 0 and time.perf_counter() < commit_deadline:
            occ = fifo.read(FIFO_RDFO)

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

    in_buf.close()


if __name__ == "__main__":
    main()
