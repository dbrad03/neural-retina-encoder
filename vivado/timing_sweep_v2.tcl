# timing_sweep_v2.tcl
# Characterize the 100 MHz setup-timing MARGIN of the retina datapath as a
# distribution across implementation (placement/route) variation under the
# SHIPPED synthesis strategy (default).
#
# Why not vary synth -directive? An earlier version did, and it conflated two
# different things: forcing AreaOptimized/RuntimeOptimized/PerformanceOptimized
# reinfers the netlist into genuinely slower mappings (PerformanceOptimized was
# the WORST here), which measures "strategy choice", not the headroom of the
# design we actually build. Margin is the spread under the real strategy as the
# placer/router vary -- that is what this sweep reports.
#
# Why only the standalone neuron_array_controller? Synthesizing the full
# axi_retina_wrapper out-of-context times its AXI ports as unconstrained chip
# I/O (zero input/output-delay budget), producing phantom failures that are
# identical across every placement -- not representative. The real, in-context
# full-system timing is the committed system_timing_summary.txt from build_bd.tcl
# (WNS +0.378 / WHS +0.018 ns at 100 MHz); that is the wrapper evidence.
#
# Outputs:
#   sweep_results/sweep_v2.csv      (working, gitignored)
#   timing_sweep_summary.md         (committable: stats + per-run table)
#
# Run: cd vivado && vivado -mode batch -source timing_sweep_v2.tcl

set PART   xc7z020clg400-1
set OUTDIR ./sweep_results
file mkdir $OUTDIR
set CSV $OUTDIR/sweep_v2.csv

# Placement + route directives sampled under default synthesis.
set PLACE_DIRS {
    Default Explore WLDrivenBlockPlacement EarlyBlockPlacement
    ExtraNetDelay_high ExtraNetDelay_low
    AltSpreadLogic_high AltSpreadLogic_medium AltSpreadLogic_low
    SSI_SpreadLogic_high
}
set ROUTE_DIRS {Explore AggressiveExplore}

# ---- shared parsers -------------------------------------------------------
proc parse_timing {ts} {
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

# ---- one implementation run from the post-synth checkpoint -----------------
proc run_impl {csv run synth_dcp place_dir route_dir} {
    puts "=========== RUN $run : place=$place_dir route=$route_dir ==========="
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
    puts $ch "$run,default,$place_dir,$route_dir,$wns,$tns,$whs,$ths,$fs,$fh,$lut,$ff,$dsp,$bram"
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
puts $ch "run,synth_directive,place_directive,route_directive,WNS_ns,TNS_ns,WHS_ns,THS_ns,failing_setup,failing_hold,LUT,FF,DSP,BRAM_tiles"
close $ch

# ---- Synthesize once (default strategy), then sweep impl -------------------
set SRC {
    ../hdl/izh_pkg.sv
    ../hdl/izh_neuron_engine.sv
    ../hdl/neuron_state_mem.sv
    ../hdl/spike_fifo.sv
    ../hdl/neuron_array_controller.sv
}
read_verilog -sv $SRC
read_xdc ./constraints.xdc
synth_design -top neuron_array_controller -part $PART
set DCP $OUTDIR/post_synth_v2.dcp
write_checkpoint -force $DCP
close_design

set run 0
set wns_list {}
foreach pd $PLACE_DIRS {
    foreach rd $ROUTE_DIRS {
        incr run
        lappend wns_list [run_impl $CSV $run $DCP $pd $rd]
    }
}

# =================== SUMMARY ===============================================
set s [stats "Datapath (neuron_array_controller, default synth)" $wns_list]
puts "\n================= SWEEP v2 SUMMARY ================="
puts $s
puts "CSV: $CSV"
puts "==================================================="

# Committable markdown summary (recomputes the table from the CSV so it is
# self-consistent with the per-run rows).
set md [open ./timing_sweep_summary.md w]
puts $md "# 100 MHz Datapath Timing-Margin Sweep"
puts $md ""
puts $md "Worst-case setup slack (WNS) of the retina datapath"
puts $md "(\`neuron_array_controller\`) across [llength $PLACE_DIRS] placement x"
puts $md "[llength $ROUTE_DIRS] route directives under the shipped default"
puts $md "synthesis strategy, on $PART at a 10.000 ns / 100 MHz constraint."
puts $md "Generated by \`vivado/timing_sweep_v2.tcl\`. Positive WNS = timing met."
puts $md ""
puts $md "## Stats"
puts $md ""
puts $md "- $s"
puts $md ""
puts $md "The full in-context system_wrapper (PS + AXI DMA + retina) closes at"
puts $md "WNS +0.378 / WHS +0.018 ns -- see the committed \`system_timing_summary.txt\`."
puts $md "Per-run rows: \`vivado/sweep_results/sweep_v2.csv\` (gitignored)."
puts $md ""
puts $md "| run | place | route | WNS (ns) | WHS (ns) | LUT | FF |"
puts $md "|----:|-------|-------|---------:|---------:|----:|---:|"
set fh [open $CSV r]
gets $fh ;# skip header
while {[gets $fh line] >= 0} {
    set c [split $line ,]
    puts $md "| [lindex $c 0] | [lindex $c 2] | [lindex $c 3] | [lindex $c 4] | [lindex $c 6] | [lindex $c 10] | [lindex $c 11] |"
}
close $fh
close $md
puts "Summary: ./timing_sweep_summary.md"
