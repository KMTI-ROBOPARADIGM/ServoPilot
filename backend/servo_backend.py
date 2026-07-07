"""Servo Backend — QObject bridge wrapping the ST3215 hardware library.

FILE: backend/servo_backend.py
PURPOSE: Provides a thread-safe abstraction over the ST3215 servo library.
         All blocking serial I/O runs in a dedicated QThread (_HardwareWorker)
         so the UI never freezes. Communication with the UI is purely via Qt signals.
CALLED BY: main_window.py → ServoBackend(self)
CALLS INTO: st3215.ST3215 (hardware library), QThread, QMutex, QTimer
CONTAINS: _HardwareWorker (inner QObject), ServoBackend (public API)
"""

import sys              # [STDLIB] Path manipulation
import os               # [STDLIB] Path manipulation
import time             # [STDLIB] sleep() for motion profiles
import threading        # [STDLIB] Event() for motion stop flag
from typing import Optional, List, Dict, Any  # [STDLIB] Type hints

from PySide6.QtCore import QObject, Signal, Slot, QThread, QMutex, QMutexLocker  # [PySide6] Threading + signals

# Make sure the st3215 package on the repository root is importable
_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

try:
    from st3215.st3215 import ST3215
    from st3215.values import (
        DEFAULT_BAUDRATE, MIN_POSITION, MAX_POSITION, MAX_SPEED,
        STS_ID, STS_BAUD_RATE, STS_MODE, STS_ACC, STS_TORQUE_ENABLE,
        STS_GOAL_POSITION_L, STS_GOAL_SPEED_L, STS_GOAL_TIME_L,
        STS_PRESENT_POSITION_L, STS_PRESENT_SPEED_L, STS_PRESENT_LOAD_L,
        STS_PRESENT_VOLTAGE, STS_PRESENT_TEMPERATURE, STS_PRESENT_CURRENT_L,
        STS_STATUS, STS_MOVING, STS_LOCK, STS_OFS_L,
        STS_MIN_ANGLE_LIMIT_L, STS_MAX_ANGLE_LIMIT_L,
        STS_CW_DEAD, STS_CCW_DEAD, STS_MODEL_L,
        COMM_SUCCESS,
    )
    _ST3215_AVAILABLE = True
except ImportError as _e:
    _ST3215_AVAILABLE = False
    _ST3215_IMPORT_ERROR = str(_e)


# ── Register map for the Control Table tab ───────────────────────────────────
REGISTER_MAP = [
    # (addr, name, size_bytes, access, description)
    (3,  "Model Number L",       1, "R",  "Low byte of model number"),
    (4,  "Model Number H",       1, "R",  "High byte of model number"),
    (5,  "ID",                   1, "RW", "Servo ID (0–253)"),
    (6,  "Baud Rate",            1, "RW", "Bus baud rate code (0=1M…7=38400)"),
    (9,  "Min Angle Limit L",    1, "RW", "Min angle low byte"),
    (10, "Min Angle Limit H",    1, "RW", "Min angle high byte"),
    (11, "Max Angle Limit L",    1, "RW", "Max angle low byte"),
    (12, "Max Angle Limit H",    1, "RW", "Max angle high byte"),
    (26, "CW Dead Band",         1, "RW", "Clockwise dead-band"),
    (27, "CCW Dead Band",        1, "RW", "Counter-clockwise dead-band"),
    (31, "Position Offset L",    1, "RW", "Position correction low byte"),
    (32, "Position Offset H",    1, "RW", "Position correction high byte"),
    (33, "Mode",                 1, "RW", "0=Position 1=Wheel 2=PWM 3=Step"),
    (40, "Torque Enable",        1, "RW", "1=ON 0=OFF"),
    (41, "Acceleration",         1, "RW", "Acceleration (×100 step/s²)"),
    (42, "Goal Position L",      1, "RW", "Target position low byte"),
    (43, "Goal Position H",      1, "RW", "Target position high byte"),
    (44, "Goal Time L",          1, "RW", "Move time low byte"),
    (45, "Goal Time H",          1, "RW", "Move time high byte"),
    (46, "Goal Speed L",         1, "RW", "Target speed low byte"),
    (47, "Goal Speed H",         1, "RW", "Target speed high byte"),
    (55, "EEPROM Lock",          1, "RW", "1=EEPROM locked 0=unlocked"),
    (56, "Present Position L",   1, "R",  "Current position low byte"),
    (57, "Present Position H",   1, "R",  "Current position high byte"),
    (58, "Present Speed L",      1, "R",  "Current speed low byte"),
    (59, "Present Speed H",      1, "R",  "Current speed high byte"),
    (60, "Present Load L",       1, "R",  "Current load low byte"),
    (61, "Present Load H",       1, "R",  "Current load high byte"),
    (62, "Present Voltage",      1, "R",  "Current voltage (×0.1 V)"),
    (63, "Present Temperature",  1, "R",  "Current temperature (°C)"),
    (65, "Status",               1, "R",  "Status flags byte"),
    (66, "Moving",               1, "R",  "1=moving 0=stopped"),
    (69, "Present Current L",    1, "R",  "Current draw low byte"),
    (70, "Present Current H",    1, "R",  "Current draw high byte"),
]

