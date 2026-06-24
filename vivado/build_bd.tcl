# build_bd.tcl
# Run with: vivado -mode batch -source build_bd.tcl

create_project -force zynq_retina ./zynq_retina -part xc7z020clg400-1

# Read all RTL sources
add_files ../hdl/izh_pkg.sv
add_files ../hdl/izh_neuron_engine.sv
add_files ../hdl/neuron_state_mem.sv
add_files ../hdl/spike_fifo.sv
add_files ../hdl/neuron_array_controller.sv
add_files ../hdl/axis_pixel_ingress.sv
add_files ../hdl/axi_retina_wrapper.sv
add_files ../hdl/axi_retina_wrapper_v.v
update_compile_order -fileset sources_1

# Create Block Design
create_bd_design "system"

# 1. Processing System
set ps7_vlnv [lindex [get_ipdefs -filter {NAME == processing_system7}] 0]
create_bd_cell -type ip -vlnv $ps7_vlnv processing_system7_0
apply_bd_automation -rule xilinx.com:bd_rule:processing_system7 -config {make_external "FIXED_IO, DDR" apply_board_preset "1" Master "Disable" Slave "Disable" }  [get_bd_cells processing_system7_0]

# Enable PL to PS Interrupts so we can potentially use AXI Stream interrupts
set_property -dict [list CONFIG.PCW_USE_FABRIC_INTERRUPT {1} CONFIG.PCW_IRQ_F2P_INTR {1}] [get_bd_cells processing_system7_0]

# Enable the HP0 AXI slave so AXI DMA can read the stimulus buffer from PS DDR
# with high-bandwidth bursts (the DMA stimulus-input path).
set_property -dict [list CONFIG.PCW_USE_S_AXI_HP0 {1}] [get_bd_cells processing_system7_0]

# 2. AXI-Stream FIFO
set fifo_vlnv [lindex [get_ipdefs -filter {NAME == axi_fifo_mm_s}] 0]
create_bd_cell -type ip -vlnv $fifo_vlnv axi_fifo_mm_s_0
# Configure FIFO for RX only (PL to PS).
# C_RX_FIFO_DEPTH must hold a whole frame's spikes (worst case = NUM_NEURONS =
# 16384) because the design emits one TLAST-delimited packet per frame; the data
# stays uncommitted in the RX FIFO until that closing TLAST arrives.
set_property -dict [list CONFIG.C_USE_TX_DATA {0} CONFIG.C_USE_TX_CTRL {0} CONFIG.C_USE_RX_DATA {1} CONFIG.C_RX_FIFO_DEPTH {16384}] [get_bd_cells axi_fifo_mm_s_0]

# 3. Custom IP
create_bd_cell -type module -reference axi_retina_wrapper_v axi_retina_wrapper_v_0

# 3b. AXI DMA for the stimulus-input path (PS DDR -> PL pixel BRAM).
# MM2S only (PL never writes pixels back), simple mode (no scatter-gather):
# the PS does PYNQ allocate() + dma.sendchannel.transfer() of one contiguous
# 16384-word frame buffer, which AXI DMA bursts into the retina ingress stream.
set dma_vlnv [lindex [get_ipdefs -filter {NAME == axi_dma}] 0]
create_bd_cell -type ip -vlnv $dma_vlnv axi_dma_0
set_property -dict [list \
  CONFIG.c_include_sg {0} \
  CONFIG.c_sg_include_stscntrl_strm {0} \
  CONFIG.c_include_mm2s {1} \
  CONFIG.c_include_s2mm {0} \
  CONFIG.c_mm2s_burst_size {16} \
  CONFIG.c_m_axi_mm2s_data_width {32} \
  CONFIG.c_m_axis_mm2s_tdata_width {32} \
  CONFIG.c_sg_length_width {26} \
] [get_bd_cells axi_dma_0]

# 4. AXI Interconnects
apply_bd_automation -rule xilinx.com:bd_rule:axi4 -config { Clk_master {Auto} Clk_slave {Auto} Clk_xbar {Auto} Master {/processing_system7_0/M_AXI_GP0} Slave {/axi_retina_wrapper_v_0/s_axi} ddr_seg {Auto} intc_ip {New AXI Interconnect} master_apm {0}}  [get_bd_intf_pins axi_retina_wrapper_v_0/s_axi]

