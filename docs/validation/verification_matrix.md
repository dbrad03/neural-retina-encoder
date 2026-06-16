# Verification Matrix

| Requirement | Test Name | Status |
| :--- | :--- | :--- |
| Single Izhikevich Engine math | `test_izh_engine.py` | **Passing** |
| Full 16,384 frame scan | `test_retina_system.py` | **Passing** |
| Foveated Parameter Selection | `test_pipeline.py` | *Planned* (Needs RTL change) |
| Pipeline Alignment | `test_pipeline.py` | *Planned* |
| Golden Fixed-Point Scoreboard | `test_golden.py` | *Planned* |
| AXI-Lite AW/W Decoupling Stress | `test_axi_stress.py` | *Planned* (Needs RTL change) |
| Interrupt Latched/Clear | `test_interrupt.py` | *Planned* (Needs RTL change) |
| AXI-Stream Backpressure | `test_backpressure.py` | *Planned* (Needs RTL change) |
