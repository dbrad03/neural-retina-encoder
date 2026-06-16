# build.tcl
create_project -force science-eye-fpga ./science-eye-fpga -part xc7z020clg400-1
add_files ../hdl/izh_pkg.sv
add_files ../hdl/izh_neuron_engine.sv
add_files ../hdl/neuron_state_mem.sv
add_files ../hdl/spike_fifo.sv
add_files ../hdl/neuron_array_controller.sv
read_xdc ./constraints.xdc

set_property top neuron_array_controller [current_fileset]
update_compile_order -fileset sources_1

# Run synthesis
launch_runs synth_1 -jobs 4
wait_on_run synth_1

# Run implementation
launch_runs impl_1 -jobs 4
wait_on_run impl_1

# Open implemented design
open_run impl_1

# Run power analysis
report_power -file power_report.txt
report_utilization -file util_report.txt
report_timing_summary -file timing_report.txt
