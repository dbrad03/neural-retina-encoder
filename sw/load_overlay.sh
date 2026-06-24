#!/bin/bash
# load_overlay.sh - program the Zynq PL with a PYNQ overlay (.bit + matching .hwh).
#
# The PL configuration is VOLATILE (wiped on every power-off), so run this once
# per boot before first_light.py / the camera driver -- those assume the PL is
# already configured and do NOT program it themselves. Lights the DONE LED.
#
# Usage:  ./load_overlay.sh [bitfile]     (default: retina.bit)
#         Auto-elevates with sudo and sources the XRT env (plain sudo strips it,
#         which otherwise causes PYNQ 'RuntimeError: No Devices Found').
set -u
PYNQ_PY=/usr/local/share/pynq-venv/bin/python3
BIT="${1:-retina.bit}"

if [ ! -f "$BIT" ]; then
    echo "ERROR: bitfile '$BIT' not found (cwd: $(pwd))." >&2
    exit 1
fi
BIT="$(readlink -f "$BIT")"
HWH="${BIT%.bit}.hwh"
if [ ! -f "$HWH" ]; then
    echo "ERROR: matching '$HWH' not found -- PYNQ needs the .hwh beside the .bit." >&2
    exit 1
fi

# PL programming + /dev/mem need root.
if [ "$(id -u)" -ne 0 ]; then
    echo "Elevating with sudo ..."
    exec sudo "$0" "$BIT"
fi

# Restore the XRT environment that plain sudo dropped.
[ -f /etc/profile.d/xrt_setup.sh ] && . /etc/profile.d/xrt_setup.sh

exec "$PYNQ_PY" - "$BIT" <<'PYEOF'
import sys
from pynq import Overlay
bit = sys.argv[1]
ol = Overlay(bit)
print("Loaded overlay:", bit)
print("IP blocks:", list(ol.ip_dict.keys()))
print("DONE LED should now be on.")
PYEOF
