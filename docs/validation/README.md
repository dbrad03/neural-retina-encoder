# Validation Status

This repository contains RTL simulation evidence, Vivado routed implementation reports, and a board-demonstrated Zybo Z7-20 bring-up path.

Current claim boundaries:
- **Cocotb RTL regression:** `make verify` covers twelve tests and is the source for functional RTL verification claims. Latest local run: 2026-06-24, all twelve tests passed (including the 300-frame full system integration test, the DMA pixel-ingress AXI-Stream adapter, the DMA-enabled wrapper integration test, and the float-vs-RTL accuracy scoreboard).
- **Fixed-point accuracy:** two complementary checks. `test_golden.py` is a **bit-exact** check against a fixed-point reference (implementation consistency). `test_float_scoreboard.py` is the **accuracy** check against an independent **floating-point** Izhikevich reference, with explicit limits: per-step membrane error < 0.2 mV (observed ~0.005 mV) and matching free-run spike rate. Note: over long inter-spike intervals the fixed-point dt-integration legitimately drifts a few steps in spike *timing* — that drift is reported, not asserted tightly. (An offline characterization also exists in `sim/fixed_point_compare.cpp`.)
- **Integration test (scope):** `test_retina_system` verifies frame completion and post-frame FIFO drain sequencing (an integration/smoke test); it does not assert value-level state, spike addresses/counts, or TLAST placement — those are covered by `test_izh_engine`/`test_golden`/`test_spike_fifo`. It is not a measured-coverage sign-off.
- **Spike packetization (caveats):** the design emits one TLAST-delimited packet per frame **that produces ≥1 spike**; a zero-spike frame emits no beat and therefore no packet (software treats RDFO==0 as "no spikes this frame"). Software should finish draining a frame's packet before the next `start` and polls the **drain-busy status bit (bit7)** to do so. As a hardware backstop, a `start` issued while busy (scanning or draining) is now **ignored** — it can no longer restart the scan mid-drain or clear the drain gate and cut a still-in-flight packet's TLAST. The `!busy` software handshake remains the intended contract; the gate just makes an out-of-contract start a safe no-op. Verified by `sim/test_backpressure.py` (rogue starts fired at a stalled frame still yield one clean TLAST-delimited packet); the FIFO spike-drop/overflow path — now unreachable via the start interface — is covered directly by `sim/test_spike_fifo.py`.
- **AXI-Lite / DMA BRAM arbitration (caveat):** with `USE_DMA_INGRESS`, a DMA pixel beat has unconditional priority on the shared BRAM port. The two paths are not meant to be used concurrently (DMA replaces the per-pixel AXI-Lite writes); a simultaneous AXI-Lite access during an active DMA transfer is overridden and still returns OKAY (no SLVERR). It is no longer *silent*, though: such a collision is latched into a sticky **status bit6** so software can detect a contract violation after the fact. This is observability, not full arbitration — do not issue AXI-Lite pixel writes/reads while a DMA transfer is in flight.
- **DMA stimulus-input path:** board-validated on Zybo Z7-20 (2026-06-23). The DMA-enabled overlay (`axi_dma_0` on PS HP0) loads, `dma_frame_loaded` (status bit3) asserts after the burst, and the retina computes identical output to the AXI-Lite path. See the timing benchmark below.
- **Timing/utilization:** two routed reports are tracked. (1) Standalone datapath: `vivado/timing_report.txt` / `util_report.txt` are routed `neuron_array_controller` reports from Vivado 2025.1 — **WNS +0.449 ns, WHS +0.091 ns** at 100 MHz. (2) Full overlay: `vivado/system_timing_summary.txt` / `system_util_summary.txt` are the routed `system_wrapper` reports emitted by `build_bd.tcl` on each bitstream build — **WNS +0.346 ns, WHS +0.015 ns** at 100 MHz (this supersedes the earlier uncommitted +0.305 figure; the worst setup path is `controller_inst/engine_inst/du_reg[29]`). The start-gating change adds a single combinational term to the start path; the full-wrapper timing sweep (`timing_sweep_v2.tcl`, Pass B) re-confirms closure on the gated RTL.
- **Power:** `vivado/power_report.txt` is a vector-less standalone PL-only estimate (0.289 W, Low confidence). 
- **Board demo:** The Zybo Z7-20 overlay loads and the file-fed plus live V4L2 camera paths work in the bring-up environment documented in `hardware_bringup_artifact.md`.

Do not describe the project as fully hardware validated unless additional board-level stress, temperature/voltage margin sweep, and regression artifacts are added.

---

