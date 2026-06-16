import os
import sys
from pathlib import Path
import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer

# Q8.10 and Q16.16 Arithmetic Constants (matching izh_pkg.sv)
IZH_A = 0x0000051E
IZH_B = 0x00003333
IZH_C = -0x00410000
IZH_D = 0x00080000

V_THRESH = 0x001E0000
V_REST   = -0x00410000

IZH_0_04 = 0x00000A3D
IZH_5    = 0x00050000
IZH_140  = 0x008C0000
IZH_DT   = 0x00001999

IZH_A_PARASOL = 0x0000199A # 0.1 in Q8.10
IZH_D_PARASOL = 0x00020000 # 2.0 in Q16.16

def sign_extend_64(val, bits=32):
    sign_bit = 1 << (bits - 1)
    return (val & (sign_bit - 1)) - (val & sign_bit)

def fp_mul(a, b):
    # Matches Q16.16 fp_mul in SV: res = (a * b) >> 16
    a_ext = sign_extend_64(a, 32)
    b_ext = sign_extend_64(b, 32)
    res = a_ext * b_ext
    return (res >> 16) & 0xFFFFFFFF

def s2c(s):
    # Q8.10 to Q16.16
    s_ext = sign_extend_64(s, 18)
    return (s_ext << 6) & 0xFFFFFFFF

def c2s(c):
    # Q16.16 to Q8.10
    c_ext = sign_extend_64(c, 32)
    return (c_ext >> 6) & 0x3FFFF

class IzhikevichGoldenModel:
    """Pure Python fixed-point reference model of the 6-stage hardware pipeline."""
    def __init__(self):
        pass
        
    def evaluate(self, v_curr_s, u_curr_s, i_ext_s, is_midget=True):
        if is_midget:
            A = IZH_A
            D = IZH_D
        else:
            A = IZH_A_PARASOL
            D = IZH_D_PARASOL
            
        # Stage 1: Convert to Q16.16
        v1 = s2c(v_curr_s)
        u1 = s2c(u_curr_s)
        i1 = s2c(i_ext_s)
        spike_reset1 = sign_extend_64(v1) >= sign_extend_64(V_THRESH)
        
        # Stage 2
        v_sq = fp_mul(v1, v1)
        v_5  = fp_mul(IZH_5, v1)
        bv   = fp_mul(IZH_B, v1)
        
        # Stage 3
        v2_04 = fp_mul(IZH_0_04, v_sq)
        v_sum_part1 = (v_5 + IZH_140) & 0xFFFFFFFF
        v_sum_part2 = (i1 - u1) & 0xFFFFFFFF
        du_diff = (bv - u1) & 0xFFFFFFFF
        
        # Stage 4
        du = fp_mul(A, du_diff)
        dv_sum = (v2_04 + v_sum_part1 + v_sum_part2) & 0xFFFFFFFF
        
        # Stage 5
        dv = fp_mul(dv_sum, IZH_DT)
        du_dt = fp_mul(du, IZH_DT)
        
        # Stage 6
        if spike_reset1:
            v_next_s = c2s(IZH_C)
            u_next_s = c2s((u1 + D) & 0xFFFFFFFF)
            spike = 1
        else:
            v_next_s = c2s((v1 + dv) & 0xFFFFFFFF)
            u_next_s = c2s((u1 + du_dt) & 0xFFFFFFFF)
            spike = 0
            
        return v_next_s, u_next_s, spike

@cocotb.test()
async def test_golden_scoreboard(dut):
    """Feed random stimuli into the engine and assert RTL exactly matches the Fixed-Point Python model."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    
    dut.rst_n.value = 0
    await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)
    
    golden = IzhikevichGoldenModel()
    
    # Starting base: -65mV
    v = c2s(V_REST)
    u = c2s(fp_mul(IZH_B, V_REST))
    
    dut._log.info("Starting Golden Model Scoreboard Test (100 cycles)...")
    
    # We will pipeline the checks.
    class Check:
        def __init__(self, exp_v, exp_u, exp_spike):
            self.exp_v = exp_v
            self.exp_u = exp_u
            self.exp_spike = exp_spike
            
    expected_queue = []
    
    for cycle in range(100):
        # Generate random stimulus between 0 and 30
        i_ext = c2s((random.randint(0, 30) << 16))
        is_midget = random.choice([0, 1])
        
        # Drive RTL
        dut.v_curr_s.value = v
        dut.u_curr_s.value = u
        dut.i_ext_s.value  = i_ext
        dut.is_midget.value = is_midget
        dut.start.value    = 1
        
        # Calculate Golden
        gold_v, gold_u, gold_spike = golden.evaluate(v, u, i_ext, is_midget=is_midget)
        expected_queue.append(Check(gold_v, gold_u, gold_spike))
        
        await RisingEdge(dut.clk)
        dut.start.value = 0
        
        # Wait for done (3-stage pipeline means done should hit soon)
        timeout = 0
        while dut.done.value == 0 and timeout < 10:
            await RisingEdge(dut.clk)
            timeout += 1
            
        if dut.done.value == 0:
            raise RuntimeError(f"Engine timed out at cycle {cycle}")
            
        # RTL Outputs
        rtl_v = int(dut.v_next_s.value)
        rtl_u = int(dut.u_next_s.value)
        rtl_spike = int(dut.spike.value)
        
        check = expected_queue.pop(0)
        
        # Assertions
        assert rtl_v == check.exp_v, f"Cycle {cycle}: V mismatch! RTL={rtl_v:05X}, Gold={check.exp_v:05X}"
        assert rtl_u == check.exp_u, f"Cycle {cycle}: U mismatch! RTL={rtl_u:05X}, Gold={check.exp_u:05X}"
        assert rtl_spike == check.exp_spike, f"Cycle {cycle}: Spike mismatch!"
        
        if cycle % 20 == 0:
            dut._log.info(f"Cycle {cycle:02d} MATCH: V={rtl_v:05X}, U={rtl_u:05X}, Spike={rtl_spike}")
            
        # Feed back RTL values for next cycle
        v = rtl_v
        u = rtl_u

    dut._log.info("Golden Scoreboard Test PASSED: RTL perfectly matches Fixed-Point model!")

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
        test_module="test_golden",
    )

if __name__ == "__main__":
    engine_runner()
