import numpy as np
import matplotlib.pyplot as plt
import os

# Izhikevich Parameters for Foveated Model
CELL_TYPES = {
    'midget':  {'a': 0.02, 'b': 0.2, 'c': -65.0, 'd': 8.0},
    'parasol': {'a': 0.1,  'b': 0.2, 'c': -65.0, 'd': 2.0}
}

def simulate_spike_storm(size=128, duration_ms=50, dt=0.5):
    steps = int(duration_ms / dt)
    num_neurons = size * size
    
    # Initialize foveated grid
    v = np.full((size, size), -65.0)
    u = 0.2 * v
    a = np.full((size, size), CELL_TYPES['midget']['a'])
    d = np.full((size, size), CELL_TYPES['midget']['d'])
    
    # Peripheral neurons (Parasol)
    y, x = np.ogrid[:size, :size]
    dist = np.sqrt((x-64)**2 + (y-64)**2)
    peripheral_mask = dist > 40
    a[peripheral_mask] = CELL_TYPES['parasol']['a']
    d[peripheral_mask] = CELL_TYPES['parasol']['d']
    
    # Stimulus: Global Flash at t=5ms
    # 0 to 20mA intensity everywhere
    stimulus = 20.0
    
    spikes_per_step = []
    
    for t in range(steps):
        current_time = t * dt
        i_ext = stimulus if current_time >= 5.0 else 0.0
        
        # Vectorized Izhikevich
        dv = (0.04 * v**2 + 5 * v + 140 - u + i_ext) * dt
        du = (a * (0.2 * v - u)) * dt
        v += dv
        u += du
        
        spikes = v >= 30.0
        spike_count = np.sum(spikes)
        spikes_per_step.append(spike_count)
        
        if spike_count > 0:
            v[spikes] = -65.0
            u[spikes] += d[spikes]
            
    return np.array(spikes_per_step)

def analyze_bandwidth():
    dt = 0.5
    size = 128
    spikes_per_step = simulate_spike_storm(size=size, duration_ms=100, dt=dt)
    
    # Group into 1ms bins (Biological windows)
    # Every 2 steps = 1ms
    spikes_per_ms = spikes_per_step.reshape(-1, 2).sum(axis=1)
    
    time_ms = np.arange(len(spikes_per_ms))
    
    # Calculate Data Rate
    # Each spike needs ~14 bits for address (log2(16384))
    # Let's say 16 bits for a clean 2-byte packet per spike.
    bits_per_ms = spikes_per_ms * 16
    mbps = bits_per_ms / 1000 # Mbps (bits per ms is kbits per sec)
    
    peak_spikes = np.max(spikes_per_ms)
    avg_spikes = np.mean(spikes_per_ms[10:]) # Average during the flash
    
    plt.figure(figsize=(10, 6))
    plt.plot(time_ms, spikes_per_ms, color='red', linewidth=2)
    plt.fill_between(time_ms, spikes_per_ms, color='red', alpha=0.2)
    
    plt.axhline(y=peak_spikes, color='black', linestyle='--', alpha=0.5)
    plt.text(5, peak_spikes+100, f'Peak: {peak_spikes} spikes/ms', fontweight='bold')
    
    plt.title('Spike Bandwidth: Global Flash Response (16,384 Neurons)')
    plt.ylabel('Spikes per 1ms window')
    plt.xlabel('Time (ms)')
    plt.grid(True, alpha=0.3)
    
    img_path = os.path.expanduser('~/Projects/science-eye-fpga/sim/bandwidth_test.png')
    plt.savefig(img_path)
    
    print(f"--- Bandwidth Analysis ---")
    print(f"Peak Spikes/ms: {peak_spikes}")
    print(f"Avg Spikes/ms during flash: {avg_spikes:.1f}")
    print(f"Peak Data Rate: {(peak_spikes * 16 * 1000) / 1e6:.2f} Mbps")
    print(f"Avg Data Rate: {(avg_spikes * 16 * 1000) / 1e6:.2f} Mbps")
    print(f"--------------------------")
    print(f"Graph saved to {img_path}")

if __name__ == "__main__":
    analyze_bandwidth()
