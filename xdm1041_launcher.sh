#!/usr/bin/env bash
# ───────────────────────────────────────────────────────────────
#  XDM1041 Large-Display Launcher
#  Starts the WebSocket server, opens the browser, and tears
#  everything down cleanly on exit.
# ───────────────────────────────────────────────────────────────

# ── Configuration (edit these to match your setup) ─────────────
APP_DIR="$HOME/xdm1041"
SERIAL_PORT="/dev/ttyUSB0"
BAUD=115200
WS_PORT=8765
HTTP_PORT=8080
POLL_INTERVAL=0.25
BROWSER="xdg-open"          # or: firefox, chromium-browser, google-chrome
# ───────────────────────────────────────────────────────────────

SERVER_PID=""
URL="http://localhost:${HTTP_PORT}/xdm1041_display.html"

cleanup() {
    echo "[xdm1041] Shutting down …"
    if [ -n "$SERVER_PID" ] && kill -0 "$SERVER_PID" 2>/dev/null; then
        kill "$SERVER_PID" 2>/dev/null
        wait "$SERVER_PID" 2>/dev/null
    fi
    echo "[xdm1041] Done."
}
trap cleanup EXIT INT TERM

# ── Sanity checks ──────────────────────────────────────────────
if [ ! -f "$APP_DIR/xdm1041_server.py" ]; then
    notify-send -u critical "XDM1041" \
        "Server script not found at $APP_DIR/xdm1041_server.py"
    echo "[xdm1041] ERROR: $APP_DIR/xdm1041_server.py not found." >&2
    exit 1
fi

if [ ! -c "$SERIAL_PORT" ]; then
    notify-send -u critical "XDM1041" \
        "Serial port $SERIAL_PORT not found. Is the meter connected?"
    echo "[xdm1041] ERROR: $SERIAL_PORT not found." >&2
    exit 1
fi

# ── Start the server ───────────────────────────────────────────
echo "[xdm1041] Starting server on ws://localhost:$WS_PORT …"
python3 "$APP_DIR/xdm1041_server.py" \
    --port "$SERIAL_PORT" \
    --baud "$BAUD" \
    --ws-port "$WS_PORT" \
    --http-port "$HTTP_PORT" \
    --interval "$POLL_INTERVAL" &
SERVER_PID=$!

# Give the server a moment to bind its ports
sleep 2

# Check it's still alive
if ! kill -0 "$SERVER_PID" 2>/dev/null; then
    notify-send -u critical "XDM1041" \
        "Server failed to start. Check terminal for details."
    echo "[xdm1041] ERROR: Server exited prematurely." >&2
    exit 1
fi

# ── Open the browser ───────────────────────────────────────────
echo "[xdm1041] Opening $URL …"
$BROWSER "$URL" &

# ── Keep running until the server exits or we get a signal ─────
wait "$SERVER_PID"
