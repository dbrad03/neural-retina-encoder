# Zybo Z7-20 Hardware Bringup Runbook

Step-by-step procedure to bring the Science Eye retina up on a physical
Zybo Z7-20 over PYNQ. Reflects what actually worked during bringup on
2026-06-22 (PYNQ 3.0.1 / Ubuntu 22.04 image, kernel 5.15 v2022.1).
Companion plan: project memory `bringup-plan`.

## Contents of this directory
- `retina.bit` / `retina.hwh` — the PYNQ overlay pair (Vivado 2025.1 build).
  Regenerate with `cd vivado && vivado -mode batch -source build_bd.tcl`, then
  copy `impl_1/system_wrapper.bit` -> `retina.bit` and
  `hw_handoff/system.hwh` -> `retina.hwh`.

## Confirmed on hardware
- Address map (from `system.hwh`) matches the drivers exactly:
  retina IP `0x40000000`, AXI-Stream FIFO `0x43C00000`.
- Design has **no PL I/O pins** — pure PS/AXI, so no XDC pins / LEDs / HDMI.
- The 2025.1 bitstream loads fine on the 2022.1 PYNQ stack (version skew was a
  non-issue — same `xc7z020`).
- Full 16,384-neuron frame computes in ~320–340 µs (well inside the 1 ms budget).

## Register map (hdl/axi_retina_wrapper.sv)
- `0x40000000 + 0x00000` pixel RAM: 32-bit words, low 18 bits = Q8.10, one per neuron.
- `0x40000000 + 0x10000` control/status:
  - write: bit0 start_frame, bit1 clear frame_done, bit2 clear overflow
  - read:  bit0 start, bit1 frame_done, bit2 overflow_seen
- `0x43C00000` AXI-Stream FIFO (`axi_fifo_mm_s`): one TLAST packet per frame.
  Drain: read `RDFO (0x1C)`; if >0, read `RLR (0x24)` for byte length, then pop
  `RLR/4` words from `RDFD (0x20)`. **Never read RLR when RDFO==0** — it returns
  SLVERR → external abort / SIGBUS.

## Gotchas hit during bringup (read these)
1. **Micro-USB must be a DATA cable.** A charge-only cable powers the board
   (PGOOD lights) but the FT2232 won't enumerate — no `/dev/ttyUSB*`. Verify with
   `sudo dmesg -w` while replugging; expect "FTDI ... attached to ttyUSB0/1".
2. **Serial console = `ttyUSB1`** (ttyUSB0 is JTAG): `sudo screen /dev/ttyUSB1 115200`.
   Power-cycle with the board's **SW4 slide switch**, not the cable (the cable
   also powers the board, so unplugging kills the console).
3. **Run board Python with the venv interpreter**: `/usr/local/share/pynq-venv/bin/python3`.
   The system `python3` lacks PYNQ's deps (e.g. pydantic lives in the venv).
4. **Run as root via a LOGIN shell** (`sudo -i`), not plain `sudo`. Plain `sudo`
   strips the XRT environment (`/etc/profile.d/xrt_setup.sh`) → PYNQ throws
   `RuntimeError: No Devices Found`. `sudo -i` sources it.
5. **TLAST**: the spike stream now asserts `m_axis_tlast` once per frame and the
   FIFO RX depth is 16384 (one frame). (Earlier builds had no TLAST → `RDFO=0`,
   no spikes drainable.)

