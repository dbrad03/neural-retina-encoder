"""Coverage workload for AXI-Lite ordering, read stalls, and BRAM collisions."""

import os
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, ReadOnly
from cocotb_coverage.coverage import CoverPoint

from coverage_utils import export_coverage, safe_int


@CoverPoint("axil.write_order", xf=lambda sample: sample,
            bins=["aw_first", "w_first", "simultaneous"], at_least=1)
def sample_write_order(sample):
    return sample


@CoverPoint("axil.read_behavior", xf=lambda sample: sample,
            bins=["normal", "backpressure"], at_least=1)
def sample_read(sample):
    return sample


@CoverPoint("wrapper.collision", xf=lambda sample: sample,
            bins=["dma_vs_axil_write", "dma_vs_axil_read"], at_least=1)
def sample_collision(sample):
    return sample


async def wrapper_monitor(dut):
    # Wait for reset
    while not safe_int(dut.aresetn.value, default=0):
        await RisingEdge(dut.aclk)

    aw_handshaked = False
    w_handshaked = False

    read_active = False
    backpressured = False

    while True:
        await RisingEdge(dut.aclk)
        await ReadOnly()

        # 1. Collision monitor
        dma_we = safe_int(dut.dma_pix_we.value)
        axil_wr = safe_int(dut.axil_bram_wr.value)
        axil_rd = safe_int(dut.axil_bram_rd.value)
        if dma_we and axil_wr:
            sample_collision("dma_vs_axil_write")
        elif dma_we and axil_rd:
            sample_collision("dma_vs_axil_read")

        # 2. AXI-Lite write order monitor
        awvalid = safe_int(dut.s_axi_awvalid.value)
        awready = safe_int(dut.s_axi_awready.value)
        wvalid = safe_int(dut.s_axi_wvalid.value)
        wready = safe_int(dut.s_axi_wready.value)
        bvalid = safe_int(dut.s_axi_bvalid.value)
        bready = safe_int(dut.s_axi_bready.value)

        aw_hs = awvalid and awready
        w_hs = wvalid and wready

        if aw_hs and w_hs:
            sample_write_order("simultaneous")
            aw_handshaked = False
            w_handshaked = False
        elif aw_hs:
            if w_handshaked:
                sample_write_order("w_first")
                aw_handshaked = False
                w_handshaked = False
            else:
                aw_handshaked = True
        elif w_hs:
            if aw_handshaked:
                sample_write_order("aw_first")
                aw_handshaked = False
                w_handshaked = False
            else:
                w_handshaked = True

        if bvalid and bready:
            aw_handshaked = False
            w_handshaked = False

        # 3. AXI-Lite read behavior monitor
        arvalid = safe_int(dut.s_axi_arvalid.value)
        arready = safe_int(dut.s_axi_arready.value)
        rvalid = safe_int(dut.s_axi_rvalid.value)
        rready = safe_int(dut.s_axi_rready.value)

        if arvalid and arready:
            read_active = True
            backpressured = False

        if read_active:
            if rvalid and not rready:
                backpressured = True
            if rvalid and rready:
                sample_read("backpressure" if backpressured else "normal")
                read_active = False


async def reset(dut):
    dut.aresetn.value = 0
    for name in ("s_axi_awvalid", "s_axi_wvalid", "s_axi_bready",
                 "s_axi_arvalid", "s_axi_rready",
                 "s_axis_pixel_tvalid", "s_axis_pixel_tlast"):
        getattr(dut, name).value = 0
    dut.s_axi_awaddr.value = 0
    dut.s_axi_wdata.value = 0
    dut.s_axi_wstrb.value = 0xF
    dut.s_axi_araddr.value = 0
    dut.s_axis_pixel_tdata.value = 0
    await RisingEdge(dut.aclk)
    await RisingEdge(dut.aclk)
    dut.aresetn.value = 1
    await RisingEdge(dut.aclk)