BAUD_CODES = {
    0: 1_000_000,
    1: 500_000,
    2: 250_000,
    3: 128_000,
    4: 115_200,
    5: 76_800,
    6: 57_600,
    7: 38_400,
}

BAUD_CODE_LABELS = {v: f"{v//1000}k ({k})" for k, v in BAUD_CODES.items()}
BAUD_CODE_FROM_RATE = {v: k for k, v in BAUD_CODES.items()}


class _HardwareWorker(QObject):
    """Runs in a QThread. Serialises all hardware calls and emits results."""

    # ── outgoing signals ────────────────────────────────────────────
    connected         = Signal()
    connection_failed = Signal(str)
    disconnected      = Signal()
    servos_found      = Signal(list)         # list[int]
    telemetry_update  = Signal(int, dict)    # (id, data_dict)
    registers_read    = Signal(int, list)    # (id, list[dict])
    register_written  = Signal(int, int, int)  # (id, addr, value)
    log_message       = Signal(str)          # text → packet console
    error_occurred    = Signal(str)
    id_changed        = Signal(int, int)     # old, new
    baud_changed      = Signal(int, int)     # id, code
    motion_finished   = Signal(int)          # servo id
    pid_values        = Signal(int, int, int, int)  # servo_id, P, I, D
    estop_done        = Signal(int)          # number of servos stopped
    sync_write_done   = Signal(dict)         # {servo_id: position} that was sent

    def __init__(self):
        """TYPE: User-defined | CALLED BY: ServoBackend.__init__
        PURPOSE: Initialise worker state: no servo, a mutex for thread-safety,
                 and a threading.Event to stop motion profiles.
        """
        super().__init__()
        self._servo: Optional["ST3215"] = None
        self._mutex = QMutex()                  # Thread-safe lock for all serial I/O
        self._motion_stop = threading.Event()    # Stop flag for motion profile thread

    def _ensure_port_ready(self):
        """Reset the is_using flag so the next txPacket() won't return
        COMM_PORT_BUSY.  A failed rxPacket() (e.g. SerialException during
        readPort) can leave this flag stuck True, permanently killing ALL
        subsequent serial communication."""
        if self._servo:
            self._servo.portHandler.is_using = False

    # ── connection ──────────────────────────────────────────────────
    @Slot(str, int)
    def connect_device(self, port: str, baudrate: int):
        """Open serial port and create ST3215 instance.
        TYPE: User-defined Qt Slot | CALLED BY: ServoBackend.connect_device → QMetaObject.invokeMethod
        CALLS: PortHandler() [st3215], ST3215, GroupSyncWrite [st3215]
        EMITS: connected() or connection_failed(str)
        """
        if not _ST3215_AVAILABLE:
            self.connection_failed.emit(f"ST3215 library not importable: {_ST3215_IMPORT_ERROR}")
            return
        with QMutexLocker(self._mutex):
            # Always close any previously open connection first
            if self._servo is not None:
                try:
                    self._servo.portHandler.closePort()
                except Exception:
                    pass
                self._servo = None

            try:
                # PortHandler has no setBaudRate() method — the baudrate must be
                # set on portHandler.baudrate BEFORE openPort() is called.
                # We manually build the connection to support non-default baud rates.
                from st3215.port_handler import PortHandler
                from st3215.protocol_packet_handler import protocol_packet_handler
                from st3215.group_sync_write import GroupSyncWrite
                from st3215.values import STS_ACC
                import threading

                ph = PortHandler(port)
                ph.baudrate = baudrate          # set BEFORE openPort()
                if not ph.openPort():
                    raise OSError(f"Could not open port: {port}")

                servo = ST3215.__new__(ST3215)  # skip ST3215.__init__
                servo.portHandler = ph
                protocol_packet_handler.__init__(servo, ph)
                servo.groupSyncWrite = GroupSyncWrite(servo, STS_ACC, 7)
                servo.lock = threading.Lock()
                self._servo = servo

                self.connected.emit()
                self.log_message.emit(f"[CONNECT] {port} @ {baudrate} bps")
            except PermissionError:
                self._servo = None
                self.connection_failed.emit(
                    f"Access denied on {port}.\n\n"
                    "Another application is holding the port open.\n"
                    "Close Arduino IDE, PuTTY, or any other serial terminal, "
                    "then try again."
                )
            except Exception as exc:
                self._servo = None
                self.connection_failed.emit(str(exc))

    @Slot()
    def disconnect_device(self):
        """Close the serial port and reset state.
        TYPE: User-defined Qt Slot | CALLED BY: ServoBackend.disconnect_device
        CALLS: portHandler.closePort() [st3215]
        EMITS: disconnected()
        """
        with QMutexLocker(self._mutex):
            if self._servo:
                try:
                    self._servo.portHandler.closePort()
                except Exception:
                    pass
                self._servo = None
            self.disconnected.emit()
            self.log_message.emit("[DISCONNECT]")

    # ── scan ────────────────────────────────────────────────────────
    @Slot()
    def scan_servos(self):
        """Scan entire bus (IDs 0–253) and emit list of found servo IDs.
        TYPE: User-defined Qt Slot | CALLED BY: ServoBackend.scan_servos
        CALLS: ST3215.PingServo() [st3215] for each ID
        EMITS: servos_found(list[int])
        """
        with QMutexLocker(self._mutex):
            if not self._servo:
                self.error_occurred.emit("Not connected")
                return
            self._ensure_port_ready()
            # Flush stale bytes from a prior unclean exit
            try:
                self._servo.portHandler.ser.reset_input_buffer()
            except Exception:
                pass
            self.log_message.emit("[SCAN] Scanning IDs 0–253 …")
            try:
                ids = self._servo.ListServos()
            except Exception as exc:
                self._ensure_port_ready()
                self.error_occurred.emit(f"Scan failed: {exc}")
                self.log_message.emit(f"[SCAN] FAILED: {exc}")
                return
            self.servos_found.emit(ids)
            self.log_message.emit(f"[SCAN] Found: {ids}")

    # ── telemetry read ──────────────────────────────────────────────
    @Slot(int)
    def read_telemetry(self, servo_id: int):
        """Read telemetry for one servo and emit the result.
        TYPE: User-defined Qt Slot | CALLED BY: ServoBackend.read_telemetry
        CALLS: _read_telemetry_locked() [self]
        EMITS: telemetry_update(int, dict)
        """
        with QMutexLocker(self._mutex):
            if not self._servo:
                return
            data = self._read_telemetry_locked(servo_id)
            if data:
                self.telemetry_update.emit(servo_id, data)

    def _read_telemetry_locked(self, servo_id: int) -> Optional[Dict]:
        """Read position/speed/load/voltage/temp/current/moving from one servo.
        TYPE: User-defined (private) | CALLED BY: read_telemetry(), TelemetryWorker
        CALLS: ST3215.ReadPosition/ReadSpeed/ReadLoad/ReadVoltage/
               ReadTemperature/ReadCurrent/IsMoving [st3215 library]
        """
        s = self._servo
        self._ensure_port_ready()
        try:
            pos  = s.ReadPosition(servo_id)
            spd_tpl = s.ReadSpeed(servo_id)
            spd = spd_tpl[0] if isinstance(spd_tpl, tuple) else spd_tpl
            load = s.ReadLoad(servo_id)
            volt = s.ReadVoltage(servo_id)
            temp = s.ReadTemperature(servo_id)
            cur  = s.ReadCurrent(servo_id)
            mov  = s.IsMoving(servo_id)
            return {
                "position":    pos    if pos    is not None else 0,
                "velocity":    spd    if spd    is not None else 0,
                "load":        load   if load   is not None else 0.0,
                "voltage":     volt   if volt   is not None else 0.0,
                "temperature": temp   if temp   is not None else 0,
                "current":     cur    if cur    is not None else 0.0,
                "moving":      bool(mov),
            }
        except Exception:
            self._ensure_port_ready()
            return None

    # ── control ─────────────────────────────────────────────────────
    @Slot(int, int)
    def write_goal_position(self, servo_id: int, position: int):
        """Write target position to servo (clamped 0–4095).
        TYPE: User-defined Qt Slot | CALLED BY: ServoBackend.write_goal_position
              (ultimately from MonitorTab slider, SyncTab, API commands)
        CALLS: ST3215.WritePosition() [st3215 library]
        """
        with QMutexLocker(self._mutex):
            if not self._servo:
                return
            self._ensure_port_ready()
            res = self._servo.WritePosition(servo_id, max(0, min(4095, position)))
            self.log_message.emit(f"[WRITE] ID={servo_id} GoalPos={position} → {'OK' if res else 'ERR'}")

    @Slot(int, int)
    def write_goal_speed(self, servo_id: int, speed: int):
        with QMutexLocker(self._mutex):
            if not self._servo:
                return
            self._ensure_port_ready()
            res = self._servo.SetSpeed(servo_id, speed)
            self.log_message.emit(f"[WRITE] ID={servo_id} Speed={speed} → {'OK' if res else 'ERR'}")

    @Slot(int, int)
    def write_acceleration(self, servo_id: int, acc: int):
        with QMutexLocker(self._mutex):
            if not self._servo:
                return
            self._ensure_port_ready()
            res = self._servo.SetAcceleration(servo_id, acc)
            self.log_message.emit(f"[WRITE] ID={servo_id} Acc={acc} → {'OK' if res else 'ERR'}")

    @Slot(int, bool)
    def set_torque(self, servo_id: int, on: bool):
        with QMutexLocker(self._mutex):
            if not self._servo:
                return
            self._ensure_port_ready()
            if on:
                self._servo.StartServo(servo_id)
            else:
                self._servo.StopServo(servo_id)
            self.log_message.emit(f"[WRITE] ID={servo_id} Torque={'ON' if on else 'OFF'}")

    @Slot(int, int)
    def set_mode(self, servo_id: int, mode: int):
        with QMutexLocker(self._mutex):
            if not self._servo:
                return
            self._servo.SetMode(servo_id, mode)
            self.log_message.emit(f"[WRITE] ID={servo_id} Mode={mode}")

    # ── PID ─────────────────────────────────────────────────────────
    @Slot(int, int, int, int)
    def write_pid(self, servo_id: int, p: int, i: int, d: int):
        """Write PID gains to EEPROM (unlock → write P/I/D → re-lock).
        TYPE: User-defined Qt Slot | CALLED BY: ServoBackend.write_pid
              (from PIDTab → main_window._wire_widgets)
        CALLS: ST3215.UnLockEprom/write1ByteTxOnly/LockEprom [st3215]
        EMITS: log_message(str) on success or error_occurred(str) on failure
        """
        with QMutexLocker(self._mutex):
            if not self._servo:
                return
            s = self._servo
            s.UnLockEprom(servo_id)
            time.sleep(0.01)  # small settle after unlock
            s.write1ByteTxOnly(servo_id, 21, p)
            time.sleep(0.005)
            s.write1ByteTxOnly(servo_id, 22, i)
            time.sleep(0.005)
            s.write1ByteTxOnly(servo_id, 23, d)
            time.sleep(0.01)  # settle before re-lock
            s.LockEprom(servo_id)
            self.log_message.emit(f"[PID WRITE] ID={servo_id} P={p} I={i} D={d} → EEPROM OK")

    @Slot(int)
    def read_pid(self, servo_id: int):
        """Read P/I/D values from EEPROM registers 21/22/23.
        TYPE: User-defined Qt Slot | CALLED BY: ServoBackend.read_pid
        CALLS: ST3215.read1ByteTxRx [st3215] for addrs 21, 22, 23
        EMITS: pid_values(servo_id, P, I, D)
        """
        with QMutexLocker(self._mutex):
            if not self._servo:
                return
            self._ensure_port_ready()
            s = self._servo
            try:
                p, comm_p, _ = s.read1ByteTxRx(servo_id, 21)
                i, comm_i, _ = s.read1ByteTxRx(servo_id, 22)
                d, comm_d, _ = s.read1ByteTxRx(servo_id, 23)
                if comm_p == 0 and comm_i == 0 and comm_d == 0:
                    self.log_message.emit(f"[PID READ] ID={servo_id} P={p} I={i} D={d}")
                    self.pid_values.emit(servo_id, p, i, d)
                else:
                    self.log_message.emit(f"[PID READ] ID={servo_id} comm error — check connection")
            except Exception as exc:
                self._ensure_port_ready()
                self.log_message.emit(f"[PID READ] ID={servo_id} exception: {exc}")

    # ── register table ──────────────────────────────────────────────
    @Slot(int)
    def read_all_registers(self, servo_id: int):
        """Read every register in REGISTER_MAP for one servo.
        TYPE: User-defined Qt Slot | CALLED BY: ServoBackend.read_all_registers
        CALLS: ST3215.read1ByteTxRx/read2ByteTxRx [st3215] per register
        EMITS: registers_read(servo_id, list[dict])
        """
        with QMutexLocker(self._mutex):
            if not self._servo:
                return
            result = []
            s = self._servo
            for addr, name, size, access, desc in REGISTER_MAP:
                try:
                    if size == 1:
                        val, comm, err = s.read1ByteTxRx(servo_id, addr)
                    else:
                        val, comm, err = s.read2ByteTxRx(servo_id, addr)
                    if comm != 0 or err != 0:
                        val = None
                except Exception:
                    val = None
                result.append({
                    "addr": addr, "name": name, "value": val,
                    "access": access, "desc": desc, "size": size,
                })
            self.registers_read.emit(servo_id, result)
            self.log_message.emit(f"[REG READ] ID={servo_id} {len(result)} registers")

    @Slot(int, int, int)
    def write_register(self, servo_id: int, addr: int, value: int):
        """Write a single register value (unlock EEPROM → write → re-lock).
        TYPE: User-defined Qt Slot | CALLED BY: ServoBackend.write_register
        CALLS: ST3215.UnLockEprom/writeTxRx/LockEprom [st3215]
        EMITS: register_written(servo_id, addr, value)
        """
        with QMutexLocker(self._mutex):
            if not self._servo:
                return
            s = self._servo
            # Find size for this address
            size = next((r[2] for r in REGISTER_MAP if r[0] == addr), 1)
            s.UnLockEprom(servo_id)
            if size == 1:
                comm, err = s.writeTxRx(servo_id, addr, 1, [value & 0xFF])
            else:
                lo = value & 0xFF
                hi = (value >> 8) & 0xFF
                comm, err = s.writeTxRx(servo_id, addr, 2, [lo, hi])
            s.LockEprom(servo_id)
            ok = comm == 0 and err == 0
            self.log_message.emit(f"[REG WRITE] ID={servo_id} addr=0x{addr:02X} val={value} → {'OK' if ok else 'ERR'}")
            if ok:
                self.register_written.emit(servo_id, addr, value)

    # ── device config ────────────────────────────────────────────────
    @Slot(int, int)
    def change_id(self, old_id: int, new_id: int):
        """Change a servo's ID on the bus.
        TYPE: User-defined Qt Slot | CALLED BY: ServoBackend.change_id
        CALLS: ST3215.ChangeId() [st3215]  EMITS: id_changed(old, new)
        """
        with QMutexLocker(self._mutex):
            if not self._servo:
                return
            err = self._servo.ChangeId(old_id, new_id)
            if err:
                self.error_occurred.emit(f"Change ID failed: {err}")
                self.log_message.emit(f"[ID] Change {old_id}→{new_id} FAILED: {err}")
            else:
                self.id_changed.emit(old_id, new_id)
                self.log_message.emit(f"[ID] Changed {old_id} → {new_id}")

    @Slot(int, int)
    def change_baudrate(self, servo_id: int, baud_code: int):
        """Change a servo's baud rate code (0–7).
        TYPE: User-defined Qt Slot | CALLED BY: ServoBackend.change_baudrate
        CALLS: ST3215.ChangeBaudrate() [st3215]  EMITS: baud_changed(id, code)
        """
        with QMutexLocker(self._mutex):
            if not self._servo:
                return
            err = self._servo.ChangeBaudrate(servo_id, baud_code)
            if err:
                self.error_occurred.emit(f"Baud change failed: {err}")
            else:
                self.baud_changed.emit(servo_id, baud_code)
                self.log_message.emit(f"[BAUD] ID={servo_id} code={baud_code} ({BAUD_CODES.get(baud_code,'?')} bps)")

    @Slot(int, int)
    def set_angle_limits(self, servo_id: int, min_pos: int, max_pos: int):
        """Set min/max angle limits in EEPROM.
        TYPE: User-defined Qt Slot | CALLED BY: ServoBackend.set_angle_limits
        CALLS: ST3215.writeTxRx [st3215] at STS_MIN/MAX_ANGLE_LIMIT_L
        """
        with QMutexLocker(self._mutex):
            if not self._servo:
                return
            s = self._servo
            s.UnLockEprom(servo_id)
            s.writeTxRx(servo_id, STS_MIN_ANGLE_LIMIT_L, 2,
                         [min_pos & 0xFF, (min_pos >> 8) & 0xFF])
            s.writeTxRx(servo_id, STS_MAX_ANGLE_LIMIT_L, 2,
                         [max_pos & 0xFF, (max_pos >> 8) & 0xFF])
            s.LockEprom(servo_id)
            self.log_message.emit(f"[LIMITS] ID={servo_id} min={min_pos} max={max_pos}")

    # ── motion profile ───────────────────────────────────────────────
    @Slot(int, list, bool)
    def execute_motion_profile(self, servo_id: int, waypoints: list, loop: bool):
        """Run single-servo waypoints in a background thread.
        TYPE: User-defined Qt Slot | CALLED BY: ServoBackend.execute_motion_profile
        CALLS: ST3215.MoveTo() [st3215] per waypoint, time.sleep() for delays
        EMITS: motion_finished(servo_id) on completion
        """
        self._motion_stop.clear()  # reset stop flag

        def _run():
            with QMutexLocker(self._mutex):
                if not self._servo:
                    return
            while not self._motion_stop.is_set():
                for wp in waypoints:
                    if self._motion_stop.is_set():
                        self.log_message.emit(f"[MOTION] Stopped by user")
                        self.motion_finished.emit(servo_id)
                        return
                    pos   = wp.get("position", 2048)
                    speed = wp.get("speed", 1000)
                    acc   = wp.get("accel", 50)
                    delay = wp.get("delay", 0.5)
                    with QMutexLocker(self._mutex):
                        if self._servo:
                            self._ensure_port_ready()
                            self._servo.MoveTo(servo_id, pos, speed=speed, acc=acc)
                            self.log_message.emit(
                                f"[MOTION] #{servo_id} → {pos} spd={speed} acc={acc}"
                            )
                    # Sleep in small chunks so stop flag is checked promptly
                    for _ in range(int(delay * 10)):
                        if self._motion_stop.is_set():
                            self.log_message.emit(f"[MOTION] Stopped by user")
                            self.motion_finished.emit(servo_id)
                            return
                        time.sleep(0.1)
                if not loop:
                    break
            self.motion_finished.emit(servo_id)

        t = threading.Thread(target=_run, daemon=True)
        t.start()

    @Slot()
    def stop_motion(self):
        """Set the stop flag so execute_motion_profile breaks out."""
        self._motion_stop.set()
        self.log_message.emit("[MOTION] Stop requested")

    @Slot(list, list, bool)
    def execute_motion_profile_group(self, servo_ids: list, waypoints: list, loop: bool):
        """Run multi-servo waypoints in a background thread."""
        self._motion_stop.clear()

        def _run():
            with QMutexLocker(self._mutex):
                if not self._servo:
                    return
            while not self._motion_stop.is_set():
                for wp in waypoints:
                    if self._motion_stop.is_set():
                        self.log_message.emit("[MOTION] Stopped by user")
                        self.motion_finished.emit(0)
                        return
                    positions = wp.get("positions", {})
                    speed = wp.get("speed", 1000)
                    acc = wp.get("accel", 50)
                    delay = wp.get("delay", 0.5)
                    with QMutexLocker(self._mutex):
                        if self._servo:
                            self._ensure_port_ready()
                            for sid in servo_ids:
                                pos = positions.get(sid, 2048)
                                self._servo.MoveTo(sid, pos, speed=speed, acc=acc)
                            sids_str = " ".join(f"#{s}→{positions.get(s, 2048)}" for s in servo_ids)
                            self.log_message.emit(
                                f"[MOTION] Group: {sids_str} spd={speed} acc={acc}"
                            )
                    for _ in range(int(delay * 10)):
                        if self._motion_stop.is_set():
                            self.log_message.emit("[MOTION] Stopped by user")
                            self.motion_finished.emit(0)
                            return
                        time.sleep(0.1)
                if not loop:
                    break
            self.motion_finished.emit(0)

        t = threading.Thread(target=_run, daemon=True)
        t.start()

    # ── sync write (multi-servo, rapid sequential) ─────────────────────
    @Slot(dict)
    def sync_write_positions(self, id_pos_map: dict):
        """Write goal positions to multiple servos sequentially.

        Uses WritePosition() (single serial transaction per servo) rather than
        MoveTo() which needs 5+ round-trips.  Assumes the user has already
        enabled torque and set mode from the Monitor tab.

        Resets portHandler.is_using before each write to clear stuck flags from
        prior failed reads, and adds a small inter-servo delay to let the bus
        settle.
        """
        with QMutexLocker(self._mutex):
            if not self._servo or not id_pos_map:
                return
            s = self._servo
            sent = {}
            for sid, pos in id_pos_map.items():
                sid = int(sid)
                pos = max(0, min(4095, int(pos)))
                try:
                    # Reset the is_using flag in case a prior telemetry read
                    # left it stuck (the ST3215 protocol layer returns
                    # COMM_PORT_BUSY if this is True).
                    s.portHandler.is_using = False
                    res = s.WritePosition(sid, pos)
                    sent[sid] = pos
                    self.log_message.emit(
                        f"[SYNC] #{sid} → {pos}  {'OK' if res else 'WARN: no ack'}"
                    )
                except Exception as exc:
                    self.log_message.emit(f"[SYNC] ERR #{sid}: {exc}")
                # Small delay so the bus settles between packets
                time.sleep(0.02)
            if sent:
                ids_str = ", ".join(f"#{k}→{v}" for k, v in sent.items())
                self.log_message.emit(f"[SYNC] Moved: {ids_str}")
                self.sync_write_done.emit(sent)


    # ── emergency stop ───────────────────────────────────────────────
    @Slot(list)
    def emergency_stop(self, servo_ids: list):
        """Immediately disable torque on every servo in servo_ids.
        Runs in the hardware thread so it cannot be interrupted by telemetry."""
        with QMutexLocker(self._mutex):
            if not self._servo:
                return
            stopped = 0
            for sid in servo_ids:
                try:
                    self._servo.StopServo(sid)
                    self.log_message.emit(f"[E-STOP] ID={sid} torque OFF")
                    stopped += 1
                except Exception as exc:
                    self.log_message.emit(f"[E-STOP] ID={sid} ERR: {exc}")
            self.log_message.emit(f"[E-STOP] {stopped}/{len(servo_ids)} servos stopped")
            self.estop_done.emit(stopped)

    # ── raw packet ──────────────────────────────────────────────────
    @Slot(int, bytes)
    def send_raw_packet(self, servo_id: int, data: bytes):
        self.log_message.emit(f"[TX] ID={servo_id} {data.hex().upper()}")

    # ── helper ──────────────────────────────────────────────────────
    def is_connected(self) -> bool:
        return self._servo is not None

    @property
    def servo(self) -> Optional["ST3215"]:
        return self._servo


