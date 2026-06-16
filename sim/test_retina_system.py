import os
import sys
from pathlib import Path
import random
import numpy as np

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer, FallingEdge

# Q8.10 Fixed-point helpers
def to_fixed_18(f):
    return int(f * 1024) & 0x3FFFF

def from_fixed_18(i):
    if i & (1 << 17):
        i -= (1 << 18)
    return i / 1024.0

class MovingBallSensor:
    def __init__(self, size=128):
        self.size = size
        self.frame_count = 0

    def get_frame(self):
        # Create a 128x128 greyscale frame with a moving circle
        frame = np.zeros((self.size, self.size), dtype=np.uint8)
        
        # Calculate center based on frame count (loops across)
        cx = (self.frame_count * 2) % self.size
        cy = 64 + int(20 * np.sin(self.frame_count / 10.0))
        
        y, x = np.ogrid[:self.size, :self.size]
        mask = (x - cx)**2 + (y - cy)**2 <= 15**2
        frame[mask] = 200 # Stimulus intensity (0-255)
        
        self.frame_count += 1
        return frame

@cocotb.test()
async def test_full_frame(dut):
    """Run full frame updates with moving stimulus and broadcast to Rust."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    
    # Initialize
    dut.rst_n.value = 0
    dut.start_frame.value = 0
    dut.spike_ready.value = 1 
    await Timer(50, unit="ns")
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)

    sensor = MovingBallSensor(128)
    current_frame = np.zeros((128, 128), dtype=np.uint8)
    
    # UDP Transmitter
    import socket
    udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp_target = ("127.0.0.1", 8080)

    # Task to handle pixel input
    async def sensor_loop():
        while True:
            await RisingEdge(dut.clk)
            try:
                addr = int(dut.pixel_addr.value)
                # Map 1D addr to 2D
                y = addr // 128
                x = addr % 128
                val = float(current_frame[y, x]) / 10.0 # Scale for Izhikevich
                dut.pixel_data.value = to_fixed_18(val)
            except ValueError:
                dut.pixel_data.value = 0
            
    cocotb.start_soon(sensor_loop())

    # Spike Collector & UDP Transmitter
    async def spike_monitor():
        while True:
            await RisingEdge(dut.clk)
            if dut.spike_valid.value == 1:
                try:
                    addr = int(dut.spike_data.value) & 0x3FFF
                    # Transmit Spike: Type 1
                    packet = bytearray([1]) + addr.to_bytes(2, byteorder='big')
                    udp_sock.sendto(packet, udp_target)
                except ValueError:
                    pass
                
    cocotb.start_soon(spike_monitor())

    # Run for 300 frames to see movement and spiking
    dut._log.info("Starting Visualizer Demo (300 frames)...")
    for f in range(300):
        # Update biological stimulus
        current_frame = sensor.get_frame()
        
        # Transmit Stimulus Image: Type 2
        stim_packet = bytearray([2]) + current_frame.tobytes()
        udp_sock.sendto(stim_packet, udp_target)

        # Trigger FPGA Frame
        dut.start_frame.value = 1
        await RisingEdge(dut.clk)
        dut.start_frame.value = 0
        
        while dut.frame_done.value == 0:
            await RisingEdge(dut.clk)
        
        if f % 20 == 0:
            dut._log.info(f"Frame {f} rendered.")
        
        # We don't need a full 1ms delay in simulation realtime, just let the loop run as fast as possible
        await Timer(1, unit="us") 

    dut._log.info("Visualizer Demo Complete.")

def system_runner():
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
        parameters={"NUM_NEURONS": 16384} # Back to full size
    )
    runner.test(
        hdl_toplevel=hdl_toplevel,
        test_module="test_retina_system",
    )

if __name__ == "__main__":
    system_runner()
