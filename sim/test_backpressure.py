import os
import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer
from cocotbext.axi import AxiLiteBus, AxiLiteMaster, AxiStreamBus, AxiStreamSink

@cocotb.test()
async def test_backpressure_and_overflow(dut):
    """Test that the spike FIFO correctly drops spikes and sets overflow_seen when backpressured."""
    
    cocotb.start_soon(Clock(dut.aclk, 10, unit="ns").start())
    
    dut.aresetn.value = 0
    await Timer(50, unit="ns")
    dut.aresetn.value = 1
    await RisingEdge(dut.aclk)

    axil_master = AxiLiteMaster(AxiLiteBus.from_prefix(dut, "s_axi"), dut.aclk, dut.aresetn, reset_active_level=False)
    axis_sink = AxiStreamSink(AxiStreamBus.from_prefix(dut, "m_axis"), dut.aclk, dut.aresetn, reset_active_level=False)
    
    # Block the stream!
    axis_sink.pause = True
    
    # Write a huge pixel value to ALL 16 neurons so they all spike immediately
    # Address space is 0x00000 to 0x0FFFF. 16 neurons * 4 bytes = 64 bytes.
    huge_pixel_val = 20000 # ~19.5 in Q8.10
    
    dut._log.info("Writing huge pixels to BRAM to guarantee spikes...")
    for i in range(16):
        await axil_master.write(i * 4, huge_pixel_val.to_bytes(4, "little"))
        
    dut._log.info("Running Frame 1 (FIFO should fill up exactly to 16, no overflow yet)...")
    await axil_master.write(0x10000, b"\x01\x00\x00\x00")
    
    while dut.frame_done_irq.value == 0:
        await RisingEdge(dut.aclk)
        
    # Clear frame done
    await axil_master.write(0x10000, b"\x02\x00\x00\x00")
    await RisingEdge(dut.aclk)
    
    # Read status
    status = await axil_master.read(0x10000, 4)
    stat_val = int.from_bytes(status.data, "little")
    overflow = (stat_val >> 2) & 1
    assert overflow == 0, "Overflow should not be seen yet, FIFO is exactly full (16/16)."
    
    dut._log.info("Running frames until overflow is detected...")
    overflow = 0
    frame_count = 0
    while overflow == 0 and frame_count < 100:
        await axil_master.write(0x10000, b"\x01\x00\x00\x00")
        
        while dut.frame_done_irq.value == 0:
            await RisingEdge(dut.aclk)
            
        await axil_master.write(0x10000, b"\x02\x00\x00\x00")
        await RisingEdge(dut.aclk)
        
        status = await axil_master.read(0x10000, 4)
        stat_val = int.from_bytes(status.data, "little")
        overflow = (stat_val >> 2) & 1
        frame_count += 1
        
    assert overflow == 1, f"Overflow was NOT seen after {frame_count} frames!"
    dut._log.info(f"Overflow correctly detected and latched in AXI status register after {frame_count} frames!")
    
    # Clear overflow
    dut._log.info("Clearing overflow bit...")
    await axil_master.write(0x10000, b"\x04\x00\x00\x00") # bit 2 high
    await RisingEdge(dut.aclk)
    
    # Release backpressure
    dut._log.info("Releasing backpressure...")
    axis_sink.pause = False
    
    # Give it plenty of time to drain
    for _ in range(100):
        await RisingEdge(dut.aclk)
        
    spikes_rcv = []
    while not axis_sink.empty():
        spike = await axis_sink.recv()
        spikes_rcv.append(int.from_bytes(spike.tdata, "little"))
        
    dut._log.info(f"Received {len(spikes_rcv)} spikes: {[hex(s) for s in spikes_rcv]}")
    # The system capacity is FIFO_DEPTH (16) + 1 for the output register (spike_data/spike_valid)
    # Therefore, 17 spikes are buffered before overflow drops them!
    assert len(spikes_rcv) == 17, f"Expected 17 spikes (16 in FIFO + 1 in skid buffer), but got {len(spikes_rcv)}"
    dut._log.info("Exactly 17 spikes successfully streamed out. Excess spikes were correctly dropped.")

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
        parameters={"NUM_NEURONS": 16, "ADDR_WIDTH": 4}
    )
    runner.test(
        hdl_toplevel=hdl_toplevel,
        test_module="test_backpressure",
    )

if __name__ == "__main__":
    system_runner()
