#!/usr/bin/env python3
"""
bench_timing.py - per-stage timing benchmark for the retina loop on PYNQ.

Runs on the DMA-enabled overlay (which keeps the AXI-Lite write path working),
so it benchmarks BOTH pixel-load methods back to back on the same board/clock and
reports where the per-frame budget actually goes.

Stages timed (min / median / mean over N reps, warmup discarded):
  - AXI-Lite pixel load : 16,384 single-beat MMIO writes (the first_light.py path)
  - DMA pixel load      : sendchannel.transfer()+wait()  (transfer only, and
                          copy+transfer = the live per-frame cost)
  - PL frame compute    : trigger START, poll frame_done  (~scan floor + overhead)
  - FIFO drain          : wait for TLAST commit, read RLR, pop spike words

Then it assembles two full per-frame loop profiles for comparison:
  AXI-Lite path = axil_load + frame + drain
  DMA path      = dma(copy+xfer) + frame + drain

HONEST CAVEATS (printed at the end too):
  - Python MMIO overhead inflates the AXI-Lite load and the frame poll; the true
    no-Python numbers are lower (see the C benchmark, BENCH=1 ./retina_v4l2).
  - The ~164 us PL scan floor (16,384 cycles @ 100 MHz) caps any pixel-load win:
    DMA removes the per-write CPU cost of 16,384 stores, it does not beat the scan.

Usage:
    sudo -i /usr/local/share/pynq-venv/bin/python3 bench_timing.py [n_reps]
"""
import sys
import statistics
from time import perf_counter_ns

import numpy as np

try:
    from pynq import Overlay, MMIO, allocate
except ImportError:
    print("Run this on the PYNQ board (pynq not found).")
    sys.exit(1)

# ---- Address map ------------------------------------------------------------
RETINA_BASE = 0x40000000
RETINA_SPAN = 0x20000
FIFO_BASE   = 0x43C00000
FIFO_SPAN   = 0x10000
OFF_PIXEL_RAM = 0x00000
OFF_CONTROL   = 0x10000

CTRL_START      = 0x1
CTRL_CLEAR_DONE = 0x2
STAT_DONE       = 0x2
STAT_DMA_LOADED = 0x8

FIFO_RDFR = 0x18
FIFO_RDFO = 0x1C   # occupancy (words)
FIFO_RDFD = 0x20   # data
FIFO_RLR  = 0x24   # length (bytes), valid only when RDFO>0

GRID = 128
NUM_NEURONS = GRID * GRID
BIT_PATH = "retina.bit"


def make_stimulus():
    """Diamond on the fovea + radial gradient (same as first_light)."""
    yy, xx = np.mgrid[0:GRID, 0:GRID]
    diamond = (np.abs(xx - 64) + np.abs(yy - 64)) < 45
    grad = (255 * (1 - (np.hypot(xx - 64, yy - 64) / 90))).clip(0, 255)
    frame = grad.astype(np.uint8)
    frame[diamond] = 255
    return frame


def to_q8_10(frame):
    return (frame.astype(np.float32) * 102.4).astype(np.int32).reshape(-1)


def stats_us(samples_ns):
    s = sorted(samples_ns)
    return (s[0] / 1e3,
            statistics.median(s) / 1e3,
            statistics.fmean(s) / 1e3)


