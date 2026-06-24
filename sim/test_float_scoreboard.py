"""
Float-vs-RTL accuracy scoreboard for the Izhikevich engine.

test_golden.py mirrors the RTL's exact fixed-point ops, so it only proves
*implementation consistency*. This test compares the RTL fixed-point engine to an
independent **floating-point** Izhikevich reference and bounds the error:

  1. Per-step accuracy (teacher-forced): for many random (v, u, I, cell-type)
     states, feed the SAME state to RTL and float and compare the one-step
     output. This isolates the engine's arithmetic/quantization error (no
     trajectory accumulation) and bounds it tightly.

  2. Free-running spike rate: run RTL and float as independent trajectories from
     rest under constant drive and check the spike COUNT agrees within a small
     tolerance. (Per-spike timing is intentionally NOT asserted tightly: Q8.10
     dt-integration legitimately drifts a few steps over a long inter-spike
     interval -- that drift is reported, not failed.)
"""
import os
import random
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge

A_MIDGET, D_MIDGET = 0.02, 8.0
A_PARASOL, D_PARASOL = 0.1, 2.0
B, C = 0.2, -65.0
V_THRESH, DT = 30.0, 0.1

# Per-step accuracy limits (set with margin over observed fixed-point error).
V_STEP_LIMIT = 0.20   # mV
U_STEP_LIMIT = 0.20


def to_q810(x):
    return int(round(x * 1024.0)) & 0x3FFFF

def from_q810(v):
    v &= 0x3FFFF
    return (v - (1 << 18)) / 1024.0 if (v & (1 << 17)) else v / 1024.0


def izh_float_step(v, u, i_ext, is_midget):
    a = A_MIDGET if is_midget else A_PARASOL
    d = D_MIDGET if is_midget else D_PARASOL
    if v >= V_THRESH:                         # threshold on current v (matches RTL stage 1)
        return C, u + d, True
    dv = 0.04 * v * v + 5.0 * v + 140.0 - u + i_ext
    du = a * (B * v - u)
    return v + DT * dv, u + DT * du, False


async def eval_engine(dut, v, u, i_ext, is_midget):
    """Drive one engine evaluation; return (v_next, u_next, spike) as floats/int."""
    dut.v_curr_s.value = to_q810(v)
    dut.u_curr_s.value = to_q810(u)
    dut.i_ext_s.value = to_q810(i_ext)
    dut.is_midget.value = 1 if is_midget else 0
    dut.start.value = 1
    await RisingEdge(dut.clk)
    dut.start.value = 0
    t = 0
    while dut.done.value == 0 and t < 12:
        await RisingEdge(dut.clk)
        t += 1
    assert dut.done.value == 1, "engine timed out"
    return (from_q810(int(dut.v_next_s.value)),
            from_q810(int(dut.u_next_s.value)),
            int(dut.spike.value))


@cocotb.test()
async def test_perstep_accuracy(dut):
    """Per-step fixed-point vs float error stays within tight bounds."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    dut.rst_n.value = 0
    dut.start.value = 0
    await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)

    random.seed(1)
    max_v_err = max_u_err = 0.0
    for _ in range(200):
        v = random.uniform(-70.0, 29.0)      # sub-threshold range
        u = random.uniform(-20.0, 8.0)
        I = random.uniform(0.0, 30.0)
        mid = random.choice([True, False])

        rtl_v, rtl_u, _ = await eval_engine(dut, v, u, I, mid)
        fv, fu, _ = izh_float_step(v, u, I, mid)
        max_v_err = max(max_v_err, abs(rtl_v - fv))
        max_u_err = max(max_u_err, abs(rtl_u - fu))

    dut._log.info(f"per-step max |v_err|={max_v_err:.4f} mV, max |u_err|={max_u_err:.4f}")
    assert max_v_err < V_STEP_LIMIT, f"v per-step error {max_v_err:.4f} >= {V_STEP_LIMIT}"
    assert max_u_err < U_STEP_LIMIT, f"u per-step error {max_u_err:.4f} >= {U_STEP_LIMIT}"
    dut._log.info("Per-step accuracy PASSED.")


@cocotb.test()
async def test_freerun_spike_rate(dut):
    """Independent RTL and float trajectories agree on spike count (rate)."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    dut.rst_n.value = 0
    dut.start.value = 0
    await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)

    I, N = 20.0, 300
    v_rtl, u_rtl = C, B * C
    vf, uf = C, B * C
    n_rtl = n_float = 0
    sr, sf = [], []
    for step in range(N):
        rtl_v, rtl_u, rtl_sp = await eval_engine(dut, v_rtl, u_rtl, I, True)
        vf, uf, f_sp = izh_float_step(vf, uf, I, True)
        if rtl_sp:
            n_rtl += 1; sr.append(step)
        if f_sp:
            n_float += 1; sf.append(step)
        v_rtl, u_rtl = rtl_v, rtl_u

    drift = max((abs(a - b) for a, b in zip(sr, sf)), default=0)
    dut._log.info(f"free-run spikes: RTL={n_rtl} float={n_float}, max timing drift={drift} steps")
    assert abs(n_rtl - n_float) <= 1, f"spike count diverges: {n_rtl} vs {n_float}"
    dut._log.info("Free-run spike-rate PASSED.")


def runner():
    from cocotb_tools.runner import get_runner
    hdl_toplevel = "izh_neuron_engine"
    sim = os.getenv("SIM", "icarus")
    proj_path = Path(__file__).resolve().parent.parent
    sources = [
        proj_path / "hdl" / "izh_pkg.sv",
        proj_path / "hdl" / "izh_neuron_engine.sv",
    ]
    runner = get_runner(sim)
    runner.build(sources=sources, hdl_toplevel=hdl_toplevel, always=True,
                 timescale=("1ns", "1ps"))
    runner.test(hdl_toplevel=hdl_toplevel, test_module="test_float_scoreboard")


if __name__ == "__main__":
    runner()