## Phase 0 — Prep (off-board)
- Flash a community PYNQ 3.0.1 image for Zybo Z7-20 (gabrielpgagne Drive image,
  or nick-petrovsky GitHub release): extract the `.tar.xz` to a scratch dir
  (NOT /tmp — it's tmpfs), then `dd` the `.img` whole-disk (NOT FAT32+BOOT.bin).
- Have: USB SD reader, microSD 16GB+ U1, UVC USB webcam, **data** micro-USB
  cable, Ethernet cable.

## Phase 1 — First boot
- Jumpers: **JP5 -> SD**. **JP6 -> USB** is fine for power (board + bitstream);
  use a wall 5V/2.1mm center-positive barrel only if the webcam browns it out.
- Insert SD (J4), Ethernet, **data** micro-USB into PROG/UART (J12). Turn on SW4.
- Console: `sudo screen /dev/ttyUSB1 115200`; boot to `pynq login:` (xilinx/xilinx,
  auto-login on serial). DONE LED stays OFF until an overlay loads — expected.
  (Webcam later goes in the USB-A host port J10, JP1 shorted for host mode.)

## Phase 1b — Networking (direct board<->laptop link)
On the **laptop** (NetworkManager): the wired link to the board must be *shared*
(laptop = DHCP server + NAT, board gets internet too). Needs `dnsmasq` installed.
```bash
sudo pacman -S dnsmasq                      # one-time (Arch)
nmcli con modify "Wired connection 1" ipv4.method shared
nmcli con up "Wired connection 1"           # laptop becomes 10.42.0.1
sudo ufw allow in on <board-iface>          # UFW blocks DHCP + the UDP stream otherwise
sudo ufw allow out on <board-iface>
```
On the **board**: `sudo dhclient -v eth0` -> leases `10.42.0.x`. Add an
`~/.ssh/config` Host entry (`Host zybo` / `HostName 10.42.0.x` / `User xilinx`)
and `ssh-copy-id` for passwordless `ssh zybo` / `scp`.

## Phase 2 — Load overlay
```bash
scp deploy/retina.bit deploy/retina.hwh sw/first_light.py zybo:~/   # from laptop
ssh zybo            # then on the board:
sudo -i
cd /tmp
/usr/local/share/pynq-venv/bin/python3 -c \
  "from pynq import Overlay; ol=Overlay('/home/xilinx/retina.bit'); print(list(ol.ip_dict.keys()))"
# expect axi_retina_wrapper_v_0, axi_fifo_mm_s_0, processing_system7_0; DONE LED on
```

## Phase 3 — First light (file-fed, polling)
```bash
# laptop:  cd bci_visualizer && cargo run
# board (root login shell):
cd /home/xilinx
/usr/local/share/pynq-venv/bin/python3 first_light.py 10.42.0.1 [image.png]
```
Expect: `frame_done in ~330 us`, `Packet RLR=… (N spikes)`, and the visualizer
renders a diamond of foveal activity. `10.42.0.1` is the laptop (UDP target).

## Phase 4 — UIO interrupts
```bash
dtc -@ -I dts -O dtb -o uio_retina.dtbo uio_retina.dts
# apply via configfs (or bundle with the overlay), then:
for d in /sys/class/uio/uio*; do echo $d $(cat $d/name); done   # find our node
```

## Phase 5 — Live V4L2 driver (no OpenCV)
```bash
scp -r sw/v4l2_driver zybo:~/        # from laptop
ssh zybo; sudo -i; cd ~xilinx/v4l2_driver && make     # or: make UIO=1
./retina_v4l2 10.42.0.1 /dev/video0
```
Expect: live webcam -> real-time spikes in the visualizer.

## Phase 5b — DMA stimulus input (optional, needs the DMA-enabled overlay)
The current `vivado/build_bd.tcl` builds a DMA-enabled overlay: `axi_dma_0`
(MM2S, simple mode) on PS `S_AXI_HP0`, with its stream feeding the retina's
`s_axis_pixel` ingress (`axi_retina_wrapper` built with `USE_DMA_INGRESS=1`).
The legacy `/dev/mem` pixel-write path still works on this overlay (DMA has
priority on the shared BRAM port but is idle unless you transfer), so
`first_light.py` remains a valid fallback.

```bash
# laptop:  cd bci_visualizer && cargo run
# board (root login shell), with the DMA overlay's retina.bit/.hwh present:
cd /home/xilinx
/usr/local/share/pynq-venv/bin/python3 first_light_dma.py 10.42.0.1 [image.png]
```
`first_light_dma.py` allocates a contiguous PYNQ buffer, fills it with the Q8.10
frame, bursts it in with `dma.sendchannel.transfer()`, then triggers/drains
exactly like `first_light.py`. It checks status bit3 (`dma_frame_loaded`) to
confirm the burst landed. Status bits: 0 start, 1 frame_done, 2 overflow,
3 dma_frame_loaded, 4 dma_err_short, 5 dma_err_long.

> Not yet hardware-validated. The ingress RTL + wrapper integration pass in
> simulation (`make verify` tests 10-11); the block design and on-board DMA flow
> still need a Vivado rebuild and a board run. Measure the AXI-Lite pixel-write
> cost first (`first_light.py` vs `first_light_dma.py` frame time) to confirm the
> DMA payoff before relying on it.

## Phase 6 — Capture + update docs
- Capture frame latency vs the 1 ms budget, live spike rates, a visualizer
  recording, and clearly sourced 2025.1 post-route timing/utilization reports.
- Keep README and portfolio claims at "board-demonstrated on Zybo Z7-20" unless
  longer-duration hardware stress, power, and corner-case artifacts are added.
