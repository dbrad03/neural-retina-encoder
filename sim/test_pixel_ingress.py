"""
Cocotb test for axis_pixel_ingress -- the AXI-Stream -> pixel-RAM write adapter
on the DMA stimulus-input path.

Verifies the one-TLAST-packet-per-frame contract:
  - an exact NUM_PIXELS-beat packet (TLAST on the final beat) lands in the
    pixel RAM in address order and pulses frame_loaded,
  - TLAST before the final beat is rejected as a short packet,
  - the final beat without TLAST (packet too long / TLAST missing) is rejected
    as a long packet AND the adapter re-aligns for the next frame,
  - a mid-stream tvalid stall does not corrupt addressing,
  - back-to-back frames reset the write counter cleanly.

Tests read NUM_PIXELS from the DUT so they pass at any build size. The runner
defaults to a small frame for fast logic checks; set INGRESS_NUM_PIXELS=16384 to
exercise the real full-size frame load.
"""
import os
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, FallingEdge


def num_pixels(dut):
    try:
        return int(dut.NUM_PIXELS.value)
    except Exception:
        return int(os.getenv("INGRESS_NUM_PIXELS", "16"))


async def reset(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    dut.rst_n.value = 0
    dut.s_axis_tdata.value = 0
    dut.s_axis_tvalid.value = 0
    dut.s_axis_tlast.value = 0
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)


class IngressMonitor:
    """Sample the combinational write port + registered status pulses mid-cycle
    (FallingEdge), where they reflect the beat about to be committed."""
    def __init__(self, dut):
        self.dut = dut
        self.mem = {}
        self.frame_loaded = 0
        self.err_short = 0
        self.err_long = 0

    def start(self):
        cocotb.start_soon(self._run())

    async def _run(self):
        while True:
            await FallingEdge(self.dut.clk)
            if self.dut.pix_we.value == 1:
                self.mem[int(self.dut.pix_addr.value)] = int(self.dut.pix_data.value)
            self.frame_loaded += int(self.dut.frame_loaded.value)
            self.err_short += int(self.dut.err_short.value)
            self.err_long += int(self.dut.err_long.value)


async def send_beats(dut, words, last_index=None, stall_at=None):
    """Stream `words` as AXI-Stream beats. Assert TLAST at `last_index`.
    Optionally drop tvalid for one cycle before beat `stall_at`."""
    for i, w in enumerate(words):
        if stall_at is not None and i == stall_at:
            dut.s_axis_tvalid.value = 0
            await RisingEdge(dut.clk)
        dut.s_axis_tdata.value = w
        dut.s_axis_tvalid.value = 1
        dut.s_axis_tlast.value = 1 if (last_index is not None and i == last_index) else 0
        await RisingEdge(dut.clk)
    dut.s_axis_tvalid.value = 0
    dut.s_axis_tlast.value = 0
    # let the status pulse (registered, fires the cycle after the last beat) land
    await RisingEdge(dut.clk)


def frame_words(n, tag=0xA5A5):
    return [((tag << 16) | (i & 0xFFFF)) for i in range(n)]


@cocotb.test()
async def test_exact_frame_loads(dut):
    """Exact-length packet with TLAST on the last beat -> frame_loaded, correct RAM."""
    n = num_pixels(dut)
    await reset(dut)
    mon = IngressMonitor(dut); mon.start()

    words = frame_words(n)
    await send_beats(dut, words, last_index=n - 1)

    assert mon.frame_loaded == 1, f"expected 1 frame_loaded pulse, got {mon.frame_loaded}"
    assert mon.err_short == 0 and mon.err_long == 0, "no errors expected"
    for addr in range(n):
        assert mon.mem.get(addr) == words[addr], \
            f"addr {addr}: expected {words[addr]:#x}, got {mon.mem.get(addr)}"
    dut._log.info(f"Exact-length frame load PASSED (n={n})")


