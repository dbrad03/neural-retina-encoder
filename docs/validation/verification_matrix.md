# Verification Matrix

| Requirement | Test Name | Status |
| :--- | :--- | :--- |
| Single Izhikevich Engine math | `test_izh_engine.py` | **Passing** |
| Full 16,384 frame scan | `test_retina_system.py` | **Passing** |
| Foveated Parameter Selection | `test_foveation.py` | **Passing** |
| Pipeline Alignment | `test_pipeline.py` | **Passing** |
| Golden Fixed-Point Scoreboard | `test_golden.py` | **Passing** |
| Spike FIFO packet/backpressure behavior | `test_spike_fifo.py` | **Passing** |
| AXI-Lite AW/W Decoupling Stress | `test_axi_stress.py` | **Passing** |
| Interrupt Latched/Clear | `test_interrupt.py` | **Passing** |
| AXI-Stream Backpressure | `test_backpressure.py` | **Passing** |
| DMA pixel ingress (AXI-Stream frame load, short/long-packet rejection) | `test_pixel_ingress.py` | **Passing** |
| DMA wrapper integration (AXI-Stream → BRAM, AXI-Lite readback, status latch) | `test_dma_wrapper.py` | **Passing** |
