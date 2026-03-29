#!/usr/bin/env python3
"""
XDM1041 Large-Display Server
=============================
Reads the Owon XDM1041 bench multimeter via USB serial (SCPI) and pushes
live readings to a browser over WebSocket.

Dependencies:
    pip install pyserial websockets

Usage:
    python3 xdm1041_server.py [--port /dev/ttyACM0] [--baud 115200] [--ws-port 8765]

Then open xdm1041_display.html in a browser (or http://localhost:8080).
"""

import argparse
import asyncio
import json
import logging
import signal
import sys
import time
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from threading import Thread

import serial
import threading
import websockets

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("xdm1041")

# ---------------------------------------------------------------------------
# SCPI helpers
# ---------------------------------------------------------------------------

# Map SCPI function names to display-friendly labels and units
FUNC_MAP = {
    "VOLT":      ("DC V",   "V"),
    "VOLT:DC":   ("DC V",   "V"),
    "VOLT:AC":   ("AC V",   "V"),
    "CURR":      ("DC A",   "A"),
    "CURR:DC":   ("DC A",   "A"),
    "CURR:AC":   ("AC A",   "A"),
    "RES":       ("Ω",      "Ω"),
    "FRES":      ("4W Ω",   "Ω"),
    "CAP":       ("Cap",    "F"),
    "FREQ":      ("Freq",   "Hz"),
    "TEMP":      ("Temp",   "°C"),
    "DIOD":      ("Diode",  "V"),
    "CONT":      ("Cont",   "Ω"),
}

SI_PREFIXES = [
    (1e12,  "T"),
    (1e9,   "G"),
    (1e6,   "M"),
    (1e3,   "k"),
    (1,     ""),
    (1e-3,  "m"),
    (1e-6,  "μ"),
    (1e-9,  "n"),
    (1e-12, "p"),
]


def format_reading(value: float, base_unit: str) -> dict:
    """Convert a raw float into a display-friendly value + prefixed unit."""
    if value == 0:
        return {"display": "0.0000", "unit": base_unit}

    abs_val = abs(value)
    for threshold, prefix in SI_PREFIXES:
        if abs_val >= threshold:
            scaled = value / threshold
            # Choose decimal places based on magnitude of scaled value
            if abs(scaled) >= 1000:
                fmt = f"{scaled:.1f}"
            elif abs(scaled) >= 100:
                fmt = f"{scaled:.2f}"
            elif abs(scaled) >= 10:
                fmt = f"{scaled:.3f}"
            else:
                fmt = f"{scaled:.4f}"
            return {"display": fmt, "unit": f"{prefix}{base_unit}"}

    # Fallback for extremely small values
    return {"display": f"{value:.6e}", "unit": base_unit}