class ServoBackend(QObject):
    """Public facade for hardware access. Thread-safe proxy to _HardwareWorker.
    TYPE: User-defined QObject | FILE: backend/servo_backend.py
    CALLED BY: main_window.py → ServoBackend(self)
    PURPOSE: Creates a QThread + _HardwareWorker, re-exports worker signals,
             and provides proxy methods that use QMetaObject.invokeMethod to
             dispatch calls to the worker thread (auto-queued connection).
    """

    # re-export worker signals
    connected         = Signal()
    connection_failed = Signal(str)
    disconnected      = Signal()
    servos_found      = Signal(list)
    telemetry_update  = Signal(int, dict)
    registers_read    = Signal(int, list)
    register_written  = Signal(int, int, int)
    log_message       = Signal(str)
    error_occurred    = Signal(str)
    pid_values        = Signal(int, int, int, int)  # servo_id, P, I, D
    id_changed        = Signal(int, int)
    baud_changed      = Signal(int, int)
    motion_finished   = Signal(int)
    estop_done        = Signal(int)
    sync_write_done   = Signal(dict)         # {servo_id: position} that was sent

    # Internal signal to dispatch dict to worker thread (QMetaObject.invokeMethod
    # with QVariantMap is broken in PySide6 — the call silently does nothing).
    _do_sync_write = Signal(dict)

    def __init__(self, parent=None):
        """Create worker thread and wire all signals through this facade.
        TYPE: User-defined | CALLED BY: main_window.py __init__
        CALLS: QThread() [PySide6], _HardwareWorker(), moveToThread() [PySide6]
        """
        super().__init__(parent)
        self._thread = QThread(self)
        self._worker = _HardwareWorker()
        self._worker.moveToThread(self._thread)
        self._thread.start()

        # wire all worker signals up through this facade
        for sig_name in [
            "connected", "connection_failed", "disconnected",
            "servos_found", "telemetry_update", "registers_read",
            "register_written", "log_message", "error_occurred",
            "id_changed", "baud_changed", "motion_finished", "pid_values",
            "estop_done", "sync_write_done",
        ]:
            getattr(self._worker, sig_name).connect(getattr(self, sig_name))

        # Connect internal signal → worker slot (cross-thread, auto-queued)
        self._do_sync_write.connect(self._worker.sync_write_positions)

    # ── public proxy methods ─────────────────────────────────────────
    # Each method below dispatches its call to _HardwareWorker via
    # QMetaObject.invokeMethod with Qt.QueuedConnection, so the actual
    # serial I/O runs on the worker QThread, not the GUI thread.
    # TYPE: User-defined proxy | CALLED BY: main_window (via _wire_widgets)
    # CALLS: QMetaObject.invokeMethod → _HardwareWorker.<same_name>

    def connect_device(self, port: str, baudrate: int):
        """Proxy → _HardwareWorker.connect_device (open serial port)."""
        QThread.currentThread()  # ensure running
        from PySide6.QtCore import QMetaObject, Qt
        QMetaObject.invokeMethod(self._worker, "connect_device",
                                 Qt.QueuedConnection,
                                 *self._args(port, baudrate))

    def disconnect_device(self):
        from PySide6.QtCore import QMetaObject, Qt
        QMetaObject.invokeMethod(self._worker, "disconnect_device", Qt.QueuedConnection)

    def scan_servos(self):
        from PySide6.QtCore import QMetaObject, Qt
        QMetaObject.invokeMethod(self._worker, "scan_servos", Qt.QueuedConnection)

    def read_telemetry(self, servo_id: int):
        from PySide6.QtCore import QMetaObject, Qt
        QMetaObject.invokeMethod(self._worker, "read_telemetry",
                                 Qt.QueuedConnection, *self._args(servo_id))

    def write_goal_position(self, servo_id: int, position: int):
        from PySide6.QtCore import QMetaObject, Qt
        QMetaObject.invokeMethod(self._worker, "write_goal_position",
                                 Qt.QueuedConnection, *self._args(servo_id, position))

    def write_goal_speed(self, servo_id: int, speed: int):
        from PySide6.QtCore import QMetaObject, Qt
        QMetaObject.invokeMethod(self._worker, "write_goal_speed",
                                 Qt.QueuedConnection, *self._args(servo_id, speed))

    def write_acceleration(self, servo_id: int, acc: int):
        from PySide6.QtCore import QMetaObject, Qt
        QMetaObject.invokeMethod(self._worker, "write_acceleration",
                                 Qt.QueuedConnection, *self._args(servo_id, acc))

    def set_torque(self, servo_id: int, on: bool):
        from PySide6.QtCore import QMetaObject, Qt
        QMetaObject.invokeMethod(self._worker, "set_torque",
                                 Qt.QueuedConnection, *self._args(servo_id, on))

    def set_mode(self, servo_id: int, mode: int):
        from PySide6.QtCore import QMetaObject, Qt
        QMetaObject.invokeMethod(self._worker, "set_mode",
                                 Qt.QueuedConnection, *self._args(servo_id, mode))

    def write_pid(self, servo_id: int, p: int, i: int, d: int):
        from PySide6.QtCore import QMetaObject, Qt
        QMetaObject.invokeMethod(self._worker, "write_pid",
                                 Qt.QueuedConnection, *self._args(servo_id, p, i, d))

    def read_pid(self, servo_id: int):
        from PySide6.QtCore import QMetaObject, Qt
        QMetaObject.invokeMethod(self._worker, "read_pid",
                                 Qt.QueuedConnection, *self._args(servo_id))

    def read_all_registers(self, servo_id: int):
        from PySide6.QtCore import QMetaObject, Qt
        QMetaObject.invokeMethod(self._worker, "read_all_registers",
                                 Qt.QueuedConnection, *self._args(servo_id))

    def write_register(self, servo_id: int, addr: int, value: int):
        from PySide6.QtCore import QMetaObject, Qt
        QMetaObject.invokeMethod(self._worker, "write_register",
                                 Qt.QueuedConnection, *self._args(servo_id, addr, value))

    def change_id(self, old_id: int, new_id: int):
        from PySide6.QtCore import QMetaObject, Qt
        QMetaObject.invokeMethod(self._worker, "change_id",
                                 Qt.QueuedConnection, *self._args(old_id, new_id))

    def change_baudrate(self, servo_id: int, baud_code: int):
        from PySide6.QtCore import QMetaObject, Qt
        QMetaObject.invokeMethod(self._worker, "change_baudrate",
                                 Qt.QueuedConnection, *self._args(servo_id, baud_code))

    def set_angle_limits(self, servo_id: int, min_pos: int, max_pos: int):
        from PySide6.QtCore import QMetaObject, Qt
        QMetaObject.invokeMethod(self._worker, "set_angle_limits",
                                 Qt.QueuedConnection, *self._args(servo_id, min_pos, max_pos))

    def execute_motion_profile(self, servo_id: int, waypoints: list, loop: bool):
        from PySide6.QtCore import QMetaObject, Qt
        QMetaObject.invokeMethod(self._worker, "execute_motion_profile",
                                 Qt.QueuedConnection, *self._args(servo_id, waypoints, loop))

    def execute_motion_profile_group(self, servo_ids: list, waypoints: list, loop: bool):
        from PySide6.QtCore import QMetaObject, Qt
        QMetaObject.invokeMethod(self._worker, "execute_motion_profile_group",
                                 Qt.QueuedConnection, *self._args(servo_ids, waypoints, loop))

    def stop_motion(self):
        """Stop a running motion profile.  Thread-safe (just sets an Event)."""
        self._worker.stop_motion()

    def emergency_stop(self, servo_ids: list):
        from PySide6.QtCore import QMetaObject, Qt
        QMetaObject.invokeMethod(self._worker, "emergency_stop",
                                 Qt.QueuedConnection, *self._args(servo_ids))

    def sync_write_positions(self, id_pos_map: dict):
        """Send goal positions to multiple servos via the hardware worker thread.

        Uses a dedicated signal instead of QMetaObject.invokeMethod because
        PySide6's invokeMethod silently drops dict/QVariantMap arguments.
        """
        self._do_sync_write.emit(id_pos_map)

    def send_raw_packet(self, servo_id: int, data: bytes):
        from PySide6.QtCore import QMetaObject, Qt
        QMetaObject.invokeMethod(self._worker, "send_raw_packet",
                                 Qt.QueuedConnection, *self._args(servo_id, data))

    def is_connected(self) -> bool:
        return self._worker.is_connected()

    def shutdown(self):
        """Stop the worker QThread and wait up to 2s for it to finish.
        TYPE: User-defined | CALLED BY: main_window.closeEvent()
        """
        self._thread.quit()
        self._thread.wait(2000)

    @staticmethod
    def _args(*args):
        """Convert Python types to Q_ARG wrappers for QMetaObject.invokeMethod.
        TYPE: User-defined static helper | CALLED BY: every proxy method above
        CALLS: Q_ARG() [PySide6]
        """
        from PySide6.QtCore import Q_ARG
        type_map = {
            str: "QString", int: "int", bool: "bool",
            list: "QVariantList", dict: "QVariantMap",
            bytes: "QByteArray", float: "double",
        }
        return [Q_ARG(type_map.get(type(a), "QVariant"), a) for a in args]
