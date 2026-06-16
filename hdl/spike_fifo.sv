module spike_fifo #(
    parameter int ADDR_WIDTH = 14, // Address of the neuron that spiked
    parameter int FIFO_DEPTH = 16384
)(
    input  logic         clk,
    input  logic         rst_n,
    
    // Write Interface
    input  logic [ADDR_WIDTH-1:0] din,
    input  logic                  wr_en,
    output logic                  full,
    
    // Read Interface
    output logic [ADDR_WIDTH-1:0] dout,
    input  logic                  rd_en,
    output logic                  empty,
    
    // Status
    output logic [ADDR_WIDTH:0]   count,
    output logic                  overflow_seen,
    input  logic                  clear_overflow
);
    // Inferred BRAM FIFO
    logic [ADDR_WIDTH-1:0] mem [FIFO_DEPTH];
    logic [ADDR_WIDTH-1:0] wr_ptr, rd_ptr;
    logic [ADDR_WIDTH:0]   internal_count;

    assign count = internal_count;
    assign full  = (internal_count == FIFO_DEPTH);
    assign empty = (internal_count == 0);

    // Pointer and count logic
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            wr_ptr <= '0;
            rd_ptr <= '0;
            internal_count <= '0;
            overflow_seen <= '0;
        end else begin
            if (clear_overflow) overflow_seen <= 1'b0;
            else if (wr_en && full && !rd_en) overflow_seen <= 1'b1;
            
            if (wr_en && rd_en && !empty) begin
                wr_ptr <= wr_ptr + 1;
                rd_ptr <= rd_ptr + 1;
            end else if (wr_en && !full) begin
                wr_ptr <= wr_ptr + 1;
                internal_count <= internal_count + 1;
            end else if (rd_en && !empty) begin
                rd_ptr <= rd_ptr + 1;
                internal_count <= internal_count - 1;
            end
        end
    end

    // Memory read/write logic (synchronous, no async reset)
    always_ff @(posedge clk) begin
        if (wr_en && (!full || rd_en)) begin
            mem[wr_ptr] <= din;
        end
        if (rd_en && !empty) begin
            dout <= mem[rd_ptr];
        end
    end

endmodule
