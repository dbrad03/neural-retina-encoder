import os
import sys
from pathlib import Path
import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer

from test_golden import IzhikevichGoldenModel, c2s

@cocotb.test()
async def test_engine_pipeline(dut):
    """Test that the engine correctly pipelines back-to-back requests without structural hazards or dropped data."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    
    dut.rst_n.value = 0
    await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)
    
    golden = IzhikevichGoldenModel()
    
    dut._log.info("Starting Pipeline Alignment Test (Feeding 20 consecutive inputs)...")
    
    # We will generate 20 sets of inputs
    inputs = []
    expected = []
    
    # Base starting point
    base_v = -0x00410000
    base_u = 0
    
    for i in range(20):
        v = c2s(base_v)
        u = c2s(base_u)
        i_ext = c2s((i * 2) << 16)
        
        inputs.append((v, u, i_ext))
        
        gold_v, gold_u, gold_spike = golden.evaluate(v, u, i_ext)
        expected.append((gold_v, gold_u, gold_spike))
        
    # Drive 20 back-to-back cycles and capture concurrently
    results = []
    
    async def monitor_done():
        for _ in range(20):
            while dut.done.value == 0:
                await RisingEdge(dut.clk)
            # Capture
            results.append((
                int(dut.v_next_s.value),
                int(dut.u_next_s.value),
                int(dut.spike.value)
            ))
            await RisingEdge(dut.clk)
            
    monitor_task = cocotb.start_soon(monitor_done())
    
    for idx, (v, u, i_ext) in enumerate(inputs):
        dut.v_curr_s.value = v
        dut.u_curr_s.value = u
        dut.i_ext_s.value  = i_ext
        dut.is_midget.value = 1
        dut.start.value    = 1
        await RisingEdge(dut.clk)
        
    dut.start.value = 0
    
    await monitor_task
    
    # Verify
    for idx, (exp_v, exp_u, exp_spike) in enumerate(expected):
        rtl_v, rtl_u, rtl_spike = results[idx]
        assert rtl_v == exp_v, f"Index {idx}: V mismatch! RTL={rtl_v:05X}, Gold={exp_v:05X}"
        assert rtl_u == exp_u, f"Index {idx}: U mismatch! RTL={rtl_u:05X}, Gold={exp_u:05X}"
        assert rtl_spike == exp_spike, f"Index {idx}: Spike mismatch!"
        
    dut._log.info("Pipeline correctly executed 20 back-to-back calculations with no stalls or hazards!")

def engine_runner():
    from cocotb_tools.runner import get_runner
    hdl_toplevel = "izh_neuron_engine"
    sim = os.getenv("SIM", "icarus")
    proj_path = Path(__file__).resolve().parent.parent
    sources = [
        proj_path / "hdl" / "izh_pkg.sv",
        proj_path / "hdl" / "izh_neuron_engine.sv"
    ]
    runner = get_runner(sim)
    runner.build(
        sources=sources,
        hdl_toplevel=hdl_toplevel,
        always=True,
        timescale=("1ns", "1ps"),
    )
    runner.test(
        hdl_toplevel=hdl_toplevel,
        test_module="test_pipeline",
    )

if __name__ == "__main__":
    engine_runner()
