# Utilization Summary

- **Device:** Zynq xc7z020clg400-1 (Zybo Z7-20)
- **Source:** `vivado/util_report.txt`, Vivado 2025.1 routed standalone `neuron_array_controller`, generated 2026-06-15.
- **LUTs:** 994 (1.87%)
- **Registers (FFs):** 724 (0.68%)
- **BRAM (RAMB36E1 tiles):** 25 (17.86%)
- **DSP48E1:** 6 (2.73%)

These numbers are for the standalone datapath report checked into `vivado/`, not the complete Zynq block design with PS and AXI infrastructure. The placement sweep CSV reports a related standalone configuration at roughly 877-880 LUT, 744 FF, 25 BRAM, and 10 DSP depending on directive.
