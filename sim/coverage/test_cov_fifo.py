"""Coverage workload for FIFO occupancy, full replacement, overflow, and clear."""

import os
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer, ReadOnly
from cocotb_coverage.coverage import CoverPoint

from coverage_utils import export_coverage, safe_int


@CoverPoint("fifo.occupancy", xf=lambda sample: sample,
            bins=["empty", "partial", "full"], at_least=1)
def sample_occupancy(sample):
    return sample


@CoverPoint("fifo.event", xf=lambda sample: sample,
            bins=["simultaneous_full_read_write", "overflow_drop", "clear_overflow"],
            at_least=1)
def sample_event(sample):
    return sample


async def fifo_monitor(dut):
    # Wait for reset to be released
    while not safe_int(dut.rst_n.value, default=0):
        await RisingEdge(dut.clk)

    # Sample the initial post-reset state
    await ReadOnly()
    if safe_int(dut.empty.value):
        sample_occupancy("empty")

    prev_overflow = safe_int(dut.overflow_seen.value)

    while True:
        await RisingEdge(dut.clk)
        await ReadOnly()

        # Read signal values
        wr_en = safe_int(dut.wr_en.value)
        rd_en = safe_int(dut.rd_en.value)
        full = safe_int(dut.full.value)
        empty = safe_int(dut.empty.value)
        clear_overflow = safe_int(dut.clear_overflow.value)
        overflow_seen = safe_int(dut.overflow_seen.value)

        # 1. Occupancy sampling
        if empty:
            sample_occupancy("empty")
        elif full:
            sample_occupancy("full")
        else:
            sample_occupancy("partial")

        # 2. Event sampling
        if wr_en and rd_en and full:
            sample_event("simultaneous_full_read_write")
        elif wr_en and full and not rd_en:
            sample_event("overflow_drop")
        elif clear_overflow and prev_overflow:
            sample_event("clear_overflow")

        prev_overflow = overflow_seen


@cocotb.test()
async def coverage_fifo(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    cocotb.start_soon(fifo_monitor(dut))

    dut.rst_n.value = 0
    dut.wr_en.value = 0
    dut.rd_en.value = 0
    dut.din.value = 0
    dut.clear_overflow.value = 0
    await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)

    for value in range(8):
        dut.din.value = value
        dut.wr_en.value = 1
        await RisingEdge(dut.clk)
    dut.wr_en.value = 0
    await Timer(1, unit="ns")
    assert safe_int(dut.full.value) == 1

    dut.rd_en.value = 1
    dut.wr_en.value = 1
    dut.din.value = 9
    await RisingEdge(dut.clk)
    await Timer(1, unit="ns")
    assert not safe_int(dut.overflow_seen.value)

    dut.rd_en.value = 0
    dut.din.value = 10
    await RisingEdge(dut.clk)
    await Timer(1, unit="ns")
    dut.wr_en.value = 0
    assert safe_int(dut.overflow_seen.value)

    dut.clear_overflow.value = 1
    await RisingEdge(dut.clk)
    await Timer(1, unit="ns")
    dut.clear_overflow.value = 0
    assert not safe_int(dut.overflow_seen.value)

    # Read all elements to return FIFO to empty
    dut.rd_en.value = 1
    while not safe_int(dut.empty.value):
        await RisingEdge(dut.clk)
    dut.rd_en.value = 0

    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)
    export_coverage()


def runner():
    from cocotb_tools.runner import get_runner
    root = Path(__file__).resolve().parents[2]
    runner_obj = get_runner(os.getenv("SIM", "icarus"))
    runner_obj.build(
        sources=[root / "hdl" / "spike_fifo.sv"], hdl_toplevel="spike_fifo",
        always=True, timescale=("1ns", "1ps"),
        parameters={"FIFO_DEPTH": 8, "ADDR_WIDTH": 4},
        build_dir="sim_build/cov_fifo",
    )
    runner_obj.test(hdl_toplevel="spike_fifo", test_module="test_cov_fifo",
                    build_dir="sim_build/cov_fifo")


if __name__ == "__main__":
    runner()