## Timing Benchmark — Pixel-Load Path (AXI-Lite vs DMA)

Measured on Zybo Z7-20, PYNQ 3.0.1, 100 MHz PL, via `sw/bench_timing.py`
(2026-06-23, median of 100 reps; AXI-Lite load = 20 reps; ~316 spikes/frame):

| Stage (per frame) | AXI-Lite path | DMA path |
| :--- | ---: | ---: |
| Pixel load | 312 ms | 0.73 ms |
| PL frame compute (scan) | 0.31 ms | 0.31 ms |
| FIFO spike drain | 3.0 ms | 3.0 ms |
| **Loop total → fps** | **315 ms → 3.2 fps** | **4.1 ms → 245 fps** |

Pixel-load speedup: **~425×** (312 ms → 0.73 ms). Full-loop: ~77× in the
per-frame-reload (live-video) case.

**Important caveats — these are PYNQ/Python numbers, not pure hardware:**
- The 312 ms AXI-Lite load is dominated by Python per-call MMIO overhead
  (~19 µs × 16,384 writes), *not* the bus. The C driver does these writes in
  compiled code, so its AXI-Lite load is far cheaper — the honest hardware
  comparison is the C path (`BENCH=1 ./retina_v4l2`, see `retina_v4l2.c`).
- `first_light.py` still hits ~55 fps because it writes pixels **once** at
  startup, not per frame; the 312 ms is a one-time cost there. The per-frame
  load cost only bites the live-video path.
- The PL scan (~0.31 ms, ≈164 µs floor + Python poll) is identical for both
  paths and is the unavoidable lower bound; DMA cannot beat it.
- Post-DMA, the **spike drain** (~3.0 ms, Python per-word `fifo.read`) becomes
  the dominant cost *in Python* — but see the C numbers below: in compiled code
  the drain is ~0.1 ms, so this is a Python artifact, not a real bottleneck.

### True hardware numbers — C live path (`BENCH=1 ./retina_v4l2`)

Measured on the same board (2026-06-23), live Logitech C270 at 160×120 YUYV@15,
steady-state average per frame:

| Stage | Time |
| :--- | ---: |
| capture (camera wait, `select`+`DQBUF`) | ~27 ms |
| **pixel_write** (downsample + 16,384 AXI-Lite writes) | **~5.45 ms** |
| stimulus UDP send | ~0.6 ms |
| PL frame compute (scan) | ~0.27 ms |
| FIFO spike drain | ~0.10 ms |
| **compute (write+frame+drain)** | **~5.8 ms** |
| sustained fps | 29.8 (camera-capped, C270 hardware max) |

> Initial runs showed 14.9 fps with ~60 ms capture — that was the C270's
> auto-exposure halving the delivered rate (`V4L2_CID_EXPOSURE_AUTO_PRIORITY=1`,
> dynamic framerate in low light), not a compute limit. The driver now forces
> `EXPOSURE_AUTO_PRIORITY=0`; with adequate light the camera holds its full
> 30 fps and compute is unchanged.

### Multi-timestep throughput (`STEPS_PER_FRAME`)

The Izhikevich state persists in PL BRAM, so the engine can run N timesteps per
captured image and emit a spike update each step — decoupling the output rate
from the 30 fps camera. Measured sweep (Zybo Z7-20, live 160×120 @ 30 fps,
`STEPS_PER_FRAME=N BENCH=1 ./retina_v4l2`):

| N | compute/frame | cam fps | spike updates/s |
| ---: | ---: | ---: | ---: |
| 4 | 6.9 ms | 29.8 | 119 |
| 8 | 8.5 ms | 29.8 | 238 |
| 16 | 11.1 ms | 29.8 | 477 |
| 32 | 17.0 ms | 29.8 | **954** (≈ biological 1 kHz real-time) |
| 64 | 26.6 ms | 29.8 | **1906** (≈ 2× real-time) |
| 128 | 47.6 ms | 20.3 | 2602 (compute-bound) |
| 256 | 89.5 ms | 10.8 | **~2770** (compute-bound ceiling) |

At high N the per-step cost settles to ~328 µs (true PL scan ~265 µs + drain
~63 µs); fixed per-image cost ~6.1 ms. So 30 cam fps holds up to ~80 steps
(~2,400 updates/s); beyond that the loop is compute-bound and cam fps falls
(N=128 → 20.3 fps, N=256 → 10.8 fps) while total throughput asymptotes to the
**~2,770 updates/s** hard ceiling set by the PL scan. Image quality is governed
by N and plateaus once the rate code is fully sampled (~64–128 steps for a
typical scene), so N≈64 at 30 fps is the practical knee: figures resolve, full
camera responsiveness, 30 fps held. At N=32 the full 16,384-neuron retina runs
at the ~1 kHz / 1 ms-timestep cadence of real ganglion cells while ingesting
live video, with headroom to ~2× that.

