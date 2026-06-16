#include <iostream>
#include <vector>
#include <fstream>
#include <cmath>
#include <iomanip>

// Simulation Parameters
const float DT = 0.1f;         // Timestep (ms)
const int STEPS = 2000;       // Total simulation steps (200ms)

// LIF Parameters (Parasol-like) - Adjusted to be more "excitable"
struct LIFNeuron {
    float v = -65.0f;          
    float v_rest = -65.0f;     
    float v_thresh = -50.0f;   // Lowered threshold (was -50, but let's be sure)
    float tau = 5.0f;          // Faster time constant (was 10.0)
    float r = 2.0f;            // Higher resistance (was 1.0)
    bool just_spiked = false;

    void update(float i_in) {
        if (just_spiked) {
            v = v_rest;
            just_spiked = false;
        }
        
        // Standard LIF Equation: dv/dt = (-(v - v_rest) + r*i) / tau
        float dv = (-(v - v_rest) + (r * i_in)) * (DT / tau);
        v += dv;

        if (v >= v_thresh) {
            just_spiked = true;
            // Note: v stays high for this step for the CSV capture
        }
    }
};

// Izhikevich Regular Spiking (Midget-like)
struct IzhNeuron {
    float v = -65.0f;          
    float u = -13.0f;          
    float a = 0.02f;           
    float b = 0.2f;            
    float c = -65.0f;          
    float d = 8.0f;            
    bool just_spiked = false;

    void update(float i_in) {
        if (just_spiked) {
            v = c;
            u += d;
            just_spiked = false;
        }

        // v' = 0.04v^2 + 5v + 140 - u + I
        // u' = a(bv - u)
        float dv = (0.04f * v * v + 5.0f * v + 140.0f - u + i_in) * DT;
        float du = (a * (b * v - u)) * DT;
        v += dv;
        u += du;

        if (v >= 30.0f) {
            just_spiked = true;
        }
    }
};

int main() {
    LIFNeuron lif;
    IzhNeuron izh;
    
    std::string csv_path = "/home/darchb/Projects/science-eye-fpga/sim/neuron_sim.csv";
    std::ofstream outFile(csv_path);
    
    outFile << "Time,Input_I,LIF_V,Izh_V,LIF_Spike,Izh_Spike\n";

    float input_i = 0.0f;

    for (int t = 0; t < STEPS; ++t) {
        float time_ms = t * DT;
        
        // Strong input to guarantee many spikes
        if (time_ms > 10.0f && time_ms < 180.0f) input_i = 20.0f; 
        else input_i = 0.0f;

        lif.update(input_i);
        izh.update(input_i);

        // Capture if the neuron is CURRENTLY in a spike state
        // In our models, V will be >= thresh for exactly ONE dt
        int lif_s = (lif.just_spiked) ? 1 : 0;
        int izh_s = (izh.just_spiked) ? 1 : 0;

        // Visual spike for the Voltage plot (makes it look like a real spike)
        float v_plot_lif = (lif_s) ? 30.0f : lif.v;
        float v_plot_izh = (izh_s) ? 30.0f : izh.v;

        outFile << std::fixed << std::setprecision(4) 
                << time_ms << "," << input_i << "," 
                << v_plot_lif << "," << v_plot_izh << "," 
                << lif_s << "," << izh_s << "\n";
    }

    return 0;
}
