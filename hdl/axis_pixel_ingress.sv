// axis_pixel_ingress.sv
//
// AXI4-Stream -> pixel-RAM write adapter for the DMA stimulus-input path.
//
// Replaces the per-pixel /dev/mem AXI-Lite store loop (16,384 single-beat CPU
// writes per frame) with a single AXI DMA MM2S burst: the PS fills a contiguous
// buffer, AXI DMA streams it here, and this block writes the beats sequentially
// into the existing 128x128 pixel BRAM. The neuron datapath's BRAM *read* port
// is untouched, so nothing downstream of the pixel RAM changes.
//
// Contract (one TLAST-delimited packet per frame):
//   - Accept exactly NUM_PIXELS beats. Beat i is written to pixel address i.
//   - TLAST must land on the final beat (index NUM_PIXELS-1).
//       * correct length + TLAST on last beat  -> frame_loaded pulses (1 cycle)
//       * TLAST before the last beat            -> err_short pulses, counter resets
//       * last beat without TLAST (packet long
//         or TLAST missing/misaligned)          -> err_long  pulses, counter resets
//   - tready is held high: the BRAM sinks one beat per clock, so the stream
//     never needs to be back-pressured. (Kept as a real handshake so an
//     upstream that de-asserts tvalid simply pauses cleanly.)
//
// frame_loaded / err_short / err_long are single-cycle pulses; the integrating
// wrapper is expected to latch them into AXI-Lite status bits.

module axis_pixel_ingress #(
    parameter int NUM_PIXELS = 16384,
    parameter int DATA_WIDTH = 32,
    parameter int ADDR_WIDTH = $clog2(NUM_PIXELS)
)(
    input  logic                    clk,
    input  logic                    rst_n,

    // AXI4-Stream slave (from AXI DMA MM2S)
    input  logic [DATA_WIDTH-1:0]   s_axis_tdata,
    input  logic                    s_axis_tvalid,
    output logic                    s_axis_tready,
    input  logic                    s_axis_tlast,

    // Pixel-RAM write port (drives port A of the stimulus BRAM)
    output logic                    pix_we,
    output logic [ADDR_WIDTH-1:0]   pix_addr,
    output logic [DATA_WIDTH-1:0]   pix_data,

    // Status (single-cycle pulses)
    output logic                    frame_loaded,
    output logic                    err_short,
    output logic                    err_long
);

    // Index of the next beat to be written (0 .. NUM_PIXELS-1).
    logic [ADDR_WIDTH-1:0] count;

    // The BRAM accepts a write every cycle, so we are always ready.
    assign s_axis_tready = 1'b1;

    wire beat        = s_axis_tvalid && s_axis_tready;
    wire is_last_idx = (count == ADDR_WIDTH'(NUM_PIXELS-1));

    // Combinational write port: beat i -> address i.
    assign pix_we   = beat;
    assign pix_addr = count;
    assign pix_data = s_axis_tdata;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            count        <= '0;
            frame_loaded <= 1'b0;
            err_short    <= 1'b0;
            err_long     <= 1'b0;
        end else begin
            // Status outputs default to a single-cycle pulse.
            frame_loaded <= 1'b0;
            err_short    <= 1'b0;
            err_long     <= 1'b0;

            if (beat) begin
                if (s_axis_tlast) begin
                    // TLAST seen: only valid if it is the final beat.
                    if (is_last_idx) frame_loaded <= 1'b1;
                    else             err_short    <= 1'b1;
                    count <= '0;
                end else if (is_last_idx) begin
                    // Reached the last index but no TLAST -> packet too long /
                    // TLAST missing. Reset so the stream re-aligns on the next
                    // frame (the next beat starts a fresh frame at address 0).
                    err_long <= 1'b1;
                    count    <= '0;
                end else begin
                    count <= count + 1'b1;
                end
            end
        end
    end

endmodule
