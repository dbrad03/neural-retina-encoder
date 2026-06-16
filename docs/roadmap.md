# Science Eye FPGA: Project Roadmap (128x128 Izhikevich Encoder)

## Phase 1: The Core Engine (Week 1)
*   **Goal:** Implement a single Izhikevich neuron in SystemVerilog using fixed-point math.
*   **Tasks:**
    *   Implement the 3-stage pipeline in `izh_neuron_engine.sv`.
    *   Verify against the C++ Golden Model using `cocotb`.
    *   **Success Metric:** RTL output matches C++ output within 1% error margin.

## Phase 2: Scaling to 16,384 Neurons (Weeks 2-3)
*   **Goal:** Use time-multiplexing to process a full 128x128 array.
*   **Tasks:**
    *   Instantiate Xilinx Dual-Port BRAM to store state ($V$ and $U$).
    *   Build the `neuron_array_controller` state machine.
    *   Handle input "Pixel Data" (Current $I$) and output "Spike Map."
*   **Success Metric:** Process all 16,384 neurons within a 1ms biological window.

## Phase 3: The "Brain's Eye View" Bridge (Week 4)
*   **Goal:** Create a real-time visualization of the spike patterns.
*   **Tasks:**
    *   Implement a simple UART or AXI-Stream interface to dump spike data.
    *   Write a Python script to reconstruct the 128x128 grid from spikes.
*   **Success Metric:** Visualizing the "Rate Adaptation" (initial burst -> steady state) on a live heat-map.

## Phase 4: Optimization & Professional Polish (Week 5)
*   **Goal:** Target Science Corp's specific hardware constraints.
*   **Tasks:**
    *   Run Vivado Synthesis/Implementation (Targeting Artix-7 or Zynq).
    *   Perform Power Analysis (aiming for <100mW).
    *   Write a "Deep Dive" README explaining the neuro-biological choices (Midget/Parasol).
*   **Success Metric:** A portfolio-ready project that solves a real Science Corp bottleneck.
