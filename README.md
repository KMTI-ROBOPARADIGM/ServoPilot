<h1 align="center">
  <br>
  ServoPilot
  <br>
</h1>
<h4 align="center">A comprehensive desktop application designed for high-performance management and control of ST3215 serial bus servos.</h4>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License: MIT"></a>
</p>


ServoPilot eliminates the complexity of interacting with serial bus servos by providing a visual, professional-grade interface. Whether you're configuring IDs, tuning PID loops, or orchestrating multi-servo movements via external scripts, everything is available in a clean, real-time desktop dashboard. Simply connect, scan, and pilot your robotic creations.

---

## TABLE OF CONTENTS
- [ABOUT THE PROJECT](#about-the-project)
- [KEY FEATURES](#key-features)
- [TECH STACK](#tech-stack)
- [SYSTEM REQUIREMENTS & PREREQUISITES](#system-requirements--prerequisites)
- [GETTING STARTED](#getting-started)
- [INSTALLATION — FULL STEP-BY-STEP GUIDE](#installation--full-step-by-step-guide)
- [CONFIGURATION](#configuration)
- [RUNNING THE PROJECT](#running-the-project)
- [USAGE GUIDE](#usage-guide)
- [API REFERENCE](#api-reference)
- [PROJECT STRUCTURE](#project-structure)
- [TESTING](#testing)
- [REPRODUCING THE INDICON 2026 PAPER](#reproducing-the-indicon-2026-paper)
- [CONTRIBUTING](#contributing)
- [ROADMAP](#roadmap)
- [LICENSE](#license)

---

## ABOUT THE PROJECT
ServoPilot is an all-in-one desktop environment designed to configure, monitor, and control ST3215 serial bus servos. Working with serial bus servos typically requires writing custom scripts to handle raw byte packets, making hardware debugging and tuning a slow, painful process. ServoPilot solves this by giving developers immediate, visual access to the servo's control table and high-speed telemetry. 

What sets ServoPilot apart from basic hardware diagnostic tools is its integrated FastAPI server, which allows external scripts to command the servos via REST/WebSocket while you monitor performance graphically. Combined with high-performance 20Hz pyqtgraph plotting and a modern dark-mode GUI, it serves as the ultimate mission control for your hardware.

![Demo](./ArchitectureDiAGRAM.png)

---

## KEY FEATURES
- 🖥️ **Real-Time Monitor**: Track position, speed, load, voltage, and temperature at up to 20Hz for immediate hardware feedback.
- 📈 **Live Graphing**: Visualize performance metrics with high-performance, real-time plots using pyqtgraph.
- 🎛️ **PID Tuning**: Interactively tune proportional, integral, and derivative gains with integrated step tests to perfect your servo's responsiveness.
- 📋 **Control Table Editor**: Get direct read/write access to the ST3215 Control Table for deep low-level hardware configuration.
- ⚙️ **Device Configuration**: Easily change essential parameters like Servo IDs, baud rates, and physical angle limits without writing scripts.
- 🤝 **Sync Control & Homing**: Group multiple servos together for synchronized movements, precise poses, and reliable homing routines.
- 🔌 **REST & WebSocket API**: Built-in FastAPI server allows you to remotely control servos from external scripts or web dashboards.
- ⛔ **Global Emergency Stop**: Instant torque-off safety switch to prevent physical damage during unexpected collisions.

---

## TECH STACK
| Category | Technology | Version | Purpose |
| --- | --- | --- | --- |
| Frontend | PySide6 | 6.6+ | Powerful bindings for the Qt UI framework to build the desktop GUI |
| Frontend | pyqtgraph | 0.13+ | Extremely fast, high-performance real-time data visualization |
| Backend | Python | 3.10+ | Core application logic and fast execution engine |
| Backend | pyserial | 3.5+ | Reliable UART serial communication with physical hardware |
| API | FastAPI | 0.100+ | High-performance REST API integration for external scripting |
| API | Uvicorn | 0.23+ | ASGI server to route and handle API traffic efficiently |
| Data | Pydantic | 2.0+ | Strict data validation and settings management |
| Data | NumPy | 1.24+ | Vectorized mathematical operations and array processing |

---

## SYSTEM REQUIREMENTS & PREREQUISITES
To run ServoPilot smoothly on your machine, you will need the following baseline software and hardware configurations installed:

- **Python**: Version 3.10 or newer — [Download here](https://www.python.org/downloads/)
- **Git**: Version control — [Download here](https://git-scm.com/downloads)
- **Serial UART Driver**: Depending on your ST3215 adapter (e.g., CP210X, CH340, FTDI), ensure the correct drivers are installed to read the serial port.
- **Hardware**: An ST3215 Servo motor connected to your PC with an appropriate 12V power supply.

**Quick check:**
```bash
python --version   # Required: v3.10+ (or use 'python3' on macOS/Linux)
pip --version      # Required: pip installed
git --version      # Required: any version
```

---

## GETTING STARTED
⚡ **TL;DR Quick Start**
If you already have Python and Git installed, run these four commands to get started:
```bash
git clone https://github.com/KMTI-ROBOPARADIGM/ServoPilot.git
cd ServoPilot
pip install -r requirements.txt
python main.py
```

---

## INSTALLATION — FULL STEP-BY-STEP GUIDE
Follow these steps for a complete, clean setup of the project environment:

1. **Fork the repository** (Optional): Click the "Fork" button at the top right of this repository on GitHub.
2. **Clone the repo**:
```bash
git clone https://github.com/KMTI-ROBOPARADIGM/ServoPilot.git
```
3. **Navigate to the project directory**:
```bash
cd ServoPilot
```
4. **Create a virtual environment (Recommended)**:
```bash
python -m venv venv
# Windows:
venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate
```
5. **Install all dependencies**:
```bash
pip install -r requirements.txt
```
6. **Connect your hardware**: Plug your ST3215 serial bus interface into a USB port on your machine and ensure it has 12V power.
7. **Run the application**:
```bash
python main.py
```

---

## CONFIGURATION
Settings are chosen in the GUI: serial port and baud rate (default 1,000,000) in the servo list panel, telemetry poll rate (10/20/30/50 Hz, default 20 Hz) in the Monitor tab, and the API server (bound to `127.0.0.1:8765`) with the "API ▶" button in the status bar. No `.env` file is used.
---

## RUNNING THE PROJECT
### Development Mode
To launch the core application GUI:
```bash
python main.py
```
**Expected Output:** A dark-themed desktop window will launch, displaying "Disconnected" in the bottom-left status bar.

### API Mode
You can toggle the API directly within the app by clicking the `API ▶` button in the lower right status bar. Once active, the API will be available at:
`http://localhost:8765`

### Troubleshooting Startup
- **"Permission denied (COMx / /dev/ttyUSB0)"**: Your user lacks permission to access the serial port. On Linux, run `sudo usermod -a -G dialout $USER` and log out/in. On Windows, ensure no other terminal apps are using COMx.

---

## USAGE GUIDE
### Core User Flow
1. **Connect**: Open ServoPilot. On the left "Servo List" dock, select your port (e.g., `COM3` or `/dev/ttyUSB0`), leave the baudrate at `1000000`, and click **Connect**.
2. **Scan**: Click **Scan** to ping the bus and discover connected ST3215 servos.
3. **Monitor**: Click a discovered servo ID. The central area will automatically begin streaming telemetry (Position, Speed, Load).
4. **Move**: In the "Monitor" tab, toggle "Torque: ON". Use the Goal Position slider to move the motor.

### Advanced Usage: Synchronized Movements
To move several servos together:
1. Navigate to the **Sync Control** tab.
2. Ensure you have scanned the bus for at least two servos.
3. Use the unified slider handles to define target positions for your robotic leg or arm.
4. Click **Sync Move**. The goal positions are sent as rapid sequential writes, one per servo with a 20 ms guard delay, so every servo acknowledges its command on the shared bus. The servos therefore don't start at the same instant: with n servos, the last one gets its command about 20 ms × (n − 1) after the first. (The driver also includes a `GroupSyncWrite` packet builder, but the app does not use it for group moves.)

### Pro Tips
- **Use the Packet Console**: Toggle the "Console ▲" button at the bottom of the window to see raw hexadecimal packet logs flowing in and out of the hardware.
- **Clearing the Graph**: The **✕ Clear** button on the Real-Time Graph drops the stored samples. You don't need it for long sessions, because the plot buffers are bounded (see Known limitations).
- **Identify via Step Test**: Not sure what your PID constants do? Go to the PID tab and click **▶ Trigger Step Test (+200 steps)**. It commands a fixed step of A = 200 encoder steps and plots the step response, with overshoot, rise time, settling time and steady-state error.

---

## API REFERENCE
Click **API ▶** in the status bar to start the FastAPI server. It binds to `127.0.0.1:8765` (loopback only) and serves REST endpoints plus a WebSocket telemetry channel. Commands are queued and run by the GUI every 100 ms, so the response means "queued", not "done". Interactive docs are at `http://localhost:8765/docs` while the server is running.

**Base URL**: `http://localhost:8765`  
**Authentication**: Optional API key, disabled by default. When a key is set, every REST request must send it in the `X-API-Key` header, or it gets `401`. There is no GUI field for it yet; set it in code with `ApiBridge.set_api_key("...")` before starting the server. The server is meant for scripts on the same computer or a trusted lab network, not for external networks.

| Method | Endpoint | Description | Request Body | Response |
| --- | --- | --- | --- | --- |
| GET | `/servos` | List connected servos with their latest telemetry | None | `{"servos": [{"id": 1, "position": 2048, ...}], "count": 1}` |
| GET | `/servos/{id}/state` | Latest telemetry for one servo (`404` if none) | None | `{"id": 1, "position": 2048, "velocity": 0, ..., "timestamp": ...}` |
| POST | `/servos/{id}/position` | Move one servo to a goal position | `{"position": 2048, "speed": 1000}` (`speed` optional) | `{"status": "queued", "servo_id": 1, "position": 2048}` |
| POST | `/servos/{id}/torque` | Enable or disable torque | `{"enable": true}` | `{"status": "queued", "servo_id": 1, "torque": true}` |
| POST | `/servos/{id}/mode` | Set operating mode | `{"mode": "position"}` (`position`, `wheel`, `pwm`, `step`) | `{"status": "queued", "servo_id": 1, "mode": "position"}` |
| GET | `/servos/groups` | List servo groups defined in the Sync tab | None | `{"groups": {...}}` |
| POST | `/servos/groups/{name}/sync_move` | Group move (sequential writes, as in the Sync tab) | `[{"id": 1, "position": 2048}, {"id": 2, "position": 1024}]` | `{"status": "queued", "group": "...", "positions": {...}}` |
| POST | `/servos/home` | Move servos to the saved home pose | None | `{"status": "queued"}` |
| POST | `/servos/emergency_stop` | Disable torque on all servos | None | `{"status": "queued"}` |
| WS | `/ws/telemetry` | Streams telemetry for all servos at 10 Hz; also accepts `set_position`, `set_torque`, `emergency_stop` and `home` commands as JSON | See below | `{"timestamp": ..., "servos": {"1": {"position": ..., ...}}}` |

WebSocket command example: `{"command": "set_position", "id": 1, "position": 2048}`. The WebSocket does not check the API key.

#### Example API Request (Move Servo)
```bash
# Example request
curl -X POST http://localhost:8765/servos/1/position \
  -H "Content-Type: application/json" \
  -d '{"position": 2048, "speed": 1000}'
```
```json
// Example response
{
  "status": "queued",
  "servo_id": 1,
  "position": 2048
}
```

#### Error Codes
| Code | Meaning | Common Cause |
| --- | --- | --- |
| 404 | Server Not Running | You forgot to hit "API ▶" in the bottom right corner of the GUI. |
| 500 | Hardware Timeout | The serial connection dropped or the targeted servo disconnected. |

---

## PROJECT STRUCTURE
```text
ServoPilot/
├── backend/            # Serial worker threads, API server handlers, and data logic
├── st3215/             # The canonical device protocol package for packet generation
├── styles/             # UI themes, including custom high-contrast dark_theme.py
├── test/               # All Pytest unit and integration testing files
├── widgets/            # Heavily compartmentalized PySide tabs (Monitor, PID, Control Table)
├── .gitignore          # Excluded tracking files
├── experiments/        # Scripts, raw data and analysis for the INDICON 2026 paper
├── main_window.py      # The massive UI glue layer coordinating tabs and backend
├── main.py             # Application entry point — Run this!
├── requirements.txt    # Project Python dependencies
├── setup.py            # Local packaging script for the st3215 module
└── README.md           # The file you are currently reading
```

---

## TESTING
The `test/` folder contains hardware test scripts for the `st3215` driver. They need a servo connected and the serial port given in the `ST3215_DEV` environment variable:
```bash
# Windows (PowerShell):  $env:ST3215_DEV="COM3"
# Linux/macOS:           export ST3215_DEV=/dev/ttyUSB0
python test/test_01_ping_servo.py
python test/test_12_read_position.py
```
---

## REPRODUCING THE INDICON 2026 PAPER
The `experiments/` folder holds everything behind the results in *ServoPilot: A Deterministic Multi-Threaded Orchestration Framework with Rule-Based PID Advisory for Serial Bus Actuators* (IEEE INDICON 2026).

| Folder | Paper result | What it contains |
| --- | --- | --- |
| `E1_baseline/` | Telemetry latency, polling-rate test | Scripts and raw CSVs |
| `E2_scalability/` | Table II (one to four servos) | Cycle-latency and back-to-back throughput scripts and CSVs |
| `E3_pid/` | Operator study (Tables III–V, Fig. 3) | Anonymized trial data (`dataset_cleaned.csv`), `verify_stats.py`, and `revision_reanalysis.py` with its output |
| `E4_ui/` | CPU and memory use | Resource-monitor script (values are the script's 60 s summaries) |
| `E5_api/` | REST round-trip time | Script and raw log |

**Test bench.** SO-ARM101 arm with six ST3215 servos on one RS-485 bus at 1 Mbps through a USB adapter; Windows laptop with an Intel i5-1335U, 16 GB RAM and Python 3.10; telemetry poll rate 20 Hz. Operator trials started from P=10, I=0, D=0 and ended when overshoot < 15%, rise time < 0.8 s, settling time ≤ 750 ms and steady-state error < 10 steps.

**Re-running the analysis** (no hardware needed):
```bash
pip install numpy pandas scipy statsmodels
cd experiments
python E3_pid/revision_reanalysis.py
```
The hardware experiments additionally need `psutil`, `requests` and `websocket-client`, a connected servo, and the serial port passed with `--port` (see the header of each script).

---

## CONTRIBUTING
We strongly welcome feedback and contributions from the community. If you build robotics and think we missed an important feature, jump in!

1. Fork the project on GitHub
2. Create a feature branch: `git checkout -b feature/advanced-profiler`
3. Make your changes in your IDE of choice
4. Test thoroughly through Pytest and actual Hardware if possible.
5. Commit using conventional commits: `git commit -m 'feat: added advanced cubic spline profiler'`
6. Push to the branch: `git push origin feature/advanced-profiler`
7. Open a Pull Request

| Prefix | When to use |
|--------|-------------|
| feat:  | New feature |
| fix:   | Bug fix |
| docs:  | Documentation only |
| style: | Formatting, no logic change |
| refactor: | Code restructure, no feature/fix |
| test:  | Adding or fixing tests |
| chore: | Build process, dependencies |

---

## ROADMAP
**Vision:** Establish ServoPilot as the absolute standard open-source desktop client for low-cost serial bus hardware hacking and development.

**Near-term (v1.x):**
- [ ] 📝 Support for ST-series Wave Profiles
- [ ] 💾 Config persistence (Save/Load JSON configs)
- [ ] 📱 Mobile companion dashboard connection UI

**Long-term (v2.0+):**
- [ ] 🛠️ Automated hardware calibration routines
- [ ] 📡 Remote telemetry streaming over external cloud websockets
- [ ] 🕹️ Physical joystick map bindings integration

**Known limitations:**
- The Real-Time Graph keeps at most 10,000 samples per metric per servo (`collections.deque` with a fixed `maxlen`, about 8 minutes at 20 Hz), so plot memory doesn't grow with session length. Memory use over multi-hour sessions has not been measured.

---

## LICENSE
ServoPilot is released under the MIT License. See [LICENSE](LICENSE) for details.

**Third-party code:** the `st3215/` servo driver is based on [python-st3215](https://github.com/Mickael-Roger/python-st3215) by Mickael Roger and remains under the Apache License 2.0; see [st3215/LICENSE](st3215/LICENSE). `setup.py` and `setup.cfg` package that driver and keep its Apache licence metadata.



