# timing_sweep.tcl
# Characterize 100 MHz datapath timing margin across placement variation.
# Synthesize neuron_array_controller once, then route under ~10 placement
# directives and record WNS/TNS/WHS/THS + utilization to a CSV.
#
# Run: vivado -mode batch -source timing_sweep.tcl
set PART  xc7z020clg400-1
set OUTDIR ./sweep_results
file mkdir $OUTDIR

# Placement directives to sample the timing distribution.
set directives {
    Default
    Explore
    WLDrivenBlockPlacement
    EarlyBlockPlacement
    ExtraNetDelay_high
    ExtraNetDelay_low
    AltSpreadLogic_high
    AltSpreadLogic_medium
    AltSpreadLogic_low
    SSI_SpreadLogic_high
}

# ---- Synthesize once ------------------------------------------------------
read_verilog -sv {
    ../hdl/izh_pkg.sv
    ../hdl/izh_neuron_engine.sv
    ../hdl/neuron_state_mem.sv
    ../hdl/spike_fifo.sv
    ../hdl/neuron_array_controller.sv
}
read_xdc ./constraints.xdc
synth_design -top neuron_array_controller -part $PART
set synth_dcp $OUTDIR/post_synth.dcp
write_checkpoint -force $synth_dcp

# ---- CSV header -----------------------------------------------------------
set csv $OUTDIR/sweep.csv
set fh [open $csv w]
puts $fh "run,place_directive,WNS_ns,TNS_ns,WHS_ns,THS_ns,failing_setup,failing_hold,LUT,FF,DSP,BRAM_tiles"
close $fh

proc grab {dcp_timing pattern} {
    # not used; kept for reference
}

set run 0
set wns_list {}
foreach dir $directives {
    incr run
    puts "=========== RUN $run : place_design -directive $dir ==========="
    open_checkpoint $synth_dcp
    opt_design
    if {[catch {place_design -directive $dir} err]} {
        puts "WARN: place_design -directive $dir failed ($err); falling back to Default"
        place_design
    }
    phys_opt_design
    route_design -directive Explore

    # ---- Timing ----
    set ts [report_timing_summary -no_header -return_string]
    # WNS / TNS / WHS / THS and failing endpoint counts come from the
    # Design Timing Summary table.
    set WNS  [regexp -inline -line {WNS\(ns\).*}  $ts]
    # Parse the numeric summary line: it has WNS TNS TNS_failing TNS_total WHS THS ...
    set wns  "NA"; set tns "NA"; set whs "NA"; set ths "NA"; set fs "NA"; set fh2 "NA"
    foreach line [split $ts "\n"] {
        if {[regexp {^\s*(-?\d+\.\d+)\s+(-?\d+\.\d+)\s+(\d+)\s+(\d+)\s+(-?\d+\.\d+)\s+(-?\d+\.\d+)\s+(\d+)\s+(\d+)} $line -> a b c d e f g h]} {
            set wns $a; set tns $b; set fs $c
            set whs $e; set ths $f; set fh2 $g
            break
        }
    }

    # ---- Utilization ----
    set ur [report_utilization -return_string]
    proc util_val {ur name} {
        foreach line [split $ur "\n"] {
            if {[string match "*| $name *|*" $line]} {
                set cols [split $line "|"]
                return [string trim [lindex $cols 2]]
            }
        }
        return "NA"
    }
    set lut  [util_val $ur "Slice LUTs"]
    set ff   [util_val $ur "Slice Registers"]
    set dsp  [util_val $ur "DSPs"]
    set bram [util_val $ur "Block RAM Tile"]

    set fh [open $csv a]
    puts $fh "$run,$dir,$wns,$tns,$whs,$ths,$fs,$fh2,$lut,$ff,$dsp,$bram"
    close $fh
    puts "RUN $run ($dir): WNS=$wns ns TNS=$tns ns | LUT=$lut FF=$ff DSP=$dsp BRAM=$bram"
    if {$wns ne "NA"} { lappend wns_list $wns }
    close_design
}

# ---- Summary --------------------------------------------------------------
puts "\n================= SWEEP SUMMARY ================="
if {[llength $wns_list] > 0} {
    set sorted [lsort -real $wns_list]
    set n [llength $sorted]
    set minw [lindex $sorted 0]
    set maxw [lindex $sorted end]
    set med  [lindex $sorted [expr {$n/2}]]
    puts "Runs with timing: $n / [llength $directives]"
    puts "WNS  min=$minw  median=$med  max=$maxw  (positive = met @ 100 MHz)"
    if {$minw >= 0} { puts "ALL runs met timing at 100 MHz." } else { puts "Some runs FAILED setup timing." }
} else {
    puts "No WNS parsed; inspect $csv and the log."
}
puts "CSV: $csv"
puts "================================================="
