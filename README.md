# Owon XDM1041 Large-Display Server

The Owon XDM1041 Large-Display Server provides a web-based dashboard for real-time monitoring and control of the **Owon-XDM1041** benchtop 50,000-count true RMS digital multimeter over USB.

The software acts as a bridge between the multimeter and a browser, replacing bulky and slow official PC software with a fast, lightweight, and modern UI.

## Features

- **Live Streaming Measurements**: Reads values directly via USB SCPI at high speed and pushes them over WebSockets to a web dashboard.
- **Bi-directional Web Control**: Change measurement modes (DC V, AC V, DC A, AC A, Res, Cap, Freq, Temp, Diode, Cont), ranges, and polling speeds directly from your browser.
- **Adaptive SI Prefixing**: Automatically scales readings mathematically via the server, displaying precise measurements with the correct symbols (e.g. `kΩ`, `mV`, `μA`).
- **Multi-client Display**: You can open the display panel simultaneously on a phone, tablet, and PC across your local network.
- **Cross-platform**: Runs natively on Linux (and other systems supporting Python and PySerial). 
- **Easy Installation**: Comes with a quick launch Desktop shortcut to immediately spin up the local server and default browser.

## Components

- **`xdm1041_server.py`**: The core Python backend. It handles USB serial communications with the XDM1041 via SCPI, implements a WebSocket server to push data in real-time, and spins up an HTTP server to serve the frontend interface.
- **`xdm1041_display.html`**: A clean, responsive HTML/JS web application that communicates with the Python server. It controls the DMM and beautifully renders the meter displays.
- **`xdm1041_launcher.sh`**: Helper shell script that automatically locates device ports, ensures all dependencies are fulfilled, launches the backend seamlessly, and opens the front-end in your browser.
- **`install.sh`**: Sets up desktop shortcuts and installs dependencies for Linux platforms (like Ubuntu/Debian).

## Requirements

- Python 3.7+
- `pyserial`
- `websockets`

## Usage

### Using the Automated Launcher
If you are running a Linux desktop environment, you can run the simplified launcher:
```bash
./xdm1041_launcher.sh
```

### Manual Execution
1. Install dependencies via pip:
   ```bash
   pip install pyserial websockets
   ```
2. Start the server (replace `/dev/ttyUSB0` with the actual USB serial port of the DMM):
   ```bash
   python3 xdm1041_server.py --port /dev/ttyUSB0 --baud 115200
   ```
3. Open your browser and navigate to:
   ```
   http://localhost:8080
   ```

*Note: For USB access on Linux systems, assure that your user is part of the `dialout` group (`sudo usermod -aG dialout $USER`), otherwise root privileges might be required to open the USB serial port.*

## License

MIT License
