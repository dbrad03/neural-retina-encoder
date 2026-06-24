"""Coverage workload for neuron type, stimulus, voltage, and spike behavior."""

import os
import random
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge
from cocotb_coverage.coverage import CoverCross, CoverPoint

from coverage_utils import FIXED_SEED, export_coverage, to_fixed_18, signed_18, safe_int


@CoverPoint("neuron.type", xf=lambda sample: sample["type"],
            bins=["midget", "parasol"], at_least=5)
@CoverPoint("neuron.stimulus", xf=lambda sample: sample["stimulus"],
            bins=["negative", "zero", "moderate", "strong"], at_least=2)
@CoverPoint("neuron.spike_outcome", xf=lambda sample: sample["spike"],
            bins=["no_spike", "spike"], at_least=2)
@CoverCross("neuron.type_x_stimulus_x_spike",
            items=["neuron.type", "neuron.stimulus", "neuron.spike_outcome"],
            ign_bins=[
                ("midget", "negative", "spike"),
                ("midget", "zero", "spike"),
                ("midget", "moderate", "spike"),
                ("parasol", "negative", "spike"),
                ("parasol", "zero", "spike"),
                ("parasol", "moderate", "spike"),
            ],
            at_least=1)
def sample_neuron(sample):
    return sample


@CoverPoint("neuron.voltage_region", xf=lambda sample: sample,
            bins=["below_reset", "reset", "subthreshold", "threshold"], at_least=1)
def sample_voltage(sample):
    return sample


async def transact(dut, is_midget, stimulus, voltage):
    dut.is_midget.value = is_midget
    dut.v_curr_s.value = to_fixed_18(voltage)
    dut.u_curr_s.value = to_fixed_18(-13.0)
    dut.i_ext_s.value = to_fixed_18(stimulus)
    dut.start.value = 1
    await RisingEdge(dut.clk)
    dut.start.value = 0
    while not safe_int(dut.done.value):
        await RisingEdge(dut.clk)

    # Read actual values back from the DUT dynamically
    is_midget_val = safe_int(dut.is_midget.value)
    cell = "midget" if is_midget_val else "parasol"

    i_ext_raw = safe_int(dut.i_ext_s.value)
    i_ext_val = signed_18(i_ext_raw)
    stim_float = i_ext_val / 1024.0
    if stim_float < 0:
        stimulus_bin = "negative"
    elif stim_float == 0:
        stimulus_bin = "zero"
    elif stim_float <= 10.0:
        stimulus_bin = "moderate"
    else:
        stimulus_bin = "strong"

    v_curr_raw = safe_int(dut.v_curr_s.value)
    v_curr_val = signed_18(v_curr_raw)
    v_curr_float = v_curr_val / 1024.0

    if v_curr_float < -65.0:
        v_region = "below_reset"
    elif v_curr_float == -65.0:
        v_region = "reset"
    elif v_curr_float >= 30.0:
        v_region = "threshold"
    else:
        v_region = "subthreshold"

    outcome = "spike" if safe_int(dut.spike.value) else "no_spike"

    sample_neuron({"type": cell, "stimulus": stimulus_bin, "spike": outcome})
    sample_voltage(v_region)
    return outcome


@cocotb.test()
async def coverage_engine(dut):
    random.seed(FIXED_SEED)
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    dut.rst_n.value = 0
    dut.start.value = 0
    await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)

    vectors = [-10.0, 0.0, 8.0, 20.0]
    for is_midget in [1, 0]:
        for stimulus in vectors:
            assert await transact(
                dut, is_midget, stimulus, -65.0
            ) == "no_spike"
        # Test spike outcome and threshold region
        assert await transact(
            dut, is_midget, 20.0, 30.0
        ) == "spike"
        # Test below_reset region
        assert await transact(
            dut, is_midget, 0.0, -70.0
        ) == "no_spike"
        # Test subthreshold region
        assert await transact(
            dut, is_midget, 0.0, -50.0
        ) == "no_spike"

    export_coverage()


def runner():
    from cocotb_tools.runner import get_runner
    root = Path(__file__).resolve().parents[2]
    runner_obj = get_runner(os.getenv("SIM", "icarus"))
    runner_obj.build(
        sources=[root / "hdl" / "izh_pkg.sv", root / "hdl" / "izh_neuron_engine.sv"],
        hdl_toplevel="izh_neuron_engine", always=True, timescale=("1ns", "1ps"),
        build_dir="sim_build/cov_engine",
    )
    runner_obj.test(hdl_toplevel="izh_neuron_engine",
                    test_module="test_cov_engine",
                    build_dir="sim_build/cov_engine")


if __name__ == "__main__":
    runner()
