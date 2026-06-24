# Simulation and Testing

Ensuring the behavioral accuracy of the hardware is critical. Testing is primarily handled in Python.

## Running Tests
Ensure your python virtual environment is activated and all dependencies (cocotb, numpy, matplotlib, scipy) are installed.

```bash
cd sim
source ../.venv/bin/activate
make verify
```

### RTL Validation
We use Cocotb and Icarus Verilog to validate the SystemVerilog HDL against our biological goals.

1. **Test Single Izhikevich Engine**:
   ```bash
   python test_izh_engine.py
   ```
   *Claim: the fixed-point engine integrates membrane voltage correctly — charging under stimulus and resetting at threshold. (Bit-exact RTL-vs-fixed-point-reference checking is in `test_golden.py`; floating-point error is characterized offline in `sim/fixed_point_compare.cpp`, not in this regression.)*
   **Status: Re-verified and Passing.** The fixed-point integration properly calculates membrane voltage jumps when stimulated.

2. **Test 16,384 Array Controller**:
   ```bash
   python test_retina_system.py
   ```
   *Claim: Process all 16,384 neurons and streams out valid spikes under dynamic stimuli.*
   **Status: Re-verified and Passing.** Full 128x128 frame integration logic works cleanly, buffering spikes efficiently.

The full `make verify` target runs twelve Cocotb tests: engine, golden model, pipeline, spike FIFO, backpressure/overflow, interrupt logic, foveation zones, AXI-Lite stress, full retina integration, the DMA pixel-ingress AXI-Stream adapter, the DMA-enabled wrapper integration test, and a float-vs-RTL accuracy scoreboard. Latest local run: 2026-06-24, all twelve tests passed.

### System Verification Scripts
We have several higher-level simulation scripts to analyze bottlenecks and stability limits of the system.

1. **Bandwidth Testing**:
   ```bash
   python sim_bandwidth.py
   ```
   This generates a global flash to observe peak spiking rates and computes network stress.
   - Peak Data Rate: ~262 Mbps.
   - Output: `bandwidth_test.png`

2. **Heterogeneity Testing**:
   ```bash
   python sim_heterogeneity.py
   ```
   This validates the visual benefit of using our mixed Midget/Parasol Foveated model against a uniform grid. *(Note: This demonstrates the model-level Python simulation; the underlying parameter multiplexing is also verified in RTL).*
   - Output: `heterogeneity_test_final.png`

3. **Stability & Temporal Aliasing**:
   ```bash
   python sim_stability.py
   ```
   This evaluates different discrete timesteps `dt` and confirms that Euler Integration remains stable at our target timeframe of $1\text{ms}$.
   - Output: `stability_test.png`
