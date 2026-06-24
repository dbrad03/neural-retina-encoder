"""Coverage workload for neuron math, foveation, starts, and spike packets."""

import os
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge
from cocotb_coverage.coverage import CoverCross, CoverPoint
from coverage_utils import export_coverage, to_fixed_18, safe_int


@CoverPoint("controller.foveation_region", xf=lambda sample: sample,
            bins=["center", "distance_44", "distance_45", "periphery", "corner"],
            at_least=1)
def sample_foveation(sample):
    return sample


@CoverPoint("controller.start_state", xf=lambda sample: sample["state"],
            bins=["idle", "scanning", "draining"], at_least=1)
@CoverPoint("controller.start_outcome", xf=lambda sample: sample["outcome"],
            bins=["accepted", "ignored"], at_least=1)
@CoverCross("controller.start_state_x_outcome",
            items=["controller.start_state", "controller.start_outcome"],
            ign_bins=[("idle", "ignored"), ("scanning", "accepted"),
                      ("draining", "accepted")],
            at_least=1)
def sample_start(sample):
    return sample


@CoverPoint("axis.frame_spike_count", xf=lambda sample: sample,
            bins=["zero", "one", "many"], at_least=1)
def sample_frame_count(sample):
    return sample


@CoverPoint("axis.stall_duration", xf=lambda sample: sample,
            bins=["zero", "one", "many"], at_least=1)
def sample_stall(sample):
    return sample


async def reset(dut):
    dut.rst_n.value = 0
    dut.start_frame.value = 0
    dut.pixel_data.value = 0
    dut.spike_ready.value = 1
    dut.clear_overflow.value = 0
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)


def get_foveation_region(addr: int) -> str:
    x = addr % 128
    y = addr // 128
    dx = abs(x - 64)
    dy = abs(y - 64)
    dist = dx + dy
    if dist == 0:
        return "center"
    elif dist == 44:
        return "distance_44"
    elif dist == 45:
        return "distance_45"
    elif dist == 128:
        return "corner"
    else:
        return "periphery"


async def run_frame(dut, threshold_addrs=(), stall_cycles=0, test_busy_starts=False):
    for addr in threshold_addrs:
        dut.state_mem_inst.v_mem[addr].value = to_fixed_18(30.0)

    async def trigger_and_sample_start():
        busy_before = safe_int(dut.busy.value)
        state_before = safe_int(dut.state.value)
        
        state_str = "idle"
        if busy_before:
            state_str = "scanning" if state_before == 1 else "draining"
        outcome_str = "ignored" if busy_before else "accepted"
        
        dut.start_frame.value = 1
        await RisingEdge(dut.clk)
        dut.start_frame.value = 0
        sample_start({"state": state_str, "outcome": outcome_str})

    await trigger_and_sample_start()
    await RisingEdge(dut.clk)
    assert safe_int(dut.busy.value) == 1

    if test_busy_starts:
        await trigger_and_sample_start()
        await RisingEdge(dut.clk)
        assert safe_int(dut.busy.value) == 1

    max_stall = 0
    current_stall = 0

    writebacks = {}
    while not safe_int(dut.frame_done.value):
        await RisingEdge(dut.clk)
        if safe_int(dut.dbg_we_state.value):
            addr = safe_int(dut.dbg_wr_addr.value)
            if addr in threshold_addrs:
                writebacks[addr] = safe_int(dut.u_next_s.value)

    spikes = []
    if threshold_addrs:
        # Keep ready = 0 from the start to prevent early handshake
        dut.spike_ready.value = 0
        
        # Wait until the spike actually appears on the bus (while keeping ready = 0)
        while not safe_int(dut.spike_valid.value):
            await RisingEdge(dut.clk)
        
        if test_busy_starts:
            await trigger_and_sample_start()
            await RisingEdge(dut.clk)
            assert safe_int(dut.busy.value) == 1
        for _ in range(stall_cycles):
            if safe_int(dut.spike_valid.value):
                current_stall += 1
                if current_stall > max_stall:
                    max_stall = current_stall
                held = safe_int(dut.spike_data.value)
                await RisingEdge(dut.clk)
                assert safe_int(dut.spike_valid.value) == 1
                assert safe_int(dut.spike_data.value) == held
            else:
                current_stall = 0
                await RisingEdge(dut.clk)
        dut.spike_ready.value = 1

    for _ in range(200):
        await RisingEdge(dut.clk)
        if safe_int(dut.spike_valid.value) and safe_int(dut.spike_ready.value):
            spikes.append(safe_int(dut.spike_data.value))
            current_stall = 0
        elif safe_int(dut.spike_valid.value) and not safe_int(dut.spike_ready.value):
            current_stall += 1
            if current_stall > max_stall:
                max_stall = current_stall
        else:
            current_stall = 0
        if not safe_int(dut.busy.value):
            break
    assert not safe_int(dut.busy.value), "frame did not finish draining"

    # Sample stall duration dynamically
    if max_stall == 0:
        sample_stall("zero")
    elif max_stall == 1:
        sample_stall("one")
    else:
        sample_stall("many")

    # Sample frame spike count dynamically
    spike_cnt = len(spikes)
    if spike_cnt == 0:
        sample_frame_count("zero")
    elif spike_cnt == 1:
        sample_frame_count("one")
    else:
        sample_frame_count("many")

    return spikes, writebacks


