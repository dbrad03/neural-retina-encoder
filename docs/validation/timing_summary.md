# Timing Summary

- **Device:** Zynq xc7z020clg400-1 (Zybo Z7-20)
- **Source:** `vivado/timing_report.txt`, Vivado 2025.1 routed standalone `neuron_array_controller`, generated 2026-06-15.
- **Target Clock:** `clk` @ 100 MHz (10.00 ns)
- **Worst Negative Slack (WNS):** +0.449 ns — timing met
- **Total Negative Slack (TNS):** 0.000 ns (0 failing endpoints)
- **Hold Slack (WHS):** +0.091 ns — met

This is datapath implementation evidence, not a full Zynq block-design `system_wrapper` timing report.

## Placement robustness sweep

To confirm closure is not a single-placement result, the standalone datapath
(`neuron_array_controller`, swept via `vivado/timing_sweep.tcl`) was routed under
10 placement directives. **All 10 met timing**, worst-case WNS +0.396 ns,
best-case +0.782 ns. Per-run data: `vivado/sweep_results/sweep.csv`.

Conclusion: the design meets 100 MHz with modest (~4–8%) margin, robustly across
placement variation.