async def axil_write(dut, addr, data, order):
    dut.s_axi_awaddr.value = addr
    dut.s_axi_wdata.value = data
    dut.s_axi_wstrb.value = 0xF
    dut.s_axi_bready.value = 1
    if order == "aw_first":
        dut.s_axi_awvalid.value = 1
        while not safe_int(dut.s_axi_awready.value):
            await RisingEdge(dut.aclk)
        await RisingEdge(dut.aclk)
        dut.s_axi_awvalid.value = 0
        await RisingEdge(dut.aclk)
        dut.s_axi_wvalid.value = 1
    elif order == "w_first":
        dut.s_axi_wvalid.value = 1
        while not safe_int(dut.s_axi_wready.value):
            await RisingEdge(dut.aclk)
        await RisingEdge(dut.aclk)
        dut.s_axi_wvalid.value = 0
        await RisingEdge(dut.aclk)
        dut.s_axi_awvalid.value = 1
    else:
        dut.s_axi_awvalid.value = 1
        dut.s_axi_wvalid.value = 1
    while not safe_int(dut.s_axi_bvalid.value):
        await RisingEdge(dut.aclk)
    dut.s_axi_awvalid.value = 0
    dut.s_axi_wvalid.value = 0
    await RisingEdge(dut.aclk)
    dut.s_axi_bready.value = 0


async def axil_read(dut, addr, stall_cycles=0, inspect_data=True):
    dut.s_axi_araddr.value = addr
    dut.s_axi_arvalid.value = 1
    if stall_cycles == 0:
        dut.s_axi_rready.value = 1
    else:
        dut.s_axi_rready.value = 0
    while not safe_int(dut.s_axi_arready.value):
        await RisingEdge(dut.aclk)
    await RisingEdge(dut.aclk)
    dut.s_axi_arvalid.value = 0
    while not safe_int(dut.s_axi_rvalid.value):
        await RisingEdge(dut.aclk)
    held = safe_int(dut.s_axi_rdata.value) if inspect_data else None
    for _ in range(stall_cycles):
        await RisingEdge(dut.aclk)
        assert safe_int(dut.s_axi_rvalid.value)
        if inspect_data:
            assert safe_int(dut.s_axi_rdata.value) == held
    if stall_cycles > 0:
        dut.s_axi_rready.value = 1
        await RisingEdge(dut.aclk)
    dut.s_axi_rready.value = 0
    return held


async def collide(dut, kind):
    dut.s_axis_pixel_tdata.value = 0xABCDE
    dut.s_axis_pixel_tvalid.value = 1
    if kind == "dma_vs_axil_write":
        await axil_write(dut, 0, 0x1111, "simultaneous")
    else:
        await axil_read(dut, 0, inspect_data=False)
    dut.s_axis_pixel_tvalid.value = 0
    for _ in range(3):
        await RisingEdge(dut.aclk)
    assert safe_int(dut.dma_axil_collision_l.value)


@cocotb.test()
async def coverage_wrapper(dut):
    cocotb.start_soon(Clock(dut.aclk, 10, unit="ns").start())
    cocotb.start_soon(wrapper_monitor(dut))
    await reset(dut)
    await axil_write(dut, 4, 0x1111, "aw_first")
    await axil_write(dut, 8, 0x2222, "w_first")
    await axil_write(dut, 12, 0x3333, "simultaneous")
    await axil_read(dut, 4)
    await axil_read(dut, 8, stall_cycles=4)
    await collide(dut, "dma_vs_axil_write")

    # Clear the sticky collision before independently covering a read collision.
    await axil_write(dut, 0x10000, 0x2, "simultaneous")
    assert not safe_int(dut.dma_axil_collision_l.value)
    await collide(dut, "dma_vs_axil_read")

    await RisingEdge(dut.aclk)
    await RisingEdge(dut.aclk)
    export_coverage()


def runner():
    from cocotb_tools.runner import get_runner
    root = Path(__file__).resolve().parents[2]
    sources = [
        root / "hdl" / "izh_pkg.sv",
        root / "hdl" / "izh_neuron_engine.sv",
        root / "hdl" / "neuron_state_mem.sv",
        root / "hdl" / "spike_fifo.sv",
        root / "hdl" / "neuron_array_controller.sv",
        root / "hdl" / "axis_pixel_ingress.sv",
        root / "hdl" / "axi_retina_wrapper.sv",
    ]
    runner_obj = get_runner(os.getenv("SIM", "icarus"))
    runner_obj.build(
        sources=sources, hdl_toplevel="axi_retina_wrapper", always=True,
        timescale=("1ns", "1ps"),
        parameters={"NUM_NEURONS": 16, "ADDR_WIDTH": 4, "USE_DMA_INGRESS": 1},
        build_dir="sim_build/cov_wrapper",
    )
    runner_obj.test(hdl_toplevel="axi_retina_wrapper",
                    test_module="test_cov_wrapper",
                    build_dir="sim_build/cov_wrapper")


if __name__ == "__main__":
    runner()
