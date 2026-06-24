"""
Integration test for the DMA stimulus-input path through axi_retina_wrapper
built with USE_DMA_INGRESS=1.

Proves the full PS->PL->BRAM path that AXI DMA MM2S will drive on hardware:
  - stream a whole frame in over the s_axis_pixel AXI-Stream slave,
  - read the pixels back over AXI-Lite to confirm they landed in address order,
  - confirm the latched dma_frame_loaded status bit (status reg bit3),
  - confirm the legacy AXI-Lite /dev/mem pixel-write path still works when the
    DMA stream is idle (the two share BRAM port A; DMA just has priority).
"""
import os
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer
from cocotbext.axi import AxiLiteBus, AxiLiteMaster, AxiStreamBus, AxiStreamSource, AxiStreamFrame

N = 16  # NUM_NEURONS for this build (small for speed)

OFF_PIXEL_RAM = 0x00000
OFF_CONTROL = 0x10000
CTRL_CLEAR_DONE = 0x2
STAT_DMA_LOADED = 0x8  # status reg bit3


@cocotb.test()
async def test_dma_frame_load(dut):
    """Stream a frame via AXI DMA path; verify BRAM contents + status bit."""
    cocotb.start_soon(Clock(dut.aclk, 10, unit="ns").start())
    dut.aresetn.value = 0
    await Timer(50, unit="ns")
    dut.aresetn.value = 1
    await RisingEdge(dut.aclk)

    axil = AxiLiteMaster(AxiLiteBus.from_prefix(dut, "s_axi"), dut.aclk, dut.aresetn,
                         reset_active_level=False)
    src = AxiStreamSource(AxiStreamBus.from_prefix(dut, "s_axis_pixel"), dut.aclk, dut.aresetn,
                          reset_active_level=False)

    # Stream one frame of distinct 18-bit Q8.10-range payloads (TLAST auto on last beat).
    pixels = [((0x100 + i) & 0x3FFFF) for i in range(N)]
    payload = b"".join(p.to_bytes(4, "little") for p in pixels)
    await src.send(AxiStreamFrame(tdata=payload))
    await src.wait()

    # Let the ingress commit + latch frame_loaded.
    for _ in range(8):
        await RisingEdge(dut.aclk)

    # Status reg bit3 (dma_frame_loaded) must be latched.
    status = int.from_bytes((await axil.read(OFF_CONTROL, 4)).data, "little")
    assert status & STAT_DMA_LOADED, f"dma_frame_loaded not set; status={status:#x}"

    # Read every pixel back over AXI-Lite; must match the streamed frame in order.
    for i in range(N):
        rb = int.from_bytes((await axil.read(OFF_PIXEL_RAM + i * 4, 4)).data, "little")
        assert rb == pixels[i], f"addr {i}: streamed {pixels[i]:#x}, read back {rb:#x}"

    dut._log.info(f"DMA frame load + AXI-Lite readback PASSED ({N} pixels)")


@cocotb.test()
async def test_axilite_write_still_works(dut):
    """With the DMA stream idle, the legacy AXI-Lite pixel write must still land."""
    cocotb.start_soon(Clock(dut.aclk, 10, unit="ns").start())
    dut.aresetn.value = 0
    await Timer(50, unit="ns")
    dut.aresetn.value = 1
    await RisingEdge(dut.aclk)

    axil = AxiLiteMaster(AxiLiteBus.from_prefix(dut, "s_axi"), dut.aclk, dut.aresetn,
                         reset_active_level=False)
    # DMA stream is never driven here (tvalid stays 0).
    val = 0x0001ABCD
    await axil.write(OFF_PIXEL_RAM + 4 * 3, val.to_bytes(4, "little"))
    rb = int.from_bytes((await axil.read(OFF_PIXEL_RAM + 4 * 3, 4)).data, "little")
    assert rb == val, f"AXI-Lite write/read broken by DMA mux: wrote {val:#x}, read {rb:#x}"
    dut._log.info("Legacy AXI-Lite pixel write/read PASSED with DMA enabled")


def runner():
    from cocotb_tools.runner import get_runner
    hdl_toplevel = "axi_retina_wrapper"
    sim = os.getenv("SIM", "icarus")
    proj_path = Path(__file__).resolve().parent.parent
    sources = [
        proj_path / "hdl" / "izh_pkg.sv",
        proj_path / "hdl" / "izh_neuron_engine.sv",
        proj_path / "hdl" / "neuron_state_mem.sv",
        proj_path / "hdl" / "spike_fifo.sv",
        proj_path / "hdl" / "neuron_array_controller.sv",
        proj_path / "hdl" / "axis_pixel_ingress.sv",
        proj_path / "hdl" / "axi_retina_wrapper.sv",
    ]
    runner = get_runner(sim)
    runner.build(
        sources=sources,
        hdl_toplevel=hdl_toplevel,
        always=True,
        timescale=("1ns", "1ps"),
        parameters={"NUM_NEURONS": N, "USE_DMA_INGRESS": 1},
    )
    runner.test(hdl_toplevel=hdl_toplevel, test_module="test_dma_wrapper")


if __name__ == "__main__":
    runner()
