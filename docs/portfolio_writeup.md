# Science Eye FPGA Portfolio Writeup

## Project Summary
Science Eye FPGA is a real-time retinal spiking encoder designed for visual prosthetic research. It time-multiplexes 16,384 Izhikevich neuron states in a 128x128 grid, converting physical stimulus frames into biologically *inspired* spiking dynamics (Izhikevich Midget/Parasol model) within a 1 ms frame budget.

---

## Technical Architecture

### 1. Hardware Pipeline & Time-Multiplexing
*   **Sequential Evaluation Engine (`izh_neuron_engine.sv`):** The core datapath is a deeply pipelined execution unit computing Izhikevich dynamics using resource-efficient Q8.10 fixed-point representation.
*   **Six-Stage Pipeline:** Calculates the quadratic voltage equations ($v' = 0.04v^2 + 5v + 140 - u + I$) and recovery variables ($u' = a(bv - u)$). After pipeline initialization, one neuron state is resolved per clock cycle.
*   **Time-Multiplexed Controller (`neuron_array_controller.sv`):** Sequentially streams 16,384 neuron states from inferred Block RAMs through the engine. At 100 MHz, a complete frame is computed in under 330 $\mu\text{s}$ (well within the 1 ms budget).
*   **Diamond Foveation:** Leverages coordinate distance calculations ($|x - 64| + |y - 64|$) to map foveal cells (center) to regular-spiking Midget cell dynamics and peripheral cells to adapting/bursting Parasol cell dynamics.

### 2. SoC Interface & Gated FIFO Drain
*   **AXI-Lite Register Interface (`axi_retina_wrapper.sv`):** Exposes the 16,384-word pixel BRAM and control/status registers to the Zynq ARM PS (Processing System), enabling raw `/dev/mem` memory-mapped writes.
*   **Gated AXI-Stream Spike Drain:** While scanning, spike events are buffered in an internal FIFO. Upon frame completion, the controller opens the drain and asserts `spike_last` (TLAST) on the final valid beat, so the downstream AXI-Stream FIFO IP commits the frame's spikes as one TLAST-delimited packet. (A frame with zero spikes emits no beat and therefore no packet; software must finish draining a frame before issuing the next `start`.)

---

## Hardware-Software Interface & Optimizations

The live demonstration path has been heavily optimized for lean, embedded execution on the ARM Cortex-A9 Processing System:
```
[USB UVC Camera] -> [V4L2 YUYV Capture] -> [Luma Integer Downsample] -> [Memory-Mapped PL BRAM Write] -> [RTL Execution] -> [AXI FIFO Drain] -> [UDP Broadcast] -> [Rust Quadrant Visualizer]
```

### 1. Pure V4L2 C Driver (`sw/v4l2_driver/retina_v4l2.c`)
*   **Zero OpenCV Dependency:** A lean, pure V4L2 C driver that compiles directly against standard Linux libraries with no third-party image stack, facilitating future PetaLinux distribution builds.
*   **FPU-Free Downsampling:** The camera's YUYV luma channel is downsampled and scaled to the retina Q8.10 representation in a single step using exact integer arithmetic:
    ```c
    retina_ram[gy * GRID + gx] = ((uint32_t)y * 512) / 5;
    ```
    This completely eliminates floating-point arithmetic (`y * 102.4f`) from the inner loop, optimizing execution speed on the ARM NEON unit.
*   **Reliability Features:** Incorporates non-blocking `select()` calls with 2-second timeouts on the V4L2 buffer queues to prevent driver stalls.

### 2. Real-Time Rust Visualizer (`bci_visualizer/`)
*   A high-performance UDP receiver and window renderer. It reads batched spike and stimulus UDP packets (packets `2` and `3`) to overlay instant spikes and green-decay spike persistence onto the live grayscale stimulus.

---

## Verification & Implementation Evidence

### 1. RTL Functional Verification
*   **Regression Suite:** Cocotb/Python simulation verifies the neuron datapath, the AXI interfaces, and full-array integration on Icarus Verilog.
*   **Coverage:** 12 test modules verify core math, a bit-exact fixed-point golden scoreboard, an independent float-vs-RTL accuracy scoreboard (per-step error < 0.2 mV), pipeline stage alignments, FIFO depth/overflow bounds, AXI-Lite write/read decoupling under stress, interrupt behavior, full-system integration, the DMA pixel-ingress AXI-Stream frame loader (exact-length load plus short/long-packet rejection), and the DMA-enabled wrapper (AXI-Stream frame burst into BRAM with AXI-Lite readback).
*   **Status:** All 12 tests pass.

### 2. Vivado 2025.1 Synthesis & Timing Reports
*   **Target Device:** Xilinx Zynq-7000 (`xc7z020clg400-1`).
*   **Timing:** standalone `neuron_array_controller` routes at 100 MHz with **WNS +0.449 ns** and **WHS +0.091 ns**; the full `system_wrapper` overlay (PS + AXI DMA + retina) closes at 100 MHz with **WNS +0.378 ns** and **WHS +0.018 ns** (committed routed report `vivado/system_timing_summary.txt`).
*   **Resource Utilization:** Standalone design utilizes 994 LUTs (1.87%), 724 Registers (0.68%), 25 RAMB36E1 (17.86%), and 6 DSP48E1 (2.73%).
*   **Power:** Vivado vector-less standalone estimate reports 0.289 W total on-chip power.

### 3. Board Demo
*   **Platform:** Zybo Z7-20 running PYNQ 3.0.1 (Ubuntu 22.04, kernel 5.15).
*   **Video Input:** Logitech C270 USB UVC camera connected to the J10 Host port.
*   **Measured Latency:** The PL frame evaluation (engine scan + spike-FIFO drain) completes in ~320–340 $\mu\text{s}$, well within the 1 ms biological budget. This is the **hardware processing latency, not** end-to-end camera-to-UDP — the live loop is camera-bound at ~33 ms/frame (30 fps). See `docs/validation/README.md` for the full per-stage breakdown.

---

## Resume Highlights (MIT EECS Format)
*   Designed and implemented a 128x128 foveated Izhikevich retinal ganglion cell accelerator in SystemVerilog, time-multiplexing 16,384 spiking neuron states within a 1 ms biological frame budget on a Zynq-7000 FPGA.
*   Pipelined the execution datapath into a 6-stage fixed-point execution engine, achieving 100 MHz timing closure in Vivado 2025.1 with a Worst Negative Slack (WNS) of +0.449 ns and minimal DSP slice footprint.
*   Developed a pure V4L2 C driver with a custom integer-only downsampling pipeline to eliminate floating-point arithmetic in the hot loop, streaming live USB camera input to the FPGA PL.
*   Wrote a real-time Rust UDP visualizer to process and display composites of stimulus frames and persistent spiking arrays at 60 FPS.
*   Built a 12-group Cocotb verification suite covering AXI-Lite register stress, AXI-Stream packetization, interrupts, DMA ingress, a bit-exact fixed-point scoreboard, and an independent float-vs-RTL accuracy scoreboard (per-step error < 0.2 mV).