class XDM1041:
    """Thin wrapper around the serial connection to the XDM1041."""

    def __init__(self, port: str, baud: int = 115200, timeout: float = 1.0):
        self.port = port
        self.baud = baud
        self.timeout = timeout
        self.ser: serial.Serial | None = None
        self._func_cache: str = ""
        self._func_ts: float = 0.0
        self._lock = threading.Lock()  # serialise all access to the port

    # -- connection ----------------------------------------------------------

    def open(self):
        log.info("Opening %s @ %d baud …", self.port, self.baud)
        self.ser = serial.Serial(
            self.port,
            baudrate=self.baud,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=self.timeout,
            write_timeout=self.timeout,
        )
        # Flush any stale data
        self.ser.reset_input_buffer()
        self.ser.reset_output_buffer()
        idn = self._query("*IDN?")
        log.info("Connected: %s", idn.strip() if idn else "(no IDN response)")

    def close(self):
        if self.ser and self.ser.is_open:
            self.ser.close()
            log.info("Serial port closed.")

    # -- low-level I/O -------------------------------------------------------

    def _write(self, cmd: str):
        self.ser.write((cmd + "\n").encode("ascii"))

    def _read(self) -> str:
        return self.ser.readline().decode("ascii", errors="replace").strip()

    def _query(self, cmd: str) -> str:
        with self._lock:
            self.ser.reset_input_buffer()
            self._write(cmd)
            return self._read()

    # -- high-level queries ---------------------------------------------------

    def get_function(self) -> tuple[str, str]:
        """Return (mode_label, base_unit).  Cached for 0.5 s."""
        now = time.monotonic()
        if now - self._func_ts > 0.5:
            resp = self._query("FUNC?")
            if resp:
                # Meter returns e.g. "VOLT AC" (quoted, space-separated)
                # Normalise to colon-separated to match FUNC_MAP keys
                cleaned = resp.strip().strip('"').upper()
                cleaned = cleaned.replace(" ", ":")
                self._func_cache = cleaned
            self._func_ts = now
        info = FUNC_MAP.get(self._func_cache, (self._func_cache, ""))
        return info

    def invalidate_func_cache(self):
        """Force a fresh FUNC? query on the next get_function() call."""
        self._func_ts = 0.0

    # Map FUNC arguments to CONF: command syntax.
    # On firmware V3.1.0 the FUNC command is ignored; only CONF: works.
    FUNC_TO_CONF = {
        "VOLT":    "CONF:VOLT:DC",
        "VOLT:DC": "CONF:VOLT:DC",
        "VOLT:AC": "CONF:VOLT:AC",
        "CURR":    "CONF:CURR:DC",
        "CURR:DC": "CONF:CURR:DC",
        "CURR:AC": "CONF:CURR:AC",
        "RES":     "CONF:RES",
        "FRES":    "CONF:FRES",
        "CAP":     "CONF:CAP",
        "FREQ":    "CONF:FREQ",
        "TEMP":    "CONF:TEMP:RTD",
        "DIOD":    "CONF:DIOD",
        "CONT":    "CONF:CONT",
    }

    def send_command(self, cmd: str) -> str:
        """Send a SCPI command and return the meter's response.

        On XDM1041 V3.1.0 firmware, FUNC commands are silently ignored.
        This method translates FUNC <mode> into the equivalent CONF:
        command which does work.
        """
        with self._lock:
            self.ser.reset_input_buffer()
            upper = cmd.strip().upper()

            # Translate FUNC <mode> → CONF:<mode> syntax
            if upper.startswith("FUNC ") and "?" not in upper:
                func_arg = upper[5:].strip().strip('"')
                conf_cmd = self.FUNC_TO_CONF.get(func_arg)
                if conf_cmd:
                    cmd = conf_cmd
                    log.info("  Translated FUNC → %s", cmd)
                else:
                    log.warning("  Unknown FUNC arg: %r", func_arg)

            self._write(cmd)

            # Function and range changes need settling time
            if "CONF:" in cmd.upper() or "RANGE" in upper:
                time.sleep(0.4)
            else:
                time.sleep(0.1)

            # Read response (query or ack)
            resp = ""
            if self.ser.in_waiting or "?" in cmd:
                resp = self._read()

            log.info("  → sent: %r  ← recv: %r", cmd, resp)
            return resp

    def get_range_auto(self) -> bool | None:
        """Query whether auto-range is currently enabled.
        Note: V3.1.0 firmware does not respond to RANGE:AUTO? queries,
        so this always returns None."""
        return None

    def get_speed(self) -> str | None:
        """Query measurement speed: F(ast), M(edium), S(low)."""
        resp = self._query("RATE?")
        return resp.strip() if resp else None

    def get_reading(self) -> dict:
        """
        Poll MEAS? and return a JSON-ready dict:
            { value, display, unit, mode, raw, ok }
        """
        resp = self._query("MEAS?")
        if not resp:
            return {"ok": False, "error": "No response"}

        try:
            # MEAS? may return two comma-separated values in dual-display mode
            parts = resp.split(",")
            raw_val = float(parts[0])
        except (ValueError, IndexError):
            return {"ok": False, "error": f"Parse error: {resp!r}"}

        mode_label, base_unit = self.get_function()
        formatted = format_reading(raw_val, base_unit)

        result = {
            "ok":       True,
            "value":    raw_val,
            "display":  formatted["display"],
            "unit":     formatted["unit"],
            "mode":     mode_label,
            "raw_func": self._func_cache,
            "raw":      resp,
        }

        # If dual display, include secondary reading
        if len(parts) > 1:
            try:
                result["secondary"] = float(parts[1])
            except ValueError:
                pass

        return result


# ---------------------------------------------------------------------------
# WebSocket server
# ---------------------------------------------------------------------------

clients: set[websockets.WebSocketServerProtocol] = set()
meter: XDM1041 | None = None
poll_interval: float = 0.25  # seconds


# Whitelist of allowed SCPI command prefixes (safety: don't let the browser
# send arbitrary strings to the meter — only known-safe commands).
ALLOWED_CMD_PREFIXES = (
    "FUNC ",       # switch measurement function
    "FUNC?",       # query current function
    "VOLT:",       # voltage range/config
    "CURR:",       # current range/config
    "RES:",        # resistance range/config
    "FRES:",       # 4-wire resistance range/config
    "CAP:",        # capacitance range/config
    "FREQ:",       # frequency config
    "RATE ",       # measurement speed
    "RATE?",       # query speed
    "CONT:THRE",   # continuity threshold
    "TEMP:",       # temperature config
    "*RST",        # reset
    "*IDN?",       # identify
)


def is_command_allowed(cmd: str) -> bool:
    """Check if a SCPI command is in the whitelist."""
    upper = cmd.strip().upper()
    return any(upper.startswith(p) for p in ALLOWED_CMD_PREFIXES)


