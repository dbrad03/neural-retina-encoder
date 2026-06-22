# Timing Summary

- **Device:** Zynq xc7z020clg400-1 (Zybo Z7-20)
- **Source:** Vivado 2025.1 full-system implementation (`vivado/build_bd.tcl`), post-Phase-2 RTL. Pre-silicon (not yet board-validated).
- **Target Clock:** clk_fpga_0 @ 100 MHz (10.00 ns)
- **Worst Negative Slack (WNS):** +0.533 ns — timing met
- **Total Negative Slack (TNS):** 0.000 ns (0 failing endpoints)
- **Hold Slack (WHS):** +0.022 ns — met

## Placement robustness sweep

To confirm closure is not a single-placement fluke, the standalone datapath
(`neuron_array_controller`, swept via `vivado/timing_sweep.tcl`) was routed under
10 placement directives. **All 10 met timing**, worst-case WNS +0.396 ns,
best-case +0.782 ns (Fmax ≈ 104–108 MHz). Per-run data:
`vivado/sweep_results/sweep.csv`.

Conclusion: the design meets 100 MHz with modest (~4–8%) margin, robustly across
placement variation.