**Corrected conclusions (these supersede the Python-inflated reading):**
- The honest AXI-Lite pixel-write cost is **~5.45 ms** in C (not 312 ms — Python
  MMIO overhead was ~98% of that). At ~333 ns per uncached GP-port store × 16,384.
- DMA still helps in C: ~5.45 ms → ~0.7 ms (**~8×**), freeing ~4.7 ms/frame of CPU.
  This is a real, bus-level win, not a Python artifact.
- The live loop is **camera-bound** at 30 fps (the C270's hardware max; ~27 ms
  waiting on the camera, compute is <20% of the budget). So DMA today **frees
  CPU rather than raising fps** — it only raises throughput with a faster frame
  source. The PL could sustain ~170 fps of processing; the camera is the limiter.
  (To exceed the camera rate, run multiple Izhikevich timesteps per captured
  frame and emit spikes at the higher rate — decoupled from camera delivery.)
- The FIFO drain in C is **~0.10 ms** (negligible). An S2MM spike-output DMA is
  **not** warranted for the C path — the 3 ms Python drain was overhead only.

---

## On-Board Power Measurement Guide (via XADC)

Instead of relying on the low-confidence Vivado power estimate, you can measure the real-time physical current and power consumption of the Zybo Z7-20 using the onboard Texas Instruments TPS25940 eFuse (IC26) and the Zynq-7000 XADC.

### 1. Hardware Routing
The TPS25940 outputs a current monitor signal (`IMON`) proportional to the load current passing through it. This signal is converted to a voltage via an onboard $4.99\text{ k}\Omega$ (1% precision) resistor to GND, and is routed directly to the Zynq dedicated analog input pair (`V_P/V_N`).

### 2. Software Interface (Linux / PYNQ)
The Linux IIO kernel driver registers the Zynq XADC and exposes its channels under sysfs.

To read the raw digitized voltage on `V_P/V_N` (typically channel `in_voltage6` or `in_voltage8` depending on driver indexing):
```bash
# Check available channels
ls /sys/bus/iio/devices/iio:device0/

# Read raw ADC code (0 - 4095)
raw_val=$(cat /sys/bus/iio/devices/iio:device0/in_voltage6_raw)

# Read scaling factor (scales raw ADC code to millivolts)
scale_val=$(cat /sys/bus/iio/devices/iio:device0/in_voltage6_scale)
```

### 3. Conversion Formulas
Compute the voltage at the IMON pin ($V_{\text{IMON}}$):
$$V_{\text{IMON}}\text{ (Volts)} = \frac{\text{raw\_val} \times \text{scale\_val}}{1000}$$

Compute total input current ($I$) based on the eFuse gain ($52\ \mu\text{A/A}$) and shunt resistor ($R_{\text{IMON}} = 4.99\text{ k}\Omega$):
$$I\text{ (Amps)} = \frac{V_{\text{IMON}}\text{ (Volts)}}{52 \times 10^{-6}\ \text{A/A} \times 4990\ \Omega} = \frac{V_{\text{IMON}}}{0.25948} \approx V_{\text{IMON}} \times 3.854$$

Compute total board power consumption ($P$):
$$P\text{ (Watts)} = 5.0\text{V} \times I\text{ (Amps)}$$

### 4. Running a Live Power Benchmark
A simple Python command can automate this reading while running the retina engine:
```python
import time

def read_power():
    try:
        with open("/sys/bus/iio/devices/iio:device0/in_voltage6_raw", "r") as f:
            raw = float(f.read().strip())
        with open("/sys/bus/iio/devices/iio:device0/in_voltage6_scale", "r") as f:
            scale = float(f.read().strip())
        
        v_imon = (raw * scale) / 1000.0
        current = v_imon / (52e-6 * 4990)
        power = 5.0 * current
        print(f"Current: {current:.3f} A | Power: {power:.3f} W")
    except FileNotFoundError:
        print("XADC node not found. Verify driver load or channel index.")

# Read power every 500ms
for _ in range(10):
    read_power()
    time.sleep(0.5)
```
> [!TIP]
> Compare the power draw when the engine is `IDLE` versus when it is actively scanning `16384` time-multiplexed neurons to determine the exact dynamic power dissipation of the retinal encoder.
