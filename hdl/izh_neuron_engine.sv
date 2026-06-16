import izh_pkg::*;

module izh_neuron_engine (
    input  logic         clk,
    input  logic         rst_n,
    
    // Input state (from Storage/BRAM)
    input  storage_t     v_curr_s,
    input  storage_t     u_curr_s,
    input  storage_t     i_ext_s,
    
    // Control
    input  logic         start,
    output logic         done,
    
    // Output state (to Storage/BRAM)
    output storage_t     v_next_s,
    output storage_t     u_next_s,
    output logic         spike
);

    // Internal 32-bit state (from current inputs)
    calc_t v_in, u_in, i_in;
    assign v_in = s2c(v_curr_s);
    assign u_in = s2c(u_curr_s);
    assign i_in = s2c(i_ext_s);
    
    // Pipeline Registers
    // Stage 1: Input Capture
    calc_t v_s1, u_s1, i_s1;
    logic  s1_valid, s1_spike_reset;

    // Stage 2: Initial Multiplications
    calc_t v_s2, u_s2, i_s2;
    calc_t v_sq, v_5, bv;
    logic  s2_valid, s2_spike_reset;
    
    // Stage 3: Secondary Multiplications and 1-adder Chains
    calc_t v_s3, u_s3;
    calc_t v2_04, v_sum_part1, v_sum_part2, du_diff;
    logic  s3_valid, s3_spike_reset;

    // Stage 4: Tertiary Multiplications and 2-adder Chains
    calc_t v_s4, u_s4;
    calc_t dv_sum, du;
    logic  s4_valid, s4_spike_reset;

    // Stage 5: Integration Multiplications
    calc_t v_s5, u_s5;
    calc_t dv, du_dt;
    logic  s5_valid, s5_spike_reset;

    // --- PIPELINE STAGE 1: INPUT CAPTURE ---
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            v_s1            <= '0;
            u_s1            <= '0;
            i_s1            <= '0;
            s1_valid        <= '0;
            s1_spike_reset  <= '0;
        end else if (start) begin
            v_s1            <= v_in;
            u_s1            <= u_in;
            i_s1            <= i_in;
            s1_valid        <= 1'b1;
            s1_spike_reset  <= (v_in >= V_THRESH);
        end else begin
            s1_valid        <= 1'b0;
        end
    end

    // --- PIPELINE STAGE 2: INITIAL MULTIPLICATIONS ---
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            v_s2            <= '0;
            u_s2            <= '0;
            i_s2            <= '0;
            v_sq            <= '0;
            v_5             <= '0;
            bv              <= '0;
            s2_valid        <= '0;
            s2_spike_reset  <= '0;
        end else if (s1_valid) begin
            v_s2            <= v_s1;
            u_s2            <= u_s1;
            i_s2            <= i_s1;
            
            // MULTIPLICATIONS ONLY
            v_sq            <= fp_mul(v_s1, v_s1);
            v_5             <= fp_mul(IZH_5, v_s1);
            bv              <= fp_mul(IZH_B, v_s1);
            
            s2_valid        <= 1'b1;
            s2_spike_reset  <= s1_spike_reset;
        end else begin
            s2_valid        <= 1'b0;
        end
    end

    // --- PIPELINE STAGE 3: MULTIPLICATIONS & 1-ADDER CHAINS ---
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            v_s3            <= '0;
            u_s3            <= '0;
            v2_04           <= '0;
            v_sum_part1     <= '0;
            v_sum_part2     <= '0;
            du_diff         <= '0;
            s3_valid        <= '0;
            s3_spike_reset  <= '0;
        end else if (s2_valid) begin
            v_s3 <= v_s2;
            u_s3 <= u_s2;
            
            // MULTIPLICATIONS ONLY
            v2_04 <= fp_mul(IZH_0_04, v_sq);
            
            // 1-ADDER CHAINS
            v_sum_part1 <= v_5 + IZH_140;
            v_sum_part2 <= i_s2 - u_s2;
            du_diff     <= bv - u_s2;
            
            s3_valid        <= 1'b1;
            s3_spike_reset  <= s2_spike_reset;
        end else begin
            s3_valid        <= 1'b0;
        end
    end

    // --- PIPELINE STAGE 4: MULTIPLICATIONS & 2-ADDER CHAINS ---
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            v_s4            <= '0;
            u_s4            <= '0;
            dv_sum          <= '0;
            du              <= '0;
            s4_valid        <= '0;
            s4_spike_reset  <= '0;
        end else if (s3_valid) begin
            v_s4 <= v_s3;
            u_s4 <= u_s3;
            
            // MULTIPLICATIONS ONLY
            du <= fp_mul(IZH_A, du_diff);
            
            // 2-ADDER CHAIN: A + B + C
            dv_sum <= v2_04 + v_sum_part1 + v_sum_part2;
            
            s4_valid        <= 1'b1;
            s4_spike_reset  <= s3_spike_reset;
        end else begin
            s4_valid        <= 1'b0;
        end
    end

    // --- PIPELINE STAGE 5: INTEGRATION MULTIPLICATIONS ---
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            v_s5            <= '0;
            u_s5            <= '0;
            dv              <= '0;
            du_dt           <= '0;
            s5_valid        <= '0;
            s5_spike_reset  <= '0;
        end else if (s4_valid) begin
            v_s5 <= v_s4;
            u_s5 <= u_s4;
            
            // MULTIPLICATIONS ONLY
            dv    <= fp_mul(dv_sum, IZH_DT);
            du_dt <= fp_mul(du, IZH_DT);
            
            s5_valid        <= 1'b1;
            s5_spike_reset  <= s4_spike_reset;
        end else begin
            s5_valid        <= 1'b0;
        end
    end

    // --- PIPELINE STAGE 6: WRITEBACK (1-ADDER CHAINS) ---
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            v_next_s <= c2s(V_REST);
            u_next_s <= '0;
            spike    <= 1'b0;
            done     <= 1'b0;
        end else if (s5_valid) begin
            if (s5_spike_reset) begin
                v_next_s <= c2s(IZH_C);
                u_next_s <= c2s(u_s5 + IZH_D);
                spike    <= 1'b1;
            end else begin
                v_next_s <= c2s(v_s5 + dv);
                u_next_s <= c2s(u_s5 + du_dt);
                spike    <= 1'b0;
            end
            done     <= 1'b1;
        end else begin
            done     <= 1'b0;
            spike    <= 1'b0;
        end
    end

endmodule
