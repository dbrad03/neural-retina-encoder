package izh_pkg;
    // Storage Type: 18-bit Q8.10 (Fits in native BRAM)
    typedef logic signed [17:0] storage_t;

    // Calculation Type: 32-bit Q16.16 (Better headroom for v^2)
    typedef logic signed [31:0] calc_t;

    // Fixed-point constants in Q16.16
    localparam calc_t FP_ZERO = 32'sh00000000;
    localparam calc_t FP_ONE  = 32'sh00010000; // 1.0 << 16
    
    // Izhikevich Regular Spiking (Midget-like) parameters
    localparam calc_t IZH_A_MIDGET = 32'sh0000051E; // 0.02 * 2^16 = 1310 (0x51E)
    localparam calc_t IZH_D_MIDGET = 32'sh00080000; // 8.0 * 2^16

    // Izhikevich Fast Spiking (Parasol-like) parameters
    localparam calc_t IZH_A_PARASOL = 32'sh0000199A; // 0.1 * 2^16 = 6554 (0x199A)
    localparam calc_t IZH_D_PARASOL = 32'sh00020000; // 2.0 * 2^16

    // Common Parameters
    localparam calc_t IZH_B = 32'sh00003333; // 0.2 * 2^16  = 13107 (0x3333)
    localparam calc_t IZH_C = -32'sh00410000; // -65 * 2^16

    // Thresholds
    localparam calc_t V_THRESH = 32'sh001E0000; // 30mV * 2^16
    localparam calc_t V_REST   = -32'sh00410000; // -65mV * 2^16

    // Model Constants
    localparam calc_t IZH_0_04 = 32'sh00000A3D; // 0.04 * 2^16 = 2621 (0xA3D)
    localparam calc_t IZH_5    = 32'sh00050000; // 5.0 * 2^16
    localparam calc_t IZH_140  = 32'sh008C0000; // 140.0 * 2^16
    localparam calc_t IZH_DT   = 32'sh00001999; // 0.1 * 2^16 = 6553 (0x1999)

    // Helper Functions
    function automatic calc_t fp_mul(calc_t a, calc_t b);
        logic signed [63:0] res;
        res = 64'(a) * 64'(b);
        return res[47:16]; // Shift right by 16
    endfunction

    // Conversion: Storage -> Calculation (Q8.10 to Q16.16)
    function automatic calc_t s2c(storage_t s);
        return calc_t'(s) << 6; 
    endfunction

    // Conversion: Calculation -> Storage (Q16.16 to Q8.10)
    function automatic storage_t c2s(calc_t c);
        return storage_t'(c >> 6);
    endfunction

endpackage
