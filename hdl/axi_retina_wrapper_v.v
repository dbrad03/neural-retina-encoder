`timescale 1ns / 1ps

module axi_retina_wrapper_v (
    input  wire         aclk,
    input  wire         aresetn,
    
    // S_AXI
    input  wire [16:0]  s_axi_awaddr,
    input  wire [2:0]   s_axi_awprot,
    input  wire         s_axi_awvalid,
    output wire         s_axi_awready,
    input  wire [31:0]  s_axi_wdata,
    input  wire [3:0]   s_axi_wstrb,
    input  wire         s_axi_wvalid,
    output wire         s_axi_wready,
    output wire [1:0]   s_axi_bresp,
    output wire         s_axi_bvalid,
    input  wire         s_axi_bready,
    input  wire [16:0]  s_axi_araddr,
    input  wire [2:0]   s_axi_arprot,
    input  wire         s_axi_arvalid,
    output wire         s_axi_arready,
    output wire [31:0]  s_axi_rdata,
    output wire [1:0]   s_axi_rresp,
    output wire         s_axi_rvalid,
    input  wire         s_axi_rready,

    // M_AXIS
    output wire [15:0]  m_axis_tdata,
    output wire         m_axis_tvalid,
    output wire         m_axis_tlast,
    input  wire         m_axis_tready,

    // S_AXIS_PIXEL (AXI DMA MM2S -> pixel BRAM)
    input  wire [31:0]  s_axis_pixel_tdata,
    input  wire         s_axis_pixel_tvalid,
    output wire         s_axis_pixel_tready,
    input  wire         s_axis_pixel_tlast,

    // Interrupts
    output wire         frame_done_irq
);

    axi_retina_wrapper #(
        .NUM_NEURONS(16384),
        .ADDR_WIDTH(14),
        .USE_DMA_INGRESS(1'b1)
    ) inst (
        .aclk(aclk),
        .aresetn(aresetn),
        .s_axi_awaddr(s_axi_awaddr),
        .s_axi_awprot(s_axi_awprot),
        .s_axi_awvalid(s_axi_awvalid),
        .s_axi_awready(s_axi_awready),
        .s_axi_wdata(s_axi_wdata),
        .s_axi_wstrb(s_axi_wstrb),
        .s_axi_wvalid(s_axi_wvalid),
        .s_axi_wready(s_axi_wready),
        .s_axi_bresp(s_axi_bresp),
        .s_axi_bvalid(s_axi_bvalid),
        .s_axi_bready(s_axi_bready),
        .s_axi_araddr(s_axi_araddr),
        .s_axi_arprot(s_axi_arprot),
        .s_axi_arvalid(s_axi_arvalid),
        .s_axi_arready(s_axi_arready),
        .s_axi_rdata(s_axi_rdata),
        .s_axi_rresp(s_axi_rresp),
        .s_axi_rvalid(s_axi_rvalid),
        .s_axi_rready(s_axi_rready),
        .m_axis_tdata(m_axis_tdata),
        .m_axis_tvalid(m_axis_tvalid),
        .m_axis_tlast(m_axis_tlast),
        .m_axis_tready(m_axis_tready),
        .s_axis_pixel_tdata(s_axis_pixel_tdata),
        .s_axis_pixel_tvalid(s_axis_pixel_tvalid),
        .s_axis_pixel_tready(s_axis_pixel_tready),
        .s_axis_pixel_tlast(s_axis_pixel_tlast),
        .frame_done_irq(frame_done_irq)
    );

endmodule
