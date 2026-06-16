import izh_pkg::*;

module neuron_state_mem #(
    parameter int ADDR_WIDTH = 14,
    parameter int NUM_NEURONS = 16384
)(
    input  logic              clk,
    
    // Port A: Read/Write for Controller update
    input  logic [ADDR_WIDTH-1:0] addr_a,
    input  storage_t          v_din_a,
    input  storage_t          u_din_a,
    input  logic              we_a,
    output storage_t          v_dout_a,
    output storage_t          u_dout_a,
    
    // Port B: Optional external access (e.g. initialization)
    input  logic [ADDR_WIDTH-1:0] addr_b,
    input  storage_t          v_din_b,
    input  storage_t          u_din_b,
    input  logic              we_b,
    output storage_t          v_dout_b,
    output storage_t          u_dout_b
);
    // Inferred Dual-Port BRAM
    storage_t v_mem [NUM_NEURONS];
    storage_t u_mem [NUM_NEURONS];

    initial begin
        for (int i = 0; i < NUM_NEURONS; i++) begin
            v_mem[i] = -18'sh10400; // -65.0 in Q8.10
            u_mem[i] = -18'sh03400; // -13.0 in Q8.10
        end
    end

    always_ff @(posedge clk) begin
        if (we_a) begin
            v_mem[addr_a] <= v_din_a;
            u_mem[addr_a] <= u_din_a;
        end
        v_dout_a <= v_mem[addr_a];
        u_dout_a <= u_mem[addr_a];
    end

    always_ff @(posedge clk) begin
        if (we_b) begin
            v_mem[addr_b] <= v_din_b;
            u_mem[addr_b] <= u_din_b;
        end
        v_dout_b <= v_mem[addr_b];
        u_dout_b <= u_mem[addr_b];
    end

endmodule
