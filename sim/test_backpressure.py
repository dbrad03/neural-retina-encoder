import os
import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer
from cocotbext.axi import AxiLiteBus, AxiLiteMaster, AxiStreamBus, AxiStreamSink

STATUS_REG = 0x10000


async def read_status(axil_master):
    status = await axil_master.read(STATUS_REG, 4)
    return int.from_bytes(status.data, "little")


def packet_spikes(frame):
    data = bytes(frame.tdata)
    assert len(data) % 2 == 0, f"AXIS packet has odd byte length: {len(data)}"
    return [int.from_bytes(data[i:i + 2], "little") for i in range(0, len(data), 2)]


async def run_frame_drained(dut, axil_master, axis_sink):
    """Start one frame with the stream draining freely, wait for it to complete and
    fully drain (busy clears), and return the spikes from its single packet."""
    await axil_master.write(STATUS_REG, b"\x01\x00\x00\x00")
    while dut.frame_done_irq.value == 0:
        await RisingEdge(dut.aclk)
    await axil_master.write(STATUS_REG, b"\x02\x00\x00\x00")  # clear frame_done
    # Wait for the post-scan drain to finish (busy bit7 low) so the next start is
    # in-contract.
    for _ in range(2000):
        await RisingEdge(dut.aclk)
        if (await read_status(axil_master)) >> 7 & 1 == 0:
            break
    spikes = []
    while not axis_sink.empty():
        spikes.extend(packet_spikes(await axis_sink.recv()))
    return spikes


@cocotb.test()
async def test_start_gated_while_busy(dut):
    """A start_frame issued while the controller is busy (scanning or draining) is
    IGNORED. This proves the hardware backstop for the !busy software contract:
    an out-of-contract start cannot restart the scan mid-drain or sever the
    in-flight packet's TLAST. With backpressure held the drain stalls, so the
    controller stays busy; rogue starts during that window must be no-ops, and the
    frame must still drain as exactly one clean 16-spike packet once released.
    """
    cocotb.start_soon(Clock(dut.aclk, 10, unit="ns").start())

    dut.aresetn.value = 0
    await Timer(50, unit="ns")
    dut.aresetn.value = 1
    await RisingEdge(dut.aclk)

    axil_master = AxiLiteMaster(AxiLiteBus.from_prefix(dut, "s_axi"), dut.aclk, dut.aresetn, reset_active_level=False)
    axis_sink = AxiStreamSink(AxiStreamBus.from_prefix(dut, "m_axis"), dut.aclk, dut.aresetn, reset_active_level=False)

    # Drive every neuron hard. Izhikevich neurons need a few timesteps of this
    # input to integrate past threshold, so warm up (stream draining) until a frame
    # produces a stable, non-zero spike count -- that's our baseline packet.
    huge_pixel_val = 20000  # ~19.5 in Q8.10
    dut._log.info("Writing huge pixels to BRAM and warming up the neurons...")
    for i in range(16):
        await axil_master.write(i * 4, huge_pixel_val.to_bytes(4, "little"))

    # With identical constant input the 16 neurons fire synchronously but only on
    # isolated frames (one burst, then many silent frames). Warm up with the stream
    # draining until one frame spikes, and record that canonical spike set as the
    # reference packet.
    axis_sink.pause = False
    expected = None
    for _ in range(80):
        spikes = await run_frame_drained(dut, axil_master, axis_sink)
        if spikes:
            expected = sorted(spikes)
            break
    assert expected, "neurons never spiked during warm-up"
    dut._log.info(f"Reference spiking frame = {len(expected)} spikes: {[hex(s) for s in expected]}")

    # Now hold the stream and keep stepping frames. A silent frame drains instantly
    # (busy clears), but the next spiking frame stalls in flight with busy(bit7)
    # high -- that's the window we want to fire rogue starts into. Each frame is one
    # timestep, so the neurons keep integrating toward the next burst.
    axis_sink.pause = True
    stat_val = 0
    for _ in range(80):
        await axil_master.write(STATUS_REG, b"\x01\x00\x00\x00")
        while dut.frame_done_irq.value == 0:
            await RisingEdge(dut.aclk)
        await axil_master.write(STATUS_REG, b"\x02\x00\x00\x00")  # clear frame_done
        for _ in range(40):
            await RisingEdge(dut.aclk)
        stat_val = await read_status(axil_master)
        if (stat_val >> 7) & 1 == 1:
            break  # this frame spiked and is now stalled under backpressure

    assert (stat_val >> 7) & 1 == 1, "busy (bit7) should be high while a spiking frame stalls under backpressure"
    assert (stat_val >> 2) & 1 == 0, "no overflow expected for a single frame in a depth-16 FIFO"

    # Fire several rogue starts WHILE busy. With start-gating these are no-ops:
    # they must not restart the scan or clear frame_complete (which would cut TLAST).
    dut._log.info("Issuing rogue start_frame writes while busy (must be ignored)...")
    for _ in range(5):
        await axil_master.write(STATUS_REG, b"\x01\x00\x00\x00")
        await RisingEdge(dut.aclk)

    stat_val = await read_status(axil_master)
    assert (stat_val >> 7) & 1 == 1, "busy should remain high; a rogue start must not restart or clear the frame"
    assert (stat_val >> 2) & 1 == 0, "rogue starts must not corrupt the packet or trigger overflow"

    # Release backpressure and let the single frame drain out cleanly.
    dut._log.info("Releasing backpressure...")
    axis_sink.pause = False
    for _ in range(400):
        await RisingEdge(dut.aclk)

    packets = []
    spikes_rcv = []
    while not axis_sink.empty():
        frame = await axis_sink.recv()
        packets.append(frame)
        spikes_rcv.extend(packet_spikes(frame))

    dut._log.info(f"Received {len(packets)} packet(s), {len(spikes_rcv)} spikes: {[hex(s) for s in spikes_rcv]}")
    assert len(packets) == 1, f"Expected exactly one TLAST-delimited packet, got {len(packets)}"
    assert sorted(spikes_rcv) == expected, (
        f"Packet corrupted by rogue starts: expected {expected}, got {sorted(spikes_rcv)}"
    )

    # The frame is fully drained -> controller idle again.
    stat_val = await read_status(axil_master)
    assert (stat_val >> 7) & 1 == 0, "busy should clear once the packet has fully drained"
    dut._log.info("Start-gating-safety test PASSED: rogue starts ignored, one clean packet delivered.")


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
