"""PIDTab — Tab 3: PID tuning controls + step-response mini-plot
with live Settling Time & Overshoot metrics panel.

FILE: widgets/pid_tab.py
PURPOSE: Provides PID gain editors (P/I/D spinboxes mapped to ST3215 EEPROM
         registers 21/22/23), a step-response test button, a live step-response
         pyqtgraph mini-plot, and automatic metrics (overshoot, settling time,
         steady-state error). Also includes auto-tuning suggestions.
CALLED BY: main_window._build_central() → PIDTab()
EMITS SIGNALS: read_pid_requested(int), write_pid_requested(int, int, int, int),
               step_test_requested(int, int)
               — consumed by main_window._wire_widgets
KEY METHODS:
  • __init__           — builds PID controls, plot, metrics [USER-DEFINED]
  • add_servo(id)      — add servo to dropdown [CALLED BY: main_window._on_servos_found]
  • set_servo(id)      — select active servo [CALLED BY: main_window._on_servo_selected]
  • set_pid_values     — populate P/I/D spinboxes [CALLED BY: backend.pid_values signal]
  • update_telemetry   — feed step-response plot [CALLED BY: main_window._on_telemetry]
  • clear_servos()     — reset on disconnect [CALLED BY: main_window._on_disconnected]
USES: pyqtgraph.PlotWidget, QSpinBox, deque, numpy [pyqtgraph/PySide6/stdlib]

Metrics algorithm:
  A "step event" is detected when goal_position changes by > STEP_THRESHOLD steps.
  After a step, we track:
    - Peak overshoot  : max excursion beyond the goal (as % of step amplitude)
    - Settling time   : elapsed time until position stays within ±SETTLE_BAND_PCT
                        of the step size continuously for >= SETTLE_MIN_DURATION s
    - Steady-state err: mean |pos - goal| over the last SS_WINDOW_S seconds once settled
"""

import time
from collections import deque
import pyqtgraph as pg
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QGroupBox, QLabel, QSpinBox, QPushButton, QMessageBox,
    QComboBox, QFrame, QSizePolicy, QScrollArea, QTextEdit,
)
from PySide6.QtCore import Signal, Qt, QTimer

pg.setConfigOptions(antialias=True, background="#0d1117", foreground="#c9d1d9")

# ── Metric algorithm constants ─────────────────────────────────────────────────
STEP_THRESHOLD    = 20       # positions steps that count as a "step command"
SETTLE_BAND_PCT   = 0.05     # ±5 % of step amplitude = settled band
SETTLE_MIN_STEPS  = 3        # minimum band width in steps regardless of amplitude
SETTLE_DURATION   = 0.30     # seconds position must stay in band to be "settled"
SS_WINDOW_S       = 1.0      # seconds of data to average for steady-state error
CAPTURE_TIMEOUT_S = 3.0      # force-finalize metrics after 3 s regardless

# ── Strict success criteria (shared between metrics display AND advisor) ────
OS_THRESHOLD      = 2.0      # overshoot < 2.0%
RISE_THRESHOLD    = 0.50     # rise time <= 0.50s
SETTLE_THRESHOLD  = 1.00     # settling time <= 1.0s
SSE_THRESHOLD     = 1.0      # steady-state error <= 1 step


