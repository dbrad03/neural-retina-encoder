"""Coverage workload for exact, short, long, and stalled DMA packets."""

import os
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, ReadOnly
from cocotb_coverage.coverage import CoverPoint

from coverage_utils import export_coverage, safe_int


@CoverPoint("dma.packet_kind", xf=lambda sample: sample,
            bins=["exact", "short", "long", "stalled"], at_least=1)
def sample_packet(sample):
    return sample


async def ingress_monitor(dut):
    # Wait for reset
    while not safe_int(dut.rst_n.value, default=0):
        await RisingEdge(dut.clk)

    stalled_seen = False
    packet_active = False

    while True:
        await RisingEdge(dut.clk)
        await ReadOnly()

        # Read signal values
        tvalid = safe_int(dut.s_axis_tvalid.value)
        tready = safe_int(dut.s_axis_tready.value)
        frame_loaded = safe_int(dut.frame_loaded.value)
        err_short = safe_int(dut.err_short.value)
        err_long = safe_int(dut.err_long.value)
        count = safe_int(dut.count.value)

        # Check if a packet is starting
        if tvalid and tready and count == 0 and not packet_active:
            packet_active = True
            stalled_seen = False

        # Check for stall during packet
        if packet_active and not tvalid:
            stalled_seen = True

        # Check for packet end
        if frame_loaded:
            if stalled_seen:
                sample_packet("stalled")
            else:
                sample_packet("exact")
            packet_active = False
        elif err_short:
            sample_packet("short")
            packet_active = False
        elif err_long:
            sample_packet("long")
            packet_active = False


async def send(dut, count, last_index, stall_at=None):
    for index in range(count):
        if index == stall_at:
            dut.s_axis_tvalid.value = 0
            await RisingEdge(dut.clk)
            await RisingEdge(dut.clk)
        dut.s_axis_tdata.value = 0x1000 + index
        dut.s_axis_tvalid.value = 1
        dut.s_axis_tlast.value = int(index == last_index)
        await RisingEdge(dut.clk)
    dut.s_axis_tvalid.value = 0
    dut.s_axis_tlast.value = 0
    await RisingEdge(dut.clk)


@cocotb.test()
async def coverage_ingress(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    cocotb.start_soon(ingress_monitor(dut))

    dut.rst_n.value = 0
    dut.s_axis_tvalid.value = 0
    dut.s_axis_tdata.value = 0
    dut.s_axis_tlast.value = 0
    await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)

    await send(dut, 8, 7)
    assert safe_int(dut.frame_loaded.value)

    await send(dut, 4, 3)
    assert safe_int(dut.err_short.value)

    await send(dut, 8, None)
    assert safe_int(dut.err_long.value)

    await send(dut, 8, 7, stall_at=4)
    assert safe_int(dut.frame_loaded.value)

    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)
    export_coverage()


def runner():
    from cocotb_tools.runner import get_runner
    root = Path(__file__).resolve().parents[2]
    runner_obj = get_runner(os.getenv("SIM", "icarus"))
    runner_obj.build(
        sources=[root / "hdl" / "axis_pixel_ingress.sv"],
        hdl_toplevel="axis_pixel_ingress", always=True,
        timescale=("1ns", "1ps"), parameters={"NUM_PIXELS": 8, "ADDR_WIDTH": 3},
        build_dir="sim_build/cov_ingress",
    )
    runner_obj.test(hdl_toplevel="axis_pixel_ingress",
                    test_module="test_cov_ingress",
                    build_dir="sim_build/cov_ingress")


if __name__ == "__main__":
    runner()
