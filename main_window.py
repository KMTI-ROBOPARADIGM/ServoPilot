"""ServoPilotMainWindow — main QMainWindow, glues all widgets together."""

import sys
from PySide6.QtWidgets import (
    QMainWindow, QDockWidget, QTabWidget, QWidget,
    QLabel, QApplication, QMessageBox, QStatusBar, QToolBar, QPushButton,
)
from PySide6.QtCore import Qt, QTimer, Signal, Slot
from PySide6.QtGui import QAction, QFont, QIcon

from styles.dark_theme import get_stylesheet
from backend.servo_backend import ServoBackend
from backend.telemetry_worker import TelemetryWorker
from widgets.servo_list_panel   import ServoListPanel
from widgets.monitor_tab        import MonitorTab
from widgets.graph_tab          import GraphTab
from widgets.pid_tab            import PIDTab
from widgets.control_table_tab  import ControlTableTab
from widgets.firmware_tab       import FirmwareTab
from widgets.motion_profile_tab import MotionProfileTab
from widgets.packet_console     import PacketConsole


class ServoPilotMainWindow(QMainWindow):
    """Main window assembling all ServoPilot components."""

    def __init__(self):
        super().__init__()
        self._active_servo_id = -1
        self._goal_positions: dict[int, int] = {}
        self._connected_servos: list[int] = []

        self.setWindowTitle("ServoPilot — ST3215 Servo Management")
        self.setMinimumSize(1200, 700)
        self.resize(1440, 860)
        self.setStyleSheet(get_stylesheet())

        # ── Backend ──────────────────────────────────────────────────
        self._backend = ServoBackend(self)

        # ── Telemetry Timer (UI-side): calls backend.read_telemetry ──
        self._telemetry_timer = QTimer(self)
        self._telemetry_timer.timeout.connect(self._poll_telemetry)
        self._telemetry_hz = 20.0

        # ── Build UI ─────────────────────────────────────────────────
        self._build_menu()
        self._build_status_bar()
        self._build_central()
        self._build_left_dock()
        self._build_bottom_dock()

        # ── Wire signals ─────────────────────────────────────────────
        self._wire_backend()
        self._wire_widgets()

    # ── Build ─────────────────────────────────────────────────────────
    def _build_menu(self):
        mb = self.menuBar()

        # File
        file_menu = mb.addMenu("File")
        self._new_action("Save Config…",   file_menu, self._save_config)
        self._new_action("Load Config…",   file_menu, self._load_config)
        file_menu.addSeparator()
        self._new_action("Exit",           file_menu, self.close)

        # Device
        dev_menu = mb.addMenu("Device")
        self._act_scan       = self._new_action("Scan",       dev_menu, self._request_scan)
        self._act_disconnect = self._new_action("Disconnect", dev_menu, self._request_disconnect)
        dev_menu.addSeparator()
        self._new_action("Read All Registers", dev_menu, self._read_all_registers)
        self._new_action("Torque ON  (all)",   dev_menu, lambda: self._torque_all(True))
        self._new_action("Torque OFF (all)",   dev_menu, lambda: self._torque_all(False))

        # Tools
        tools_menu = mb.addMenu("Tools")
        self._new_action("Bus Diagnostics (Ping All)", tools_menu, self._ping_all)
        self._new_action("Export Telemetry CSV",       tools_menu, self._export_csv)

        # Help
        help_menu = mb.addMenu("Help")
        self._new_action("About ServoPilot", help_menu, self._about)
        self._new_action("ST3215 Datasheet", help_menu, self._open_datasheet)

    def _new_action(self, text, menu, slot):
        act = QAction(text, self)
        act.triggered.connect(slot)
        menu.addAction(act)
        return act

    def _build_status_bar(self):
        sb = self.statusBar()
        sb.setFixedHeight(26)
        self._sb_conn  = QLabel("● Disconnected")
        self._sb_conn.setStyleSheet("color: #484f58; margin: 0 8px;")
        self._sb_port  = QLabel("")
        self._sb_port.setStyleSheet("color: #8b949e; margin: 0 8px;")
        self._sb_count = QLabel("")
        self._sb_count.setStyleSheet("color: #8b949e; margin: 0 8px;")
        self._sb_servo = QLabel("")
        self._sb_servo.setStyleSheet("color: #c9d1d9; margin: 0 8px;")
        sb.addWidget(self._sb_conn)
        sb.addWidget(self._sb_port)
        sb.addWidget(self._sb_count)
        sb.addPermanentWidget(self._sb_servo)

        # Console toggle button — always visible in status bar
        self._console_toggle_btn = QPushButton("Console ▲")
        self._console_toggle_btn.setObjectName("btn_flat")
        self._console_toggle_btn.setFixedHeight(20)
        self._console_toggle_btn.setCheckable(True)
        self._console_toggle_btn.setChecked(False)   # starts collapsed
        self._console_toggle_btn.toggled.connect(self._toggle_console)
        sb.addPermanentWidget(self._console_toggle_btn)

    def _build_central(self):
        self._tabs = QTabWidget()
        self._tabs.setTabPosition(QTabWidget.North)
        self._tabs.setDocumentMode(False)

        self._monitor_tab   = MonitorTab()
        self._graph_tab     = GraphTab()
        self._pid_tab       = PIDTab()
        self._ctrl_tab      = ControlTableTab()
        self._firmware_tab  = FirmwareTab()
        self._motion_tab    = MotionProfileTab()

        self._tabs.addTab(self._monitor_tab,  "🖥  Monitor")
        self._tabs.addTab(self._graph_tab,    "📈  Real-Time Graph")
        self._tabs.addTab(self._pid_tab,      "🎛  PID Tuning")
        self._tabs.addTab(self._ctrl_tab,     "📋  Control Table")
        self._tabs.addTab(self._firmware_tab, "⚙  Device Config")
        self._tabs.addTab(self._motion_tab,   "🎬  Motion Profile")

        self.setCentralWidget(self._tabs)

    def _build_left_dock(self):
        self._servo_panel = ServoListPanel()
        dock = QDockWidget("SERVO LIST", self)
        dock.setObjectName("servo_list_dock")
        dock.setWidget(self._servo_panel)
        dock.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        dock.setFeatures(
            QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable
        )
        dock.setMinimumWidth(240)
        dock.setMaximumWidth(340)
        self.addDockWidget(Qt.LeftDockWidgetArea, dock)

    def _build_bottom_dock(self):
        self._console = PacketConsole()
        self._console_dock = QDockWidget("PACKET CONSOLE", self)
        self._console_dock.setObjectName("console_dock")
        self._console_dock.setWidget(self._console)
        self._console_dock.setAllowedAreas(Qt.BottomDockWidgetArea | Qt.TopDockWidgetArea)
        self._console_dock.setFeatures(
            QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable
        )
        self._console_dock.setMaximumHeight(220)
        self.addDockWidget(Qt.BottomDockWidgetArea, self._console_dock)
        self._console_dock.setVisible(False)  # starts collapsed

    # ── Wire backend signals ──────────────────────────────────────────
    def _wire_backend(self):
        b = self._backend

        b.connected.connect(self._on_connected)
        b.connection_failed.connect(self._on_connection_failed)
        b.disconnected.connect(self._on_disconnected)
        b.servos_found.connect(self._on_servos_found)
        b.telemetry_update.connect(self._on_telemetry)
        b.registers_read.connect(self._ctrl_tab.populate_registers)
        b.log_message.connect(self._console.append_log)
        b.error_occurred.connect(self._on_error)
        b.id_changed.connect(self._on_id_changed)
        b.pid_values.connect(
            lambda sid, p, i, d: self._pid_tab.set_pid_values(p, i, d)
        )

    # ── Wire widget signals to backend ────────────────────────────────
    def _wire_widgets(self):
        sp = self._servo_panel
        sp.connect_requested.connect(self._backend.connect_device)
        sp.disconnect_requested.connect(self._backend.disconnect_device)
        sp.scan_requested.connect(self._backend.scan_servos)
        sp.servo_selected.connect(self._on_servo_selected)

        mo = self._monitor_tab
        mo.goal_position_changed.connect(self._write_goal_position)
        mo.goal_speed_changed.connect(self._backend.write_goal_speed)
        mo.acceleration_changed.connect(self._backend.write_acceleration)
        mo.torque_toggled.connect(self._backend.set_torque)
        mo.mode_changed.connect(self._backend.set_mode)
        mo.rate_changed.connect(self._set_poll_rate)

        gt = self._graph_tab
        # start/stop handled internally in graph_tab; no backend calls needed

        pt = self._pid_tab
        pt.read_pid_requested.connect(self._backend.read_pid)
        pt.write_pid_requested.connect(self._backend.write_pid)

        ct = self._ctrl_tab
        ct.read_requested.connect(self._backend.read_all_registers)
        ct.write_requested.connect(self._backend.write_register)

        fw = self._firmware_tab
        fw.id_change_requested.connect(self._backend.change_id)
        fw.baud_change_requested.connect(self._backend.change_baudrate)
        fw.limits_requested.connect(self._backend.set_angle_limits)

        mt = self._motion_tab
        mt.execute_requested.connect(self._backend.execute_motion_profile)

        con = self._console
        con.raw_send_requested.connect(self._backend.send_raw_packet)

    # ── Backend signal handlers ───────────────────────────────────────
    @Slot()
    def _on_connected(self):
        self._servo_panel.on_connected()
        self._sb_conn.setText("● Connected")
        self._sb_conn.setStyleSheet("color: #2ea043; font-weight: bold; margin: 0 8px;")
        port = self._servo_panel.get_current_port()
        baud = self._servo_panel.get_current_baud()
        self._sb_port.setText(f"{port} @ {baud:,} bps")
        self._console.append_log(f"Connected {port} @ {baud:,} bps")

    @Slot(str)
    def _on_connection_failed(self, msg: str):
        self._servo_panel.on_connection_failed(msg)
        self._sb_conn.setText("✗ Failed")
        self._sb_conn.setStyleSheet("color: #f85149; font-weight: bold; margin: 0 8px;")
        QMessageBox.critical(self, "Connection Failed", msg)

    @Slot()
    def _on_disconnected(self):
        self._servo_panel.on_disconnected()
        self._telemetry_timer.stop()
        self._connected_servos.clear()
        self._active_servo_id = -1
        self._monitor_tab.clear_servo()
        self._graph_tab.clear_servos()
        self._pid_tab.clear_servos()   # reset PID servo selector
        self._sb_conn.setText("● Disconnected")
        self._sb_conn.setStyleSheet("color: #484f58; margin: 0 8px;")
        self._sb_port.setText("")
        self._sb_count.setText("")

    @Slot(list)
    def _on_servos_found(self, ids: list):
        self._connected_servos = sorted(ids)
        self._servo_panel.on_servos_found(ids)
        self._sb_count.setText(f"{len(ids)} servo{'s' if len(ids)!=1 else ''}")
        for sid in ids:
            self._graph_tab.register_servo(sid)
            self._pid_tab.add_servo(sid)   # populate PID servo selector
        if ids:
            self._on_servo_selected(ids[0])
            self._telemetry_timer.start(int(1000 / self._telemetry_hz))

    @Slot(int, dict)
    def _on_telemetry(self, servo_id: int, data: dict):
        self._servo_panel.update_telemetry(servo_id, data)
        self._monitor_tab.update_telemetry(servo_id, data)
        self._graph_tab.update_telemetry(
            servo_id, data, self._goal_positions.get(servo_id)
        )
        self._pid_tab.update_telemetry(
            servo_id, data, self._goal_positions.get(servo_id)
        )
        self._firmware_tab.update_telemetry(servo_id, data)

    @Slot(str)
    def _on_error(self, msg: str):
        self._console.append_log(f"[ERROR] {msg}", error=True)
        self.statusBar().showMessage(f"Error: {msg}", 4000)

    @Slot(int, int)
    def _on_id_changed(self, old_id: int, new_id: int):
        QMessageBox.information(
            self, "ID Changed",
            f"Servo ID changed: {old_id} → {new_id}\n"
            "Please rescan to update the device list.",
        )
        self._backend.scan_servos()

    # ── Widget signal handlers ────────────────────────────────────────
    @Slot(int)
    def _on_servo_selected(self, servo_id: int):
        self._active_servo_id = servo_id
        self._monitor_tab.set_servo(servo_id)
        self._pid_tab.set_servo(servo_id)
        self._ctrl_tab.set_servo(servo_id)
        self._firmware_tab.set_servo(servo_id)
        self._motion_tab.set_servo(servo_id)
        self._sb_servo.setText(f"Active: Servo #{servo_id}")

    @Slot(int, int)
    def _write_goal_position(self, servo_id: int, position: int):
        self._goal_positions[servo_id] = position
        self._backend.write_goal_position(servo_id, position)

    # ── Telemetry polling (timer-based, runs in main thread) ──────────
    def _poll_telemetry(self):
        for sid in self._connected_servos:
            self._backend.read_telemetry(sid)

    @Slot(float)
    def _set_poll_rate(self, hz: float):
        self._telemetry_hz = hz
        if self._telemetry_timer.isActive():
            self._telemetry_timer.start(int(1000 / hz))

    # ── Console toggle ────────────────────────────────────────────────
    def _toggle_console(self, checked: bool):
        self._console_dock.setVisible(checked)
        self._console_toggle_btn.setText("Console ▼" if checked else "Console ▲")

    # ── Menu actions ──────────────────────────────────────────────────
    def _request_scan(self):
        self._backend.scan_servos()

    def _request_disconnect(self):
        self._backend.disconnect_device()

    def _read_all_registers(self):
        if self._active_servo_id >= 0:
            self._backend.read_all_registers(self._active_servo_id)
            self._tabs.setCurrentWidget(self._ctrl_tab)

    def _torque_all(self, on: bool):
        for sid in self._connected_servos:
            self._backend.set_torque(sid, on)

    def _ping_all(self):
        if self._connected_servos:
            self._console.append_log("[DIAG] Pinging all servos …")
            self._backend.scan_servos()
        else:
            QMessageBox.information(self, "Not connected", "Connect first then ping.")

    def _export_csv(self):
        self._tabs.setCurrentWidget(self._graph_tab)
        self._graph_tab._export_csv()

    def _save_config(self):
        QMessageBox.information(self, "Save Config", "Config save — coming soon.")

    def _load_config(self):
        QMessageBox.information(self, "Load Config", "Config load — coming soon.")

    def _about(self):
        QMessageBox.about(
            self, "About ServoPilot",
            "<b>ServoPilot v1.0</b><br>"
            "Professional ST3215 Servo Management Tool<br><br>"
            "Features: Real-time telemetry, PID tuning, register editor,<br>"
            "motion profiles, device configuration, packet console.<br><br>"
            "Built with PySide6 + pyqtgraph.",
        )

    def _open_datasheet(self):
        import webbrowser
        webbrowser.open(
            "https://www.feetechrc.com/Data/feetechrc.com/upload/file/20210902/start%20%20use%20ST%20series%20servo.pdf"
        )

    # ── Cleanup ───────────────────────────────────────────────────────
    def closeEvent(self, event):
        self._telemetry_timer.stop()
        self._backend.disconnect_device()
        self._backend.shutdown()
        super().closeEvent(event)
