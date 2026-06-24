# Physical Bring-up Plan

The initial Zybo Z7-20 bring-up has completed; see `hardware_bringup_artifact.md` for the current artifact summary. The remaining plan below is for deeper validation and repeatable evidence capture.

1. **Physical Setup:**
   - Connect Zybo power and micro-USB UART/JTAG.
   - Connect a physical 720p USB webcam to the board's USB OTG port.
   - Connect the Zybo Ethernet port to the development laptop.
   - **Artifact:** Photo of the physical testing setup.

2. **Linux & Device Tree Validation:**
   - Boot PetaLinux.
   - Run `dmesg | grep uio` to verify `generic-uio` has successfully bound to the custom Retina IP at `0x40000000` and the AXI FIFO at `0x43C00000`.
   - **Artifact:** Console screenshot showing successful UIO binding.

3. **Software Driver Bring-up:**
   - Copy `retina.bit`, `retina.hwh`, and the board software to the board.
   - Load the overlay through PYNQ.
   - Run file-fed `first_light.py`, then `retina_v4l2 <LAPTOP_IP> /dev/video0`.
   - **Artifact:** Serial/log output showing successful `/dev/mem` mmap and camera initialization.

4. **Network & Timing Validation:**
   - On the laptop, run `tcpdump -i eth0 udp port 8080` to verify spikes and images are streaming.
   - Measure the frame latency (trigger to `frame_done_irq` wake up) by adding timestamps around the `read(uio_fd)` call. Verify it is $< 1\text{ms}$.
   - **Artifact:** Wireshark/tcpdump capture log.

5. **Visual Validation:**
   - Launch the Rust `bci_visualizer` in release mode.
   - Observe the real-time spiking network reacting to live physical stimuli.
   - **Artifact:** Video screen-recording of the visualizer.

*(Optional) If issues occur: Use a Vivado ILA (Integrated Logic Analyzer) over JTAG to capture `start_frame`, `frame_done_irq`, `m_axis_tvalid`, and FIFO status flags live on the board.*

### Foveation Bringup
With Foveated parameter selection implemented in RTL:
- Wave a hand in front of the camera and verify localized bursting (Parasol) in the periphery and steady firing (Midget) in the fovea.