@cocotb.test()
async def coverage_neuron_controller(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await reset(dut)

    foveation_points = {
        64 + 64 * 128: "center",
        64 + 108 * 128: "distance_44",
        64 + 109 * 128: "distance_45",
        64 + 120 * 128: "periphery",
        0: "corner",
    }
    foveation_spikes, foveation_writebacks = await run_frame(
        dut, tuple(foveation_points), 0
    )
    assert sorted(foveation_spikes) == sorted(foveation_points)
    midget_u = to_fixed_18(-5.0) & 0x3FFFF
    parasol_u = to_fixed_18(-11.0) & 0x3FFFF
    expected_u = {
        "center": midget_u,
        "distance_44": midget_u,
        "distance_45": parasol_u,
        "periphery": parasol_u,
        "corner": parasol_u,
    }
    assert set(foveation_writebacks) == set(foveation_points)
    for addr, region in foveation_points.items():
        assert foveation_writebacks[addr] == expected_u[region], (
            f"{region} at address {addr} used the wrong neuron parameters"
        )
    for spike in foveation_spikes:
        sample_foveation(get_foveation_region(spike))
    for addr in foveation_points:
        dut.state_mem_inst.v_mem[addr].value = to_fixed_18(-65.0)
        dut.state_mem_inst.u_mem[addr].value = to_fixed_18(-13.0)

    zero, _ = await run_frame(dut, (), 0)
    assert zero == []

    one, _ = await run_frame(dut, (10,), 1)
    assert one == [10]

    many, _ = await run_frame(dut, (20, 21, 22), 4, test_busy_starts=True)
    assert sorted(many) == [20, 21, 22]

    export_coverage()


def runner():
    from cocotb_tools.runner import get_runner
    root = Path(__file__).resolve().parents[2]
    sources = [
        root / "hdl" / "izh_pkg.sv",
        root / "hdl" / "izh_neuron_engine.sv",
        root / "hdl" / "neuron_state_mem.sv",
        root / "hdl" / "spike_fifo.sv",
        root / "hdl" / "neuron_array_controller.sv",
    ]
    runner_obj = get_runner(os.getenv("SIM", "icarus"))
    runner_obj.build(
        sources=sources, hdl_toplevel="neuron_array_controller", always=True,
        timescale=("1ns", "1ps"),
        parameters={"NUM_NEURONS": 16384, "ADDR_WIDTH": 14},
        build_dir="sim_build/cov_neuron",
    )
    runner_obj.test(
        hdl_toplevel="neuron_array_controller", test_module="test_cov_neuron",
        build_dir="sim_build/cov_neuron",
    )


if __name__ == "__main__":
    runner()