async def ws_handler(ws):
    clients.add(ws)
    remote = ws.remote_address
    log.info("Client connected: %s", remote)
    try:
        async for msg in ws:
            # Parse incoming commands from the browser
            try:
                data = json.loads(msg)
            except json.JSONDecodeError:
                continue

            cmd_type = data.get("type")

            if cmd_type == "scpi" and meter and meter.ser and meter.ser.is_open:
                scpi_cmd = data.get("cmd", "").strip()
                if not scpi_cmd:
                    continue

                if not is_command_allowed(scpi_cmd):
                    resp = {"type": "cmd_resp", "ok": False,
                            "error": f"Command not allowed: {scpi_cmd}"}
                    await ws.send(json.dumps(resp))
                    log.warning("Blocked command: %s", scpi_cmd)
                    continue

                log.info("SCPI cmd from %s: %s", remote, scpi_cmd)
                try:
                    result = meter.send_command(scpi_cmd)
                    # Invalidate function cache after a FUNC switch
                    if scpi_cmd.upper().startswith("FUNC "):
                        meter.invalidate_func_cache()
                    resp = {"type": "cmd_resp", "ok": True,
                            "cmd": scpi_cmd, "response": result}
                except Exception as exc:
                    resp = {"type": "cmd_resp", "ok": False,
                            "cmd": scpi_cmd, "error": str(exc)}
                await ws.send(json.dumps(resp))

            elif cmd_type == "query_state" and meter and meter.ser and meter.ser.is_open:
                # Browser is asking for current range/speed state
                try:
                    auto = meter.get_range_auto()
                    speed = meter.get_speed()
                    resp = {"type": "state", "ok": True,
                            "range_auto": auto, "speed": speed}
                except Exception as exc:
                    resp = {"type": "state", "ok": False, "error": str(exc)}
                await ws.send(json.dumps(resp))

    finally:
        clients.discard(ws)
        log.info("Client disconnected: %s", remote)


async def poll_meter():
    """Continuously read the meter and broadcast to all connected clients."""
    while True:
        if meter and meter.ser and meter.ser.is_open:
            try:
                reading = meter.get_reading()
            except Exception as exc:
                reading = {"ok": False, "error": str(exc)}
        else:
            reading = {"ok": False, "error": "Not connected"}

        if clients:
            payload = json.dumps(reading)
            await asyncio.gather(
                *(c.send(payload) for c in list(clients)),
                return_exceptions=True,
            )

        await asyncio.sleep(poll_interval)


# ---------------------------------------------------------------------------
# Tiny HTTP server (serves the HTML file on port 8080)
# ---------------------------------------------------------------------------

def start_http_server(directory: str, port: int = 8080):
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=directory, **kw)

        def log_message(self, fmt, *args):
            pass  # silence request logs

    httpd = HTTPServer(("0.0.0.0", port), Handler)
    log.info("HTTP server: http://localhost:%d/xdm1041_display.html", port)
    httpd.serve_forever()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(description="XDM1041 Large-Display Server")
    p.add_argument("--port",    default="/dev/ttyUSB0", help="Serial port (default: /dev/ttyUSB0)")
    p.add_argument("--baud",    type=int, default=115200, help="Baud rate (default: 115200)")
    p.add_argument("--ws-port", type=int, default=8765, dest="ws_port", help="WebSocket port (default: 8765)")
    p.add_argument("--http-port", type=int, default=8080, dest="http_port", help="HTTP port (default: 8080)")
    p.add_argument("--interval", type=float, default=0.25, help="Poll interval in seconds (default: 0.25)")
    return p.parse_args()


async def main_async(args):
    global meter, poll_interval
    poll_interval = args.interval

    # Open the meter
    meter = XDM1041(args.port, args.baud)
    try:
        meter.open()
    except serial.SerialException as exc:
        log.error("Cannot open %s: %s", args.port, exc)
        log.info("Tip: check the port with  ls /dev/ttyACM* /dev/ttyUSB*")
        log.info("     you may need:  sudo usermod -aG dialout $USER  (then re-login)")
        sys.exit(1)

    # Start HTTP server in a background thread
    html_dir = str(Path(__file__).resolve().parent)
    http_thread = Thread(target=start_http_server, args=(html_dir, args.http_port), daemon=True)
    http_thread.start()

    # Start WebSocket server + polling loop
    log.info("WebSocket server: ws://localhost:%d", args.ws_port)
    async with websockets.serve(ws_handler, "0.0.0.0", args.ws_port):
        await poll_meter()


def main():
    args = parse_args()

    loop = asyncio.new_event_loop()

    def shutdown(signum, frame):
        log.info("Shutting down …")
        if meter:
            meter.close()
        loop.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    try:
        loop.run_until_complete(main_async(args))
    except KeyboardInterrupt:
        pass
    finally:
        if meter:
            meter.close()


if __name__ == "__main__":
    main()
