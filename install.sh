#!/usr/bin/env bash
# ───────────────────────────────────────────────────────────────
#  XDM1041 Display — Installer
#  Run once:  bash install.sh
#
#  Places files in ~/xdm1041/ and installs the .desktop entry.
# ───────────────────────────────────────────────────────────────

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$HOME/xdm1041"
DESKTOP_DIR="$HOME/.local/share/applications"

echo "╔══════════════════════════════════════════╗"
echo "║   XDM1041 Large-Display — Installer      ║"
echo "╚══════════════════════════════════════════╝"
echo

# ── Create app directory ───────────────────────────────────────
mkdir -p "$APP_DIR"
echo "  [1/5]  Created $APP_DIR"

# ── Copy application files ─────────────────────────────────────
cp "$SCRIPT_DIR/xdm1041_server.py"   "$APP_DIR/"
cp "$SCRIPT_DIR/xdm1041_display.html" "$APP_DIR/"
cp "$SCRIPT_DIR/xdm1041_launcher.sh" "$APP_DIR/"
chmod +x "$APP_DIR/xdm1041_launcher.sh"
echo "  [2/5]  Copied server, display, and launcher to $APP_DIR"

# ── Install .desktop file ─────────────────────────────────────
mkdir -p "$DESKTOP_DIR"
cp "$SCRIPT_DIR/xdm1041-display.desktop" "$DESKTOP_DIR/"
chmod +x "$DESKTOP_DIR/xdm1041-display.desktop"
echo "  [3/5]  Installed desktop entry to $DESKTOP_DIR"

# ── Update desktop database ───────────────────────────────────
if command -v update-desktop-database &>/dev/null; then
    update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true
    echo "  [4/5]  Updated desktop database"
else
    echo "  [4/5]  Skipped desktop database update (not available)"
fi

# ── Install Python dependencies ────────────────────────────────
echo "  [5/5]  Checking Python dependencies …"
python3 -m pip install --user --quiet pyserial websockets 2>/dev/null \
    && echo "         pyserial + websockets installed" \
    || echo "         ⚠  pip install failed — run manually: pip install pyserial websockets"

# ── Dialout group check ───────────────────────────────────────
echo
if id -nG "$USER" | grep -qw dialout; then
    echo "  ✓  User '$USER' is already in the dialout group."
else
    echo "  ⚠  User '$USER' is NOT in the dialout group."
    echo "     Run:  sudo usermod -aG dialout $USER"
    echo "     Then log out and back in."
fi

echo
echo "  ✓  Installation complete."
echo
echo "  You can now launch from:"
echo "    • Activities / App grid → search 'XDM1041'"
echo "    • Terminal:  ~/xdm1041/xdm1041_launcher.sh"
echo
echo "  Before first run, connect the XDM1041 via USB and check:"
echo "    ls /dev/ttyACM* /dev/ttyUSB*"
echo "  If it's not /dev/ttyUSB0, edit the SERIAL_PORT line in"
echo "    $APP_DIR/xdm1041_launcher.sh"
echo
