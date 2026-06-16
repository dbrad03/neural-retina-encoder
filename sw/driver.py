import os
import mmap
import time
import struct
import numpy as np

# These base addresses match the Vivado Address Map!
RETINA_BASE = 0x40000000 
FIFO_BASE   = 0x43C00000

# Retina Offsets
RETINA_PIXEL_RAM = 0x00000
RETINA_CONTROL   = 0x10000

# AXI4-Stream FIFO Offsets (UG732)
FIFO_ISR         = 0x00
FIFO_IER         = 0x04
FIFO_RDFO        = 0x1C  # Receive length
FIFO_RDFD        = 0x20  # Receive data

class RetinaDriver:
    def __init__(self, retina_base=RETINA_BASE, fifo_base=FIFO_BASE):
        # Open /dev/mem to access physical memory
        try:
            self.mem_fd = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
        except PermissionError:
            print("Run as root to access /dev/mem")
            raise
            
        self.retina_map = mmap.mmap(self.mem_fd, 0x20000, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE, offset=retina_base)
        self.fifo_map = mmap.mmap(self.mem_fd, 0x10000, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE, offset=fifo_base)
        
    def write_pixel(self, addr, value_q8_10):
        """Write a Q8.10 pixel value to the retina's BRAM."""
        self.retina_map.seek(RETINA_PIXEL_RAM + (addr * 4))
        self.retina_map.write(struct.pack("<I", value_q8_10))
        
    def trigger_frame(self):
        """Start the FPGA execution and wait for completion."""
        # Write 0x03 to trigger start_frame and clear the frame_done latch
        self.retina_map.seek(RETINA_CONTROL)
        self.retina_map.write(struct.pack("<I", 0x03))
        
        # Poll frame_done (bit 1)
        while True:
            self.retina_map.seek(RETINA_CONTROL)
            status = struct.unpack("<I", self.retina_map.read(4))[0]
            if (status & 0x02) != 0:
                break
                
    def read_spikes(self):
        """Read all available spikes from the AXI-Stream FIFO."""
        spikes = []
        
        # Read the receive length register
        self.fifo_map.seek(FIFO_RDFO)
        length_bytes = struct.unpack("<I", self.fifo_map.read(4))[0]
        
        if length_bytes == 0:
            return spikes
            
        # The FIFO Length is the number of bytes available.
        # Spikes are 16-bit (2 bytes), but packed into 32-bit AXI words
        num_words = length_bytes // 4
        
        self.fifo_map.seek(FIFO_RDFD)
        for _ in range(num_words):
            data = struct.unpack("<I", self.fifo_map.read(4))[0]
            # Data is 16-bit spike addr in lower 16 bits
            spikes.append(data & 0xFFFF)
            
        return spikes
        
    def close(self):
        self.retina_map.close()
        self.fifo_map.close()
        os.close(self.mem_fd)

if __name__ == "__main__":
    print("Initializing Retina Driver...")
    driver = RetinaDriver()
    
    print("Writing pixel value to addr 0...")
    driver.write_pixel(0, 20000) # ~19.5 in Q8.10
    
    for frame in range(100):
        driver.trigger_frame()
        
    spikes = driver.read_spikes()
    print(f"Spikes received after 100 frames: {len(spikes)}")
    for spike in spikes:
        print(f"Neuron {spike} fired.")
        
    driver.close()
