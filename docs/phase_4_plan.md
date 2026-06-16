# Phase 4 Plan: Hardware Optimization & Synthesis

With the biological and system-level verification complete (Phase 1-3), Phase 4 focuses on proving this design can run efficiently on real silicon, specifically targeting the power and area constraints of a neural implant.

## Current State
- **Completed from Phase 4 roadmap:** The "Deep Dive" documentation explaining the neuro-biological choices (Midget/Parasol cells) has already been written (`docs/biological_motivation.md`).
- **Remaining Tasks:** Vivado Synthesis and Power Analysis.

## Step-by-Step Execution Plan

### Step 1: Create Vivado Project and Constraint Files
- Initialize a new Vivado project inside the empty `vivado/` directory.
- Target a low-power, small-footprint Xilinx FPGA (e.g., Artix-7 or Zynq-7000 series).
- Create an XDC (Xilinx Design Constraints) file to define the target clock speed (e.g., 100MHz).

### Step 2: Synthesis and Area (Utilization) Analysis
- Run Vivado Synthesis on the `hdl/` source files (`izh_pkg.sv`, `izh_neuron_engine.sv`, `neuron_state_mem.sv`, `spike_fifo.sv`, `neuron_array_controller.sv`).
- **Goal:** Review the Utilization Report to ensure the design fits comfortably.
- **Key Metric:** Verify that the Block RAM (BRAM) usage is sufficient for the 16,384 neuron states and that the DSP usage (if any) is within limits (though our Q8.10 fixed-point design should heavily reduce DSP reliance).

### Step 3: Implementation and Timing Closure
- Run Vivado Implementation (Place and Route).
- Review the Timing Summary.
- **Goal:** Ensure there are no Negative Slack (WNS/TNS) violations at our target 100MHz clock. The 3-stage pipeline in the `izh_neuron_engine` should easily meet this, but routing congestion around the BRAMs must be checked.

### Step 4: Power Analysis
- Generate a Switching Activity Interchange Format (SAIF) file from a realistic simulation run (e.g., `test_retina_system.py`) to capture true toggle rates of the nodes.
- Import the SAIF file into Vivado's Power Analyzer.
- **Goal:** Achieve a total on-chip power of **< 100mW**, which is critical for implantable devices to prevent thermal tissue damage.
- **Optimization (if needed):** If power is too high, investigate clock gating for the engine pipeline or reducing the BRAM clock frequency when inactive.

### Step 5: Final Portfolio Polish
- Export the Utilization, Timing, and Power reports.
- Summarize the hardware metrics into a new document (`docs/hardware_metrics.md`) or append to the `README.md`.
- Conclude the project!