class PIDTab(QWidget):
    """PID gain controls + live step-response graph + settling metrics."""

    read_pid_requested   = Signal(int)               # servo_id
    write_pid_requested  = Signal(int, int, int, int)  # id, P, I, D
    step_test_requested  = Signal(int, int)           # servo_id, position

    WINDOW_S = 10.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self._servo_id = -1
        self._pos_buf  = deque(maxlen=5000)
        self._goal_buf = deque(maxlen=5000)
        self._t0       = time.monotonic()
        self._pre_step_pos: int | None = None   # position from previous telemetry tick
        self._spinboxes_unwritten = False
        self._active_gains = (32, 0, 16)
        self._build_ui()
        self._reset_metrics_state()
        # Advisor iteration memory (persists across step tests / clear_plot)
        self._prev_metrics: dict | None = None
        self._prev_suggestion: dict | None = None
        self._i_increase_count = 0
        self._prev_sse: float | None = None

    # ── UI Build ───────────────────────────────────────────────────────

    def _build_ui(self):
        from PySide6.QtWidgets import QSplitter
        
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        
        main_h_splitter = QSplitter(Qt.Horizontal)
        left_v_splitter = QSplitter(Qt.Vertical)
        right_v_splitter = QSplitter(Qt.Vertical)
        
        # Prevent accidental collapse of any block
        main_h_splitter.setChildrenCollapsible(False)
        left_v_splitter.setChildrenCollapsible(False)
        right_v_splitter.setChildrenCollapsible(False)
        
        main_h_splitter.addWidget(left_v_splitter)
        main_h_splitter.addWidget(right_v_splitter)
        root.addWidget(main_h_splitter)

        # ── Block 1: PID Values & Controls (scrollable) ─────────────
        b1 = QGroupBox("Block 1 — PID Values and Controls")
        b1.setStyleSheet("QGroupBox { font-weight: bold; border: 1px solid #30363d; border-radius: 4px; margin-top: 1ex; } QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 3px; color: #58a6ff; }")
        b1.setMinimumSize(200, 150)
        b1.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        b1_outer = QVBoxLayout(b1)
        b1_outer.setContentsMargins(0, 14, 0, 0)
        b1_outer.setSpacing(0)

        # Wrap all Block 1 content in a scroll area so it never pushes Block 3
        b1_scroll = QScrollArea()
        b1_scroll.setWidgetResizable(True)
        b1_scroll.setFrameShape(QFrame.NoFrame)
        b1_scroll.setStyleSheet(
            "QScrollArea { background: transparent; }"
            "QScrollBar:vertical { width: 6px; }"
        )
        b1_inner = QWidget()
        b1_layout = QVBoxLayout(b1_inner)
        b1_layout.setContentsMargins(10, 4, 10, 8)
        b1_layout.setSpacing(6)
        
        # Servo selector
        servo_box = QWidget()
        servo_row = QHBoxLayout(servo_box)
        servo_row.setContentsMargins(0, 0, 0, 0)
        
        servo_icon = QLabel("🎯")
        servo_icon.setStyleSheet("font-size: 14px; padding-right: 4px;")
        servo_row.addWidget(servo_icon)
        
        self._servo_combo = QComboBox()
        self._servo_combo.setMinimumWidth(140)
        self._servo_combo.setToolTip("Select which servo to read/write PID gains for")
        self._servo_combo.addItem("— no servos found —", -1)
        self._servo_combo.currentIndexChanged.connect(self._on_combo_changed)
        servo_row.addWidget(self._servo_combo, stretch=1)
        
        self._info_lbl = QLabel("No servo selected")
        self._info_lbl.setStyleSheet("color: #8b949e; font-size: 11px; margin-left: 6px;")
        self._info_lbl.setWordWrap(True)
        self._info_lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        servo_row.addWidget(self._info_lbl)
        b1_layout.addWidget(servo_box)
        
        # Description
        desc = QLabel(
            "Adjust P/I/D gains and write to EEPROM. "
            "Changes persist across power cycles."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #8b949e; font-size: 11px;")
        desc.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        b1_layout.addWidget(desc)
        
        # Spinboxes — Fixed size so they never influence splitter
        gain_grid = QGridLayout()
        gain_grid.setColumnStretch(1, 1)
        
        self._p_spin = QSpinBox(); self._p_spin.setRange(0, 255); self._p_spin.setValue(32)
        self._i_spin = QSpinBox(); self._i_spin.setRange(0, 255); self._i_spin.setValue(0)
        self._d_spin = QSpinBox(); self._d_spin.setRange(0, 255); self._d_spin.setValue(16)
        
        for spin in (self._p_spin, self._i_spin, self._d_spin):
            spin.setFixedWidth(80)
            spin.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        
        for row, (lbl, spin, tip) in enumerate([
            ("P — Proportional", self._p_spin, "Higher P = faster response, may oscillate"),
            ("I — Integral",     self._i_spin, "Higher I = reduces steady-state error, may overshoot"),
            ("D — Derivative",   self._d_spin, "Higher D = dampens oscillation, reduces overshoot"),
        ]):
            l = QLabel(lbl)
            l.setStyleSheet("color: #c9d1d9; font-weight: bold;")
            l.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            t = QLabel(tip)
            t.setStyleSheet("color: #8b949e; font-size: 10px;")
            t.setWordWrap(True)
            t.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            gain_grid.addWidget(l,    row * 2,     0)
            gain_grid.addWidget(spin, row * 2,     1)
            gain_grid.addWidget(t,    row * 2 + 1, 0, 1, 2)
            
        def _mark_dirty():
            self._spinboxes_unwritten = True
            if hasattr(self, '_sync_indicator'):
                self._sync_indicator.setText("⚠ Not Written")
                self._sync_indicator.setStyleSheet("color: #e3b341; font-weight: bold; font-size: 11px;")
                
        self._p_spin.valueChanged.connect(lambda _: _mark_dirty())
        self._i_spin.valueChanged.connect(lambda _: _mark_dirty())
        self._d_spin.valueChanged.connect(lambda _: _mark_dirty())
        
        b1_layout.addLayout(gain_grid)
        
        # Action Buttons
        btn_row_top = QHBoxLayout()
        self._read_btn = QPushButton("📖  Read from Servo")
        self._read_btn.setToolTip("Read the current P/I/D values stored on the selected servo")
        self._read_btn.clicked.connect(self._read_pid)
        btn_row_top.addWidget(self._read_btn)
        
        self._sync_indicator = QLabel("✓ Synced")
        self._sync_indicator.setStyleSheet("color: #2ea043; font-weight: bold; font-size: 11px;")
        self._sync_indicator.setAlignment(Qt.AlignCenter)
        sp_sync = self._sync_indicator.sizePolicy()
        sp_sync.setRetainSizeWhenHidden(True)
        self._sync_indicator.setSizePolicy(sp_sync)
        btn_row_top.addWidget(self._sync_indicator)
        b1_layout.addLayout(btn_row_top)
        
        self._write_btn = QPushButton("💾  Write to Servo  (EEPROM)")
        self._write_btn.setObjectName("btn_danger")
        self._write_btn.setToolTip("Permanently saves P/I/D values to the servo's EEPROM.\nValues are applied immediately and survive power cycles.")
        self._write_btn.clicked.connect(self._write_pid)
        b1_layout.addWidget(self._write_btn)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color: #30363d; margin: 2px 0;")
        b1_layout.addWidget(sep)

        self._defaults_btn = QPushButton("↺  Restore Defaults  (P=32 I=0 D=16)")
        self._defaults_btn.setObjectName("btn_flat")
        self._defaults_btn.setToolTip("Reset spinboxes to factory defaults. Does NOT write to servo.")
        self._defaults_btn.clicked.connect(self._restore_defaults)
        b1_layout.addWidget(self._defaults_btn)
        
        btn_row = QHBoxLayout()
        clr_btn = QPushButton("Clear Plot")
        clr_btn.setObjectName("btn_flat")
        clr_btn.clicked.connect(self._clear_plot)
        
        self._step_test_btn = QPushButton("▶  Step Test (+200)")
        self._step_test_btn.setObjectName("btn_warn")
        self._step_test_btn.setEnabled(False)
        self._step_test_btn.clicked.connect(self._trigger_step_test)
        
        btn_row.addWidget(clr_btn)
        btn_row.addWidget(self._step_test_btn)
        b1_layout.addLayout(btn_row)

        b1_scroll.setWidget(b1_inner)
        b1_outer.addWidget(b1_scroll)

        # ── Block 3: Step Response Metrics ──────────────────────────
        b3 = QGroupBox("Block 3 — Step Response Metrics")
        b3.setStyleSheet("QGroupBox { font-weight: bold; border: 1px solid #30363d; border-radius: 4px; margin-top: 1ex; } QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 3px 0 3px; color: #58a6ff; }")
        b3.setMinimumSize(200, 200)
        b3.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        metrics_grid = QGridLayout(b3)
        metrics_grid.setContentsMargins(12, 16, 12, 10)
        metrics_grid.setVerticalSpacing(6)
        metrics_grid.setHorizontalSpacing(16)
        
        for col, hdr in enumerate(["Metric", "Value", "Status"]):
            lbl = QLabel(hdr)
            lbl.setStyleSheet("color: #58a6ff; font-weight: bold; font-size: 11px;")
            lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            metrics_grid.addWidget(lbl, 0, col)
            
        hsep = QFrame()
        hsep.setFrameShape(QFrame.HLine)
        hsep.setStyleSheet("color: #30363d;")
        metrics_grid.addWidget(hsep, 1, 0, 1, 3)
            
        def _metric_row(grid, row, label_text):
            lbl = QLabel(label_text)
            lbl.setStyleSheet("color: #c9d1d9; font-size: 11px;")
            lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            val = QLabel("—")
            val.setStyleSheet("color: #8b949e; font-family: Consolas; font-size: 12px; font-weight: bold;")
            val.setMinimumWidth(90)
            val.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            sp_v = val.sizePolicy()
            sp_v.setRetainSizeWhenHidden(True)
            val.setSizePolicy(sp_v)
            badge = QLabel("waiting…")
            badge.setStyleSheet("color: #484f58; background: #161b22; border: 1px solid #30363d; border-radius: 3px; padding: 1px 6px; font-size: 10px;")
            badge.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
            sp_b = badge.sizePolicy()
            sp_b.setRetainSizeWhenHidden(True)
            badge.setSizePolicy(sp_b)
            grid.addWidget(lbl,   row, 0)
            grid.addWidget(val,   row, 1)
            grid.addWidget(badge, row, 2)
            return val, badge

        self._overshoot_val, self._overshoot_badge = _metric_row(metrics_grid, 2, "Peak Overshoot")
        self._rise_time_val, self._rise_time_badge = _metric_row(metrics_grid, 3, "Rise Time")
        self._settle_val, self._settle_badge       = _metric_row(metrics_grid, 4, "Settling Time")
        self._ss_error_val, self._ss_error_badge   = _metric_row(metrics_grid, 5, "Steady-State Error")
        
        self._overall_status_lbl = QLabel(" waiting…")
        self._overall_status_lbl.setAlignment(Qt.AlignCenter)
        self._overall_status_lbl.setStyleSheet("color: #8b949e; font-size: 14px; margin-top: 6px;")
        self._overall_status_lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        sp = self._overall_status_lbl.sizePolicy()
        sp.setRetainSizeWhenHidden(True)
        self._overall_status_lbl.setSizePolicy(sp)
        metrics_grid.addWidget(self._overall_status_lbl, 6, 0, 1, 3)

        self._failing_metrics_lbl = QLabel("")
        self._failing_metrics_lbl.setAlignment(Qt.AlignCenter)
        self._failing_metrics_lbl.setStyleSheet("color: #f85149; font-size: 11px;")
        self._failing_metrics_lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._failing_metrics_lbl.setWordWrap(True)
        sp2 = self._failing_metrics_lbl.sizePolicy()
        sp2.setRetainSizeWhenHidden(True)
        self._failing_metrics_lbl.setSizePolicy(sp2)
        metrics_grid.addWidget(self._failing_metrics_lbl, 7, 0, 1, 3)
        
        # Target criteria reference
        ref = QLabel(f"Target: OS<{OS_THRESHOLD}% | Rise≤{RISE_THRESHOLD}s | Settle≤{SETTLE_THRESHOLD}s | SSE≤{int(SSE_THRESHOLD)}")
        ref.setStyleSheet("color: #8b949e; font-size: 10px; margin-top: 3px;")
        ref.setAlignment(Qt.AlignCenter)
        ref.setWordWrap(True)
        ref.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        metrics_grid.addWidget(ref, 8, 0, 1, 3)

        # ── Block 2: Step Response Live Graph ───────────────────────
        b2 = QGroupBox("Block 2 — Step Response Graph")
        b2.setStyleSheet("QGroupBox { font-weight: bold; border: 1px solid #30363d; border-radius: 4px; margin-top: 1ex; } QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 3px 0 3px; color: #58a6ff; }")
        b2.setMinimumSize(200, 150)
        b2.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        b2_layout = QVBoxLayout(b2)
        b2_layout.setContentsMargins(2, 16, 2, 2)
        
        self._plot = pg.PlotWidget()
        self._plot.setLabel("left", "Position (steps)")
        self._plot.setLabel("bottom", "Time (s)")
        self._plot.showGrid(x=True, y=True, alpha=0.25)
        self._plot.addLegend(offset=(10, 10))
        self._plot.enableAutoRange(axis=pg.ViewBox.XAxis, enable=True)
        self._plot.enableAutoRange(axis=pg.ViewBox.YAxis, enable=True)
        self._plot.setMouseEnabled(x=True, y=True)
        self._plot.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        
        self._curve_pos = self._plot.plot([], [], pen=pg.mkPen("#00ff88", width=2.5), name="Actual")
        self._curve_goal = self._plot.plot([], [], pen=pg.mkPen("#ffd700", width=2, style=Qt.DashLine), name="Goal")
        
        self._settle_region = pg.LinearRegionItem(values=[0, 0], orientation="horizontal", brush=pg.mkBrush(40, 180, 100, 25), pen=pg.mkPen("#28a745", width=1, style=Qt.DotLine), movable=False)
        self._settle_region.setVisible(False)
        self._plot.addItem(self._settle_region)
        
        self._goal_line = pg.InfiniteLine(pos=0, angle=0, pen=pg.mkPen("#ffd700", width=1.5, style=Qt.DashDotLine), movable=False)
        self._goal_line.setVisible(False)
        self._plot.addItem(self._goal_line)
        
        b2_layout.addWidget(self._plot)

        # ── Block 4: Tuning Advisor ─────────────────────────────
        b4 = self._build_advisor_panel()

        # Add to splitters
        left_v_splitter.addWidget(b1)
        left_v_splitter.addWidget(b3)
        right_v_splitter.addWidget(b2)
        right_v_splitter.addWidget(b4)
        
        # Initial proportions: 65/35 left (Block1/Block3), 55/45 right (Block2/Block4)
        main_h_splitter.setSizes([500, 500])
        left_v_splitter.setSizes([420, 280])
        right_v_splitter.setSizes([360, 340])
        
        # Store references — never call setSizes() outside __init__
        self._main_h_splitter = main_h_splitter
        self._left_v_splitter = left_v_splitter
        self._right_v_splitter = right_v_splitter

    # ── Advisor panel builder ─────────────────────────────────────────

    def _build_advisor_panel(self) -> "QGroupBox":
        """Build and return the Tuning Advisor group box."""
        box = QGroupBox("Block 4 — Tuning Advisor")
        box.setStyleSheet("QGroupBox { font-weight: bold; border: 1px solid #30363d; border-radius: 4px; margin-top: 1ex; } QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 3px 0 3px; color: #58a6ff; }")
        box.setMinimumSize(200, 220)
        box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        box.setToolTip(
            "Automatically analyses the last step response and suggests"
            " approximate P/I/D adjustments. Click \"Apply\" to stage the"
            " suggested values into the spinboxes — you still need to"
            " click \"Write to Servo\" to save them."
        )
        layout = QVBoxLayout(box)
        layout.setContentsMargins(12, 16, 12, 10)
        layout.setSpacing(6)

        # Read-only QTextEdit: expands inside block, never pushes splitter
        self._advisor_text = QTextEdit()
        self._advisor_text.setReadOnly(True)
        self._advisor_text.setHtml(
            "<span style='color:#8b949e; font-size:11px;'>"
            "Run a step test to receive tuning suggestions.</span>"
        )
        self._advisor_text.setStyleSheet(
            "QTextEdit { background: transparent; border: none;"
            " color: #c9d1d9; font-size: 11px; }"
        )
        self._advisor_text.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._advisor_text.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        layout.addWidget(self._advisor_text, stretch=1)

        self._confidence_label = QLabel("")
        self._confidence_label.setStyleSheet(
            "color: #484f58; font-size: 10px; margin-top: 2px;"
        )
        self._confidence_label.setVisible(False)
        self._confidence_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        sp = self._confidence_label.sizePolicy()
        sp.setRetainSizeWhenHidden(True)
        self._confidence_label.setSizePolicy(sp)
        layout.addWidget(self._confidence_label)

        # Stretch pushes the Apply button to the bottom of Block 4
        layout.addStretch()

        self._advisor_apply_btn = QPushButton("Apply Suggestion to Spinboxes")
        self._advisor_apply_btn.setObjectName("btn_flat")
        self._advisor_apply_btn.setEnabled(False)
        self._advisor_apply_btn.setToolTip(
            "Loads the suggested P/I/D values into the spinboxes above.\n"
            "You must still click \"Write to Servo\" to save them to the servo."
        )
        self._advisor_apply_btn.clicked.connect(self._apply_suggestion)
        layout.addWidget(self._advisor_apply_btn)

        # Stores the last computed suggestion (p, i, d) or None
        self._suggested_pid: tuple | None = None
        return box

    # ── Public API ────────────────────────────────────────────────────

    def set_servo(self, servo_id: int):
        if self._servo_combo.currentData() == -1:
            self._select_servo_in_combo(servo_id)

    def add_servo(self, servo_id: int):
        for i in range(self._servo_combo.count()):
            if self._servo_combo.itemData(i) == servo_id:
                return
        if self._servo_combo.count() == 1 and self._servo_combo.itemData(0) == -1:
            self._servo_combo.clear()
        self._servo_combo.addItem(f"Servo #{servo_id}", servo_id)
        if self._servo_combo.count() == 1:
            self._servo_combo.setCurrentIndex(0)

    def clear_servos(self):
        self._servo_combo.clear()
        self._servo_combo.addItem("— no servos found —", -1)
        self._servo_id = -1
        self._info_lbl.setText("No servo selected")
        self._step_test_btn.setEnabled(False)
        self._clear_plot()

    def update_telemetry(self, servo_id: int, data: dict, goal_pos: int = None):
        """Feed step-response plot with telemetry data.

        THREAD SAFETY: This method is called exclusively from the Qt main thread
        via the signal/slot mechanism (ServoBackend.telemetry_update → MainWindow._on_telemetry
        → PIDTab.update_telemetry). All metric computation therefore runs on the main thread
        with no concurrent access — no locking is required.
        """
        if servo_id != self._servo_id:
            return
        t = time.monotonic() - self._t0
        pos = data.get("position", 0)
        self._pos_buf.append((t, pos))
        if goal_pos is not None:
            self._goal_buf.append((t, goal_pos))
            self._detect_and_track_step(t, pos, goal_pos)
        # Update _pre_step_pos AFTER detection uses it — holds previous tick's pos
        self._pre_step_pos = pos

        # ── Sliding window ───────────────────────────────────────────
        t_min = t - self.WINDOW_S

        if self._pos_buf:
            xs = [p[0] for p in self._pos_buf if p[0] >= t_min]
            ys = [p[1] for p in self._pos_buf if p[0] >= t_min]
            self._curve_pos.setData(xs, ys)

        if self._goal_buf:
            xs = [p[0] for p in self._goal_buf if p[0] >= t_min]
            ys = [p[1] for p in self._goal_buf if p[0] >= t_min]
            self._curve_goal.setData(xs, ys)

        self._plot.setXRange(max(0.0, t - self.WINDOW_S), t + 0.5, padding=0)

        all_ys = ([p[1] for p in self._pos_buf if p[0] >= t_min] +
                  [p[1] for p in self._goal_buf if p[0] >= t_min])
        if all_ys:
            y_lo, y_hi = min(all_ys), max(all_ys)
            span = max(y_hi - y_lo, 20)
            mid  = (y_lo + y_hi) / 2
            self._plot.setYRange(mid - span / 2 - 5, mid + span / 2 + 5, padding=0)

    def set_pid_values(self, p: int, i: int, d: int):
        self._p_spin.blockSignals(True)
        self._i_spin.blockSignals(True)
        self._d_spin.blockSignals(True)
        self._p_spin.setValue(p)
        self._i_spin.setValue(i)
        self._d_spin.setValue(d)
        self._p_spin.blockSignals(False)
        self._i_spin.blockSignals(False)
        self._d_spin.blockSignals(False)
        self._spinboxes_unwritten = False
        self._active_gains = (p, i, d)
        if hasattr(self, '_sync_indicator'):
            self._sync_indicator.setText("✓ Synced")
            self._sync_indicator.setStyleSheet("color: #2ea043; font-weight: bold; font-size: 11px;")
        if self._servo_id >= 0:
            self._info_lbl.setText(f"ID: {self._servo_id}  ✓ P={p} I={i} D={d}")

    # ── Step metrics engine ───────────────────────────────────────────

    def _reset_metrics_state(self, preserve_last_goal: bool = False):
        """Reset all step tracking state (called on clear / servo change)."""
        if not preserve_last_goal:
            self._last_goal       = None   # last known goal position
        self._step_start_t        = None   # time of last step event
        self._step_start_pos      = None   # actual position at step time
        self._step_goal           = None   # new goal after step
        self._step_amp            = None   # |new_goal - pos_at_step|
        self._step_dir            = 0      # +1 (forward) or -1 (backward)
        # Overshoot/crossing tracking (all measured post-goal-crossing)
        self._crossed_goal        = False  # has the servo first reached the goal?
        self._past_goal           = False  # currently on the overshoot side?
        self._max_overshoot_steps = 0.0    # max steps PAST the goal (true overshoot)
        self._goal_crossings      = 0      # number of times goal line crossed
        self._rise_time_s         = None   # time from 10% to 90% of step amplitude
        self._t_10                = None   # time reached 10% of amplitude
        self._t_90                = None   # time reached 90% of amplitude
        self._min_dist_to_goal    = None   # used for undershoot tracking
        self._capture_timed_out   = False  # True if capture ended via timeout
        # Settle state
        self._settled             = False
        self._settled_since       = None
        self._settle_time_s       = None
        self._ss_error            = None
        self._settle_band         = None

        self._settle_region.setVisible(False)
        self._goal_line.setVisible(False)
        self._suggested_pid  = None
        self._update_metric_display()

    def _finalize_metrics_timeout(self, t: float, pos: int):
        """Force-finalize metrics after capture timeout.
        Does NOT assume the servo crossed the goal — sets overshoot to 0."""
        self._capture_timed_out = True
        self._settled = True
        self._settle_time_s = CAPTURE_TIMEOUT_S
        # Compute SSE from most recent samples
        if self._step_goal is not None and self._pos_buf:
            recent = [p[1] for p in self._pos_buf if p[0] >= t - 0.5]
            if len(recent) >= 2:
                self._ss_error = sum(abs(p - self._step_goal) for p in recent) / len(recent)
            else:
                self._ss_error = abs(pos - self._step_goal)
        self._update_metric_display()
        self._refresh_advisor()

    def on_step_test_started(self):
        """Called by main_window BEFORE a step test goal is written.
        Resets graph to t=0 and clears metrics but preserves _last_goal
        so step detection triggers on the first goal change."""
        self._t0 = time.monotonic()
        self._pos_buf.clear()
        self._goal_buf.clear()
        self._curve_pos.setData([], [])
        self._curve_goal.setData([], [])
        self._reset_metrics_state(preserve_last_goal=True)

    def _detect_and_track_step(self, t: float, pos: int, goal: int):
        """Called every telemetry tick to detect steps and compute metrics."""
        # ── Capture timeout check ─────────────────────────────────────
        if (self._step_start_t is not None
                and not self._settled
                and not self._capture_timed_out
                and (t - self._step_start_t) >= CAPTURE_TIMEOUT_S):
            self._finalize_metrics_timeout(t, pos)
            return

        # ── Step detection ───────────────────────────────────────────
        if self._last_goal is not None:
            delta = abs(goal - self._last_goal)
            if delta >= STEP_THRESHOLD:
                # Use pre-step position (previous tick) for accurate amplitude
                start_pos = self._pre_step_pos if self._pre_step_pos is not None else pos
                # New step — reset all tracking
                self._step_start_t        = t
                self._step_start_pos      = start_pos
                self._step_goal           = goal
                amp = abs(goal - start_pos)
                if amp < STEP_THRESHOLD:
                    # A=0 guard: servo is already near the goal — skip capture
                    self._last_goal = goal
                    return
                self._step_amp            = max(amp, SETTLE_MIN_STEPS)
                self._step_dir            = 1 if goal > start_pos else -1
                self._crossed_goal        = False
                self._past_goal           = False
                self._max_overshoot_steps = 0.0
                self._goal_crossings      = 0
                self._rise_time_s         = None
                self._t_10                = None
                self._t_90                = None
                self._min_dist_to_goal    = None
                self._capture_timed_out   = False
                self._settled             = False
                self._settled_since       = None
                self._settle_time_s       = None
                self._ss_error            = None
                band_half = max(
                    self._step_amp * SETTLE_BAND_PCT,
                    SETTLE_MIN_STEPS,
                )
                self._settle_band = (goal - band_half, goal + band_half)
                self._settle_region.setRegion(self._settle_band)
                self._settle_region.setVisible(True)
                self._goal_line.setValue(goal)
                self._goal_line.setVisible(True)

        self._last_goal = goal

        # ── If no step yet or already finalized, nothing to compute ──
        if self._step_start_t is None or self._capture_timed_out:
            return

        # ── Rise time 10-90% and Undershoot tracking ──────────────────────
        past_signed = self._step_dir * (pos - self._step_goal)   # +ve = past goal
        dist_to_goal = abs(self._step_goal - pos)
        
        if self._min_dist_to_goal is None or dist_to_goal < self._min_dist_to_goal:
            self._min_dist_to_goal = dist_to_goal

        pos_delta = abs(pos - self._step_start_pos)
        pct_complete = pos_delta / self._step_amp
        if self._t_10 is None and pct_complete >= 0.1:
            self._t_10 = t
        if self._t_90 is None and pct_complete >= 0.9:
            self._t_90 = t
            if self._t_10 is not None:
                self._rise_time_s = self._t_90 - self._t_10

        if not self._crossed_goal:
            if past_signed >= 0:
                self._crossed_goal    = True
                self._past_goal       = True
                self._goal_crossings  = 1
        else:
            was_past = self._past_goal
            now_past = past_signed >= 0
            if now_past != was_past:
                self._goal_crossings += 1
            self._past_goal = now_past

        if self._crossed_goal and past_signed > self._max_overshoot_steps:
            self._max_overshoot_steps = past_signed

        # ── Settle tracking ──────────────────────────────────────────
        if not self._settled:
            lo, hi = self._settle_band
            in_band = lo <= pos <= hi
            if in_band:
                if self._settled_since is None:
                    self._settled_since = t
                elif (t - self._settled_since) >= SETTLE_DURATION:
                    self._settled       = True
                    # Record time when 300ms in-band was CONFIRMED, not entry time
                    self._settle_time_s = t - self._step_start_t
            else:
                # Left band — reset settle timer
                self._settled_since = None

        # ── Steady-state error (once settled) ────────────────────────
        if self._settled and self._settled_since is not None:
            ss_cutoff = self._settled_since + SETTLE_DURATION
            ss_window = [
                p[1] for p in self._pos_buf
                if p[0] >= ss_cutoff
            ]
            if len(ss_window) >= 3:
                self._ss_error = sum(abs(p - self._step_goal) for p in ss_window) / len(ss_window)

        self._update_metric_display()
        self._refresh_advisor()

    def _update_metric_display(self):
        """Refresh the metric label+badge pairs according to strict target criteria."""
        failing_metrics = []
        is_moving = False

        def set_badge(val_lbl, badge_lbl, raw_val, text_fmt, is_pass, waiting=False, moving=False):
            if waiting:
                val_lbl.setText("—")
                val_lbl.setStyleSheet("color: #8b949e; font-family: Consolas; font-size: 12px; font-weight: bold;")
                badge_lbl.setText("waiting…")
                badge_lbl.setStyleSheet("color: #484f58; background: #161b22; border: 1px solid #30363d; border-radius: 3px; padding: 1px 6px; font-size: 10px;")
            elif moving:
                val_lbl.setText("moving…")
                val_lbl.setStyleSheet("color: #58a6ff; font-family: Consolas; font-size: 12px; font-weight: bold;")
                badge_lbl.setText("in transit")
                badge_lbl.setStyleSheet("color: #58a6ff; background: #161b22; border: 1px solid #1f6feb; border-radius: 3px; padding: 1px 6px; font-size: 10px;")
            else:
                formatted_str = text_fmt.format(raw_val)
                if is_pass:
                    color, status = "#2ea043", "✓ PASS"
                    val_lbl.setText(f"✓ {formatted_str}")
                else:
                    color, status = "#f85149", "✗ FAIL"
                    val_lbl.setText(f"✗ {formatted_str}")
                val_lbl.setStyleSheet(f"color: {color}; font-family: Consolas; font-size: 12px; font-weight: bold;")
                badge_lbl.setText(status)
                badge_lbl.setStyleSheet(f"color: {color}; background: #161b22; border: 1px solid {color}; border-radius: 3px; padding: 1px 6px; font-size: 10px;")

        # ── Overshoot / Undershoot ────────────────────────────────────────────────
        metric_label = self._overshoot_val.parentWidget().layout().itemAtPosition(2,0).widget()
        if self._step_amp is not None and self._step_amp > 0:
            if self._crossed_goal:
                metric_label.setText("Peak Overshoot")
                pct = (self._max_overshoot_steps / self._step_amp) * 100.0
                passed = pct < OS_THRESHOLD
                if not passed: failing_metrics.append("Overshoot")
                set_badge(self._overshoot_val, self._overshoot_badge, pct, "{:.1f} %", passed)
            else:
                if self._capture_timed_out or self._settled:
                    metric_label.setText("Undershoot")
                    us_pct = (getattr(self, '_min_dist_to_goal', self._step_amp) / self._step_amp) * 100.0
                    passed = False
                    set_badge(self._overshoot_val, self._overshoot_badge, us_pct, "{:.1f} %", passed)
                    self._overshoot_val.setStyleSheet("color: #e3b341; font-family: Consolas; font-size: 12px; font-weight: bold;")
                    self._overshoot_badge.setText("✗ FAIL")
                    self._overshoot_badge.setStyleSheet("color: #e3b341; background: #161b22; border: 1px solid #e3b341; border-radius: 3px; padding: 1px 6px; font-size: 10px;")
                    failing_metrics.append("Undershoot")
                else:
                    metric_label.setText("Peak Overshoot")
                    set_badge(self._overshoot_val, self._overshoot_badge, 0, "", False, False, True)
                    is_moving = True
        else:
            metric_label.setText("Peak Overshoot")
            set_badge(self._overshoot_val, self._overshoot_badge, 0, "", False, True)

        # ── Rise Time ────────────────────────────────────────────────
        if self._rise_time_s is not None:
            passed = self._rise_time_s <= RISE_THRESHOLD
            if not passed: failing_metrics.append("Rise Time")
            set_badge(self._rise_time_val, self._rise_time_badge, self._rise_time_s, "{:.2f} s", passed)
        elif self._step_start_t is not None and not self._capture_timed_out and not self._settled:
            set_badge(self._rise_time_val, self._rise_time_badge, 0, "", False, False, True)
            is_moving = True
        elif self._capture_timed_out or (self._settled and not self._crossed_goal):
            self._rise_time_val.setText("N/A (undershoot)")
            self._rise_time_val.setStyleSheet("color: #e3b341; font-family: Consolas; font-size: 12px; font-weight: bold;")
            self._rise_time_badge.setText("✗ FAIL")
            self._rise_time_badge.setStyleSheet("color: #e3b341; background: #161b22; border: 1px solid #e3b341; border-radius: 3px; padding: 1px 6px; font-size: 10px;")
            failing_metrics.append("Rise Time")
        else:
            set_badge(self._rise_time_val, self._rise_time_badge, 0, "", False, True)

        # ── Settling Time ────────────────────────────────────────────
        if self._settle_time_s is not None and self._settled and not self._capture_timed_out:
            passed = self._settle_time_s <= SETTLE_THRESHOLD
            if not passed: failing_metrics.append("Settling Time")
            set_badge(self._settle_val, self._settle_badge, self._settle_time_s, "{:.2f} s", passed)
        elif self._step_start_t is not None and not self._settled and not self._capture_timed_out:
            set_badge(self._settle_val, self._settle_badge, 0, "", False, False, True)
            is_moving = True
        elif self._capture_timed_out and not self._settled:
            self._settle_val.setText("N/A (did not settle)")
            self._settle_val.setStyleSheet("color: #f85149; font-family: Consolas; font-size: 12px; font-weight: bold;")
            self._settle_badge.setText("✗ FAIL")
            self._settle_badge.setStyleSheet("color: #f85149; background: #161b22; border: 1px solid #f85149; border-radius: 3px; padding: 1px 6px; font-size: 10px;")
            failing_metrics.append("Settling Time")
        elif self._capture_timed_out and self._settled:
            self._settle_val.setText(f"> {CAPTURE_TIMEOUT_S:.1f}s (timeout)")
            self._settle_val.setStyleSheet("color: #f85149; font-family: Consolas; font-size: 12px; font-weight: bold;")
            self._settle_badge.setText("✗ FAIL")
            self._settle_badge.setStyleSheet("color: #f85149; background: #161b22; border: 1px solid #f85149; border-radius: 3px; padding: 1px 6px; font-size: 10px;")
            failing_metrics.append("Settling Time")
        else:
            set_badge(self._settle_val, self._settle_badge, 0, "", False, True)

        # ── Steady-State Error ───────────────────────────────────────
        if self._ss_error is not None:
            passed = self._ss_error <= SSE_THRESHOLD
            if not passed: failing_metrics.append("SS Error")
            set_badge(self._ss_error_val, self._ss_error_badge, self._ss_error, "{:.1f} steps", passed)
        elif self._step_start_t is not None and not self._capture_timed_out:
            set_badge(self._ss_error_val, self._ss_error_badge, 0, "", False, False, True)
            is_moving = True
        else:
            set_badge(self._ss_error_val, self._ss_error_badge, 0, "", False, True)

        # ── Overall Status ───────────────────────────────────────────
        has_run = (self._ss_error is not None) or self._capture_timed_out
        
        if self._step_start_t is None:
            self._overall_status_lbl.setText("waiting for step…")
            self._overall_status_lbl.setStyleSheet("color: #8b949e; font-size: 14px;")
            self._failing_metrics_lbl.setText("")
        elif is_moving:
            self._overall_status_lbl.setText("⏳ Measuring...")
            self._overall_status_lbl.setStyleSheet("color: #e3b341; font-weight: bold; font-size: 14px;")
            self._failing_metrics_lbl.setText("")
        elif has_run:
            if not failing_metrics:
                self._overall_status_lbl.setText("✓ Well-Tuned")
                self._overall_status_lbl.setStyleSheet("color: #2ea043; font-weight: bold; font-size: 14px;")
                self._failing_metrics_lbl.setText("")
            else:
                self._overall_status_lbl.setText("✗ Not Yet Tuned")
                self._overall_status_lbl.setStyleSheet("color: #f85149; font-weight: bold; font-size: 14px;")
                self._failing_metrics_lbl.setText("Failing: " + ", ".join(failing_metrics))

    # ── Tuning Advisor engine ─────────────────────────────────────────

    def _compute_suggestions(self) -> tuple[list[dict], str]:
        if not self._settled and not self._capture_timed_out:
            return [], ""
        if self._step_amp is None or self._step_amp == 0:
            return [], ""
        if self._ss_error is None:
            return [], ""

        p, i, d = getattr(self, '_active_gains', (self._p_spin.value(), self._i_spin.value(), self._d_spin.value()))

        os_pct = 0.0
        us_pct = 0.0
        if self._crossed_goal:
            os_pct = (self._max_overshoot_steps / self._step_amp) * 100.0
        else:
            us_pct = (getattr(self, '_min_dist_to_goal', self._step_amp) / self._step_amp) * 100.0

        st_s = self._settle_time_s
        rt_s = self._rise_time_s
        sse  = self._ss_error

        # Helper to compute scaled P-delta
        def scale_d(base: int) -> int:
            return max(2, base)

        suggestions = []
        failing = False
        if (os_pct >= OS_THRESHOLD or us_pct >= OS_THRESHOLD
                or (rt_s is None or rt_s > RISE_THRESHOLD)
                or (st_s is None or st_s > SETTLE_THRESHOLD)
                or sse > SSE_THRESHOLD):
            failing = True

        if not failing:
            rt_str = f"{rt_s:.2f}s" if rt_s is not None else "n/a"
            st_str = f"{st_s:.2f}s" if st_s is not None else "n/a"
            suggestions.append({
                "symptom": "Response is well-tuned!",
                "icon": "✅", "dp": 0, "di": 0, "dd": 0,
                "why": (
                    f"Overshoot/Undershoot < 2.0% ✓   Rise: {rt_str} ✓   "
                    f"Settling: {st_str} ✓   SS error: {sse:.1f} steps ✓\n"
                    "Current PID values hit all strict targets. No changes needed."
                )
            })
            return suggestions, "high"

        # Rule evaluation
        # Undershoot scenarios
        if not self._crossed_goal:
            if us_pct > 20:
                dp = scale_d(round(p * 0.30))
                suggestions.append({
                    "symptom": f"Large undershoot ({us_pct:.1f}%)", "icon": "🔴", "dp": dp, "di": 0, "dd": -max(1, min(d, 2)),
                    "why": f"Servo fell far short of the target. P is significantly too low.\nRaise P by {dp} (to {min(255, p+dp)})."
                })
            elif us_pct > 5:
                dp = scale_d(round(p * 0.15))
                dd = -min(d, scale_d(round(d * 0.10)))
                suggestions.append({
                    "symptom": f"Moderate undershoot ({us_pct:.1f}%)", "icon": "🟡", "dp": dp, "di": 0, "dd": dd,
                    "why": f"Servo stopped before target. Raise P by {dp} and slightly reduce D to allow faster convergence."
                })
            else:
                dp = 2
                suggestions.append({
                    "symptom": f"Small undershoot ({us_pct:.1f}%)", "icon": "🟡", "dp": dp, "di": 0, "dd": 0,
                    "why": f"Target nearly reached. Small bump to P (+{dp}) will close the gap."
                })
        else:
            # Overshoot scenarios
            if os_pct > 15:
                dp = -min(p-4, scale_d(round(p * 0.15))) if p > 5 else 0
                dd = scale_d(round(d * 0.20))
                suggestions.append({
                    "symptom": f"High overshoot ({os_pct:.1f}%)", "icon": "🔴", "dp": dp, "di": 0, "dd": dd,
                    "why": f"Servo blew past the target. Reduce P (to {p+dp}) and raise D (to {min(255, d+dd)}) for braking."
                })
            elif os_pct >= OS_THRESHOLD:
                dd = scale_d(round(d * 0.15))
                suggestions.append({
                    "symptom": f"Moderate overshoot ({os_pct:.1f}%)", "icon": "🟡", "dp": 0, "di": 0, "dd": dd,
                    "why": f"Slight overshoot. Raise D by {dd} to damp the response."
                })

        # Speed and Settling handling (if not severely undershooting)
        if (us_pct <= 5 and os_pct <= 10):
            if rt_s is None or rt_s > RISE_THRESHOLD:
                dp = scale_d(round(p * 0.10))
                rt_val = f"{rt_s:.2f}s" if rt_s is not None else "N/A"
                if not any(s['dp'] > 0 for s in suggestions): # Avoid conflicting P suggestions
                    suggestions.append({
                        "symptom": f"Slow rise time ({rt_val})", "icon": "🔴", "dp": dp, "di": 0, "dd": -min(d, 1),
                        "why": f"Getting to the target takes >{RISE_THRESHOLD}s. Increase P by {dp} to speed up response."
                    })
        
        # Steady-state error
        if sse > SSE_THRESHOLD and not self._capture_timed_out:
            # Anti-windup protection: check I-increase counter
            if self._i_increase_count >= 3 and sse > 5:
                di = -min(2, i)
                if di < 0:
                    suggestions.append({
                        "symptom": f"Integral windup suspected (I increased {self._i_increase_count}× without improvement)",
                        "icon": "🔴", "dp": 0, "di": di, "dd": 0,
                        "why": f"I has been increased {self._i_increase_count} consecutive times but SSE persists at {sse:.1f} steps. Likely integral windup. Reduce I by {abs(di)}."
                    })
            else:
                di = 1 if i < 10 else 0
                if di > 0:
                    suggestions.append({
                        "symptom": f"Persistent steady-state error ({sse:.1f} steps)", "icon": "🔴", "dp": 0, "di": di, "dd": 0,
                        "why": f"Servo does not rest exactly on target. Raise I by {di} (max 10)."
                    })
                else:
                    suggestions.append({
                        "symptom": f"Steady-state error but I is maxed", "icon": "🟠", "dp": 0, "di": 0, "dd": 0,
                        "why": "I is at safe cap of 10. Consider reducing mechanical friction."
                    })

        # Anti-windup: reset I-increase counter if SSE improved > 20%
        if self._prev_sse is not None and self._prev_sse > 0 and sse is not None:
            sse_improvement = (self._prev_sse - sse) / self._prev_sse
            if sse_improvement > 0.20:
                self._i_increase_count = 0

        # Escalation (Iteration Memory)
        if self._prev_metrics is not None and suggestions:
            prev_os = self._prev_metrics.get("os_pct", 0)
            prev_us = self._prev_metrics.get("us_pct", 0)
            
            for s in suggestions:
                if "overshoot" in s["symptom"].lower() and prev_os >= OS_THRESHOLD and os_pct >= OS_THRESHOLD:
                    improv = (prev_os - os_pct) / prev_os if prev_os > 0 else 1.0
                    if improv < 0.15:
                        for k in ("dp", "di", "dd"):
                            s[k] = round(s[k] * 1.5)
                        s["symptom"] += " ⚡ Escalated"
                        s["why"] += "\n⚡ Less than 15% improvement from last test, applying larger change."
                elif "undershoot" in s["symptom"].lower() and prev_us >= OS_THRESHOLD and us_pct >= OS_THRESHOLD:
                    improv = (prev_us - us_pct) / prev_us if prev_us > 0 else 1.0
                    if improv < 0.15:
                        for k in ("dp", "di", "dd"):
                            s[k] = round(s[k] * 1.5)
                        s["symptom"] += " ⚡ Escalated"
                        s["why"] += "\n⚡ Less than 15% improvement from last test, applying larger change."

        # Keep everything in bounds
        final_suggestions = []
        for s in suggestions:
            s["dp"] = max(-p, min(255 - p, int(s["dp"])))
            s["di"] = max(-i, min(255 - i, int(s["di"])))  
            s["dd"] = max(-d, min(255 - d, int(s["dd"])))
            if s["dp"] != 0 or s["di"] != 0 or s["dd"] != 0 or "maxed" in s["symptom"]:
                final_suggestions.append(s)

        if not final_suggestions and failing:
            final_suggestions.append({
                "symptom": "Metrics failing but no clear tuning direction", "icon": "❓", "dp": 0, "di": 0, "dd": 0,
                "why": "The response fails strict criteria but heuristic bounds prevent further standard PID adjustments."
            })

        self._prev_metrics = {
            "os_pct": os_pct, "us_pct": us_pct, "settle_time_s": st_s,
            "rise_time_s": rt_s, "sse": sse
        }
        self._prev_sse = sse

        # Update I-increase counter for anti-windup
        total_di = sum(s.get("di", 0) for s in final_suggestions)
        if total_di > 0:
            self._i_increase_count += 1
        elif total_di < 0:
            self._i_increase_count = 0

        # Confidence metric
        if not failing:
            conf = "high"
        elif len(final_suggestions) == 1:
            conf = "high" 
        elif len(final_suggestions) > 2:
            conf = "low"
        else:
            conf = "medium"

        return final_suggestions, conf

    def _refresh_advisor(self):
        """Update the advisor panel. Shows 'settling' during transient."""
        # During transient: stable message, no advice yet
        if self._step_start_t is not None and not self._settled:
            self._advisor_text.setHtml(
                "<span style='color:#58a6ff'>⏳ Settling in progress…"
                "  Advice will appear once the response is complete.</span>"
            )
            self._advisor_apply_btn.setEnabled(False)
            self._suggested_pid = None
            return

        suggestions, confidence = self._compute_suggestions()

        if not suggestions:
            self._advisor_text.setHtml(
                "<span style='color:#8b949e; font-size:11px;'>"
                "Run a step test to receive tuning suggestions.</span>"
            )
            self._advisor_text.setStyleSheet(
                "QTextEdit { background: transparent; border: none;"
                " color: #8b949e; font-size: 11px; }"
            )
            self._advisor_apply_btn.setEnabled(False)
            self._confidence_label.setVisible(False)
            self._suggested_pid = None
            return

        # Use _active_gains (actual hardware values) — not spinbox values which may be dirty
        p, i, d = self._active_gains

        total_dp = sum(s["dp"] for s in suggestions)
        total_di = sum(s["di"] for s in suggestions)
        total_dd = sum(s["dd"] for s in suggestions)

        new_p = max(0, min(255, p + total_dp))
        new_i = max(0, min(255, i + total_di))
        new_d = max(0, min(255, d + total_dd))

        any_change = (new_p, new_i, new_d) != (p, i, d)
        all_ok     = (len(suggestions) == 1
                      and total_dp == 0 and total_di == 0 and total_dd == 0)

        lines = []
        for s in suggestions:
            lines.append(f"<b>{s['icon']} {s['symptom']}</b>")
            # Replace newlines in why with <br> for HTML
            why_html = s['why'].replace('\n', '<br>&nbsp;&nbsp;&nbsp;')
            lines.append(f"&nbsp;&nbsp;&nbsp;{why_html}")
            lines.append("")  # spacer

        if any_change:
            p_str = f"<b style='color:#ffd700'>{new_p}</b>" if new_p != p else str(p)
            i_str = f"<b style='color:#ffd700'>{new_i}</b>" if new_i != i else str(i)
            d_str = f"<b style='color:#ffd700'>{new_d}</b>" if new_d != d else str(d)
            delta_str = f"P{total_dp:+d} I{total_di:+d} D{total_dd:+d}"
            lines.append(
                f"<b>▸ Try:</b>  P = {p_str}&nbsp;&nbsp;"
                f"I = {i_str}&nbsp;&nbsp;"
                f"D = {d_str}&nbsp;&nbsp;"
                f"<span style='color:#484f58'>({delta_str})</span>"
            )

        self._advisor_text.setHtml("<br>".join(lines))

        if all_ok:
            self._advisor_text.setStyleSheet(
                "QTextEdit { background: transparent; border: none;"
                " color: #2ea043; font-size: 11px; }"
            )
        else:
            self._advisor_text.setStyleSheet(
                "QTextEdit { background: transparent; border: none;"
                " color: #c9d1d9; font-size: 11px; }"
            )

        if any_change:
            self._suggested_pid = (new_p, new_i, new_d)
            self._advisor_apply_btn.setEnabled(True)
        else:
            self._suggested_pid = None
            self._advisor_apply_btn.setEnabled(False)

        # ── 5C: Confidence display ────────────────────────────────────
        if confidence:
            conf_colors = {
                "high": "#2ea043", "medium": "#e3b341", "low": "#f85149"
            }
            conf_color = conf_colors.get(confidence, "#8b949e")
            self._confidence_label.setText(
                f"Confidence: <b style='color:{conf_color}'>{confidence.capitalize()}</b>"
            )
            self._confidence_label.setStyleSheet(
                f"color: {conf_color}; font-size: 10px; margin-top: 2px;"
            )
            self._confidence_label.setVisible(True)
        else:
            self._confidence_label.setVisible(False)

    def _apply_suggestion(self):
        """Load the suggested P/I/D into the spinboxes."""
        if self._suggested_pid is None:
            return
        p, i, d = self._suggested_pid
        self._p_spin.setValue(p)
        self._i_spin.setValue(i)
        self._d_spin.setValue(d)
        self._advisor_apply_btn.setEnabled(False)
        self._advisor_text.setHtml(
            f"<b style='color:#2ea043'>\u2714 Staged: P={p}  I={i}  D={d}</b><br>"
            "<span style='color:#8b949e'>Click "
            "<b>Write to Servo (EEPROM)</b> to commit.</span>"
        )

    # ── Internals ─────────────────────────────────────────────────────

    def _on_combo_changed(self, index: int):
        sid = self._servo_combo.currentData()
        if sid is None or sid == -1:
            self._servo_id = -1
            self._info_lbl.setText("No servo selected")
            self._step_test_btn.setEnabled(False)
        else:
            self._servo_id = sid
            self._info_lbl.setText(f"ID: {sid}  — reading PID…")
            self._t0 = time.monotonic()
            self._clear_plot()
            self._step_test_btn.setEnabled(True)
            self.read_pid_requested.emit(sid)

    def _select_servo_in_combo(self, servo_id: int):
        for i in range(self._servo_combo.count()):
            if self._servo_combo.itemData(i) == servo_id:
                self._servo_combo.setCurrentIndex(i)
                return

    def _read_pid(self):
        if self._servo_id < 0:
            QMessageBox.information(self, "No Servo", "Select a servo from the dropdown first.")
            return
        self.read_pid_requested.emit(self._servo_id)

    def _write_pid(self):
        if self._servo_id < 0:
            QMessageBox.information(self, "No Servo", "Select a servo from the dropdown first.")
            return
        reply = QMessageBox.question(
            self, "Write PID to EEPROM",
            f"This will permanently save P/I/D gains to Servo #{self._servo_id}.\n\n"
            f"  P (Proportional) = {self._p_spin.value()}\n"
            f"  I (Integral)     = {self._i_spin.value()}\n"
            f"  D (Derivative)   = {self._d_spin.value()}\n\n"
            "Values are stored in EEPROM and survive power cycles.\n"
            "Are you sure?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            p, i, d = self._p_spin.value(), self._i_spin.value(), self._d_spin.value()
            self.write_pid_requested.emit(self._servo_id, p, i, d)
            self._spinboxes_unwritten = False
            self._active_gains = (p, i, d)
            if hasattr(self, '_sync_indicator'):
                self._sync_indicator.setText("✓ Synced")
                self._sync_indicator.setStyleSheet("color: #2ea043; font-weight: bold; font-size: 11px;")

    def _restore_defaults(self):
        self._p_spin.setValue(32)
        self._i_spin.setValue(0)
        self._d_spin.setValue(16)

    def _trigger_step_test(self):
        """Emit a +200-step goal, then return after 1 s."""
        if self._servo_id < 0:
            QMessageBox.information(self, "No Servo", "Select a servo in the dropdown first.")
            return

        if getattr(self, '_spinboxes_unwritten', False):
            msgBox = QMessageBox(self)
            msgBox.setWindowTitle("Unwritten PID Gains")
            msgBox.setText("Your PID values have been changed but not written to the servo.\nThe step test will run with the OLD servo gains, not the values shown in the spinboxes.")
            msgBox.setInformativeText("Click OK to run step test with OLD gains anyway.\nClick Write & Test to write new gains first, then run the step test.")
            btn_run_old = msgBox.addButton("OK (Use Old Gains)", QMessageBox.AcceptRole)
            btn_write_test = msgBox.addButton("Write & Test", QMessageBox.ActionRole)
            btn_cancel = msgBox.addButton(QMessageBox.Cancel)
            msgBox.exec()

            if msgBox.clickedButton() == btn_cancel:
                return
            elif msgBox.clickedButton() == btn_write_test:
                p, i, d = self._p_spin.value(), self._i_spin.value(), self._d_spin.value()
                self.write_pid_requested.emit(self._servo_id, p, i, d)
                self._spinboxes_unwritten = False
                self._active_gains = (p, i, d)
                if hasattr(self, '_sync_indicator'):
                    self._sync_indicator.setText("✓ Synced")
                    self._sync_indicator.setStyleSheet("color: #2ea043; font-weight: bold; font-size: 11px;")

        # Snapshot _active_gains: if user ran with old gains, capture the actual HW values.
        # If they chose Write & Test, _active_gains was already updated above.
        # If spinboxes were NOT dirty (no dialog shown), the last known write values are correct.
        self.on_step_test_started()
        self.step_test_requested.emit(self._servo_id, 200)
        self._step_test_btn.setEnabled(False)
        QTimer.singleShot(1200, lambda: self._step_test_btn.setEnabled(self._servo_id >= 0))

    def _clear_plot(self):
        self._pos_buf.clear()
        self._goal_buf.clear()
        self._curve_pos.setData([], [])
        self._curve_goal.setData([], [])
        self._reset_metrics_state()
