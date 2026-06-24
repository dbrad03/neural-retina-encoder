# Timing Sweep Extension — Handoff Plan (for Gemini)

**Goal:** Produce a credible *distribution* of 100 MHz timing margin (~20+ data
points) for the Science Eye retina datapath, so the portfolio can cite a real
WNS min/median/max and slack margin instead of a single run. Output: an extended
CSV + a short markdown stats summary.

This is an offline characterization task. It does **not** touch the board, the
block design (`build_bd.tcl`), or the RTL. Work only in `vivado/`.

---

## Current state (read first)

- Existing script: `vivado/timing_sweep.tcl`. It synthesizes
  `neuron_array_controller` standalone (the critical-path datapath block, NOT
  the full `axi_retina_wrapper`/`system_wrapper`), writes a post-synth
  checkpoint, then loops over 10 `place_design -directive` values, routes each
  with `route_design -directive Explore`, and records WNS/TNS/WHS/THS + util to
  `vivado/sweep_results/sweep.csv`.
- Run command: `cd vivado && vivado -mode batch -source timing_sweep.tcl`
- Part: `xc7z020clg400-1`. Clock constraint lives in `vivado/constraints.xdc`.
- **Existing results (all met timing):**

  | runs | WNS range | WHS range | LUT | FF | DSP | BRAM |
  |------|-----------|-----------|-----|----|----|------|
  | 10   | 0.396 – 0.782 ns | +0.029 – +0.065 ns | ~877 | 744 | 10 | 25 |

  Board reality (full `system_wrapper` *with DMA*) closes at WNS +0.305 /
  WHS +0.033 ns — so the standalone block is optimistic; keep that caveat in the
  writeup.

## The problem to fix

Runs 1, 2, 3, and 10 produced *identical* WNS (0.396). On a design this small,
`place_design -directive` alone barely perturbs placement, so most directives
converge to the same result — that's not a real distribution. To get genuine
spread you must vary the flow **upstream of placement** and combine stages.

## Approach — get real variation, ~20+ points

Build the run matrix from the **product of stage strategies**, not just placer
directives:

1. **Synthesis directives** (rerun `synth_design`, don't reuse one checkpoint) —
   e.g. `default`, `AreaOptimized_high`, `PerformanceOptimized`,
   `AlternateRoutability`, `FlowAreaOptimized`. This is the biggest source of
   real variation because it changes the netlist.
2. **Placement directives** — keep the meaningful subset from the current list
   (`Default`, `Explore`, `WLDrivenBlockPlacement`, `EarlyBlockPlacement`,
   `ExtraNetDelay_high`, `AltSpreadLogic_high/medium/low`,
   `SSI_SpreadLogic_high`). Drop near-duplicates if you need to cap runtime.
3. **Route directives** — sample at least `Explore`,
   `AggressiveExplore`, `NoTimingRelaxation`, `Default`.

Pick ~20–24 combinations (e.g. 5 synth × 4 place + a few route variants, or a
randomized subset) so the sweep finishes in reasonable wall-clock time. Each
synth directive should write its own post-synth `.dcp` and be reused across the
placement/route variants under it to save time.

### Optional: also sweep the *integrated* wrapper

The standalone block hides inter-IP routing. If time allows, add a second pass
that reads the full RTL set and synthesizes `-top axi_retina_wrapper_v` (see the
file list in `build_bd.tcl` / `build.tcl` for the complete source list incl.
`axis_pixel_ingress.sv`, `axi_retina_wrapper.sv`, the FIFO, etc.). Report it as a
separate table — it's closer to board reality. If this balloons runtime, skip it
and just note the +0.305 board number as ground truth.

## Implementation steps

1. Copy `timing_sweep.tcl` → `timing_sweep_v2.tcl` (keep the original for
   reference). Refactor the single synth + place-loop into a nested loop over the
   strategy matrix above.
2. Keep the existing CSV parsing (the `report_timing_summary -return_string`
   regex and the `report_utilization` `util_val` proc both work — reuse them).
   Add columns: `synth_directive`, `route_directive`, and `top` (which top was
   built). New header order suggestion:
   `run,top,synth_directive,place_directive,route_directive,WNS_ns,TNS_ns,WHS_ns,THS_ns,failing_setup,failing_hold,LUT,FF,DSP,BRAM_tiles`
3. Write results to `vivado/sweep_results/sweep_v2.csv` (don't clobber the old
   one).
4. After the loop, compute and print: count, WNS min / median / mean / max,
   stddev, and "all runs met timing? (min WNS >= 0)". Do the same for WHS (hold).
5. Write a `vivado/sweep_results/SUMMARY.md` with: the stats table, the run
   matrix used, total wall-clock, and a one-line portfolio-ready sentence
   (e.g. "Across N implementation strategies the 100 MHz datapath held positive
   slack on every run, WNS median X ns / worst Y ns").

## Pitfalls / notes

- `place_design` has **no `-seed`** option in non-project batch mode — don't try
  to seed it; vary synth/route strategy instead. (This is why the original
  10-directive run produced duplicates.)
- Some directive combos can error (e.g. `NoTimingRelaxation` on an already-met
  design, or a directive unsupported for this part). Wrap each stage in
  `catch {}` like the original does for `place_design`, log a WARN, and continue
  — never let one combo abort the whole sweep.
- `phys_opt_design` can return "nothing to do" on an easily-met design; that's
  fine, keep it.
- Hold (WHS) is already comfortably positive; the headline metric is setup
  (WNS). Report both but lead with WNS.
- Don't commit the large `.dcp` files or `vivado*.log/.jou`; only the CSV and
  SUMMARY.md are worth keeping (check `vivado/.gitignore` patterns).

## Acceptance criteria

- `sweep_v2.csv` has ≥20 rows with genuinely varied WNS (not all identical).
- `SUMMARY.md` reports WNS min/median/max + "all met timing" verdict.
- The original `timing_sweep.tcl` and `sweep_results/sweep.csv` are untouched.
- No board/BD/RTL files modified.
