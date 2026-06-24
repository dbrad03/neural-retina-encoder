import os
import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer
from cocotbext.axi import AxiLiteBus, AxiLiteMaster, AxiStreamBus, AxiStreamSink

@cocotb.test()
async def test_axi_operations(dut):
    """Test AXI-Lite registers, BRAM writes, and AXI-Stream spikes."""
    
    # Start clock
    cocotb.start_soon(Clock(dut.aclk, 10, unit="ns").start())
    
    # Initialize resets
    dut.aresetn.value = 0
    await Timer(50, unit="ns")
    dut.aresetn.value = 1
    await RisingEdge(dut.aclk)

    # Initialize AXI interfaces
    axil_master = AxiLiteMaster(AxiLiteBus.from_prefix(dut, "s_axi"), dut.aclk, dut.aresetn, reset_active_level=False)
    axis_sink = AxiStreamSink(AxiStreamBus.from_prefix(dut, "m_axis"), dut.aclk, dut.aresetn, reset_active_level=False)
    
    # Write a test pixel to offset 0x00000 (RAM byte addr 0)
    test_pixel_val = 20000 # ~19.5 in Q8.10 format
    await axil_master.write(0x00000, test_pixel_val.to_bytes(4, "little"))
    
    # Write another pixel to word address 1 (byte offset 0x00004)
    await axil_master.write(0x00004, (25000).to_bytes(4, "little"))
    
    # Read back to verify BRAM mapped properly
    readback = await axil_master.read(0x00000, 4)
    assert int.from_bytes(readback.data, "little") == test_pixel_val, "BRAM readback failed"

    # Write multiple times to charge up the neuron so it spikes
    for f in range(100):
        # Wait until the controller is no longer busy (status bit7) before
        # starting; starting while a prior frame is still draining would cut the
        # in-flight packet's TLAST (the documented software contract).
        while True:
            status = int.from_bytes((await axil_master.read(0x10000, 4)).data, "little")
            if not (status & 0x80):
                break
            await Timer(5, unit="us")

        # Trigger start_frame at offset 0x10000 (Bit 0) and clear frame_done (Bit 1)
        await axil_master.write(0x10000, b"\x03\x00\x00\x00")

        # Poll frame_done (Bit 1)
        frame_done = False
        while not frame_done:
            status_bytes = await axil_master.read(0x10000, 4)
            status = int.from_bytes(status_bytes.data, "little")
            frame_done = (status & 0x2) != 0
            await Timer(5, unit="us")
            
    dut._log.info("Frames processed successfully!")
    
    # Check if we got spikes! The neuron at address 1 had value 200, it should spike after 20 frames!
    assert not axis_sink.empty(), "No spikes received from AXI-Stream!"
    
    spikes_received = 0
    while not axis_sink.empty():
        spike = await axis_sink.recv()
        spike_addr = int.from_bytes(spike.tdata, "little")
        dut._log.info(f"Received spike on neuron address: {spike_addr}")
        spikes_received += 1
        
    dut._log.info(f"Total spikes successfully streamed: {spikes_received}")


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
        parameters={"NUM_NEURONS": 128} # Small size for extremely fast polling test
    )
    runner.test(
        hdl_toplevel=hdl_toplevel,
        test_module="test_axi_wrapper",
    )

if __name__ == "__main__":
    system_runner()
