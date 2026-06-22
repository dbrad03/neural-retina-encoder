# Utilization Summary

- **Device:** Zynq xc7z020clg400-1 (Zybo Z7-20)
- **Source:** Vivado 2025.1 full-system implementation (`vivado/build_bd.tcl`), post-Phase-2 RTL. Pre-silicon (not yet board-validated).
- **LUTs:** 1,886 (3.55%)
- **Registers (FFs):** 1,838 (1.73%)
- **BRAM (RAMB36E1 tiles):** 42 (30.00%)
- **DSP48E1:** 10 (4.55%)

*Note: After the Phase-2 RTL changes, DSP usage rose from 6 to 10 and LUTs fell from 1,995 to 1,886. BRAM (30%) is the dominant resource — three 16K-deep memories (v-state, u-state, and the spike FIFO).*
