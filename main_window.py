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
from backend.api_bridge import ApiBridge
from widgets.servo_list_panel   import ServoListPanel
from widgets.monitor_tab        import MonitorTab
from widgets.graph_tab          import GraphTab
from widgets.pid_tab            import PIDTab
from widgets.control_table_tab  import ControlTableTab
from widgets.firmware_tab       import FirmwareTab
from widgets.motion_profile_tab import MotionProfileTab
from widgets.packet_console     import PacketConsole
from widgets.sync_tab           import SyncTab


class ServoPilotMainWindow(QMainWindow):
    """Main window assembling all ServoPilot components."""

    def __init__(self):
        super().__init__()
        self._active_servo_id = -1
        self._goal_positions: dict[int, int] = {}
        self._connected_servos: list[int] = []
        self._last_telemetry: dict[int, int] = {}   # servo_id → last-seen position
        self._api_bridge = ApiBridge()

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
        sb.setFixedHeight(28)
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

        # ── Emergency Stop button — always visible, disabled until connected ──
        self._estop_btn = QPushButton("⛔  EMERGENCY STOP")
        self._estop_btn.setObjectName("btn_estop")
        self._estop_btn.setFixedHeight(22)
        self._estop_btn.setToolTip(
            "Immediately disable torque on ALL connected servos.\n"
            "Servos will go limp. Use when hardware is about to collide."
        )
        self._estop_btn.setEnabled(False)   # disabled until connected
        self._estop_btn.clicked.connect(self._emergency_stop)
        sb.addPermanentWidget(self._estop_btn)

        # Console toggle button — always visible in status bar
        self._console_toggle_btn = QPushButton("Console ▲")
        self._console_toggle_btn.setObjectName("btn_flat")
        self._console_toggle_btn.setFixedHeight(20)
        self._console_toggle_btn.setCheckable(True)
        self._console_toggle_btn.setChecked(False)   # starts collapsed
        self._console_toggle_btn.toggled.connect(self._toggle_console)
        sb.addPermanentWidget(self._console_toggle_btn)

        # API server toggle
        self._api_label = QLabel("")
        self._api_label.setStyleSheet("color: #3fb950; font-size: 10px; margin: 0 4px;")
        sb.addPermanentWidget(self._api_label)

        self._api_btn = QPushButton("API ▶")
        self._api_btn.setObjectName("btn_flat")
        self._api_btn.setFixedHeight(20)
        self._api_btn.setToolTip("Start/stop the REST + WebSocket API server on localhost:8765")
        self._api_btn.setCheckable(True)
        self._api_btn.toggled.connect(self._toggle_api_server)
        sb.addPermanentWidget(self._api_btn)

        # API command queue polling timer
        self._api_cmd_timer = QTimer(self)
        self._api_cmd_timer.setInterval(100)  # 10 Hz
        self._api_cmd_timer.timeout.connect(self._poll_api_commands)
        self._api_cmd_timer.start()

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
        self._sync_tab      = SyncTab()

        self._tabs.addTab(self._monitor_tab,  "🖥  Monitor")
        self._tabs.addTab(self._graph_tab,    "📈  Real-Time Graph")
        self._tabs.addTab(self._pid_tab,      "🎛  PID Tuning")
        self._tabs.addTab(self._ctrl_tab,     "📋  Control Table")
        self._tabs.addTab(self._firmware_tab, "⚙  Device Config")
        self._tabs.addTab(self._motion_tab,   "🎬  Motion Profile")
        self._tabs.addTab(self._sync_tab,     "🤝  Sync Control")

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
            lambda sid, p, i, d: (
                self._pid_tab.set_pid_values(p, i, d),
                self._pid_tab.set_active_gains(p, i, d),
            )
        )
        b.estop_done.connect(self._on_estop_done)
        b.sync_write_done.connect(self._sync_tab.on_sync_write_done)

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
        pt.step_test_requested.connect(self._on_step_test_requested)

        ct = self._ctrl_tab
        ct.read_requested.connect(self._backend.read_all_registers)
        ct.write_requested.connect(self._backend.write_register)

        fw = self._firmware_tab
        fw.id_change_requested.connect(self._backend.change_id)
        fw.baud_change_requested.connect(self._backend.change_baudrate)
        fw.limits_requested.connect(self._backend.set_angle_limits)

        mt = self._motion_tab
        mt.execute_requested.connect(self._backend.execute_motion_profile)
        mt.execute_group_requested.connect(self._backend.execute_motion_profile_group)
        mt.stop_requested.connect(self._backend.stop_motion)

        st = self._sync_tab
        st.sync_write_requested.connect(self._on_sync_write_requested)
        # Feed groups to motion profile tab whenever they change
        st.groups_changed.connect(self._motion_tab.set_groups)
        # ↺ Read button: one-shot fill from last-seen telemetry position (no
        # continuous feed — that would fight the user dragging the slider)
        st.read_position_requested.connect(self._on_sync_read_requested)
        st.torque_off_requested.connect(self._backend.emergency_stop)
        # Homing — reuses the same proven write path
        st.home_requested.connect(self._on_sync_write_requested)
        st.homing_started.connect(
            lambda: self.statusBar().showMessage("🏠 Homing in progress…", 3000)
        )
        st.homing_complete.connect(
            lambda: self.statusBar().showMessage("🏠 Homing complete", 3000)
        )

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
        self._estop_btn.setEnabled(True)

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
        self._sync_tab.clear_servos()  # reset Sync tab
        self._sb_conn.setText("● Disconnected")
        self._sb_conn.setStyleSheet("color: #484f58; margin: 0 8px;")
        self._sb_port.setText("")
        self._sb_count.setText("")
        self._estop_btn.setEnabled(False)

    @Slot(list)
    def _on_servos_found(self, ids: list):
        self._connected_servos = sorted(ids)
        self._servo_panel.on_servos_found(ids)
        self._sb_count.setText(f"{len(ids)} servo{'s' if len(ids)!=1 else ''}")
        self._api_bridge.set_connected_servos(ids)
        for sid in ids:
            self._graph_tab.register_servo(sid)
            self._pid_tab.add_servo(sid)   # populate PID servo selector
            self._sync_tab.add_servo(sid)  # populate Sync tab servo list
            self._motion_tab.add_servo(sid)  # populate Motion Profile selector
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
        self._sync_tab.update_telemetry(servo_id, data)
        self._api_bridge.update_telemetry(servo_id, data)
        # Cache position for the Sync tab's one-shot '↺ Read Current' button.
        # Do NOT call sync_tab.on_position_read here — that would fight the
        # user dragging sliders by resetting them at 20 Hz.
        if "position" in data:
            self._last_telemetry[servo_id] = data["position"]

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

    @Slot(int)
    def _on_sync_read_requested(self, servo_id: int):
        """One-shot: fill the sync tab slider with the last-seen telemetry position.
        This is triggered by the ↺ button on each row and does NOT create a
        continuous feed that would fight slider dragging."""
        pos = self._last_telemetry.get(servo_id)
        if pos is not None:
            self._sync_tab.on_position_read(servo_id, pos)

    @Slot(dict)
    def _on_sync_write_requested(self, id_pos_map: dict):
        """Move every servo in the sync group to its goal position.

        Uses the exact same write_goal_position() path that the Monitor tab
        uses — which is the only path we know works reliably through Qt's
        cross-thread dispatch.  No fancy telemetry pausing, no direct mutex
        access, no QTimer delays.
        """
        for sid, pos in id_pos_map.items():
            self._goal_positions[sid] = pos
            self._backend.write_goal_position(int(sid), int(pos))

        ids_str = ", ".join(f"#{k}→{v}" for k, v in id_pos_map.items())
        self.statusBar().showMessage(f"🤝 Sync move: {ids_str}", 4000)

    # ── Telemetry polling (timer-based, runs in main thread) ──────────
    def _poll_telemetry(self):
        for sid in self._connected_servos:
            self._backend.read_telemetry(sid)

    @Slot(float)
    def _set_poll_rate(self, hz: float):
        self._telemetry_hz = hz
        if self._telemetry_timer.isActive():
            self._telemetry_timer.start(int(1000 / hz))

    @Slot(int, int)
    def _on_step_test_requested(self, servo_id: int, delta: int):
        """Step 1: Read current pos. Step 2: Compute goal. Step 3: Write goal.

        CRITICAL ORDER — never change:
          1. Read actual position from telemetry (BEFORE any write)
          2. Compute goal = actual_position + delta
          3. Tell PID tab to begin capture (sets pre_step_pos and goal)
          4. Write goal to servo hardware
          5. Schedule return to original position after 1.0s
        """
        # STEP 1: Read current position BEFORE any write
        pre_pos = self._last_telemetry.get(servo_id)
        if pre_pos is None:
            self.statusBar().showMessage(
                "⚠ No telemetry yet — cannot step test", 3000
            )
            return

        # STEP 2: Compute goal from ACTUAL position (not stored goal)
        target = max(0, min(4095, pre_pos + delta))

        # STEP 3: Begin capture in PID tab BEFORE writing goal
        self._pid_tab.begin_capture(pre_pos, target)

        # STEP 4: Write goal AFTER capture setup
        self._write_goal_position(servo_id, target)
        self.statusBar().showMessage(
            f"▶ Step test: Servo #{servo_id}  {pre_pos} → {target}", 3000
        )

        # STEP 5: Return to actual position after 1.0s
        # (capture window closes at 0.95s — 50ms safety margin)
        QTimer.singleShot(1000, lambda: self._write_goal_position(servo_id, pre_pos))

    # ── Emergency Stop ────────────────────────────────────────────────
    def _emergency_stop(self):
        """Immediately disable torque on all known servos."""
        if not self._connected_servos:
            self.statusBar().showMessage("⛔ No servos connected.", 3000)
            return
        # Clear stored goal positions so nothing re-sends to them
        self._goal_positions.clear()
        self._backend.emergency_stop(list(self._connected_servos))
        self.statusBar().showMessage(
            f"⛔ E-STOP sent to {len(self._connected_servos)} servo(s) — torque disabled!", 5000
        )

    @Slot(int)
    def _on_estop_done(self, count: int):
        """Called when backend confirms all servos stopped."""
        self._console.append_log(
            f"[E-STOP] Complete — {count} servo(s) torque disabled.", error=False
        )

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

    # ── Cleanup ─────────────────────────────────────────────────
    def closeEvent(self, event):
        self._telemetry_timer.stop()
        # Stop API server if running
        if self._api_bridge.server_running:
            from backend.api_server import stop_server
            stop_server(self._api_bridge)
        self._backend.disconnect_device()
        self._backend.shutdown()
        super().closeEvent(event)

    # ── API Server ───────────────────────────────────────────────

    def _toggle_api_server(self, on: bool):
        from backend.api_server import start_server, stop_server
        if on:
            start_server(self._api_bridge, host="127.0.0.1", port=8765)
            self._api_btn.setText("API ⏹")
            self._api_label.setText("API: http://localhost:8765")
            self._console.append_log("[API] Server started on http://localhost:8765")
        else:
            stop_server(self._api_bridge)
            self._api_btn.setText("API ▶")
            self._api_label.setText("")
            self._console.append_log("[API] Server stopped")

    def _poll_api_commands(self):
        """Process commands queued by the REST/WebSocket API."""
        for cmd in self._api_bridge.poll_commands():
            action = cmd.get("action")
            try:
                if action == "set_position":
                    sid = int(cmd["id"])
                    pos = int(cmd["position"])
                    if cmd.get("speed") is not None:
                        self._backend.write_goal_speed(sid, int(cmd["speed"]))
                    self._backend.write_goal_position(sid, pos)

                elif action == "set_torque":
                    sid = int(cmd["id"])
                    self._backend.set_torque(sid, bool(cmd["enable"]))

                elif action == "set_mode":
                    sid = int(cmd["id"])
                    self._backend.set_mode(sid, int(cmd["mode"]))

                elif action == "home":
                    # Trigger the sync tab's home routine
                    self._sync_tab._home_all()

                elif action == "emergency_stop":
                    self._emergency_stop()

                elif action == "sync_move":
                    positions = cmd.get("positions", {})
                    self._on_sync_write_requested(positions)

            except Exception as e:
                self._console.append_log(f"[API] Command error: {e}")