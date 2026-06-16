import os
import sys
from pathlib import Path
import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer

IZH_D = 0x00080000        # 8.0 in Q16.16
IZH_D_PARASOL = 0x00020000 # 2.0 in Q16.16

def c2s(c):
    return (c >> 6) & 0x3FFFF

@cocotb.test()
async def test_foveation_zones(dut):
    """Test that neurons inside the fovea use Midget parameters and outside use Parasol parameters."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    
    dut.rst_n.value = 0
    dut.start_frame.value = 0
    dut.clear_overflow.value = 0
    dut.spike_ready.value = 1
    await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)
    
    # We need to test specific boundaries. The diamond is defined as |x - 64| + |y - 64| < 45.
    # Boundary points:
    # 1. x=64, y=108 => |0| + |44| = 44 < 45 (Midget edge)
    # 2. x=64, y=109 => |0| + |45| = 45 >= 45 (Parasol edge)
    
    addr_midget = 64 + 108 * 128
    addr_parasol = 64 + 109 * 128
    
    # Force V to Threshold
    v_thresh_s = 0x07800
    u_init_s = 0x00000
    
    dut.state_mem_inst.v_mem[addr_midget].value = v_thresh_s
    dut.state_mem_inst.u_mem[addr_midget].value = u_init_s
    
    dut.state_mem_inst.v_mem[addr_parasol].value = v_thresh_s
    dut.state_mem_inst.u_mem[addr_parasol].value = u_init_s
    
    # Start frame
    dut.start_frame.value = 1
    await RisingEdge(dut.clk)
    dut.start_frame.value = 0
    
    # We need to monitor dbg_wr_addr and dbg_we_state
    midget_u_next = None
    parasol_u_next = None
    
    while midget_u_next is None or parasol_u_next is None:
        await RisingEdge(dut.clk)
        if dut.dbg_we_state.value == 1:
            addr = int(dut.dbg_wr_addr.value)
            if addr == addr_midget:
                midget_u_next = int(dut.u_next_s.value)
            elif addr == addr_parasol:
                parasol_u_next = int(dut.u_next_s.value)
                
    # Check results
    expected_midget_u = c2s(IZH_D)
    expected_parasol_u = c2s(IZH_D_PARASOL)
    
    assert midget_u_next == expected_midget_u, f"Midget boundary U mismatch: Expected {expected_midget_u:05X}, Got {midget_u_next:05X}"
    assert parasol_u_next == expected_parasol_u, f"Parasol boundary U mismatch: Expected {expected_parasol_u:05X}, Got {parasol_u_next:05X}"
    
    dut._log.info("Foveation Exact Boundary Test PASSED! Midgets and Parasols correctly assigned at |x-64| + |y-64| == 45 bounds.")

def foveation_runner():
    from cocotb_tools.runner import get_runner
    hdl_toplevel = "neuron_array_controller"
    sim = os.getenv("SIM", "icarus")
    proj_path = Path(__file__).resolve().parent.parent
    sources = [
        proj_path / "hdl" / "izh_pkg.sv",
        proj_path / "hdl" / "izh_neuron_engine.sv",
        proj_path / "hdl" / "neuron_state_mem.sv",
        proj_path / "hdl" / "spike_fifo.sv",
        proj_path / "hdl" / "neuron_array_controller.sv"
    ]
    runner = get_runner(sim)
    runner.build(
        sources=sources,
        hdl_toplevel=hdl_toplevel,
        always=True,
        timescale=("1ns", "1ps"),
        parameters={"NUM_NEURONS": 16384, "ADDR_WIDTH": 14}
    )
    runner.test(
        hdl_toplevel=hdl_toplevel,
        test_module="test_foveation",
    )

if __name__ == "__main__":
    foveation_runner()
