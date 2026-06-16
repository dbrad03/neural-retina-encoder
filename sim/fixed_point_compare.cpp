#include <iostream>
#include <vector>
#include <fstream>
#include <cmath>
#include <iomanip>
#include <cstdint>

// Fixed-Point Emulation Helper
struct FixedPoint {
    int64_t val;
    int frac_bits;

    FixedPoint(float f, int fb) : frac_bits(fb) {
        val = static_cast<int64_t>(f * (1LL << frac_bits));
    }

    FixedPoint(int64_t raw, int fb) : val(raw), frac_bits(fb) {}

    float to_float() const {
        return static_cast<float>(val) / (1LL << frac_bits);
    }

    FixedPoint operator*(const FixedPoint& other) const {
        int64_t res = (val * other.val) >> frac_bits;
        return FixedPoint(res, frac_bits);
    }

    FixedPoint operator+(const FixedPoint& other) const {
        return FixedPoint(val + other.val, frac_bits);
    }

    FixedPoint operator-(const FixedPoint& other) const {
        return FixedPoint(val - other.val, frac_bits);
    }

    bool operator>=(const FixedPoint& other) const {
        return val >= other.val;
    }
};

struct IzhNeuronFixed {
    int frac_bits;
    FixedPoint v, u, a, b, c, d, dt;
    FixedPoint f004, f5, f140;
    bool spiked = false;

    IzhNeuronFixed(int fb) : 
        frac_bits(fb),
        v(-65.0f, fb), u(-13.0f, fb), 
        a(0.02f, fb), b(0.2f, fb), c(-65.0f, fb), d(8.0f, fb),
        dt(0.1f, fb), f004(0.04f, fb), f5(5.0f, fb), f140(140.0f, fb) {}

    void update(float i_in_float) {
        FixedPoint i_in(i_in_float, frac_bits);
        if (spiked) {
            v = c;
            u = u + d;
            spiked = false;
        }

        FixedPoint v_sq = v * v;
        FixedPoint term1 = f004 * v_sq;
        FixedPoint term2 = f5 * v;
        FixedPoint dv = (term1 + term2 + f140 - u + i_in) * dt;
        FixedPoint du = (a * ((b * v) - u)) * dt;

        v = v + dv;
        u = u + du;

        if (v >= FixedPoint(30.0f, frac_bits)) {
            spiked = true;
        }
    }
};

int main() {
    const float SIM_DT = 0.1f;
    const int STEPS = 2000;

    float v_float = -65.0f;
    float u_float = -13.0f;

    IzhNeuronFixed izh_q10(10); 
    IzhNeuronFixed izh_q20(20); 

    std::string csv_path = "/home/darchb/Projects/science-eye-fpga/sim/fixed_point_compare.csv";
    std::ofstream outFile(csv_path);
    outFile << "Time,Float_V,Q10_V,Q20_V\n";

    for (int t = 0; t < STEPS; ++t) {
        float i_in = (t * SIM_DT > 10.0f) ? 15.0f : 0.0f;

        if (v_float >= 30.0f) { v_float = -65.0f; u_float += 8.0f; }
        float dv = (0.04f * v_float * v_float + 5.0f * v_float + 140.0f - u_float + i_in) * SIM_DT;
        float du = (0.02f * (0.2f * v_float - u_float)) * SIM_DT;
        v_float += dv; u_float += du;

        izh_q10.update(i_in);
        izh_q20.update(i_in);

        outFile << t * SIM_DT << "," << v_float << "," << izh_q10.v.to_float() << "," << izh_q20.v.to_float() << "\n";
    }

    return 0;
}
