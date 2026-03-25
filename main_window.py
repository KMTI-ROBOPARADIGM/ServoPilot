"""ServoPilotMainWindow — main QMainWindow, glues all widgets together.

FILE: main_window.py
PURPOSE: Central orchestrator for the entire ServoPilot GUI. Creates all UI
         components (tabs, docks, menus, status bar), instantiates the backend,
         and wires every signal/slot connection between widgets and backend.
CALLED BY: main.py → ServoPilotMainWindow()
CALLS INTO: Every widget class, ServoBackend, TelemetryWorker, ApiBridge,
            api_server (start/stop), dark_theme stylesheet.
"""

import sys  # [STDLIB] System exit, argv
from PySide6.QtWidgets import (       # [PySide6] Core widget classes
    QMainWindow, QDockWidget, QTabWidget, QWidget,
    QLabel, QApplication, QMessageBox, QStatusBar, QToolBar, QPushButton,
)
from PySide6.QtCore import Qt, QTimer, Signal, Slot  # [PySide6] Qt enums, timer, signal/slot decorators
from PySide6.QtGui import QAction, QFont, QIcon      # [PySide6] Menu actions, fonts, icons

from styles.dark_theme import get_stylesheet          # [USER-DEFINED, styles/dark_theme.py] Returns QSS stylesheet string
from backend.servo_backend import ServoBackend        # [USER-DEFINED, backend/servo_backend.py] Hardware abstraction layer
from backend.telemetry_worker import TelemetryWorker  # [USER-DEFINED, backend/telemetry_worker.py] Threaded telemetry poller
from backend.api_bridge import ApiBridge              # [USER-DEFINED, backend/api_bridge.py] Thread-safe API↔Qt bridge
from widgets.servo_list_panel   import ServoListPanel  # [USER-DEFINED] Left dock — port selector + servo list
from widgets.monitor_tab        import MonitorTab      # [USER-DEFINED] Tab 1 — live LCD telemetry + controls
from widgets.graph_tab          import GraphTab        # [USER-DEFINED] Tab 2 — real-time pyqtgraph plots
from widgets.pid_tab            import PIDTab          # [USER-DEFINED] Tab 3 — PID tuning + step response
from widgets.control_table_tab  import ControlTableTab # [USER-DEFINED] Tab 4 — full register map editor
from widgets.firmware_tab       import FirmwareTab     # [USER-DEFINED] Tab 5 — device ID/baud/limits config
from widgets.motion_profile_tab import MotionProfileTab# [USER-DEFINED] Tab 6 — waypoint trajectory editor
from widgets.packet_console     import PacketConsole   # [USER-DEFINED] Bottom dock — hex packet logger
from widgets.sync_tab           import SyncTab         # [USER-DEFINED] Tab 7 — group sync write + homing


