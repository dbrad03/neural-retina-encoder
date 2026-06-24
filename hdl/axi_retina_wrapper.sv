`timescale 1ns / 1ps
import izh_pkg::*;

module axi_retina_wrapper #(
    parameter int NUM_NEURONS = 16384,
    parameter int ADDR_WIDTH = 14,
    // When 1, an AXI-Stream slave (fed by AXI DMA MM2S) can burst a whole frame
    // into the pixel BRAM. DMA writes are arbitrated ABOVE the AXI-Lite write
    // path on the shared BRAM port A, so the legacy /dev/mem pixel-write path
    // still works whenever the DMA stream is idle (strictly additive).
    parameter bit USE_DMA_INGRESS = 1'b0
)(
    // System Signals
    input  logic         aclk,
    input  logic         aresetn,
    
    // S_AXI (AXI4-Lite Slave)
    // 128KB Space: 0x00000-0x0FFFF = BRAM, 0x10000 = Control Reg
    input  logic [16:0]  s_axi_awaddr,
    input  logic [2:0]   s_axi_awprot,
    input  logic         s_axi_awvalid,
    output logic         s_axi_awready,
    input  logic [31:0]  s_axi_wdata,
    input  logic [3:0]   s_axi_wstrb,
    input  logic         s_axi_wvalid,
    output logic         s_axi_wready,
    output logic [1:0]   s_axi_bresp,
    output logic         s_axi_bvalid,
    input  logic         s_axi_bready,
    input  logic [16:0]  s_axi_araddr,
    input  logic [2:0]   s_axi_arprot,
    input  logic         s_axi_arvalid,
    output logic         s_axi_arready,
    output logic [31:0]  s_axi_rdata,
    output logic [1:0]   s_axi_rresp,
    output logic         s_axi_rvalid,
    input  logic         s_axi_rready,

    // M_AXIS (AXI4-Stream Master)
    output logic [15:0]  m_axis_tdata,
    output logic         m_axis_tvalid,
    output logic         m_axis_tlast,
    input  logic         m_axis_tready,

    // S_AXIS_PIXEL (AXI4-Stream Slave) - DMA stimulus input.
    // Only meaningful when USE_DMA_INGRESS=1; otherwise tready is held low.
    input  logic [31:0]  s_axis_pixel_tdata,
    input  logic         s_axis_pixel_tvalid,
    output logic         s_axis_pixel_tready,
    input  logic         s_axis_pixel_tlast,

    // Interrupts
    output logic         frame_done_irq
);

    //-----------------------------------------
    // BRAM for Pixels
    //-----------------------------------------
    (* ram_style = "block" *) logic [31:0] pixel_ram [0:NUM_NEURONS-1];
    
    logic        bram_en_a;
    logic [3:0]  bram_we_a;
    logic [13:0] bram_addr_a;
    logic [31:0] bram_din_a;
    logic [31:0] bram_dout_a;
    
    logic [13:0] pixel_addr_b;
    storage_t    pixel_data_b;
    logic [31:0] bram_dout_b;

    // True Dual Port RAM inference
    always_ff @(posedge aclk) begin
        if (bram_en_a) begin
            if (bram_we_a[0]) pixel_ram[bram_addr_a][7:0]   <= bram_din_a[7:0];
            if (bram_we_a[1]) pixel_ram[bram_addr_a][15:8]  <= bram_din_a[15:8];
            if (bram_we_a[2]) pixel_ram[bram_addr_a][23:16] <= bram_din_a[23:16];
            if (bram_we_a[3]) pixel_ram[bram_addr_a][31:24] <= bram_din_a[31:24];
            bram_dout_a <= pixel_ram[bram_addr_a];
        end
        // Port B is strictly Read-Only by the engine
        bram_dout_b <= pixel_ram[pixel_addr_b];
    end
    
    assign pixel_data_b = storage_t'(bram_dout_b[17:0]);

    //-----------------------------------------
    // DMA Stimulus Ingress (AXI-Stream -> BRAM port A)
    //-----------------------------------------
    logic        dma_pix_we;
    logic [ADDR_WIDTH-1:0] dma_pix_addr;
    logic [31:0] dma_pix_data;
    logic        dma_frame_loaded, dma_err_short, dma_err_long;

    generate
        if (USE_DMA_INGRESS) begin : gen_dma_ingress
            axis_pixel_ingress #(
                .NUM_PIXELS(NUM_NEURONS),
                .DATA_WIDTH(32),
                .ADDR_WIDTH(ADDR_WIDTH)
            ) ingress_inst (
                .clk(aclk),
                .rst_n(aresetn),
                .s_axis_tdata(s_axis_pixel_tdata),
                .s_axis_tvalid(s_axis_pixel_tvalid),
                .s_axis_tready(s_axis_pixel_tready),
                .s_axis_tlast(s_axis_pixel_tlast),
                .pix_we(dma_pix_we),
                .pix_addr(dma_pix_addr),
                .pix_data(dma_pix_data),
                .frame_loaded(dma_frame_loaded),
                .err_short(dma_err_short),
                .err_long(dma_err_long)
            );
        end else begin : gen_no_dma
            assign s_axis_pixel_tready = 1'b0;
            assign dma_pix_we      = 1'b0;
            assign dma_pix_addr    = '0;
            assign dma_pix_data    = '0;
            assign dma_frame_loaded = 1'b0;
            assign dma_err_short   = 1'b0;
            assign dma_err_long    = 1'b0;
        end
    endgenerate

    // Latched DMA status, exposed in the status register (cleared by the same
    // control write that clears frame_done, i.e. wdata bit1).
    logic dma_loaded_l, dma_err_short_l, dma_err_long_l;

    //-----------------------------------------
    // Control Engine
    //-----------------------------------------
    logic start_frame_reg;
    logic start_frame_pulse;
    logic frame_done_wire;
    logic frame_done_reg;
    
    // Output the latched register as our hardware interrupt
    assign frame_done_irq = frame_done_reg;
    
    logic start_frame_d;
    always_ff @(posedge aclk or negedge aresetn) begin
        if (!aresetn) start_frame_d <= 0;
        else          start_frame_d <= start_frame_reg;
    end
    assign start_frame_pulse = start_frame_reg & ~start_frame_d;
    
    // start_frame_reg logic moved to AXI write block

    logic overflow_seen_wire;
    logic clear_overflow_reg;

    //-----------------------------------------
    // Controller Instance
    //-----------------------------------------
    neuron_array_controller #(
        .NUM_NEURONS(NUM_NEURONS),
        .ADDR_WIDTH(ADDR_WIDTH)
    ) controller_inst (
        .clk(aclk),
        .rst_n(aresetn),
        .start_frame(start_frame_pulse),
        .frame_done(frame_done_wire),
        .pixel_addr(pixel_addr_b),
        .pixel_data(pixel_data_b),
        .spike_data(m_axis_tdata),
        .spike_valid(m_axis_tvalid),
        .spike_ready(m_axis_tready),
        .spike_last(m_axis_tlast),
        .spike(),       // Raw 1-bit spike output unused here
        .v_next_s(),
        .u_next_s(),
        .dbg_wr_addr(),
        .dbg_we_state(),
        .overflow_seen(overflow_seen_wire),
        .clear_overflow(clear_overflow_reg)
    );

    //-----------------------------------------
    // AXI4-Lite Slave Logic
    //-----------------------------------------
    logic axi_awready;
    logic axi_wready;
    logic axi_bvalid;
    logic axi_arready;
    logic axi_rvalid;
    logic [31:0] axi_rdata;
    
    assign s_axi_awready = axi_awready;
    assign s_axi_wready  = axi_wready;
    assign s_axi_bvalid  = axi_bvalid;
    assign s_axi_bresp   = 2'b00; // OKAY
    assign s_axi_arready = axi_arready;
    assign s_axi_rvalid  = axi_rvalid;
    assign s_axi_rdata   = axi_rdata;
    assign s_axi_rresp   = 2'b00; // OKAY

    // Decoupled AW/W logic
    logic [16:0] awaddr_reg;
    logic awvalid_reg, wvalid_reg;
    logic [31:0] wdata_reg;
    logic [3:0]  wstrb_reg;

    always_ff @(posedge aclk or negedge aresetn) begin
        if (!aresetn) begin
            axi_awready <= 1'b0;
            awvalid_reg <= 1'b0;
            awaddr_reg  <= 17'd0;
        end else begin
            if (~axi_awready && s_axi_awvalid && ~awvalid_reg) begin
                axi_awready <= 1'b1;
                awvalid_reg <= 1'b1;
                awaddr_reg  <= s_axi_awaddr;
            end else if (axi_bvalid && s_axi_bready) begin
                awvalid_reg <= 1'b0;
                axi_awready <= 1'b0;
            end else begin
                axi_awready <= 1'b0;
            end
        end
    end

    always_ff @(posedge aclk or negedge aresetn) begin
        if (!aresetn) begin
            axi_wready <= 1'b0;
            wvalid_reg <= 1'b0;
            wdata_reg  <= 32'd0;
            wstrb_reg  <= 4'd0;
        end else begin
            if (~axi_wready && s_axi_wvalid && ~wvalid_reg) begin
                axi_wready <= 1'b1;
                wvalid_reg <= 1'b1;
                wdata_reg  <= s_axi_wdata;
                wstrb_reg  <= s_axi_wstrb;
            end else if (axi_bvalid && s_axi_bready) begin
                wvalid_reg <= 1'b0;
                axi_wready <= 1'b0;
            end else begin
                axi_wready <= 1'b0;
            end
        end
    end

    always_ff @(posedge aclk or negedge aresetn) begin
        if (!aresetn) axi_bvalid <= 1'b0;
        else if (awvalid_reg && wvalid_reg && ~axi_bvalid)
            axi_bvalid <= 1'b1;
        else if (s_axi_bready && axi_bvalid)
            axi_bvalid <= 1'b0;
    end

    logic slv_reg_wren;
    logic write_executed;
    
    // We only execute the write ONCE per valid transaction pair.
    // The transaction is valid when both regs are set, and we haven't asserted bvalid yet.
    assign slv_reg_wren = awvalid_reg && wvalid_reg && ~write_executed;

    always_ff @(posedge aclk or negedge aresetn) begin
        if (!aresetn) write_executed <= 1'b0;
        else if (slv_reg_wren) write_executed <= 1'b1;
        else if (axi_bvalid && s_axi_bready) write_executed <= 1'b0;
    end

    always_ff @(posedge aclk or negedge aresetn) begin
        if (!aresetn) begin
            start_frame_reg <= 0;
            frame_done_reg  <= 0;
            clear_overflow_reg <= 0;
        end else begin
            clear_overflow_reg <= 0; // default to pulse
            
            // Hardware Sets
            if (start_frame_pulse) start_frame_reg <= 0;
            if (frame_done_wire)   frame_done_reg  <= 1; // Latched!

            // Software Writes (Takes priority if simultaneous)
            if (slv_reg_wren && (awaddr_reg[16] == 1'b1) && (awaddr_reg[15:0] == 16'h0000)) begin
                if (wstrb_reg[0]) begin
                    start_frame_reg <= wdata_reg[0];
                    if (wdata_reg[1]) frame_done_reg <= 0; // Clear on write 1 to bit 1
                    if (wdata_reg[2]) clear_overflow_reg <= 1; // Send pulse
                end
            end 
        end
    end

    logic [16:0] araddr_reg;
    always_ff @(posedge aclk or negedge aresetn) begin
        if (!aresetn) begin
            axi_arready <= 1'b0;
            araddr_reg  <= 17'd0;
        end else begin
            if (~axi_arready && s_axi_arvalid && (~axi_rvalid || s_axi_rready)) begin
                axi_arready <= 1'b1;
                araddr_reg  <= s_axi_araddr;
            end else begin
                axi_arready <= 1'b0;
            end
        end
    end

    logic slv_reg_rden;
    assign slv_reg_rden = axi_arready && s_axi_arvalid;

    always_ff @(posedge aclk or negedge aresetn) begin
        if (!aresetn) axi_rvalid <= 1'b0;
        else if (slv_reg_rden) axi_rvalid <= 1'b1;
        else if (axi_rvalid && s_axi_rready) axi_rvalid <= 1'b0;
    end

    // BRAM Access Mux (port A is shared by DMA ingress write, AXI-Lite write,
    // and AXI-Lite read). DMA ingress has priority: a streamed pixel beat wins
    // over a concurrent AXI-Lite access. AXI-Lite write beats AXI-Lite read.
    logic axil_bram_wr, axil_bram_rd;
    assign axil_bram_wr = slv_reg_wren && (awaddr_reg[16] == 1'b0);
    assign axil_bram_rd = slv_reg_rden && (araddr_reg[16] == 1'b0);

    assign bram_en_a   = dma_pix_we || axil_bram_wr || axil_bram_rd;
    assign bram_we_a   = dma_pix_we   ? 4'hF :
                         (axil_bram_wr ? wstrb_reg : 4'd0);
    assign bram_addr_a = dma_pix_we   ? dma_pix_addr :
                         (axil_bram_wr ? awaddr_reg[15:2] : araddr_reg[15:2]);
    assign bram_din_a  = dma_pix_we   ? dma_pix_data : wdata_reg;

    // Latch the DMA ingress status pulses for software to poll.
    always_ff @(posedge aclk or negedge aresetn) begin
        if (!aresetn) begin
            dma_loaded_l    <= 1'b0;
            dma_err_short_l <= 1'b0;
            dma_err_long_l  <= 1'b0;
        end else begin
            // Clear on the control write that clears frame_done (wdata bit1).
            if (slv_reg_wren && awaddr_reg[16] && (awaddr_reg[15:0] == 16'h0000)
                && wstrb_reg[0] && wdata_reg[1]) begin
                dma_loaded_l    <= 1'b0;
                dma_err_short_l <= 1'b0;
                dma_err_long_l  <= 1'b0;
            end
            // Set takes priority over the same-cycle clear.
            if (dma_frame_loaded) dma_loaded_l    <= 1'b1;
            if (dma_err_short)    dma_err_short_l <= 1'b1;
            if (dma_err_long)     dma_err_long_l  <= 1'b1;
        end
    end

    logic [31:0] reg_rdata;
    always_ff @(posedge aclk or negedge aresetn) begin
        if (!aresetn) begin
            reg_rdata <= 32'd0;
        end else begin
            if (slv_reg_rden) begin
                if (araddr_reg[16] == 1'b1 && araddr_reg[15:0] == 16'h0000)
                    // bit0 start, bit1 frame_done, bit2 overflow,
                    // bit3 dma_frame_loaded, bit4 dma_err_short, bit5 dma_err_long
                    reg_rdata <= {26'd0, dma_err_long_l, dma_err_short_l, dma_loaded_l,
                                  overflow_seen_wire, frame_done_reg, start_frame_reg};
                else
                    reg_rdata <= 32'd0;
            end
        end
    end

    // Mux between BRAM and Registers
    assign axi_rdata = (araddr_reg[16] == 1'b0) ? bram_dout_a : reg_rdata;

endmodule
