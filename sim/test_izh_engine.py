import os
import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer

# Q8.10 Fixed-point helpers (for 18-bit storage ports)
def to_fixed_18(f):
    """Convert float to 18-bit Q8.10."""
    return int(f * (1 << 10))

def from_fixed_18(i):
    """Convert 18-bit Q8.10 back to float."""
    if i & (1 << 17):
        i -= (1 << 18)
    return i / (1 << 10)

@cocotb.test()
async def test_izh_integration(dut):
    """Verify RTL matches the biological behavior: Voltage should rise under stimulus."""
    # Start clock (100 MHz)
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    
    # Reset
    dut.start.value = 0
    dut.is_midget.value = 1
    dut.rst_n.value = 0
    await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)
    
    # Starting state: -65mV
    v = -65.0
    u = 0.2 * v
    i_ext = 20.0 # Increased stimulus
    
    dut._log.info("Starting integration test (50 cycles)...")
    
    for cycle in range(50):
        dut.v_curr_s.value = to_fixed_18(v)
        dut.u_curr_s.value = to_fixed_18(u)
        dut.i_ext_s.value  = to_fixed_18(i_ext)
        dut.start.value    = 1
        
        await RisingEdge(dut.clk)
        dut.start.value = 0
        
        # Wait for done (3-stage pipeline means done should hit soon)
        timeout = 0
        while dut.done.value == 0 and timeout < 10:
            await RisingEdge(dut.clk)
            timeout += 1
            
        if dut.done.value == 0:
            raise RuntimeError(f"Engine timed out at cycle {cycle}")
            
        v_next = from_fixed_18(int(dut.v_next_s.value))
        u_next = from_fixed_18(int(dut.u_next_s.value))
        
        # Log every 10 cycles
        if cycle % 10 == 0:
            dut._log.info(f"Cycle {cycle:02d}: V={v:7.3f} -> {v_next:7.3f}, U={u:7.3f}, Spike={dut.spike.value}")
        
        v = v_next
        u = u_next
        
    assert v > -65.0, f"Voltage did not rise! Final V: {v}"
    dut._log.info(f"Integration test PASSED: Final V = {v:.3f}")

def engine_runner():
    from cocotb_tools.runner import get_runner
    
    hdl_toplevel = "izh_neuron_engine"
    sim = os.getenv("SIM", "icarus")
    
    proj_path = Path(__file__).resolve().parent.parent
    sources = [
        proj_path / "hdl" / "izh_pkg.sv",
        proj_path / "hdl" / "izh_neuron_engine.sv"
    ]
    
    test_file = os.path.basename(__file__).replace(".py", "")

    runner = get_runner(sim)
    runner.build(
        sources=sources,
        hdl_toplevel=hdl_toplevel,
        always=True,
        timescale=("1ns", "1ps"), # Critical for Icarus
    )
    runner.test(
        hdl_toplevel=hdl_toplevel,
        test_module=test_file,
    )

if __name__ == "__main__":
    engine_runner()
