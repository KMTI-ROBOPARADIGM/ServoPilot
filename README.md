<h1 align="center">
  <br>
  ServoPilot
  <br>
</h1>
<h4 align="center">A comprehensive desktop application designed for high-performance management and control of ST3215 serial bus servos.</h4>


ServoPilot eliminates the complexity of interacting with serial bus servos by providing a visual, professional-grade interface. Whether you're configuring IDs, tuning PID loops, or orchestrating multi-servo movements via external scripts, everything is available in a clean, real-time desktop dashboard. Simply connect, scan, and pilot your robotic creations.

---

## TABLE OF CONTENTS
- [ABOUT THE PROJECT](#about-the-project)
- [KEY FEATURES](#key-features)
- [TECH STACK](#tech-stack)
- [SYSTEM REQUIREMENTS & PREREQUISITES](#system-requirements--prerequisites)
- [GETTING STARTED](#getting-started)
- [INSTALLATION — FULL STEP-BY-STEP GUIDE](#installation--full-step-by-step-guide)
- [ENVIRONMENT VARIABLES](#environment-variables)
- [RUNNING THE PROJECT](#running-the-project)
- [USAGE GUIDE](#usage-guide)
- [API REFERENCE](#api-reference)
- [PROJECT STRUCTURE](#project-structure)
- [TESTING](#testing)
- [CONTRIBUTING](#contributing)
- [ROADMAP](#roadmap)

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
git clone https://github.com/KMTI-ROBOPARADIGM/ST-Servo-Insight.git
cd <folder>
pip install -r requirements.txt
python main.py
```

---

## INSTALLATION — FULL STEP-BY-STEP GUIDE
Follow these steps for a complete, clean setup of the project environment:

1. **Fork the repository** (Optional): Click the "Fork" button at the top right of this repository on GitHub.
2. **Clone the repo**:
```bash
git clone https://github.com/KMTI-ROBOPARADIGM/ST-Servo-Insight.git
```
3. **Navigate to the project directory**:
```bash
cd <folder>
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
6. **Copy the environment file**:
```bash
cp .env.example .env
```
7. **Connect your hardware**: Plug your ST3215 serial bus interface into a USB port on your machine and ensure it has 12V power.
8. **Run the application**:
```bash
python main.py
```

---

## ENVIRONMENT VARIABLES
Below is the standard configuration using a `.env` file at the root of your project:

```env
# API Server
API_HOST=127.0.0.1                 # The host address for the REST API (defaults to 127.0.0.1)
API_PORT=8765                      # Port to run the FastAPI server on (defaults to 8765)

# Hardware Configuration (Optional Overrides)
DEFAULT_BAUDRATE=1000000           # Default serial baudrate for ST3215 servos
TELEMETRY_RATE=20                  # Global polling rate in Hz
```

| Variable | Required | Default | Description |
| --- | --- | --- | --- |
| `API_HOST` | No | `127.0.0.1` | The local IP address where the API server will listen |
| `API_PORT` | No | `8765` | The port allocated for the API server |
| `DEFAULT_BAUDRATE` | No | `1000000` | Defines the default baudrate the app attempts to use |
| `TELEMETRY_RATE` | No | `20` | Determines the speed the UI updates internal state from hardware |

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
To move multiple servos at the exact same time:
1. Navigate to the **Sync Control** tab.
2. Ensure you have scanned the bus for at least two servos.
3. Use the unified slider handles to define target positions for your robotic leg or arm.
4. Click **Write Sync Pose**; all servos will actuate simultaneously based on a single multi-device command packet.

### Pro Tips
- **Use the Packet Console**: Toggle the "Console ▲" button at the bottom of the window to see raw hexadecimal packet logs flowing in and out of the hardware.
- **Fast Plotting Filter**: During heavy network/serial polling, click the "Clear" button on the Real-Time Graph to drop historical data and stabilize CPU usage.
- **Identify via Step Test**: Not sure what your PID constants do? Go to the PID tab and hit "Step Test (+100)" to plot a rapid impulse response to measure overshoot.

---

## API REFERENCE
If the internal API server is enabled, you can command ServoPilot remotely using REST.
**Base URL**: `http://localhost:8765`  
**Authentication**: None internally (Designed for localhost inter-process communication)

| Method | Endpoint | Description | Auth Required | Request Body | Response |
| --- | --- | --- | --- | --- | --- |
| GET | `/servos` | Returns ID list for all known servos | No | None | `{"servos": [1, 2, 3]}` |
| GET | `/telemetry/{id}` | Fetches last-seen telemetry stats | No | None | `{"position": 2048, ...}` |
| POST | `/servo/{id}/position`| Move ID to a specific coordinate | No | `{"position": #, "speed": #}` | `{"status": "ok"}` |
| POST | `/emergency_stop` | Disable torque across all hardware | No | None | `{"action": "estop"}` |

#### Example API Request (Move Servo)
```bash
# Example request
curl -X POST http://localhost:8765/servo/1/position \
  -H "Content-Type: application/json" \
  -d '{"position": 2048, "speed": 1000}'
```
```json
// Example response
{
  "status": "queued",
  "command": {
    "action": "set_position",
    "id": 1,
    "position": 2048,
    "speed": 1000
  }
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
Servo-Insight/
├── backend/            # Serial worker threads, API server handlers, and data logic
├── st3215/             # The canonical device protocol package for packet generation
├── styles/             # UI themes, including custom high-contrast dark_theme.py
├── test/               # All Pytest unit and integration testing files
├── widgets/            # Heavily compartmentalized PySide tabs (Monitor, PID, Control Table)
├── .gitignore          # Excluded tracking files
├── ArchitectureDiAGRAM.png # High-level static visual map of the system
├── main_window.py      # The massive UI glue layer coordinating tabs and backend
├── main.py             # Application entry point — Run this!
├── requirements.txt    # Project Python dependencies
├── setup.py            # Local packaging script for the st3215 module
└── README.md           # The file you are currently reading
```

---

## TESTING
The application ships with a testing suite optimized for `pytest` to guarantee the integrity of the ST3215 protocol logic.
```bash
# Run the full test suite
pytest test/

# Run a specific test file
pytest test/test_st3215_packet.py

# Generate a coverage report (requires pytest-cov)
pytest --cov=st3215 test/
```
**Expected Output:** `================ test session starts ================ ... X passed in 0.5s`

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
- Graphing history will slow down the CPU if allowed to run continuously at 20Hz for more than 4 hours without manual clearing.

---



