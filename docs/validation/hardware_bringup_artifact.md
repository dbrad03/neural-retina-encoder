# Hardware Bring-up Artifact

## Environment
- **Board:** Zybo Z7-20 (`xc7z020clg400-1`)
- **Software image:** PYNQ 3.0.1 / Ubuntu 22.04
- **Kernel:** 5.15, v2022.1 stack
- **Camera:** Logitech C270, USB ID `046d:0825`
- **Network:** direct Ethernet, laptop at `10.42.0.1` via NetworkManager shared connection
- **Overlay:** `deploy/retina.bit` / `deploy/retina.hwh`, generated from Vivado 2025.1 block design

## Commands Used
Load overlay:
```bash
sudo -i
/usr/local/share/pynq-venv/bin/python3 -c \
  "from pynq import Overlay; ol=Overlay('/home/xilinx/retina.bit'); print(list(ol.ip_dict.keys()))"
```

Run file-fed first light:
```bash
/usr/local/share/pynq-venv/bin/python3 first_light.py 10.42.0.1
```

Build and run the supported live camera driver:
```bash
cd ~xilinx/v4l2_driver
make clean && make
# Defaults to 160x120 YUYV @ 15 FPS
./retina_v4l2 10.42.0.1 /dev/video0
```

Run the visualizer on the laptop:
```bash
cd bci_visualizer
cargo run --release
```

---

## Technical Blockers & Resolutions

During hardware bring-up on 2026-06-22 and 2026-06-23, two critical blockers were hit and resolved to achieve the live streaming demonstration:

### 1. USB Camera Stream Startup Hang (Bandwidth Ceiling)
*   **Problem:** Requesting `320x240 YUYV @ 30 FPS` caused the driver's `VIDIOC_STREAMON` ioctl call to fail with `ENOMEM` (Cannot allocate memory). The Zynq `ci_hdrc` USB host controller was unable to reserve the necessary isochronous bandwidth (~37 Mbps) under this kernel configuration.
*   **Resolution:** Configured the driver to default to `160x120 YUYV @ 15 FPS`, which easily fits within the USB controller's isochronous scheduling budget. The driver downsamples this input to the `128x128` retina grid anyway, so functional resolution was unaffected.

### 2. Board Reset/Crash on Camera Stream Start (Power Brownout)
*   **Problem:** Running the board solely on laptop USB power resulted in immediate board resets (DONE/PGOOD LEDs flickering and turning off, volatile PL bitstream wiped) upon starting the camera stream. The peak current draw of the Zynq core + active camera exceeds standard laptop USB current limits (0.5 A).
*   **Resolution:** Power the Zybo Z7-20 via an external 5V / 3A DC barrel jack supply (JP6 jumpered to WALL) or connect a powered USB hub between the camera and the board's USB J10 Host port to isolate the camera's current draw from the board's power rail.

---

## Observed Results
- PYNQ overlay loaded and successfully exposed IP blocks: `axi_retina_wrapper_v_0`, `axi_fifo_mm_s_0`, and `processing_system7_0`.
- Memory address map verified: retina IP register access at `0x40000000`, AXI FIFO at `0x43C00000`.
- File-fed `first_light.py` completed frames, drained FIFO packets, and displayed stimulus/spike activity in the Rust visualizer.
- Live UVC camera path successfully streams frames without crash or lag: captures raw YUYV V4L2 buffers, writes luma stimulus through memory-mapped `/dev/mem` registers using FPU-free integer downsampling, executes hardware logic, and drains spikes via batched UDP packets.
- PL frame latency (pixel write → engine scan → FIFO drain) observed around **320-340 $\mu\text{s}$**, safely inside the 1 ms biological frame budget. This is the hardware processing latency only; the end-to-end live loop is camera-bound at ~30 fps (see the timing benchmark in `validation/README.md`).

## Claim Boundary
This artifact supports the "board-demonstrated live path on Zybo Z7-20." It does not by itself prove long-duration thermal stability, all camera video modes, UIO interrupt stability under extreme loads, or complete product validation.
