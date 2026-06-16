# Science Eye FPGA: Foveated 128x128 Izhikevich Retina Encoder

A real-time hardware implementation of a foveated retinal ganglion cell encoder using the Izhikevich spiking neuron model, designed for the Science Eye visual prosthetic. It evaluates 16,384 neuron states sequentially/time-multiplexed within a 1ms biological timeframe on an FPGA.

## Project Overview

This project provides a complete end-to-end hardware-software system for simulating a retina. The engine receives "pixel" inputs and emits "spikes" that emulate the human eye's Midget (steady response) and Parasol (bursting response) ganglion cells via diamond-foveation logic.

### Key Features
- **Large-Scale Spiking Neural Network**: 16,384 Izhikevich neurons structured in a 128x128 grid.
- **Foveated Architecture**: Biological realism is achieved by mapping Midget cells to the fovea (center) and Parasol cells to the periphery.
- **Fixed-Point Pipeline**: Q8.10 arithmetic to minimize hardware usage without sacrificing biological fidelity (verified against float models).
- **BCI Visualizer**: Real-time Rust-based visualizer for UDP stream visualization of the spiking network.

## Directory Structure
- **[`hdl/`](hdl/)**: The core SystemVerilog RTL containing the neuron engine, state memory, and array controller.
- **[`sim/`](sim/)**: Comprehensive simulation framework using Python and Cocotb to verify behavioral correctness, system bandwidth, and integration.
- **[`bci_visualizer/`](bci_visualizer/)**: A Rust UDP visualization tool capable of taking spike streams and overlaying them on stimulus inputs.
- **[`docs/`](docs/)**: In-depth architecture, biological rationale, and testing documentation.

## Documentation Index
- [System Architecture](docs/architecture.md): Hardware pipeline design and controller state machines.
- [Biological Motivation](docs/biological_motivation.md): Details on Foveated modeling and Midget/Parasol cell traits.
- [Simulation and Testing](docs/simulation_and_testing.md): Instructions on running simulations and verification results.
- [Project Roadmap](docs/roadmap.md): Current progression of the project.
- [Contributing Standard](docs/CONTRIBUTING.md): A standard policy for documenting-as-you-go.

## Getting Started

### Prerequisites
- Python 3.x
- Icarus Verilog
- Rust and Cargo

### Running Tests
All tests are implemented via Python/Cocotb. We have re-verified that all claimed properties (biological engine behavior, full 128x128 array multiplexing) are completely functional and pass cleanly.

```bash
cd sim
source ../.venv/bin/activate
python test_izh_engine.py
python test_retina_system.py
```

### Starting the Visualizer
To see the spiking activity broadcasted from the `test_retina_system.py` test:
```bash
cd bci_visualizer
cargo run
```

## Status & Accomplishments

The full RTL architecture is implemented and **Pre-silicon verified through RTL simulation, synthesis, and routed implementation.**
- **100MHz Timing Closure:** Implemented a deeply-optimized 6-stage execution pipeline to hit 100MHz FMAX on a Zynq-7000 (Zybo Z7-20). A single pipelined neuron engine is time-multiplexed across 16,384 neuron states per frame; Vivado maps the datapath to 6 DSP48E1 slices *(Note: numbers reflect last routed implementation before Phase 2 RTL changes)*.
- **AXI-Lite & AXI-Stream Integration:** The hardware engine is wrapped in standard AMBA AXI interfaces. AXI-Lite is used for memory-mapped pixel stimulus and control, while AXI-Stream is used for the high-bandwidth 16-bit spike output.
- **Zynq SoC Block Design:** A fully automated Vivado `build_bd.tcl` script is provided to generate the entire hardware system, connecting the PL (Programmable Logic) retina IP to the PS (Processing System) ARM cores.
- **Software Driver:** Includes both a bare-metal Python driver and a high-performance **C++ OpenCV Driver** (`sw/c_driver/main.cpp`) that captures a live physical USB webcam feed, pushes it directly into the FPGA via `/dev/mem`, and streams the biological spikes over UDP.
- **Verification Coverage:** Strongly verified by Cocotb regression. Verifies the biological engine, full-frame controller, Foveation, AXI stress testing, interrupts, and backpressure/overflow handling against a golden Python scoreboard.