@cocotb.test()
async def test_short_packet_rejected(dut):
    """TLAST before the final beat -> err_short, no frame_loaded."""
    n = num_pixels(dut)
    await reset(dut)
    mon = IngressMonitor(dut); mon.start()

    # End the packet early (TLAST roughly halfway through).
    words = frame_words(n // 2 + 1)
    await send_beats(dut, words, last_index=len(words) - 1)

    assert mon.err_short == 1, f"expected 1 err_short pulse, got {mon.err_short}"
    assert mon.frame_loaded == 0, "frame must NOT load on a short packet"
    assert mon.err_long == 0
    dut._log.info("Short-packet rejection PASSED")


@cocotb.test()
async def test_long_packet_rejected_then_realigns(dut):
    """Final beat without TLAST -> err_long; the adapter then loads the next
    well-formed frame, proving it re-aligned."""
    n = num_pixels(dut)
    await reset(dut)
    mon = IngressMonitor(dut); mon.start()

    # n beats, no TLAST anywhere -> at index n-1 the adapter flags err_long.
    await send_beats(dut, frame_words(n, tag=0x1111), last_index=None)
    assert mon.err_long == 1, f"expected 1 err_long pulse, got {mon.err_long}"
    assert mon.frame_loaded == 0, "no frame should load without TLAST"

    # A proper frame must now load normally (counter re-aligned to 0).
    words = frame_words(n, tag=0x2222)
    await send_beats(dut, words, last_index=n - 1)
    assert mon.frame_loaded == 1, "adapter did not re-align after a long packet"
    for addr in range(n):
        assert mon.mem.get(addr) == words[addr], f"addr {addr} wrong after re-align"
    dut._log.info("Long-packet rejection + re-alignment PASSED")


@cocotb.test()
async def test_stall_preserves_addressing(dut):
    """A mid-stream tvalid de-assertion must not advance the address counter."""
    n = num_pixels(dut)
    await reset(dut)
    mon = IngressMonitor(dut); mon.start()

    words = frame_words(n, tag=0x3333)
    await send_beats(dut, words, last_index=n - 1, stall_at=n // 2)

    assert mon.frame_loaded == 1, "stalled-but-complete frame should still load"
    assert mon.err_short == 0 and mon.err_long == 0
    for addr in range(n):
        assert mon.mem.get(addr) == words[addr], \
            f"addr {addr} corrupted by stall: got {mon.mem.get(addr)}"
    dut._log.info("Stall-tolerance PASSED")


@cocotb.test()
async def test_back_to_back_frames(dut):
    """Two consecutive frames: the counter resets so frame 2 overwrites cleanly."""
    n = num_pixels(dut)
    await reset(dut)
    mon = IngressMonitor(dut); mon.start()

    await send_beats(dut, frame_words(n, tag=0x4444), last_index=n - 1)
    words2 = frame_words(n, tag=0x5555)
    await send_beats(dut, words2, last_index=n - 1)

    assert mon.frame_loaded == 2, f"expected 2 frame_loaded pulses, got {mon.frame_loaded}"
    for addr in range(n):
        assert mon.mem.get(addr) == words2[addr], f"addr {addr} not overwritten by frame 2"
    dut._log.info("Back-to-back frames PASSED")


def runner():
    from cocotb_tools.runner import get_runner
    hdl_toplevel = "axis_pixel_ingress"
    sim = os.getenv("SIM", "icarus")
    proj_path = Path(__file__).resolve().parent.parent
    sources = [proj_path / "hdl" / "axis_pixel_ingress.sv"]
    # Default to a small frame for fast logic checks; INGRESS_NUM_PIXELS=16384
    # exercises the real full-size load (the tests are size-agnostic).
    num = int(os.getenv("INGRESS_NUM_PIXELS", "16"))
    runner = get_runner(sim)
    runner.build(
        sources=sources,
        hdl_toplevel=hdl_toplevel,
        always=True,
        timescale=("1ns", "1ps"),
        parameters={"NUM_PIXELS": num},
    )
    runner.test(hdl_toplevel=hdl_toplevel, test_module="test_pixel_ingress")


if __name__ == "__main__":
    runner()