apply_bd_automation -rule xilinx.com:bd_rule:axi4 -config { Clk_master {Auto} Clk_slave {Auto} Clk_xbar {Auto} Master {/processing_system7_0/M_AXI_GP0} Slave {/axi_fifo_mm_s_0/S_AXI} ddr_seg {Auto} intc_ip {New AXI Interconnect} master_apm {0}}  [get_bd_intf_pins axi_fifo_mm_s_0/S_AXI]

# AXI DMA control (AXI-Lite) from PS GP0, and its MM2S data master into PS HP0.
apply_bd_automation -rule xilinx.com:bd_rule:axi4 -config { Clk_master {Auto} Clk_slave {Auto} Clk_xbar {Auto} Master {/processing_system7_0/M_AXI_GP0} Slave {/axi_dma_0/S_AXI_LITE} ddr_seg {Auto} intc_ip {New AXI Interconnect} master_apm {0}}  [get_bd_intf_pins axi_dma_0/S_AXI_LITE]

# Run on the SLAVE pin (S_AXI_HP0): apply_bd_automation for an AXI link must be
# invoked on the slave interface, not the master, or the DMA master IP can't be
# resolved ("No valid slave interface could be found").
apply_bd_automation -rule xilinx.com:bd_rule:axi4 -config { Clk_master {Auto} Clk_slave {Auto} Clk_xbar {Auto} Master {/axi_dma_0/M_AXI_MM2S} Slave {/processing_system7_0/S_AXI_HP0} ddr_seg {Auto} intc_ip {New AXI Interconnect} master_apm {0}}  [get_bd_intf_pins processing_system7_0/S_AXI_HP0]

# 5. AXI Stream Connections
# Spike output: retina -> FIFO. Stimulus input: DMA MM2S -> retina ingress.
connect_bd_intf_net [get_bd_intf_pins axi_retina_wrapper_v_0/m_axis] [get_bd_intf_pins axi_fifo_mm_s_0/AXI_STR_RXD]
connect_bd_intf_net [get_bd_intf_pins axi_dma_0/M_AXIS_MM2S] [get_bd_intf_pins axi_retina_wrapper_v_0/s_axis_pixel]

# 6. Clocks and Resets
# The RTL clocks were already connected during BD automation!

# Connect interrupts from FIFO, Retina, and DMA to PS via xlconcat
create_bd_cell -type ip -vlnv xilinx.com:ip:xlconcat xlconcat_0
set_property -dict [list CONFIG.NUM_PORTS {3}] [get_bd_cells xlconcat_0]
connect_bd_net [get_bd_pins axi_fifo_mm_s_0/interrupt] [get_bd_pins xlconcat_0/In0]
connect_bd_net [get_bd_pins axi_retina_wrapper_v_0/frame_done_irq] [get_bd_pins xlconcat_0/In1]
connect_bd_net [get_bd_pins axi_dma_0/mm2s_introut] [get_bd_pins xlconcat_0/In2]
connect_bd_net [get_bd_pins xlconcat_0/dout] [get_bd_pins processing_system7_0/IRQ_F2P]

# Set FCLK0 to 100MHz as per the user's requirements
set_property -dict [list CONFIG.PCW_FPGA0_PERIPHERAL_FREQMHZ {100.000000}] [get_bd_cells processing_system7_0]

# 7. Wrapping it up
make_wrapper -files [get_files ./zynq_retina/zynq_retina.srcs/sources_1/bd/system/system.bd] -top
add_files -norecurse ./zynq_retina/zynq_retina.gen/sources_1/bd/system/hdl/system_wrapper.v
set_property top system_wrapper [current_fileset]

# Validate Design
validate_bd_design
save_bd_design

# Synthesis & Implementation
launch_runs synth_1 -jobs 4
wait_on_run synth_1

launch_runs impl_1 -to_step write_bitstream -jobs 4
wait_on_run impl_1

# Export Hardware (XSA) for Vitis/Petalinux
write_hw_platform -fixed -include_bit -force -file system_wrapper.xsa