def main():
    n_reps = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    load_reps = max(10, n_reps // 5)   # AXI-Lite load is slow; fewer reps
    warmup = 20

    print(f"Loading DMA-enabled overlay {BIT_PATH} ...")
    ol = Overlay(BIT_PATH)
    try:
        dma = ol.axi_dma_0
    except AttributeError:
        print(f"axi_dma_0 not in overlay. IPs: {list(ol.ip_dict.keys())}")
        print("This board still has the non-DMA overlay. Copy the rebuilt "
              "retina.bit/.hwh first.")
        sys.exit(1)

    retina = MMIO(RETINA_BASE, RETINA_SPAN)
    fifo = MMIO(FIFO_BASE, FIFO_SPAN)

    q = to_q8_10(make_stimulus())              # numpy int32, len 16384
    qlist = q.tolist()                          # plain ints (best case for MMIO)
    in_buf = allocate(shape=(NUM_NEURONS,), dtype=np.int32)
    np.copyto(in_buf, q)

    def dma_load_once():
        dma.sendchannel.transfer(in_buf)
        dma.sendchannel.wait()

    # ---- Stage 1: AXI-Lite pixel load (16,384 MMIO writes) ------------------
    print(f"Benchmarking AXI-Lite pixel load ({load_reps} reps of 16384 writes)...")
    axil = []
    for _ in range(load_reps):
        t0 = perf_counter_ns()
        for i in range(NUM_NEURONS):
            retina.write(OFF_PIXEL_RAM + i * 4, qlist[i])
        axil.append(perf_counter_ns() - t0)

    # ---- Stage 2: DMA pixel load -------------------------------------------
    print(f"Benchmarking DMA pixel load ({n_reps} reps)...")
    dma_xfer = []
    for _ in range(n_reps):
        t0 = perf_counter_ns()
        dma.sendchannel.transfer(in_buf)
        dma.sendchannel.wait()
        dma_xfer.append(perf_counter_ns() - t0)

    dma_copy_xfer = []
    for _ in range(n_reps):
        t0 = perf_counter_ns()
        np.copyto(in_buf, q)
        dma.sendchannel.transfer(in_buf)
        dma.sendchannel.wait()
        dma_copy_xfer.append(perf_counter_ns() - t0)

    sb = retina.read(OFF_CONTROL)
    print(f"  status after DMA: {sb:#x} "
          f"(dma_frame_loaded={'set' if sb & STAT_DMA_LOADED else 'NOT set'})")

    # ---- Stage 3+4: PL frame compute + FIFO drain --------------------------
    print(f"Benchmarking PL frame compute + FIFO drain ({n_reps} reps, "
          f"{warmup} warmup)...")
    dma_load_once()
    fifo.write(FIFO_RDFR, 0x000000A5)
    frame, drain, spikes = [], [], []
    for k in range(n_reps + warmup):
        t0 = perf_counter_ns()
        retina.write(OFF_CONTROL, CTRL_START | CTRL_CLEAR_DONE)
        while not (retina.read(OFF_CONTROL) & STAT_DONE):
            pass
        t1 = perf_counter_ns()

        occ = fifo.read(FIFO_RDFO)
        deadline = perf_counter_ns() + 3_000_000
        while occ == 0 and perf_counter_ns() < deadline:
            occ = fifo.read(FIFO_RDFO)
        nspk = 0
        if occ:
            nspk = fifo.read(FIFO_RLR) // 4
            for _ in range(nspk):
                fifo.read(FIFO_RDFD)
        t2 = perf_counter_ns()

        if k >= warmup:
            frame.append(t1 - t0)
            drain.append(t2 - t1)
            spikes.append(nspk)

    in_buf.close()

    # ---- Report ------------------------------------------------------------
    rows = [
        ("AXI-Lite load (16384 MMIO wr)", stats_us(axil)),
        ("DMA load (transfer only)", stats_us(dma_xfer)),
        ("DMA load (copy + transfer)", stats_us(dma_copy_xfer)),
        ("PL frame compute (scan)", stats_us(frame)),
        ("FIFO drain", stats_us(drain)),
    ]

    print("\n================ PER-STAGE TIMING (microseconds) ================")
    print(f"{'stage':<32}{'min':>10}{'median':>10}{'mean':>10}")
    for name, (mn, md_, mean) in rows:
        print(f"{name:<32}{mn:>10.1f}{md_:>10.1f}{mean:>10.1f}")
    print(f"\navg spikes drained / frame: {statistics.fmean(spikes):.0f}")

    median = {name: vals[1] for name, vals in rows}  # name -> median us
    frame_md = median["PL frame compute (scan)"]
    drain_md = median["FIFO drain"]
    axil_md = median["AXI-Lite load (16384 MMIO wr)"]
    dma_md = median["DMA load (copy + transfer)"]

    def profile(title, load_md):
        loop = load_md + frame_md + drain_md
        print(f"\n--- {title} (per-frame, medians) ---")
        for label, val in (("pixel load", load_md),
                           ("PL frame compute", frame_md),
                           ("FIFO drain", drain_md)):
            print(f"  {label:<20}{val:>10.1f} us  ({100*val/loop:>4.1f}%)")
        print(f"  {'TOTAL':<20}{loop:>10.1f} us  -> {1e6/loop:>6.1f} fps")
        return loop

    print("\n================ ASSEMBLED LOOP PROFILES ================")
    axil_loop = profile("AXI-Lite path", axil_md)
    dma_loop = profile("DMA path", dma_md)

    print("\n================ SUMMARY ================")
    print(f"pixel-load speedup (AXI-Lite/DMA): "
          f"{axil_md/dma_md:.1f}x  ({axil_md:.0f} -> {dma_md:.0f} us)")
    print(f"full-loop speedup: {axil_loop/dma_loop:.2f}x  "
          f"({1e6/axil_loop:.0f} -> {1e6/dma_loop:.0f} fps)")
    print("\nCAVEATS:")
    print(" - Python MMIO overhead inflates the AXI-Lite load and frame poll;")
    print("   the true no-Python numbers are lower (run BENCH=1 ./retina_v4l2).")
    print(" - ~164 us PL scan floor caps the win: DMA removes 16384 per-write")
    print("   CPU stores, it does not beat the scan compute itself.")


if __name__ == "__main__":
    main()
