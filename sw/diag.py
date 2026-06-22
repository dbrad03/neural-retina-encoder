#!/usr/bin/env python3
"""Diagnostic: distinguish 'no spikes generated' from 'spikes stuck in FIFO'.

Writes strong uniform input, runs N frames WITHOUT draining, then reads the
overflow flag and FIFO occupancy. Interpretation:
  overflow=1, RDFO=0 -> neurons ARE spiking; FIFO not committing (TLAST broken)
  overflow=0, RDFO=0 -> neurons NOT spiking (input/state/engine issue)
  RDFO>0             -> TLAST works; spikes are committing
Run:  sudo -i ; /usr/local/share/pynq-venv/bin/python3 /home/xilinx/diag.py
"""
import time
from pynq import Overlay, MMIO

RETINA_BASE, FIFO_BASE = 0x40000000, 0x43C00000
OFF_PIX, OFF_CTRL = 0x00000, 0x10000
N = 200

Overlay("/home/xilinx/retina.bit")
r = MMIO(RETINA_BASE, 0x20000)
f = MMIO(FIFO_BASE, 0x10000)

val = int(200 * 102.4)           # strong uniform input, Q8.10
print(f"Writing uniform input {val} to all 16384 neurons ...")
for i in range(16384):
    r.write(OFF_PIX + i * 4, val)

# readback to confirm writes landed
print(f"pixel[0]={r.read(OFF_PIX)}  pixel[8256]={r.read(OFF_PIX + 8256*4)}  (expect {val})")

f.write(0x18, 0xA5)              # reset RX FIFO
r.write(OFF_CTRL, 0x2 | 0x4)    # clear done + overflow

print(f"Running {N} frames WITHOUT draining ...")
for i in range(N):
    r.write(OFF_CTRL, 0x1 | 0x2)            # start + clear done (NOT overflow)
    t = time.perf_counter() + 1.0
    while not (r.read(OFF_CTRL) & 0x2):
        if time.perf_counter() > t:
            print(f"  TIMEOUT at frame {i}")
            break

time.sleep(0.05)                 # let any final packet settle
st = r.read(OFF_CTRL)
rdfo = f.read(0x1C)
print(f"status=0x{st:08x}  done={bool(st&2)}  overflow={bool(st&4)}")
print(f"RDFO={rdfo} words")
if st & 4 and rdfo == 0:
    print(">>> Neurons ARE spiking, but FIFO not committing -> TLAST still broken.")
elif rdfo > 0:
    print(">>> TLAST works; spikes committing. Drain-side timing was the issue.")
else:
    print(">>> No spikes generated -> input/state/engine path. Investigate engine.")
