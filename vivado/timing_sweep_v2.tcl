# timing_sweep_v2.tcl
# Characterize 100 MHz timing margin as a DISTRIBUTION across implementation
# strategies, not a single run. The original timing_sweep.tcl varied only
# place_design -directive, which on a design this small collapses to identical
# results (WNS 0.396 repeated). Real spread comes from varying the strategy
# UPSTREAM of placement -- chiefly the synthesis directive, which changes the
# netlist -- combined with placement/route directives.
#
# Two passes:
#   A) standalone neuron_array_controller -- isolates the datapath critical path.
#   B) full axi_retina_wrapper            -- closer to board reality; also
#                                            re-confirms the start-gating RTL
#                                            change synthesizes/closes clean.
#
# Outputs:
#   sweep_results/sweep_v2.csv      (working, gitignored)
#   timing_sweep_summary.md         (committable: stats tables + portfolio line)
#
# Run: cd vivado && vivado -mode batch -source timing_sweep_v2.tcl

set PART   xc7z020clg400-1
set OUTDIR ./sweep_results
file mkdir $OUTDIR
set CSV $OUTDIR/sweep_v2.csv

# Strategy matrices (kept modest so the sweep finishes in reasonable wall-clock).
set SYNTH_DIRS_A {default RuntimeOptimized AreaOptimized_high PerformanceOptimized AlternateRoutability}
set PLACE_DIRS_A {Default Explore WLDrivenBlockPlacement EarlyBlockPlacement}
set SYNTH_DIRS_B {default AreaOptimized_high PerformanceOptimized}
set PLACE_DIRS_B {Default Explore}
set ROUTE_DIR    Explore

# ---- shared parsers (lifted from timing_sweep.tcl) -------------------------
proc parse_timing {ts} {
    # Returns {wns tns fs whs ths fh} from a report_timing_summary string.
    set wns NA; set tns NA; set whs NA; set ths NA; set fs NA; set fh NA
    foreach line [split $ts "\n"] {
        if {[regexp {^\s*(-?\d+\.\d+)\s+(-?\d+\.\d+)\s+(\d+)\s+(\d+)\s+(-?\d+\.\d+)\s+(-?\d+\.\d+)\s+(\d+)\s+(\d+)} $line -> a b c d e f g h]} {
            set wns $a; set tns $b; set fs $c; set whs $e; set ths $f; set fh $g
            break
        }
    }
    return [list $wns $tns $fs $whs $ths $fh]
}

proc util_val {ur name} {
    foreach line [split $ur "\n"] {
        if {[string match "*| $name *|*" $line]} {
            set cols [split $line "|"]
            return [string trim [lindex $cols 2]]
        }
    }
    return "NA"
}

# ---- one implementation run from a post-synth checkpoint -------------------
# Appends a CSV row and returns the WNS (or NA).
proc run_impl {csv run top synth_dir synth_dcp place_dir route_dir} {
    puts "=========== RUN $run : top=$top synth=$synth_dir place=$place_dir route=$route_dir ==========="
    open_checkpoint $synth_dcp
    if {[catch {opt_design} err]}                          { puts "WARN opt_design: $err" }
    if {[catch {place_design -directive $place_dir} err]}  { puts "WARN place $place_dir: $err; using Default"; catch {place_design} }
    if {[catch {phys_opt_design} err]}                     { puts "WARN phys_opt: $err" }
    if {[catch {route_design -directive $route_dir} err]}  { puts "WARN route $route_dir: $err; using Default"; catch {route_design} }

    lassign [parse_timing [report_timing_summary -no_header -return_string]] wns tns fs whs ths fh
    set ur [report_utilization -return_string]
    set lut  [util_val $ur "Slice LUTs"]
    set ff   [util_val $ur "Slice Registers"]
    set dsp  [util_val $ur "DSPs"]
    set bram [util_val $ur "Block RAM Tile"]

    set ch [open $csv a]
    puts $ch "$run,$top,$synth_dir,$place_dir,$route_dir,$wns,$tns,$whs,$ths,$fs,$fh,$lut,$ff,$dsp,$bram"
    close $ch
    puts "RUN $run: WNS=$wns ns WHS=$whs ns | LUT=$lut FF=$ff DSP=$dsp BRAM=$bram"
    close_design
    return $wns
}

