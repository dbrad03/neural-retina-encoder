import numpy as np
import matplotlib.pyplot as plt
import os

# Izhikevich Model Parameters
CELL_TYPES = {
    'midget':  {'a': 0.02, 'b': 0.2, 'c': -65.0, 'd': 8.0},
    'parasol': {'a': 0.1,  'b': 0.2, 'c': -65.0, 'd': 2.0}
}

def simulate_retina_final(input_img, foveated=False, dt=0.5, duration=150):
    size = input_img.shape[0]
    steps = int(duration / dt)
    v = np.full((size, size), -65.0)
    u = 0.2 * v
    a = np.full((size, size), CELL_TYPES['midget']['a'])
    d = np.full((size, size), CELL_TYPES['midget']['d'])
    
    if foveated:
        y, x = np.ogrid[:size, :size]
        dist = np.sqrt((x-64)**2 + (y-64)**2)
        peripheral_mask = dist > 40
        a[peripheral_mask] = CELL_TYPES['parasol']['a']
        d[peripheral_mask] = CELL_TYPES['parasol']['d']
    
    spike_counts = np.zeros((size, size))
    m_trace, p_trace = [], []
    
    # Coordinates to probe
    m_coord = (64, 64)   # Center of Square
    p_coord = (64, 119)  # Center of Ring (radius ~55)

    for t in range(steps):
        dv = (0.04 * v**2 + 5 * v + 140 - u + input_img) * dt
        du = (a * (0.2 * v - u)) * dt
        v += dv
        u += du
        
        spikes = v >= 30.0
        if np.any(spikes):
            spike_counts[spikes] += 1
            v[spikes] = -65.0
            u[spikes] += d[spikes]
            
        m_trace.append(35 if v[m_coord] >= 29.0 else v[m_coord])
        p_trace.append(35 if v[p_coord] >= 29.0 else v[p_coord])
            
    return spike_counts, np.array(m_trace), np.array(p_trace)

def run_final_test():
    size = 128
    img = np.zeros((size, size))
    img[48:80, 48:80] = 20.0 # Center
    y, x = np.ogrid[:size, :size]
    ring = ((x-64)**2 + (y-64)**2 <= 60**2) & ((x-64)**2 + (y-64)**2 >= 50**2)
    img[ring] = 20.0 # Ring (Same intensity)
    
    counts_u, _, _ = simulate_retina_final(img, foveated=False)
    counts_f, m_t, p_t = simulate_retina_final(img, foveated=True)
    
    plt.figure(figsize=(12, 10))
    
    # Heatmaps
    plt.subplot(2, 2, 1)
    plt.imshow(counts_u, vmin=0, vmax=25, cmap='hot')
    plt.title("Uniform (All Midget)\nSteady, even firing")
    plt.colorbar(label='Total Spikes')

    plt.subplot(2, 2, 2)
    plt.imshow(counts_f, vmin=0, vmax=25, cmap='hot')
    plt.title("Foveated (Mixed Types)\nRing is much 'hotter' (Parasol)")
    plt.colorbar(label='Total Spikes')

    # Traces
    plt.subplot(2, 1, 2)
    t = np.linspace(0, 150, len(m_t))
    plt.plot(t, m_t, label='Midget (Center)', color='blue')
    plt.plot(t, p_t, label='Parasol (Ring)', color='red', alpha=0.7)
    plt.title("Voltage over time (20mA Stimulus)")
    plt.ylabel("mV")
    plt.xlabel("Time (ms)")
    plt.legend()
    plt.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(os.path.expanduser('~/Projects/science-eye-fpga/sim/heterogeneity_test_final.png'))

if __name__ == "__main__":
    run_final_test()
