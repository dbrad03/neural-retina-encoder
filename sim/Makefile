.PHONY: verify

verify:
	@echo "Running all Cocotb tests..."
	@source ../.venv/bin/activate && \
	echo "--- 1. Testing Core Izhikevich Engine ---" && \
	python test_izh_engine.py && python check_results.py && \
	echo "--- 2. Testing Golden Scoreboard ---" && \
	python test_golden.py && python check_results.py && \
	echo "--- 3. Testing Pipeline Alignment ---" && \
	python test_pipeline.py && python check_results.py && \
	echo "--- 4. Testing Spike FIFO ---" && \
	python test_spike_fifo.py && python check_results.py && \
	echo "--- 5. Testing Backpressure & Overflow ---" && \
	python test_backpressure.py && python check_results.py && \
	echo "--- 6. Testing Interrupt Logic ---" && \
	python test_interrupt.py && python check_results.py && \
	echo "--- 7. Testing Foveation Zones ---" && \
	python test_foveation.py && python check_results.py && \
	echo "--- 8. Testing AXI-Lite Stress ---" && \
	python test_axi_stress.py && python check_results.py && \
	echo "--- 9. Testing Full Retina System Integration ---" && \
	python test_retina_system.py && python check_results.py && \
	echo "--- 10. Testing DMA Pixel Ingress (AXI-Stream) ---" && \
	python test_pixel_ingress.py && python check_results.py && \
	echo "--- 11. Testing DMA Wrapper Integration (AXI-Stream -> BRAM) ---" && \
	python test_dma_wrapper.py && python check_results.py && \
	echo "All tests passed successfully!"