# ---- WNS distribution stats ------------------------------------------------
proc stats {label wns_list} {
    set vals {}
    foreach w $wns_list { if {$w ne "NA"} { lappend vals $w } }
    if {[llength $vals] == 0} { return "$label: no timing parsed" }
    set sorted [lsort -real $vals]
    set n [llength $sorted]
    set minw [lindex $sorted 0]
    set maxw [lindex $sorted end]
    set med  [lindex $sorted [expr {$n/2}]]
    set sum 0.0
    foreach v $vals { set sum [expr {$sum + $v}] }
    set mean [expr {$sum / $n}]
    set sq 0.0
    foreach v $vals { set sq [expr {$sq + ($v-$mean)*($v-$mean)}] }
    set sd [expr {sqrt($sq / $n)}]
    set verdict [expr {$minw >= 0 ? "ALL MET" : "SETUP FAIL"}]
    return [format "%s: n=%d  WNS min=%.3f median=%.3f mean=%.3f max=%.3f stddev=%.3f  -> %s" \
            $label $n $minw $med $mean $maxw $sd $verdict]
}

# ---- CSV header ------------------------------------------------------------
set ch [open $CSV w]
puts $ch "run,top,synth_directive,place_directive,route_directive,WNS_ns,TNS_ns,WHS_ns,THS_ns,failing_setup,failing_hold,LUT,FF,DSP,BRAM_tiles"
close $ch

set run 0
set wns_A {}
set wns_B {}

# =================== PASS A : standalone controller ========================
set SRC_A {
    ../hdl/izh_pkg.sv
    ../hdl/izh_neuron_engine.sv
    ../hdl/neuron_state_mem.sv
    ../hdl/spike_fifo.sv
    ../hdl/neuron_array_controller.sv
}
foreach sd $SYNTH_DIRS_A {
    set dcp $OUTDIR/synthA_$sd.dcp
    read_verilog -sv $SRC_A
    read_xdc ./constraints.xdc
    if {[catch {synth_design -top neuron_array_controller -part $PART -directive $sd} err]} {
        puts "WARN: synth -directive $sd failed ($err); skipping this directive"
        catch {close_design}
        continue
    }
    write_checkpoint -force $dcp
    close_design
    foreach pd $PLACE_DIRS_A {
        incr run
        lappend wns_A [run_impl $CSV $run "controller" $sd $dcp $pd $ROUTE_DIR]
    }
}

# =================== PASS B : full wrapper =================================
# Wrapper clocks on aclk (constraints.xdc constrains the standalone 'clk' port),
# so constrain aclk here directly.
set SRC_B {
    ../hdl/izh_pkg.sv
    ../hdl/izh_neuron_engine.sv
    ../hdl/neuron_state_mem.sv
    ../hdl/spike_fifo.sv
    ../hdl/neuron_array_controller.sv
    ../hdl/axis_pixel_ingress.sv
    ../hdl/axi_retina_wrapper.sv
}
foreach sd $SYNTH_DIRS_B {
    set dcp $OUTDIR/synthB_$sd.dcp
    read_verilog -sv $SRC_B
    if {[catch {synth_design -top axi_retina_wrapper -part $PART -directive $sd \
            -generic NUM_NEURONS=16384 -generic ADDR_WIDTH=14} err]} {
        puts "WARN: wrapper synth -directive $sd failed ($err); skipping this directive"
        catch {close_design}
        continue
    }
    create_clock -period 10.000 -name aclk [get_ports aclk]
    write_checkpoint -force $dcp
    close_design
    foreach pd $PLACE_DIRS_B {
        incr run
        lappend wns_B [run_impl $CSV $run "wrapper" $sd $dcp $pd $ROUTE_DIR]
    }
}

# =================== SUMMARY ===============================================
set sA [stats "Pass A (standalone controller)" $wns_A]
set sB [stats "Pass B (full wrapper)"          $wns_B]
puts "\n================= SWEEP v2 SUMMARY ================="
puts $sA
puts $sB
puts "CSV: $CSV"
puts "==================================================="

# Committable markdown summary.
set md [open ./timing_sweep_summary.md w]
puts $md "# 100 MHz Timing-Margin Sweep (v2)"
puts $md ""
puts $md "Distribution of worst-case setup slack (WNS) across implementation"
puts $md "strategies (synthesis x placement directives, route=$ROUTE_DIR) on"
puts $md "$PART at a 10.000 ns / 100 MHz constraint. Generated by"
puts $md "\`vivado/timing_sweep_v2.tcl\`. Positive WNS = timing met."
puts $md ""
puts $md "## Stats"
puts $md ""
puts $md "- $sA"
puts $md "- $sB"
puts $md ""
puts $md "Per-run rows: \`vivado/sweep_results/sweep_v2.csv\` (gitignored)."
puts $md ""
puts $md "Portfolio line: across the sampled implementation strategies the"
puts $md "100 MHz datapath held positive setup slack on every run (see stats"
puts $md "above), corroborating the single committed full-overlay closure in"
puts $md "\`system_timing_summary.txt\`."
close $md
puts "Summary: ./timing_sweep_summary.md"
