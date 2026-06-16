import numpy as np
import matplotlib.pyplot as plt
import os

def izhikevich_sim(dt, total_time_ms, i_stim):
    steps = int(total_time_ms / dt)
    v = -65.0
    u = -13.0
    a, b, c, d = 0.02, 0.2, -65.0, 8.0
    
    v_history = []
    spike_times = []
    
    for t in range(steps):
        time = t * dt
        # Current stimulus starts at 10ms
        current = i_stim if time > 10.0 else 0.0
        
        # Euler Integration
        # v' = 0.04v^2 + 5v + 140 - u + I
        dv = (0.04 * v**2 + 5 * v + 140 - u + current) * dt
        du = (a * (b * v - u)) * dt
        
        v += dv
        u += du
        
        if v >= 30.0:
            spike_times.append(time)
            v = c
            u += d
            v_history.append(30.0) # For visualization
        else:
            v_history.append(v)
            
    return np.array(v_history), np.array(spike_times)

def run_stability_test():
    total_time = 200.0
    i_stim = 15.0
    dts = [0.1, 0.25, 0.5, 1.0, 2.0]
    
    plt.figure(figsize=(12, 10))
    
    for i, dt in enumerate(dts):
        v_hist, spikes = izhikevich_sim(dt, total_time, i_stim)
        
        plt.subplot(len(dts), 1, i+1)
        time_axis = np.linspace(0, total_time, len(v_hist))
        plt.plot(time_axis, v_hist, label=f'dt={dt}ms')
        plt.scatter(spikes, [35]*len(spikes), color='red', marker='|', s=50)
        plt.ylabel('mV')
        plt.legend(loc='upper right')
        plt.grid(True, alpha=0.3)
        
        print(f"dt={dt:4}ms | Spikes: {len(spikes):3} | First Spike: {spikes[0] if len(spikes)>0 else 'N/A':5.2f}ms")

    plt.suptitle('Temporal Aliasing: Stability vs. Timestep (dt)')
    plt.xlabel('Time (ms)')
    plt.tight_layout()
    img_path = os.path.expanduser('~/Projects/science-eye-fpga/sim/stability_test.png')
    plt.savefig(img_path)
    print(f"\nStability graph saved to {img_path}")

if __name__ == "__main__":
    run_stability_test()
