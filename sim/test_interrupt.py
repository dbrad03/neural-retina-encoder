import os
import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer
from cocotbext.axi import AxiLiteBus, AxiLiteMaster

@cocotb.test()
async def test_interrupt_latch_and_clear(dut):
    """Test that frame_done_irq acts as a latched interrupt and clears correctly."""
    
    cocotb.start_soon(Clock(dut.aclk, 10, unit="ns").start())
    
    dut.aresetn.value = 0
    await Timer(50, unit="ns")
    dut.aresetn.value = 1
    await RisingEdge(dut.aclk)

    axil_master = AxiLiteMaster(AxiLiteBus.from_prefix(dut, "s_axi"), dut.aclk, dut.aresetn, reset_active_level=False)
    
    assert dut.frame_done_irq.value == 0, "Interrupt should be 0 on reset"
    
    # Start a frame (Write 1 to bit 0 of 0x10000)
    await axil_master.write(0x10000, b"\x01\x00\x00\x00")
    
    # Wait for interrupt
    timeout = 0
    while dut.frame_done_irq.value == 0:
        await RisingEdge(dut.aclk)
        timeout += 1
        if timeout > 10000:
            raise RuntimeError("Frame never completed")
            
    dut._log.info("frame_done_irq asserted!")
    
    # Wait 100 cycles to prove it STAYS high (latched)
    for _ in range(100):
        await RisingEdge(dut.aclk)
        assert dut.frame_done_irq.value == 1, "Interrupt fell! It is not latched!"
        
    dut._log.info("Interrupt remained latched correctly.")
    
    # Clear the interrupt (Write 1 to bit 1, while keeping bit 0 low so we don't start a new frame)
    await axil_master.write(0x10000, b"\x02\x00\x00\x00")
    
    await RisingEdge(dut.aclk)
    await RisingEdge(dut.aclk)
    await RisingEdge(dut.aclk)
    
    assert dut.frame_done_irq.value == 0, "Interrupt did not clear after write!"
    dut._log.info("Interrupt cleared successfully via AXI-Lite.")
    
    # Start a new frame while clearing at the same time (Write 1 to bit 0 and 1)
    await axil_master.write(0x10000, b"\x03\x00\x00\x00")
    
    while dut.frame_done_irq.value == 0:
        await RisingEdge(dut.aclk)
        
    assert dut.frame_done_irq.value == 1, "Interrupt did not assert for second frame"
    dut._log.info("Second frame completed and latched successfully.")

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
        parameters={"NUM_NEURONS": 16} # Tiny grid for fast interrupt test
    )
    runner.test(
        hdl_toplevel=hdl_toplevel,
        test_module="test_interrupt",
    )

if __name__ == "__main__":
    system_runner()
