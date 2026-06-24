# System Architecture

The Science Eye FPGA project uses a custom, resource-efficient hardware pipeline tailored specifically to evaluating 16,384 Izhikevich neurons within a single 1 millisecond biological timeframe.

## The Neuron Engine Pipeline (`izh_neuron_engine.sv`)
The core processing element is a deeply pipelined execution unit calculating the Izhikevich dynamics:
1. $v' = 0.04v^2 + 5v + 140 - u + I$
2. $u' = a(bv - u)$
3. Spike conditions ($v \geq 30$) trigger voltage reset and recovery variable jumps.

It uses fixed-point Q8.10 representation and a highly optimized **6-stage pipeline** to meet 100MHz on Zynq-7000. A single pipelined neuron engine is time-multiplexed across 16,384 neuron states per frame. The current standalone `neuron_array_controller` routed report maps the datapath to 6 DSP48E1 slices; a separate placement sweep configuration reports 10 DSP48E1 slices. Treat utilization numbers as report-specific.

## The Controller and BRAMs (`neuron_array_controller.sv` & `neuron_state_mem.sv`)
Since instantiating 16,384 distinct multipliers would exceed the capacity of practically all target FPGAs, the controller leverages Time-Multiplexing.
- The 128x128 grid is stored inside Xilinx Block RAMs (BRAMs).
- The `neuron_array_controller` loops through all 16,384 states, streaming them sequentially through the `izh_neuron_engine`.
- With a 100MHz clock, calculating the entire array takes just over $16,384$ clock cycles ($~0.16$ milliseconds), safely fitting inside the biological limit of $1$ millisecond.

## Hardware SoC Integration (`axi_retina_wrapper_v.v`)
The raw RTL is wrapped in standard AMBA AXI protocols for seamless integration into a Zynq SoC environment.
- **AXI-Lite Slave:** The pixel stimulus array (16,384 words) and hardware control registers (Start/Done latches) are memory-mapped. This allows the ARM Processing System to access the retina BRAM identically to regular DDR memory (via `/dev/mem`).
- **AXI-Stream Master:** When a neuron fires, the resulting 14-bit grid address is pushed over a high-bandwidth AXI-Stream interface. This is typically connected to an AXI-Stream FIFO IP, allowing software to read burst spikes with zero data loss.

## Optional DMA Stimulus-Input Path (`axis_pixel_ingress.sv`)
The default stimulus path writes the 16,384-word pixel frame through AXI-Lite
(one 32-bit `/dev/mem` store per neuron). When the wrapper is built with
`USE_DMA_INGRESS=1`, the design also accepts a whole frame as a single AXI DMA
MM2S burst:

`PS DDR buffer -> AXI DMA MM2S -> axis_pixel_ingress -> pixel BRAM`

`axis_pixel_ingress` accepts the AXI-Stream beats and writes them sequentially
into the pixel BRAM (beat *i* -> address *i*), enforcing one TLAST-delimited
packet per frame: a correct-length packet pulses `frame_loaded`, a TLAST that is
early/late is rejected as `err_short`/`err_long`, and these latch into status
register bits 3-5. DMA writes are arbitrated **above** the AXI-Lite write on the
shared BRAM port, so the legacy `/dev/mem` path still works whenever the DMA
stream is idle (the DMA path is strictly additive). The Vivado block design adds
the `axi_dma_0` IP and the PS `S_AXI_HP0` port (`vivado/build_bd.tcl`); the
board-side demo is `sw/first_light_dma.py` (PYNQ `allocate()` +
`dma.sendchannel.transfer()`). This path is RTL- and integration-verified in
simulation AND board-validated on the Zybo Z7-20 (2026-06-23): the DMA overlay
loads, `dma_frame_loaded` asserts after the burst, the full `system_wrapper`
timing closes at 100 MHz (WNS +0.346 ns, WHS +0.015 ns; routed report committed
as `vivado/system_timing_summary.txt`), and a timing benchmark
(`sw/bench_timing.py`) measured the
pixel load dropping from 312 ms to 0.73 ms vs the AXI-Lite loop — though that
gap is largely Python MMIO overhead; see `docs/validation/README.md` for the
full breakdown and caveats.

## Supported Live Software Path
The supported live board path is:

`UVC camera -> raw V4L2 YUYV capture -> 128x128 Q8.10 pixel RAM -> RTL frame evaluation -> AXI-Stream FIFO -> batched UDP spikes -> Rust visualizer`

The board-side driver is `sw/v4l2_driver/retina_v4l2.c`. It captures YUYV frames without OpenCV, downsamples luma to the 128x128 retina grid using an optimized FPU-free integer-scaling mapping (`((uint32_t)y * 512) / 5`), writes Q8.10 stimulus values through `/dev/mem`, triggers the RTL frame, drains the AXI-Stream FIFO, and sends UDP packets to `bci_visualizer`.

The UDP protocol is intentionally small:
- packet `2`: `1 + 128*128` bytes, `[2, stimulus...]`
- packet `3`: batched spikes, `[3, count_hi, count_lo, addr_hi, addr_lo, ...]`
- packet `1`: legacy single-spike packet still accepted by the visualizer
