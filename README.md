<div align="center">

# 🦾 ServoPilot

### Professional ST3215 Servo Management & Robotics Control Suite

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python&logoColor=white)](https://python.org)
[![PySide6](https://img.shields.io/badge/PySide6-Qt6-green?logo=qt&logoColor=white)](https://doc.qt.io/qtforpython/)
[![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Windows-lightgrey?logo=windows)](https://github.com/uppalasrichaitanya/ServoDriver)

---

*A Dynamixel Wizard-inspired desktop application for real-time monitoring, tuning, and control of ST3215 serial bus servos used in robotic arms and precision motion systems.*

</div>

---

## 🤖 What This App Does

ServoPilot is a **complete servo management workstation** built for robotics engineers working with **ST3215 Feetech serial bus servos**. These servos are used in robotic arms, pan-tilt systems, hexapods, and any application requiring precise angular position control.

The app lets you:
- **Connect** to any servo bus over USB serial
- **Discover** all servos on the bus with a single scan
- **Monitor** live telemetry — position, speed, load, voltage, temperature, current
- **Control** servo positions in real-time with slider and spinbox inputs
- **Tune** PID gains and observe step response on a live graph
- **Profile** complex motion sequences with multi-waypoint planning
- **Inspect** every hardware register in the servo's memory table
- **Configure** device ID, baudrate, angle limits, and operating mode
- **Export** timestamped telemetry to CSV for analysis

---

## ✨ Features

### 🖥️ Monitor Tab
Real-time servo dashboard with:
- **Live LCD panels** — Position, Velocity, Load %, Voltage, Temperature, Current
- **Moving indicator** — green pulse when servo is in motion
- **Goal Position slider** — drag or type to set target position (0–4095 steps)
- **Speed & Acceleration** controls — smooth or snappy movement profiles
- **Torque toggle** — enable/disable motor holding torque with safety guard
  - ⚠️ Attempting to send position/speed commands with torque OFF shows a warning instead of silently misfiring
- **Poll rate selector** — 10 / 20 / 30 / 50 Hz telemetry update rate

### 📈 Real-Time Graph Tab
Live multi-metric plotter powered by **pyqtgraph**:
- **Single-servo focus** — select exactly which servo to graph (no cluttered multi-servo overlap)
- **Metrics**: Position, Goal Position, Velocity, Load, Voltage, Temperature, Current
- **Smart Y-axis auto-scaling** — fits tightly to actual data range (no 0–4095 wasteland when values only change by 100 steps)
- **Rolling time window** — adjustable 5–60 second sliding window
- **Smooth rendering** — timer-throttled 80ms redraws, numpy-accelerated data slicing
- **Export CSV** — wide-format file for the selected servo only:
  - Columns: `time_s`, `position`, `goal_position`, **`error`**, `velocity`, `load`, `voltage`, `temperature`, `current`
  - `error = goal_position − position` so you can immediately see undershoot/overshoot

### 🎛️ PID Tuning Tab
Real hardware PID controller tuning for ST3215 servos:
- **Independent servo selector** — pick which servo to tune without changing the global selection
- **Auto-read on selection** — switching to a servo instantly loads its current P/I/D values from hardware; no need to press "Read from Servo" manually
- **Read from Servo** button — manually refresh P/I/D spinboxes from the servo's EEPROM
- **Write to Servo (EEPROM)** — permanently saves P/I/D gains to the servo's internal EEPROM; values survive power cycles and take effect immediately
- **Gain reference**:
  - 📈 **P (Proportional)** — higher = faster response, may oscillate
  - 〽️ **I (Integral)** — corrects steady-state error, can cause overshoot if too high
  - 📉 **D (Derivative)** — dampens oscillation, reduces P-induced overshoot
- **Restore Defaults** — resets spinboxes to factory values (P=32, I=0, D=16) without writing to the servo
- **Live Step-Response Graph**:
  - **10-second sliding window** — graph always shows the most recent data in frame; old data scrolls off the left
  - **Actual position** (bright green) vs **Goal position** (gold dashed) clearly distinguishable on the dark theme
  - **Smart Y-axis** — guaranteed minimum 20-step visible span so small position changes are clearly visible; auto-fits around real data range
  - See the direct effect of your P/I/D changes — overshoot, oscillation, and settling time all visible in the response shape


### 📋 Control Table Tab
Full hardware register viewer/editor:
- Browse and edit all 35+ ST3215 registers (EEPROM + SRAM)
- Address, name, current value, access type (R / RW), and description all shown
- Inline edit → write back to servo with EEPROM lock/unlock handling

### ⚙️ Device Config Tab
- Change **Servo ID** (0–253)
- Change **Baudrate** (38400 – 1,000,000)
- Set **angle limits** (min/max position clamps)
- Live voltage and temperature readout

### 🎬 Motion Profile Tab
Multi-waypoint motion sequencer:
- Build a list of target positions with per-waypoint speed, acceleration, and dwell time
- Execute once or loop continuously
- Useful for repetitive tasks, calibration sweeps, and demonstration runs

### 📡 Packet Console (Collapsible)
- Full hex log of every packet sent/received
- Timestamped entries, colour-coded by type (TX, RX, error, connect)
- **Raw hex sender** — craft and fire custom packets for debugging
- **Toggle visibility** with the `Console ▲/▼` button in the status bar — stays out of the way until you need it

---

## 🔌 Hardware

| Item | Details |
|---|---|
| **Servo** | Feetech ST3215 serial bus servo |
| **Interface** | USB-to-Serial adapter (CH340 / CP210x / FTDI) |
| **Protocol** | STS half-duplex serial @ 1 Mbit/s (default) |
| **Bus topology** | Daisy-chain; up to 253 servos per bus |
| **Position range** | 0 – 4095 steps (0° – 360°) |
| **Feedback** | Position, Speed, Load, Voltage, Temperature, Current |

---

## 🚀 Quick Start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Run

```bash
python main.py
```

### 3. Connect

1. Plug in your USB serial adapter with the servo bus connected
2. Select the COM port from the **Port** dropdown (click **↺** to refresh)
3. Choose the correct **Baudrate** (default: 1,000,000)
4. Click **Connect**
5. Click **🔍 Scan for Servos**
6. Select a servo from the list → start monitoring!

---

## 📦 Requirements

```
PySide6>=6.5
pyqtgraph>=0.13
pyserial>=3.5
numpy>=1.24
```

---

## 🗂️ Project Structure

```
ServoPilot/
├── main.py                    # Entry point
├── main_window.py             # Main QMainWindow — assembles all widgets
├── requirements.txt
│
├── backend/
│   ├── servo_backend.py       # QObject wrapper — all hardware calls in a QThread
│   └── telemetry_worker.py    # Telemetry polling worker
│
├── widgets/
│   ├── servo_list_panel.py    # Left dock: port/baud selector + servo table
│   ├── monitor_tab.py         # Tab 1: live telemetry dashboard + controls
│   ├── graph_tab.py           # Tab 2: real-time pyqtgraph plotter
│   ├── pid_tab.py             # Tab 3: PID tuning + step response
│   ├── control_table_tab.py   # Tab 4: register browser/editor
│   ├── firmware_tab.py        # Tab 5: device config (ID, baud, limits)
│   ├── motion_profile_tab.py  # Tab 6: waypoint motion sequencer
│   └── packet_console.py      # Bottom dock: hex packet logger
│
├── styles/
│   └── dark_theme.py          # Dark robotics-lab QSS stylesheet + trace colors
│
└── st3215/                    # ST3215 hardware library
    ├── st3215.py
    ├── port_handler.py
    ├── protocol_packet_handler.py
    ├── group_sync_write.py
    ├── group_sync_read.py
    └── values.py
```

---

## 🛡️ Safety Features

- **Torque guard** — position and speed commands are blocked if torque is OFF, preventing accidental servo movement
- **Port access check** — friendly error with instructions if COM port is locked by another app
- **Thread-safe hardware access** — all serial I/O runs in a dedicated QThread with mutex locking; UI never freezes
- **EEPROM lock/unlock** — register writes automatically unlock and re-lock EEPROM to protect persistent settings

---

## 📊 CSV Export Format

When you export from the **Real-Time Graph** tab, you get a clean wide-format CSV for the **selected servo only**:

```csv
# ServoPilot Telemetry Export — Servo ID 1
# error = goal_position - position  (positive = undershoot, negative = overshoot)
time_s,servo_id,position,goal_position,error,velocity,load_pct,voltage_V,temperature_C,current_mA
0.082,1,2048,2048,0.0,0,0.0,7.4,32,0.0
0.162,1,2051,2200,149.0,12,8.1,7.4,32,42.3
```

The **`error`** column makes it trivial to plot tracking quality, measure settling time, and detect oscillation in any spreadsheet or Python script.

---

## 🧑‍💻 Development Notes

- Built with **PySide6** (Qt6 for Python) for a native, high-performance UI
- Real-time plotting via **pyqtgraph** with numpy-accelerated data pipelines  
- Hardware communication uses a **Producer/Consumer** pattern — UI thread only reads results via Qt signals, never blocks on serial I/O
- Dark theme inspired by professional robotics tools (Dynamixel Wizard, ROS RViz)

---

<div align="center">

Made with ❤️ for robotics  
**[github.com/uppalasrichaitanya/ServoDriver](https://github.com/uppalasrichaitanya/ServoDriver)**

</div>
