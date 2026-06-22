import izh_pkg::*;

module neuron_array_controller #(
    parameter int NUM_NEURONS = 16384,
    parameter int ADDR_WIDTH = 14
)(
    input  logic         clk,
    input  logic         rst_n,
    
    // System Control
    input  logic         start_frame, 
    output logic         frame_done,
    
    // Pixel Input
    output logic [ADDR_WIDTH-1:0] pixel_addr,
    input  storage_t              pixel_data,
    
    // Spike Output
    output logic [15:0]  spike_data,
    output logic         spike_valid,
    input  logic         spike_ready,
    output logic         spike_last,
    output logic         spike,
    
    // Output state
    output storage_t     v_next_s,
    output storage_t     u_next_s,
    
    // Debug/Status
    output logic [ADDR_WIDTH-1:0] dbg_wr_addr,
    output logic                  dbg_we_state,
    output logic                  overflow_seen,
    input  logic                  clear_overflow
);

    // --- TYPES & ENUMS ---
    typedef enum logic [1:0] {IDLE, SCANNING} state_t;
    state_t state;

    // --- INTERNAL WIRES ---
    logic [ADDR_WIDTH-1:0] rd_addr, wr_addr_int;
    storage_t v_state_in, u_state_in;
    storage_t v_state_out, u_state_out;
    logic     we_state_int;
    logic     engine_start, engine_done, engine_spike;
    
    logic [ADDR_WIDTH-1:0] fifo_din, fifo_dout;
    logic                  fifo_wr, fifo_rd, fifo_full, fifo_empty;
    logic [ADDR_WIDTH:0]   fifo_count;

    // --- PIPELINE MANAGEMENT ---
    logic [ADDR_WIDTH:0] scan_cnt;
    logic [ADDR_WIDTH:0] done_cnt;
    logic                frame_complete;  // set after scan done; gates spike drain
    logic [ADDR_WIDTH-1:0] addr_pipe [7]; 
    logic                  start_pipe [7]; 

    always_ff @(posedge clk) begin
        addr_pipe[0] <= rd_addr;
        start_pipe[0] <= engine_start;
        for (int i = 1; i < 7; i++) begin
            addr_pipe[i] <= addr_pipe[i-1];
            start_pipe[i] <= start_pipe[i-1];
        end
    end
    
    // --- FOVEATION (Diamond Midget/Parasol Selection) ---
    logic [6:0] x_coord, y_coord;
    logic signed [7:0] dx, dy;
    logic [6:0] abs_dx, abs_dy;
    logic [7:0] dist_val;
    logic is_midget_comb;
    logic is_midget_pipe [7];

    generate
        if (ADDR_WIDTH >= 14) begin : gen_fovea_coords
            assign x_coord = rd_addr[6:0];
            assign y_coord = rd_addr[13:7];
        end else begin : gen_fovea_fallback
            assign x_coord = 7'd64; // Fallback for small tests
            assign y_coord = 7'd64;
        end
    endgenerate

    always_comb begin
        dx = $signed({1'b0, x_coord}) - 8'sd64;
        dy = $signed({1'b0, y_coord}) - 8'sd64;
        abs_dx = (dx < 0) ? -dx : dx;
        abs_dy = (dy < 0) ? -dy : dy;
        dist_val = {1'b0, abs_dx} + {1'b0, abs_dy};
        is_midget_comb = (dist_val < 8'd45);
    end

    always_ff @(posedge clk) begin
        is_midget_pipe[0] <= is_midget_comb;
        for (int i = 1; i < 7; i++) begin
            is_midget_pipe[i] <= is_midget_pipe[i-1];
        end
    end

    // --- SUB-MODULE INSTANTIATION ---
    neuron_state_mem #(.ADDR_WIDTH(ADDR_WIDTH), .NUM_NEURONS(NUM_NEURONS)) state_mem_inst (
        .clk(clk),
        .addr_a(rd_addr), .v_din_a('0), .u_din_a('0), .we_a(1'b0), .v_dout_a(v_state_in), .u_dout_a(u_state_in),
        .addr_b(wr_addr_int), .v_din_b(v_state_out), .u_din_b(u_state_out), .we_b(we_state_int), .v_dout_b(), .u_dout_b()
    );

    izh_neuron_engine engine_inst (
        .clk(clk), .rst_n(rst_n), .v_curr_s(v_state_in), .u_curr_s(u_state_in), .i_ext_s(pixel_data), 
        .is_midget(is_midget_pipe[0]),
        .start(start_pipe[0]), .done(engine_done), .v_next_s(v_state_out), .u_next_s(u_state_out), .spike(engine_spike)
    );

    spike_fifo #(.ADDR_WIDTH(ADDR_WIDTH), .FIFO_DEPTH(NUM_NEURONS)) fifo_inst (
        .clk(clk), .rst_n(rst_n), .din(fifo_din), .wr_en(fifo_wr), .full(fifo_full), 
        .dout(fifo_dout), .rd_en(fifo_rd), .empty(fifo_empty), .count(fifo_count),
        .overflow_seen(overflow_seen), .clear_overflow(clear_overflow)
    );

    // --- WRITEBACK ALIGNMENT ---
    // Timing:
    // T+0: rd_addr set
    // T+1: addr_pipe[0]=addr, start_pipe[0]=1. Engine Stage 1 (Capture).
    // T+2: addr_pipe[1]=addr. Engine Stage 2 (Mults).
    // T+3: addr_pipe[2]=addr. Engine Stage 3 (Sec Mults).
    // T+4: addr_pipe[3]=addr. Engine Stage 4 (Tert Mults).
    // T+5: addr_pipe[4]=addr. Engine Stage 5 (Integ Mults).
    // T+6: addr_pipe[5]=addr. Engine Stage 6 (Writeback).
    // T+7: addr_pipe[6]=addr. Engine done. (engine_done=1)
    // At T+7, addr_pipe[6] is the address we want to write back to.
    assign wr_addr_int  = addr_pipe[6];
    assign we_state_int = engine_done && (state == SCANNING);
    assign fifo_din     = addr_pipe[6];
    assign fifo_wr      = engine_spike && engine_done && (state == SCANNING);

    assign dbg_wr_addr  = wr_addr_int;
    assign dbg_we_state = we_state_int;
    assign v_next_s     = v_state_out;
    assign u_next_s     = u_state_out;
    assign spike        = engine_spike && engine_done;

    // --- CONTROL LOGIC ---
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= IDLE;
            scan_cnt <= '0;
            done_cnt <= '0;
            rd_addr <= '0;
            pixel_addr <= '0;
            engine_start <= 1'b0;
            frame_done <= 1'b0;
        end else begin
            frame_done <= 1'b0;
            case (state)
                IDLE: begin
                    if (start_frame) begin
                        state <= SCANNING;
                        scan_cnt <= '0;
                        done_cnt <= '0;
                        rd_addr <= '0;
                    end
                end

                SCANNING: begin
                    if (scan_cnt < NUM_NEURONS) begin
                        rd_addr <= scan_cnt;
                        pixel_addr <= scan_cnt;
                        scan_cnt <= scan_cnt + 1;
                        engine_start <= 1'b1;
                    end else begin
                        engine_start <= 1'b0;
                    end

                    if (engine_done) begin
                        done_cnt <= done_cnt + 1;
                    end

                    if (done_cnt == NUM_NEURONS-1 && engine_done) begin
                        state <= IDLE;
                        frame_done <= 1'b1;
                    end
                end
                default: state <= IDLE;
            endcase
        end
    end

    // --- FIFO DRAIN ---
    // Drain is GATED on frame_complete: spikes accumulate in the internal FIFO
    // during the scan and only stream out as one burst after the frame finishes.
    // This guarantees a genuine final beat exists to carry TLAST (otherwise the
    // FIFO empties mid-scan and no beat is left to mark the packet end).
    assign spike_data = {2'b00, fifo_dout};

    assign fifo_rd = frame_complete && !fifo_empty && (!spike_valid || spike_ready);

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            spike_valid <= 1'b0;
        end else begin
            // Valid data appears exactly 1 cycle after fifo_rd
            if (fifo_rd) begin
                spike_valid <= 1'b1;
            end else if (spike_ready && spike_valid) begin
                spike_valid <= 1'b0;
            end
        end
    end

    // --- TLAST GENERATION (packet boundary = one packet per frame) ---
    // frame_complete latches once the scan has finished (frame_done), so no
    // more spikes will be enqueued. The current valid beat is the frame's last
    // spike when the internal FIFO has drained empty behind it. This single
    // TLAST lets the downstream axi_fifo_mm_s commit the frame as one packet.
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n)            frame_complete <= 1'b0;
        else if (start_frame)  frame_complete <= 1'b0;  // new frame: re-arm
        else if (frame_done)   frame_complete <= 1'b1;  // scan finished
    end

    assign spike_last = spike_valid && fifo_empty && frame_complete;

endmodule
