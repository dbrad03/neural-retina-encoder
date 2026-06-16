import os
import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer
from cocotbext.axi import AxiLiteBus, AxiLiteMaster

@cocotb.test()
async def test_axi_stress(dut):
    """Stress test AXI-Lite decoupled AW and W channels."""
    
    cocotb.start_soon(Clock(dut.aclk, 10, unit="ns").start())
    
    dut.aresetn.value = 0
    await Timer(50, unit="ns")
    dut.aresetn.value = 1
    await RisingEdge(dut.aclk)

    # Note: cocotbext-axi AxiLiteMaster randomly injects stalls and decoupled AW/W timing
    # by default if we don't constrain it. But we can explicitly test by manually driving bus.
    
    # 1. Test AW before W
    dut.s_axi_awaddr.value = 0x10000
    dut.s_axi_awvalid.value = 1
    dut.s_axi_wdata.value = 0x0
    dut.s_axi_wvalid.value = 0
    dut.s_axi_bready.value = 1
    
    while dut.s_axi_awready.value == 0:
        await RisingEdge(dut.aclk)
        
    # AW is accepted, wait a few cycles
    await RisingEdge(dut.aclk)
    dut.s_axi_awvalid.value = 0
    await RisingEdge(dut.aclk)
    await RisingEdge(dut.aclk)
    
    # Now provide W
    dut.s_axi_wdata.value = 0x3
    dut.s_axi_wstrb.value = 0xF
    dut.s_axi_wvalid.value = 1
    
    while dut.s_axi_wready.value == 0:
        await RisingEdge(dut.aclk)
        
    await RisingEdge(dut.aclk)
    dut.s_axi_wvalid.value = 0
    
    while dut.s_axi_bvalid.value == 0:
        await RisingEdge(dut.aclk)
        
    assert dut.s_axi_bresp.value == 0
    await RisingEdge(dut.aclk)
    
    dut._log.info("AW-before-W test PASSED")
    
    # Wait for frame to finish so we don't interfere
    while dut.frame_done_irq.value == 0:
        await RisingEdge(dut.aclk)
        
    # Clear interrupt
    dut.s_axi_awaddr.value = 0x10000
    dut.s_axi_awvalid.value = 1
    dut.s_axi_wdata.value = 0x2
    dut.s_axi_wstrb.value = 0xF
    dut.s_axi_wvalid.value = 1
    
    while dut.s_axi_bvalid.value == 0:
        await RisingEdge(dut.aclk)
    dut.s_axi_awvalid.value = 0
    dut.s_axi_wvalid.value = 0
    await RisingEdge(dut.aclk)
    
    # 2. Test W before AW
    dut.s_axi_wdata.value = 0x1
    dut.s_axi_wstrb.value = 0xF
    dut.s_axi_wvalid.value = 1
    dut.s_axi_awvalid.value = 0
    
    while dut.s_axi_wready.value == 0:
        await RisingEdge(dut.aclk)
        
    await RisingEdge(dut.aclk)
    dut.s_axi_wvalid.value = 0
    await RisingEdge(dut.aclk)
    await RisingEdge(dut.aclk)
    
    # Now provide AW
    dut.s_axi_awaddr.value = 0x10000
    dut.s_axi_awvalid.value = 1
    
    while dut.s_axi_awready.value == 0:
        await RisingEdge(dut.aclk)
        
    await RisingEdge(dut.aclk)
    dut.s_axi_awvalid.value = 0
    
    while dut.s_axi_bvalid.value == 0:
        await RisingEdge(dut.aclk)
        
    assert dut.s_axi_bresp.value == 0
    
    dut._log.info("W-before-AW test PASSED")
    
    # 3. Test Read Channel Stall (RREADY=0 prevents ARREADY)
    # Issue first read
    dut.s_axi_araddr.value = 0x10000
    dut.s_axi_arvalid.value = 1
    dut.s_axi_rready.value = 0
    
    while dut.s_axi_arready.value == 0:
        await RisingEdge(dut.aclk)
    await RisingEdge(dut.aclk)
    dut.s_axi_arvalid.value = 0
    
    # Wait for RVALID
    while dut.s_axi_rvalid.value == 0:
        await RisingEdge(dut.aclk)
        
    # Now issue second read while RVALID=1 but RREADY=0
    dut.s_axi_araddr.value = 0x10004
    dut.s_axi_arvalid.value = 1
    
    # ARREADY should NOT assert while we hold RREADY=0
    for _ in range(5):
        await RisingEdge(dut.aclk)
        assert dut.s_axi_arready.value == 0, "ARREADY asserted while RVALID high and RREADY low!"
        
    # Now release RREADY
    dut.s_axi_rready.value = 1
    
    # Now ARREADY should assert
    while dut.s_axi_arready.value == 0:
        await RisingEdge(dut.aclk)
        
    await RisingEdge(dut.aclk)
    dut.s_axi_arvalid.value = 0
    
    # Wait for second read to complete
    while dut.s_axi_rvalid.value == 0:
        await RisingEdge(dut.aclk)
        
    await RisingEdge(dut.aclk)
    dut.s_axi_rready.value = 0
    
    dut._log.info("Read Stall Handshake test PASSED")
    dut._log.info("AXI-Lite robust decoupling fully verified!")


def system_runner():
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
        proj_path / "hdl" / "axi_retina_wrapper.sv"
    ]
    runner = get_runner(sim)
    runner.build(
        sources=sources,
        hdl_toplevel=hdl_toplevel,
        always=True,
        timescale=("1ns", "1ps"),
        parameters={"NUM_NEURONS": 16}
    )
    runner.test(
        hdl_toplevel=hdl_toplevel,
        test_module="test_axi_stress",
    )

if __name__ == "__main__":
    system_runner()
