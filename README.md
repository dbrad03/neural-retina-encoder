# Science Eye FPGA: Foveated 128x128 Izhikevich Retina Encoder

A real-time hardware implementation of a foveated retinal ganglion cell encoder using the Izhikevich spiking neuron model, designed for the Science Eye visual prosthetic. It evaluates 16,384 neuron states sequentially/time-multiplexed within a 1ms biological timeframe on an FPGA.

## Project Overview

This project provides an end-to-end hardware-software retina encoder. The engine receives pixel stimulus inputs and emits spikes that emulate the human eye's Midget (steady response) and Parasol (bursting response) ganglion cells via diamond-foveation logic.

### Key Features
- **Large-Scale Spiking Neural Network**: 16,384 Izhikevich neurons structured in a 128x128 grid.
- **Foveated Architecture**: Biological realism is achieved by mapping Midget cells to the fovea (center) and Parasol cells to the periphery.
- **Fixed-Point Pipeline**: Q8.10 arithmetic to minimize hardware usage without sacrificing biological fidelity (verified against float models).
- **BCI Visualizer**: Real-time Rust-based visualizer for UDP stream visualization of the spiking network.

## Directory Structure
- **[`hdl/`](hdl/)**: The core SystemVerilog RTL containing the neuron engine, state memory, and array controller.
- **[`sim/`](sim/)**: Comprehensive simulation framework using Python and Cocotb to verify behavioral correctness, system bandwidth, and integration.
- **[`bci_visualizer/`](bci_visualizer/)**: A Rust UDP visualization tool capable of taking spike streams and overlaying them on stimulus inputs.
- **[`sw/v4l2_driver/`](sw/v4l2_driver/)**: Supported live-board driver using raw V4L2, `/dev/mem`, and batched UDP spike packets.
- **[`docs/`](docs/)**: In-depth architecture, biological rationale, and testing documentation.

## Documentation Index
- [System Architecture](docs/architecture.md): Hardware pipeline design and controller state machines.
- [Biological Motivation](docs/biological_motivation.md): Details on Foveated modeling and Midget/Parasol cell traits.
- [Simulation and Testing](docs/simulation_and_testing.md): Instructions on running simulations and verification results.
- [Contributing Standard](docs/CONTRIBUTING.md): A standard policy for documenting-as-you-go.

## Getting Started

### Prerequisites
- Python 3.x
- Icarus Verilog
- Rust and Cargo

### Running Tests
The RTL regression is implemented with Python/Cocotb and Icarus Verilog. The current regression target is eleven tests covering the neuron engine, fixed-point scoreboard, pipeline alignment, FIFO behavior, AXI backpressure, interrupts, foveation boundaries, AXI-Lite stress, full-system integration, the DMA pixel-ingress AXI-Stream adapter, and the DMA-enabled wrapper integration.

```bash
cd sim
source ../.venv/bin/activate
make verify
```

### Starting the Visualizer
For the live board demo or UDP-emitting simulations, run the visualizer in release mode:
```bash
cd bci_visualizer
cargo run --release
```

UDP protocol:
- packet `2`: `[2, 128*128 stimulus bytes]`
- packet `3`: `[3, count_hi, count_lo, addr_hi, addr_lo, ...]`
- packet `1`: legacy single-spike packet retained by the visualizer for compatibility

## Hardware Bringup

Physical bring-up on the Zybo Z7-20 is driven from [`deploy/README.md`](deploy/README.md),
a step-by-step runbook (PYNQ overlay → file-fed first light → UIO interrupts →
live V4L2 camera). Supporting software for bring-up lives in `sw/`:
- [`sw/first_light.py`](sw/first_light.py): file-fed, polling first-light test (no camera).
- [`sw/v4l2_driver/`](sw/v4l2_driver/): live USB-camera driver via raw V4L2 (no OpenCV dependency).
- [`sw/uio_retina.dts`](sw/uio_retina.dts): device-tree overlay exposing `frame_done_irq` as UIO.

## Status & Accomplishments

The RTL architecture is implemented, the Cocotb regression passes, and the current overlay has been board-demonstrated on a Zybo Z7-20 with both file-fed stimulus and a live UVC camera path. This is a working bring-up/demo path, not a claim of exhaustive hardware validation.

- **100MHz Timing Closure:** The standalone `neuron_array_controller` datapath routes at 100 MHz on `xc7z020clg400-1` in Vivado 2025.1 with **WNS +0.449 ns** and no failing setup/hold endpoints (`vivado/timing_report.txt`, generated 2026-06-15). A 10-directive placement sweep of the same datapath also met timing, with worst-case WNS +0.396 ns.
- **AXI-Lite & AXI-Stream Integration:** The hardware engine is wrapped in standard AMBA AXI interfaces. AXI-Lite is used for memory-mapped pixel stimulus and control, while AXI-Stream is used for the high-bandwidth 16-bit spike output.
- **Zynq SoC Block Design:** A fully automated Vivado `build_bd.tcl` script is provided to generate the entire hardware system, connecting the PL (Programmable Logic) retina IP to the PS (Processing System) ARM cores.
- **Software Driver:** The supported live path is the raw V4L2 C driver ([`sw/v4l2_driver/retina_v4l2.c`](sw/v4l2_driver/retina_v4l2.c)) plus the Rust visualizer. The C driver features an optimized downsampling pipeline using pure integer scaling (`((uint32_t)y * 512) / 5`) to eliminate floating-point arithmetic on the Zynq ARM core.
- **Verification Coverage:** Verified by Cocotb regression against Python reference behavior. Coverage includes the biological engine, full-frame controller, foveation, AXI stress testing, interrupts, and backpressure/overflow handling.
- **Board Demo Evidence:** `deploy/README.md` and `docs/validation/hardware_bringup_artifact.md` record the Zybo Z7-20 / PYNQ 3.0.1 context, overlay load, file-fed first-light run, live V4L2 camera run, and observed frame latency around 320-340 us.
