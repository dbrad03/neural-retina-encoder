import os
import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer

@cocotb.test()
async def test_fifo_simultaneous_rw_full(dut):
    """Test that reading and writing simultaneously when full preserves data and doesn't overflow."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    
    dut.rst_n.value = 0
    dut.wr_en.value = 0
    dut.rd_en.value = 0
    dut.din.value = 0
    dut.clear_overflow.value = 0
    await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)
    
    # 1. Fill FIFO with 0..15
    for i in range(16):
        dut.din.value = i
        dut.wr_en.value = 1
        await RisingEdge(dut.clk)
        
    dut.wr_en.value = 0
    
    # Wait a cycle for full to update
    await RisingEdge(dut.clk)
    assert dut.full.value == 1, "FIFO should be full"
    assert dut.overflow_seen.value == 0, "Overflow should not be seen yet"
    
    # 2. In one cycle, assert rd_en=1, wr_en=1, din=15
    dut.rd_en.value = 1
    dut.wr_en.value = 1
    dut.din.value = 15
    
    dut._log.info(f"Before clock: full={dut.full.value}, empty={dut.empty.value}, wr_ptr={dut.wr_ptr.value}, rd_ptr={dut.rd_ptr.value}")
    
    await RisingEdge(dut.clk)
    await Timer(1, "ns")
    
    dut._log.info(f"After clock: full={dut.full.value}, empty={dut.empty.value}, wr_ptr={dut.wr_ptr.value}, rd_ptr={dut.rd_ptr.value}, dout={dut.dout.value}")
    
    # First read data should be 0
    assert dut.dout.value == 0, f"Expected 0, got {dut.dout.value}"
    
    # Turn off write
    dut.wr_en.value = 0
    
    # 3. Drain remaining data
    results = [int(dut.dout.value)] # Use actual read
    for _ in range(15): # 15 more items left (1..15, 15 is 16 items, we just popped the first one)
        await RisingEdge(dut.clk)
        await Timer(1, "ns")
        results.append(int(dut.dout.value))
        
    # Read the 15
    await RisingEdge(dut.clk)
    await Timer(1, "ns")
    results.append(int(dut.dout.value))
    
    dut.rd_en.value = 0
    
    await RisingEdge(dut.clk)
    
    # 4. Expected sequence: 0..15, 15 (except 0 was popped during the simultaneous cycle)
    expected = list(range(16)) + [15]
    assert results == expected, f"Expected {expected}, got {results}"
    
    assert dut.overflow_seen.value == 0, "Overflow was incorrectly set during simultaneous read/write!"
    
    dut._log.info("Simultaneous read/write on full FIFO test PASSED!")

def fifo_runner():
    from cocotb_tools.runner import get_runner
    hdl_toplevel = "spike_fifo"
    sim = os.getenv("SIM", "icarus")
    proj_path = Path(__file__).resolve().parent.parent
    sources = [
        proj_path / "hdl" / "spike_fifo.sv",
    ]
    runner = get_runner(sim)
    runner.build(
        sources=sources,
        hdl_toplevel=hdl_toplevel,
        always=True,
        timescale=("1ns", "1ps"),
        parameters={"FIFO_DEPTH": 16, "ADDR_WIDTH": 4}
    )
    runner.test(
        hdl_toplevel=hdl_toplevel,
        test_module="test_spike_fifo",
    )

if __name__ == "__main__":
    fifo_runner()
