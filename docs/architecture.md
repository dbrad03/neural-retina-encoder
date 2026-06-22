# System Architecture

The Science Eye FPGA project uses a custom, resource-efficient hardware pipeline tailored specifically to evaluating 16,384 Izhikevich neurons within a single 1 millisecond biological timeframe.

## The Neuron Engine Pipeline (`izh_neuron_engine.sv`)
The core processing element is a deeply pipelined execution unit calculating the Izhikevich dynamics:
1. $v' = 0.04v^2 + 5v + 140 - u + I$
2. $u' = a(bv - u)$
3. Spike conditions ($v \geq 30$) trigger voltage reset and recovery variable jumps.

It uses fixed-point Q8.10 representation and a highly optimized **6-stage pipeline** to meet 100MHz on Zynq-7000. A single pipelined neuron engine is time-multiplexed across 16,384 neuron states per frame; in the post-Phase-2 implementation Vivado maps the datapath to 10 DSP48E1 slices.

## The Controller and BRAMs (`neuron_array_controller.sv` & `neuron_state_mem.sv`)
Since instantiating 16,384 distinct multipliers would exceed the capacity of practically all target FPGAs, the controller leverages Time-Multiplexing.
- The 128x128 grid is stored inside Xilinx Block RAMs (BRAMs).
- The `neuron_array_controller` loops through all 16,384 states, streaming them sequentially through the `izh_neuron_engine`.
- With a 100MHz clock, calculating the entire array takes just over $16,384$ clock cycles ($~0.16$ milliseconds), safely fitting inside the biological limit of $1$ millisecond.

## Hardware SoC Integration (`axi_retina_wrapper_v.v`)
The raw RTL is wrapped in standard AMBA AXI protocols for seamless integration into a Zynq SoC environment.
- **AXI-Lite Slave:** The pixel stimulus array (16,384 words) and hardware control registers (Start/Done latches) are memory-mapped. This allows the ARM Processing System to access the retina BRAM identically to regular DDR memory (via `/dev/mem`).
- **AXI-Stream Master:** When a neuron fires, the resulting 14-bit grid address is pushed over a high-bandwidth AXI-Stream interface. This is typically connected to an AXI-Stream FIFO IP, allowing software to read burst spikes with zero data loss.

## Software Driver
The system includes a C++ OpenCV application running in Linux user-space. It captures USB camera frames via V4L2, scales and converts them to Q8.10 format, writes directly to the memory-mapped FPGA BRAM, triggers execution, and polls the AXI-Stream FIFO for biological spikes.