class ServoPilotMainWindow(QMainWindow):
    """Main window assembling all ServoPilot components."""

    def __init__(self):
        """
        ┌──────────────────────────────────────────────────────────────────┐
        │ METHOD: __init__                                                │
        │ TYPE: User-defined constructor (overrides QMainWindow.__init__) │
        │ CALLED BY: main.py → ServoPilotMainWindow()                     │
        │ CALLS:                                                          │
        │   • get_stylesheet() — [USER, styles/dark_theme.py] QSS theme  │
        │   • ServoBackend() — [USER, backend/servo_backend.py]          │
        │   • QTimer() — [PySide6] for periodic telemetry polling        │
        │   • _build_menu/status_bar/central/left_dock/bottom_dock()      │
        │   • _wire_backend(), _wire_widgets()                            │
        │ PURPOSE: Initialise main window, create all UI and backend     │
        └──────────────────────────────────────────────────────────────────┘
        """
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

        # ── Scan Spinner Timer ───────────────────────────────────────
        self._scan_timer = QTimer(self)
        self._scan_timer.timeout.connect(self._update_scan_spinner)
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
        """Build the application menu bar (File, Device, Tools, Help).
        TYPE: User-defined | CALLED BY: __init__
        CALLS: _new_action(), self.close [PySide6], _save_config, _load_config,
               _request_scan, _request_disconnect, _read_all_registers,
               _torque_all, _ping_all, _export_csv, _about, _open_datasheet
        """
        mb = self.menuBar()  # [PySide6] QMainWindow.menuBar() — returns/creates the menu bar

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
        """Helper: create a QAction, connect its triggered signal, add to menu.
        TYPE: User-defined | CALLED BY: _build_menu()
        CALLS: QAction() [PySide6], QAction.triggered.connect [PySide6]
        """
        act = QAction(text, self)
        act.triggered.connect(slot)
        menu.addAction(act)
        return act

    def _build_status_bar(self):
        """Build the status bar with connection info, E-STOP, console toggle, API toggle.
        TYPE: User-defined | CALLED BY: __init__
        CALLS: statusBar() [PySide6], QLabel/QPushButton [PySide6],
               QTimer [PySide6] for API command polling,
               _emergency_stop, _toggle_console, _toggle_api_server, _poll_api_commands
        """
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
        """Create the central QTabWidget and add all 7 tabs.
        TYPE: User-defined | CALLED BY: __init__
        CALLS: QTabWidget() [PySide6], MonitorTab/GraphTab/PIDTab/ControlTableTab/
               FirmwareTab/MotionProfileTab/SyncTab [USER-DEFINED widgets]
        """
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
        """Create the left dock containing the ServoListPanel with a toggle button.
        TYPE: User-defined | CALLED BY: __init__
        CALLS: ServoListPanel() [USER, widgets/servo_list_panel.py],
               QDockWidget() [PySide6]
        """
        from PySide6.QtCore import QPropertyAnimation, QEasingCurve
        from PySide6.QtWidgets import QWidget, QVBoxLayout, QPushButton, QHBoxLayout, QLabel
        
        self._servo_panel = ServoListPanel()
        
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Toggle Button
        self._toggle_servo_btn = QPushButton("Hide Servos ◀")
        self._toggle_servo_btn.setObjectName("btn_flat")
        self._toggle_servo_btn.clicked.connect(self._toggle_servo_panel)
        layout.addWidget(self._toggle_servo_btn)
        
        # Scanner overlay for Change 2
        self._scan_overlay = QWidget()
        overlay_layout = QHBoxLayout(self._scan_overlay)
        overlay_layout.setContentsMargins(0, 0, 0, 0)
        self._scan_spinner = QLabel("⠋")
        self._scan_spinner.setStyleSheet("color: #58a6ff; font-weight: bold; font-size: 14px;")
        self._scan_text = QLabel("Scanning... (checking IDs 1-253)")
        self._scan_text.setStyleSheet("color: #8b949e; font-size: 11px;")
        overlay_layout.addWidget(self._scan_spinner)
        overlay_layout.addWidget(self._scan_text)
        overlay_layout.addStretch()
        self._scan_overlay.setVisible(False)
        
        # Insert overlay near the scan button
        if hasattr(self._servo_panel, '_scan_btn'):
            idx = self._servo_panel.layout().indexOf(self._servo_panel._scan_btn)
            self._servo_panel.layout().insertWidget(idx, self._scan_overlay)
        
        layout.addWidget(self._servo_panel)
        
        dock = QDockWidget("SERVO LIST", self)
        dock.setObjectName("servo_list_dock")
        dock.setWidget(container)
        dock.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        dock.setFeatures(
            QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable
        )
        self.addDockWidget(Qt.LeftDockWidgetArea, dock)
        
        # Animation setup
        self._servo_panel.setMinimumWidth(240)
        self._servo_panel.setMaximumWidth(340)
        
        self._servo_panel_anim = QPropertyAnimation(self._servo_panel, b"maximumWidth")
        self._servo_panel_anim.setDuration(300)
        self._servo_panel_anim.setEasingCurve(QEasingCurve.InOutQuad)

    def _toggle_servo_panel(self):
        """Toggle the visibility of the servo list panel using maximumWidth animation."""
        if self._servo_panel.maximumWidth() == 0:
            self._servo_panel.setMinimumWidth(240)
            self._servo_panel_anim.setStartValue(0)
            self._servo_panel_anim.setEndValue(340)
            self._toggle_servo_btn.setText("Hide Servos ◀")
            self._servo_panel_anim.start()
        else:
            self._servo_panel.setMinimumWidth(0)
            self._servo_panel_anim.setStartValue(self._servo_panel.width())
            self._servo_panel_anim.setEndValue(0)
            self._toggle_servo_btn.setText("Show Servos ▶")
            self._servo_panel_anim.start()

    def _build_bottom_dock(self):
        """Create the bottom dock containing the PacketConsole (hex logger).
        TYPE: User-defined | CALLED BY: __init__
        CALLS: PacketConsole() [USER, widgets/packet_console.py],
               QDockWidget() [PySide6]
        """
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
        """Connect ServoBackend signals → MainWindow slots (data flows backend→UI).
        TYPE: User-defined | CALLED BY: __init__
        PURPOSE: Backend emits signals when hardware events occur (connected,
                 servos found, telemetry arrives, etc.). This method routes
                 each signal to the appropriate handler method or widget slot.
        """
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
        b.estop_done.connect(self._on_estop_done)
        b.sync_write_done.connect(self._sync_tab.on_sync_write_done)

    # ── Wire widget signals to backend ────────────────────────────────
    def _wire_widgets(self):
        """Connect widget signals → backend slots (data flows UI→backend).
        TYPE: User-defined | CALLED BY: __init__
        PURPOSE: User interactions in widgets emit signals. This method routes
                 each widget signal to the appropriate backend method or handler.
                 Covers ServoListPanel, MonitorTab, PIDTab, ControlTableTab,
                 FirmwareTab, MotionProfileTab, SyncTab, and PacketConsole.
        """
        sp = self._servo_panel
        sp.connect_requested.connect(self._backend.connect_device)
        sp.disconnect_requested.connect(self._backend.disconnect_device)
        sp.scan_requested.connect(self._on_scan_requested)
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
        """Slot: backend confirms serial port opened successfully.
        TYPE: User-defined Qt Slot | CALLED BY: ServoBackend.connected signal
        CALLS: servo_panel.on_connected(), console.append_log()
        """
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
        """Slot: backend reports connection failure.
        TYPE: User-defined Qt Slot | CALLED BY: ServoBackend.connection_failed signal
        CALLS: servo_panel.on_connection_failed(), QMessageBox.critical() [PySide6]
        """
        self._servo_panel.on_connection_failed(msg)
        self._sb_conn.setText("✗ Failed")
        self._sb_conn.setStyleSheet("color: #f85149; font-weight: bold; margin: 0 8px;")
        QMessageBox.critical(self, "Connection Failed", msg)

    @Slot()
    def _on_disconnected(self):
        """Slot: backend confirms disconnection. Resets all UI state.
        TYPE: User-defined Qt Slot | CALLED BY: ServoBackend.disconnected signal
        CALLS: servo_panel.on_disconnected(), monitor/graph/pid/sync_tab.clear*()
        """
        if hasattr(self, '_scan_timer') and self._scan_timer.isActive():
            self._scan_timer.stop()
            self._scan_overlay.setVisible(False)
            if hasattr(self._servo_panel, '_scan_btn'):
                self._servo_panel._scan_btn.setVisible(True)

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
        """Slot: backend found servos on the bus after a scan.
        TYPE: User-defined Qt Slot | CALLED BY: ServoBackend.servos_found signal
        CALLS: servo_panel.on_servos_found(), graph/pid/sync/motion_tab.add_servo(),
               _on_servo_selected(), _telemetry_timer.start(), api_bridge.set_connected_servos()
        """
        if hasattr(self, '_scan_timer') and self._scan_timer.isActive():
            self._scan_timer.stop()
            self._scan_overlay.setVisible(False)
            if hasattr(self._servo_panel, '_scan_btn'):
                self._servo_panel._scan_btn.setVisible(True)

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
        """Slot: receive telemetry dict for one servo, fan out to all widgets.
        TYPE: User-defined Qt Slot | CALLED BY: ServoBackend.telemetry_update signal
        CALLS: servo_panel/monitor/graph/pid/firmware/sync_tab.update_telemetry(),
               api_bridge.update_telemetry()
        """
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
        """Slot: backend reports an error message.
        TYPE: User-defined Qt Slot | CALLED BY: ServoBackend.error_occurred signal
        CALLS: console.append_log(), statusBar().showMessage() [PySide6]
        """
        if hasattr(self, '_scan_timer') and self._scan_timer.isActive():
            self._scan_timer.stop()
            self._scan_overlay.setVisible(False)
            if hasattr(self._servo_panel, '_scan_btn'):
                self._servo_panel._scan_btn.setVisible(True)
                self._servo_panel._scan_btn.setText("🔍  Scan for Servos")
                self._servo_panel._scan_btn.setEnabled(True)

        self._console.append_log(f"[ERROR] {msg}", error=True)
        self.statusBar().showMessage(f"Error: {msg}", 4000)

    @Slot(int, int)
    def _on_id_changed(self, old_id: int, new_id: int):
        """Slot: servo ID was changed via firmware tab.
        TYPE: User-defined Qt Slot | CALLED BY: ServoBackend.id_changed signal
        CALLS: QMessageBox.information() [PySide6], backend.scan_servos()
        """
        QMessageBox.information(
            self, "ID Changed",
            f"Servo ID changed: {old_id} → {new_id}\n"
            "Please rescan to update the device list.",
        )
        self._backend.scan_servos()

    # ── Widget signal handlers ────────────────────────────────────────
    @Slot(int)
    def _on_servo_selected(self, servo_id: int):
        """Slot: user selected a servo in the list panel.
        TYPE: User-defined Qt Slot | CALLED BY: ServoListPanel.servo_selected signal,
              also called by _on_servos_found() for auto-select
        CALLS: monitor/pid/ctrl/firmware/motion_tab.set_servo()
        """
        self._active_servo_id = servo_id
        self._monitor_tab.set_servo(servo_id)
        self._pid_tab.set_servo(servo_id)
        self._ctrl_tab.set_servo(servo_id)
        self._firmware_tab.set_servo(servo_id)
        self._motion_tab.set_servo(servo_id)
        self._sb_servo.setText(f"Active: Servo #{servo_id}")

    @Slot(int, int)
    def _write_goal_position(self, servo_id: int, position: int):
        """Slot: write a goal position to one servo (caches it + sends to backend).
        TYPE: User-defined Qt Slot | CALLED BY: MonitorTab.goal_position_changed signal,
              _on_step_test_requested(), _on_sync_write_requested()
        CALLS: backend.write_goal_position() [USER, servo_backend.py]
        """
        self._goal_positions[servo_id] = position
        self._backend.write_goal_position(servo_id, position)

    @Slot(int)
    def _on_sync_read_requested(self, servo_id: int):
        """Slot: one-shot fill the sync tab slider from cached telemetry.
        TYPE: User-defined Qt Slot | CALLED BY: SyncTab.read_position_requested signal
        CALLS: sync_tab.on_position_read()
        """
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
        """Timer callback: request telemetry read for every connected servo.
        TYPE: User-defined | CALLED BY: _telemetry_timer.timeout (QTimer, ~20Hz)
        CALLS: backend.read_telemetry() for each connected servo ID
        """
        for sid in self._connected_servos:
            self._backend.read_telemetry(sid)

    @Slot(float)
    def _set_poll_rate(self, hz: float):
        """Slot: user changed the telemetry polling rate in MonitorTab.
        TYPE: User-defined Qt Slot | CALLED BY: MonitorTab.rate_changed signal
        CALLS: _telemetry_timer.start() [PySide6 QTimer]
        """
        self._telemetry_hz = hz
        if self._telemetry_timer.isActive():
            self._telemetry_timer.start(int(1000 / hz))

    @Slot(int, int)
    def _on_step_test_requested(self, servo_id: int, delta: int):
        """Send goal = current_goal + delta, then return after 1.2 s."""
        current = self._goal_positions.get(servo_id, 2048)
        target  = max(0, min(4095, current + delta))
        self._pid_tab.on_step_test_started()  # reset graph + metrics at t=0
        self._write_goal_position(servo_id, target)
        self.statusBar().showMessage(
            f"▶ Step test: Servo #{servo_id}  {current} → {target}", 3000
        )
        QTimer.singleShot(1200, lambda: self._write_goal_position(servo_id, current))

    # ── Emergency Stop ────────────────────────────────────────────────
    def _emergency_stop(self):
        """Immediately disable torque on all known servos.
        TYPE: User-defined | CALLED BY: E-STOP button click, _poll_api_commands()
        CALLS: backend.emergency_stop() [USER, servo_backend.py]
        """
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
        """Toggle the bottom packet console dock visibility.
        TYPE: User-defined | CALLED BY: Console toggle button (toggled signal)
        CALLS: _console_dock.setVisible() [PySide6 QDockWidget]
        """
        self._console_dock.setVisible(checked)
        self._console_toggle_btn.setText("Console ▼" if checked else "Console ▲")

    def _update_scan_spinner(self):
        """Timer callback: Rotate the scan spinner characters."""
        spinner_chars = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        current = self._scan_spinner.text()
        try:
            nxt = spinner_chars[(spinner_chars.index(current) + 1) % len(spinner_chars)]
        except ValueError:
            nxt = spinner_chars[0]
        self._scan_spinner.setText(nxt)

    @Slot()
    def _on_scan_requested(self):
        """Slot: Handle requests to scan for servos, start overlay animation."""
        self._backend.scan_servos()
        if hasattr(self._servo_panel, '_scan_btn'):
            self._servo_panel._scan_btn.setVisible(False)
        self._scan_overlay.setVisible(True)
        self._scan_timer.start(100)

    # ── Menu actions ──────────────────────────────────────────────────
    def _request_scan(self):
        """Menu action: trigger a servo bus scan.
        TYPE: User-defined | CALLED BY: Device > Scan menu action
        CALLS: backend.scan_servos()
        """
        self._on_scan_requested()

    def _request_disconnect(self):
        """Menu action: disconnect from serial port.
        TYPE: User-defined | CALLED BY: Device > Disconnect menu action
        CALLS: backend.disconnect_device()
        """
        self._backend.disconnect_device()

    def _read_all_registers(self):
        """Menu action: read all registers of the active servo.
        TYPE: User-defined | CALLED BY: Device > Read All Registers menu action
        CALLS: backend.read_all_registers()
        """
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
        """Override QMainWindow.closeEvent — clean shutdown.
        TYPE: User-defined (overrides QMainWindow) | CALLED BY: Qt framework on window close
        CALLS: _telemetry_timer.stop(), stop_server() [USER, api_server.py],
               backend.disconnect_device(), backend.shutdown()
        """
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
        """Start or stop the REST/WebSocket API server.
        TYPE: User-defined | CALLED BY: API toggle button (toggled signal)
        CALLS: start_server/stop_server() [USER, backend/api_server.py]
        """
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