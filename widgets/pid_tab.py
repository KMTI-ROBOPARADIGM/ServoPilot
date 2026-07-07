"""PIDTab — Tab 3: PID tuning controls + step-response mini-plot
with live Settling Time & Overshoot metrics panel.

Metrics algorithm:
  A step test sends a fixed +STEP_AMPLITUDE command to the servo.
  Capture window: 0 to CAPTURE_END_OFFSET seconds (closes before return).
  Amplitude is ALWAYS STEP_AMPLITUDE (200 steps) — never computed.
  After the step, we track:
    - Peak overshoot  : max excursion beyond the goal (as % of STEP_AMPLITUDE)
    - Rise time       : time from step command to first goal crossing
    - Settling time   : elapsed time until position stays within ±SETTLE_BAND_PCT
                        of STEP_AMPLITUDE continuously for >= SETTLE_CONFIRM_MS ms
                        (uses confirmation-end time, not first-entry time)
    - SSE (steps)     : mean |pos - goal| over post-settle samples (encoder steps)
"""

import time
from collections import deque
import pyqtgraph as pg
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QGroupBox, QLabel, QSpinBox, QPushButton, QMessageBox,
    QComboBox, QFrame, QSizePolicy,
)
from PySide6.QtCore import Signal, Qt, QTimer

pg.setConfigOptions(antialias=True, background="#0d1117", foreground="#c9d1d9")

# ── Metric / advisor constants — define once, share everywhere ─────────────
STEP_AMPLITUDE      = 200      # encoder steps per step test (fixed, never computed)
STEP_THRESHOLD      = 20       # position delta that counts as a "step command"
CAPTURE_END_OFFSET  = 0.95     # seconds — close capture before return fires
CAPTURE_TIMEOUT_S   = 3.0      # hard fallback timeout
SETTLE_BAND_PCT     = 0.05     # ±5% of STEP_AMPLITUDE = ±10 steps
SETTLE_CONFIRM_MS   = 300      # ms, must stay in band this long
RISE_THRESHOLD_PCT  = 1.0      # 100% of amplitude for rise time detection
OS_THRESHOLD_HIGH   = 15.0     # % — severe overshoot
OS_THRESHOLD_MED    = 5.0      # % — moderate overshoot
OS_THRESHOLD_LOW    = 2.0      # % — well-tuned limit
SSE_THRESHOLD_HIGH  = 10       # steps — large SSE (advisor Rule 7)
SSE_THRESHOLD_MED   = 5        # steps — moderate SSE (advisor Rule 8)
SSE_THRESHOLD_LOW   = 3        # steps — display green/amber boundary
RISE_FAST_S         = 0.5      # seconds — rise time green/amber display boundary
RISE_SLOW_S         = 0.8      # seconds — rise time amber/red display boundary
SETTLE_FAST_MS      = 500      # ms — settling time green/amber display boundary
SETTLE_SLOW_MS      = 800      # ms — settling time amber/red display boundary


class PIDTab(QWidget):
    """PID gain controls + live step-response graph + settling metrics."""

    read_pid_requested   = Signal(int)               # servo_id
    write_pid_requested  = Signal(int, int, int, int)  # id, P, I, D
    step_test_requested  = Signal(int, int)           # servo_id, delta

    WINDOW_S = 10.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self._servo_id = -1
        self._pos_buf  = deque(maxlen=5000)
        self._goal_buf = deque(maxlen=5000)
        self._graph_t0 = time.monotonic()  # base time for graph X-axis only

        # ── Step-response dedicated buffers (relative time from step trigger) ──
        self._step_pos_buf  = deque(maxlen=2000)
        self._step_goal_buf = deque(maxlen=2000)
        self._step_t0       = None   # set when step test fires (monotonic)
        self._step_active   = False  # True while step response mode is on

        # ── Active gains (last written/read — what the servo is actually using) ──
        self._active_gains  = (32, 0, 16)   # (P, I, D) — defaults
        self._spinboxes_unwritten = False

        # ── Capture state (all reset by _reset_capture_state) ──
        self._capture_t0         = None    # time.perf_counter() at step command
        self._pre_step_pos       = None    # position BEFORE step command
        self._capture_goal       = None    # target position
        self._capture_direction  = None    # +1 or -1
        self._capture_active     = False   # True during capture window
        self._capture_end_time   = None    # t0 + CAPTURE_END_OFFSET
        self._crossed_goal       = False
        self._crossing_count     = 0
        self._os_max_steps       = 0.0
        self._t_rise             = None    # elapsed seconds to first goal crossing
        self._in_band_since      = None    # perf_counter when entered settle band
        self._settled            = False
        self._t_settle           = None    # elapsed seconds when settle confirmed
        self._post_settle_samples = []
        self._metrics_finalized  = False
        self._prev_pos           = None    # for crossing detection

        # Final computed metric values (set by _finalize_metrics)
        self._final_os_pct      = None
        self._final_rise_s      = None
        self._final_settle_ms   = None
        self._final_sse         = None
        self._final_reason      = None
        self._metric_error_msg  = None     # set if sanity check fails

        # ── Capture timeout timer ──
        self._capture_timer = QTimer(self)
        self._capture_timer.setSingleShot(True)
        self._capture_timer.timeout.connect(lambda: self._finalize_metrics("timeout"))

        self._build_ui()
        self._reset_capture_state()

    # ── UI Build ───────────────────────────────────────────────────────

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(12)

        # ─ Left: PID controls ────────────────────────────────────────
        left = QVBoxLayout()
        left.setSpacing(8)

        title = QLabel("PID Gain Tuning")
        title.setStyleSheet(
            "color: #58a6ff; font-size: 14px; font-weight: bold; letter-spacing: 1px;"
        )
        left.addWidget(title)

        # ── Servo selector ───────────────────────────────────────────
        servo_box = QGroupBox("Target Servo")
        servo_row = QHBoxLayout(servo_box)
        servo_row.setContentsMargins(8, 6, 8, 6)

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
        self._info_lbl.setStyleSheet(
            "color: #8b949e; font-size: 11px; margin-left: 6px;"
        )
        servo_row.addWidget(self._info_lbl)

        left.addWidget(servo_box)

        # ── Description ──────────────────────────────────────────────
        desc = QLabel(
            "Adjust P/I/D gains and write directly to the servo's EEPROM. "
            "Changes take effect immediately and persist across power cycles.\n"
            "Note: On the ST3215, PID registers are EEPROM-only — all writes are permanent."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #8b949e; font-size: 11px;")
        left.addWidget(desc)

        # ── Gain spinboxes ───────────────────────────────────────────
        gain_box = QGroupBox("Gain Values")
        gain_grid = QGridLayout(gain_box)
        gain_grid.setColumnStretch(1, 1)

        self._p_spin = QSpinBox(); self._p_spin.setRange(0, 255); self._p_spin.setValue(32)
        self._i_spin = QSpinBox(); self._i_spin.setRange(0, 255); self._i_spin.setValue(0)
        self._d_spin = QSpinBox(); self._d_spin.setRange(0, 255); self._d_spin.setValue(16)

        for row, (lbl, spin, tip) in enumerate([
            ("P — Proportional", self._p_spin, "Higher P = faster response, may oscillate"),
            ("I — Integral",     self._i_spin, "Higher I = reduces steady-state error, may overshoot"),
            ("D — Derivative",   self._d_spin, "Higher D = dampens oscillation, reduces overshoot"),
        ]):
            l = QLabel(lbl)
            l.setStyleSheet("color: #c9d1d9; font-weight: bold;")
            t = QLabel(tip)
            t.setStyleSheet("color: #8b949e; font-size: 10px;")
            gain_grid.addWidget(l,    row * 2,     0)
            gain_grid.addWidget(spin, row * 2,     1)
            gain_grid.addWidget(t,    row * 2 + 1, 0, 1, 2)

        # ── Sync indicator — shows whether spinbox values match hardware ──
        self._sync_indicator = QLabel("✓ Synced")
        self._sync_indicator.setStyleSheet(
            "color: #2ea043; background: #0d1117; border: 1px solid #2ea043;"
            " border-radius: 3px; padding: 2px 8px; font-size: 10px; font-weight: bold;"
        )
        gain_grid.addWidget(self._sync_indicator, 6, 0, 1, 2)

        left.addWidget(gain_box)

        # ── Connect spinbox change signals for unwritten tracking ──
        self._p_spin.valueChanged.connect(self._on_spinbox_changed)
        self._i_spin.valueChanged.connect(self._on_spinbox_changed)
        self._d_spin.valueChanged.connect(self._on_spinbox_changed)

        # ── Action buttons ───────────────────────────────────────────
        btn_box = QGroupBox("Actions")
        btn_v = QVBoxLayout(btn_box)

        self._read_btn = QPushButton("📖  Read from Servo")
        self._read_btn.setToolTip("Read the current P/I/D values stored on the selected servo")
        self._read_btn.clicked.connect(self._read_pid)
        btn_v.addWidget(self._read_btn)

        self._write_btn = QPushButton("💾  Write to Servo  (saved to EEPROM)")
        self._write_btn.setObjectName("btn_danger")
        self._write_btn.setToolTip(
            "Permanently saves P/I/D values to the servo's EEPROM.\n"
            "Values are applied immediately and survive power cycles.\n"
            "On ST3215, PID registers (addr 21/22/23) are EEPROM-only."
        )
        self._write_btn.clicked.connect(self._write_pid)
        btn_v.addWidget(self._write_btn)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color: #30363d; margin: 2px 0;")
        btn_v.addWidget(sep)

        self._defaults_btn = QPushButton("↺  Restore Defaults  (P=32 I=0 D=16)")
        self._defaults_btn.setObjectName("btn_flat")
        self._defaults_btn.setToolTip("Reset spinboxes to factory defaults. Does NOT write to servo.")
        self._defaults_btn.clicked.connect(self._restore_defaults)
        btn_v.addWidget(self._defaults_btn)

        left.addWidget(btn_box)
        left.addStretch()

        root.addLayout(left, stretch=1)

        # ─ Right: step-response plot + metrics ───────────────────────
        right_v = QVBoxLayout()
        right_v.setSpacing(6)

        # ── Graph ────────────────────────────────────────────────────
        plot_box = QGroupBox("Step Response (live)")
        plot_v = QVBoxLayout(plot_box)

        self._plot = pg.PlotWidget()
        self._plot.setLabel("left", "Position (steps)")
        self._plot.setLabel("bottom", "Time (s)")
        self._plot.showGrid(x=True, y=True, alpha=0.25)
        self._plot.addLegend(offset=(10, 10))
        self._plot.setMouseEnabled(x=True, y=True)

        self._curve_pos  = self._plot.plot(
            [], [], pen=pg.mkPen("#00ff88", width=2.5), name="Actual"
        )
        self._curve_goal = self._plot.plot(
            [], [], pen=pg.mkPen("#ffd700", width=2, style=Qt.DashLine), name="Goal"
        )

        # Goal line (horizontal dashed gold) — shown during step test
        self._goal_hline = pg.InfiniteLine(
            pos=0, angle=0,
            pen=pg.mkPen("#ffd700", width=1.5, style=Qt.DashLine),
            movable=False,
        )
        self._goal_hline.setVisible(False)
        self._plot.addItem(self._goal_hline)

        # Settle band region (shown after step detected)
        self._settle_region = pg.LinearRegionItem(
            values=[0, 0], orientation="horizontal",
            brush=pg.mkBrush(40, 180, 100, 25),
            pen=pg.mkPen("#28a745", width=1, style=Qt.DotLine),
            movable=False,
        )
        self._settle_region.setVisible(False)
        self._plot.addItem(self._settle_region)

        # Capture-end vertical line (red dashed at x = CAPTURE_END_OFFSET)
        self._capture_end_vline = pg.InfiniteLine(
            pos=CAPTURE_END_OFFSET, angle=90,
            pen=pg.mkPen("#f85149", width=1, style=Qt.DashLine),
            movable=False,
        )
        self._capture_end_vline.setVisible(False)
        self._plot.addItem(self._capture_end_vline)

        plot_v.addWidget(self._plot)

        btn_row = QHBoxLayout()
        clr_btn = QPushButton("Clear Plot")
        clr_btn.setObjectName("btn_flat")
        clr_btn.clicked.connect(self._clear_plot)
        btn_row.addWidget(clr_btn)

        self._step_test_btn = QPushButton("▶  Trigger Step Test (+200 steps)")
        self._step_test_btn.setObjectName("btn_warn")
        self._step_test_btn.setToolTip(
            "Sends goal +200 steps from current position, then returns after 1 s.\n"
            "Forces a measurable step response to evaluate PID quality."
        )
        self._step_test_btn.setEnabled(False)
        self._step_test_btn.clicked.connect(self._trigger_step_test)
        btn_row.addWidget(self._step_test_btn)

        plot_v.addLayout(btn_row)
        right_v.addWidget(plot_box, stretch=3)

        # ── Metrics panel ─────────────────────────────────────────────
        metrics_box = QGroupBox("Step Response Metrics")
        metrics_grid = QGridLayout(metrics_box)
        metrics_grid.setContentsMargins(12, 10, 12, 10)
        metrics_grid.setVerticalSpacing(6)
        metrics_grid.setHorizontalSpacing(16)

        # Header labels
        for col, hdr in enumerate(["Metric", "Value", "Status"]):
            lbl = QLabel(hdr)
            lbl.setStyleSheet("color: #58a6ff; font-weight: bold; font-size: 11px;")
            metrics_grid.addWidget(lbl, 0, col)

        hsep = QFrame()
        hsep.setFrameShape(QFrame.HLine)
        hsep.setStyleSheet("color: #30363d;")
        metrics_grid.addWidget(hsep, 1, 0, 1, 3)

        def _metric_row(grid, row, label_text):
            lbl = QLabel(label_text)
            lbl.setStyleSheet("color: #c9d1d9; font-size: 11px;")
            val = QLabel("—")
            val.setStyleSheet("color: #8b949e; font-family: Consolas; font-size: 12px; font-weight: bold;")
            val.setMinimumWidth(90)
            badge = QLabel("waiting…")
            badge.setStyleSheet(
                "color: #484f58; background: #161b22; border: 1px solid #30363d;"
                " border-radius: 3px; padding: 1px 6px; font-size: 10px;"
            )
            grid.addWidget(lbl,   row, 0)
            grid.addWidget(val,   row, 1)
            grid.addWidget(badge, row, 2)
            return val, badge

        # Four metric rows: Overshoot, Rise Time, Settling Time, SSE
        self._overshoot_val,  self._overshoot_badge  = _metric_row(metrics_grid, 2, "Peak Overshoot")
        self._rise_val,       self._rise_badge        = _metric_row(metrics_grid, 3, "Rise Time")
        self._settle_val,     self._settle_badge      = _metric_row(metrics_grid, 4, "Settling Time")
        self._sse_val,        self._sse_badge          = _metric_row(metrics_grid, 5, "SSE (steps)")

        hint = QLabel("Metrics update automatically after a goal position step ≥ 20 steps.")
        hint.setStyleSheet("color: #484f58; font-size: 10px;")
        hint.setWordWrap(True)
        metrics_grid.addWidget(hint, 6, 0, 1, 3)

        right_v.addWidget(metrics_box, stretch=1)

        # ── Tuning Advisor panel ──────────────────────────────────────
        self._advisor_box = self._build_advisor_panel()
        right_v.addWidget(self._advisor_box)

        container = QWidget()
        container.setLayout(right_v)
        root.addWidget(container, stretch=2)

    # ── Advisor panel builder ─────────────────────────────────────────

    def _build_advisor_panel(self) -> "QGroupBox":
        """Build and return the Tuning Advisor group box."""
        box = QGroupBox("🔧  Tuning Advisor")
        box.setToolTip(
            "Automatically analyses the last step response and suggests"
            " approximate P/I/D adjustments. Click \"Apply\" to stage the"
            " suggested values into the spinboxes — you still need to"
            " click \"Write to Servo\" to save them."
        )
        layout = QVBoxLayout(box)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(6)

        self._advisor_label = QLabel("Run a step test to receive tuning suggestions.")
        self._advisor_label.setWordWrap(True)
        self._advisor_label.setStyleSheet(
            "color: #8b949e; font-size: 11px; line-height: 1.5;"
        )
        layout.addWidget(self._advisor_label)

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

    def set_pre_step_pos(self, pos: int):
        """Called by main_window BEFORE the step command is sent to hardware.
        Captures the servo's actual position at the moment of the step trigger."""
        self._pre_step_pos = pos

    def set_active_gains(self, p: int, i: int, d: int):
        """Called when gains are confirmed read from or written to hardware."""
        self._active_gains = (p, i, d)
        self._spinboxes_unwritten = False
        self._update_sync_indicator()

    def begin_capture(self, pre_step_pos: int, goal: int):
        """Start metric capture. Called BEFORE goal write by main_window.

        This is the ONLY entry point for metric capture. It resets all
        state and begins the capture window.

        Args:
            pre_step_pos: Servo position read BEFORE the step command.
            goal: Target position (pre_step_pos + STEP_AMPLITUDE).
        """
        # Block re-trigger if capture in progress
        if self._capture_active and not self._metrics_finalized:
            return

        # Reset all capture state
        self._reset_capture_state()

        # Set capture parameters
        self._pre_step_pos      = pre_step_pos
        self._capture_goal      = goal
        self._capture_direction = 1 if goal > pre_step_pos else -1
        self._capture_t0        = time.perf_counter()
        self._capture_end_time  = self._capture_t0 + CAPTURE_END_OFFSET
        self._capture_active    = True
        self._prev_pos          = pre_step_pos

        # Show graph markers
        self._goal_hline.setValue(goal)
        self._goal_hline.setVisible(True)
        band = SETTLE_BAND_PCT * STEP_AMPLITUDE  # = 10 steps
        self._settle_region.setRegion((goal - band, goal + band))
        self._settle_region.setVisible(True)
        self._capture_end_vline.setVisible(False)  # shown after capture ends

        # Start timeout timer
        self._capture_timer.start(int(CAPTURE_TIMEOUT_S * 1000))

        # Update display to "in transit" state
        self._update_metric_display()

    # ── Telemetry handler ─────────────────────────────────────────────

    def update_telemetry(self, servo_id: int, data: dict, goal_pos: int = None):
        if servo_id != self._servo_id:
            return
        t = time.monotonic() - self._graph_t0
        pos = data.get("position", 0)
        self._pos_buf.append((t, pos))
        if goal_pos is not None:
            self._goal_buf.append((t, goal_pos))

        # ── Process metric capture if active ──
        self._process_capture(pos)

        # ── Step-response mode: relative time from step trigger ──
        if self._step_active and self._step_t0 is not None:
            t_rel = time.monotonic() - self._step_t0
            self._step_pos_buf.append((t_rel, pos))
            if goal_pos is not None:
                self._step_goal_buf.append((t_rel, goal_pos))

            # Plot step response data
            if self._step_pos_buf:
                xs = [p[0] for p in self._step_pos_buf if p[0] <= 3.5]
                ys = [p[1] for p in self._step_pos_buf if p[0] <= 3.5]
                self._curve_pos.setData(xs, ys)

            if self._step_goal_buf:
                xs = [p[0] for p in self._step_goal_buf if p[0] <= 3.5]
                ys = [p[1] for p in self._step_goal_buf if p[0] <= 3.5]
                self._curve_goal.setData(xs, ys)

            # Fixed X range 0–3.0s per spec
            self._plot.setXRange(0, CAPTURE_TIMEOUT_S, padding=0)

            # Auto-scale Y with 15% padding
            all_ys = ([p[1] for p in self._step_pos_buf] +
                      [p[1] for p in self._step_goal_buf])
            if all_ys:
                y_lo, y_hi = min(all_ys), max(all_ys)
                span = max(y_hi - y_lo, 20)
                pad = span * 0.15
                mid  = (y_lo + y_hi) / 2
                self._plot.setYRange(mid - span / 2 - pad, mid + span / 2 + pad, padding=0)
        else:
            # ── Normal sliding-window mode ───────────────────────────
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
        # Block spinbox change signals while setting programmatically
        self._p_spin.blockSignals(True)
        self._i_spin.blockSignals(True)
        self._d_spin.blockSignals(True)
        self._p_spin.setValue(p)
        self._i_spin.setValue(i)
        self._d_spin.setValue(d)
        self._p_spin.blockSignals(False)
        self._i_spin.blockSignals(False)
        self._d_spin.blockSignals(False)
        # Also update active gains since this is called on read from hardware
        self._active_gains = (p, i, d)
        self._spinboxes_unwritten = False
        self._update_sync_indicator()
        if self._servo_id >= 0:
            self._info_lbl.setText(f"ID: {self._servo_id}  ✓ P={p} I={i} D={d}")

    # ── Spinbox change tracking ──────────────────────────────────────

    def _on_spinbox_changed(self):
        """Called when any gain spinbox value changes by user interaction."""
        current = (self._p_spin.value(), self._i_spin.value(), self._d_spin.value())
        self._spinboxes_unwritten = (current != self._active_gains)
        self._update_sync_indicator()

    def _update_sync_indicator(self):
        """Update the sync indicator label to show whether spinboxes match hardware."""
        if self._spinboxes_unwritten:
            self._sync_indicator.setText("⚠ Not Written")
            self._sync_indicator.setStyleSheet(
                "color: #e3b341; background: #0d1117; border: 1px solid #e3b341;"
                " border-radius: 3px; padding: 2px 8px; font-size: 10px; font-weight: bold;"
            )
        else:
            self._sync_indicator.setText("✓ Synced")
            self._sync_indicator.setStyleSheet(
                "color: #2ea043; background: #0d1117; border: 1px solid #2ea043;"
                " border-radius: 3px; padding: 2px 8px; font-size: 10px; font-weight: bold;"
            )

    # ══════════════════════════════════════════════════════════════════
    # METRIC CAPTURE ENGINE — rewritten from scratch
    # ══════════════════════════════════════════════════════════════════

    def _reset_capture_state(self):
        """Reset all capture / metric state. Called on clear, servo change, new test."""
        self._capture_t0         = None
        self._pre_step_pos       = None
        self._capture_goal       = None
        self._capture_direction  = None
        self._capture_active     = False
        self._capture_end_time   = None
        self._crossed_goal       = False
        self._crossing_count     = 0
        self._os_max_steps       = 0.0
        self._t_rise             = None
        self._in_band_since      = None
        self._settled            = False
        self._t_settle           = None
        self._post_settle_samples = []
        self._metrics_finalized  = False
        self._prev_pos           = None

        self._final_os_pct       = None
        self._final_rise_s       = None
        self._final_settle_ms    = None
        self._final_sse          = None
        self._final_reason       = None
        self._metric_error_msg   = None

        self._settle_region.setVisible(False)
        self._goal_hline.setVisible(False)
        self._capture_end_vline.setVisible(False)
        self._suggested_pid = None
        self._update_metric_display()

    def _process_capture(self, pos: int):
        """Process one telemetry sample for the active capture window.

        Called on every telemetry tick. Does nothing if capture is not active.
        Uses time.perf_counter() for all timing — independent of graph time base.
        Amplitude is ALWAYS STEP_AMPLITUDE (200) — never computed from positions.
        """
        if not self._capture_active:
            return
        if self._metrics_finalized:
            return

        now = time.perf_counter()

        # Close capture window BEFORE return command fires
        if now > self._capture_end_time:
            self._finalize_metrics("window_closed")
            return

        # Hard timeout fallback
        if now - self._capture_t0 > CAPTURE_TIMEOUT_S:
            self._finalize_metrics("timeout")
            return

        t_elapsed = now - self._capture_t0

        # ── RISE TIME — detect first crossing of goal ────────────────
        if not self._crossed_goal:
            if self._capture_direction * (pos - self._capture_goal) >= 0:
                self._crossed_goal   = True
                self._crossing_count = 1
                self._t_rise         = t_elapsed
        else:
            # Count subsequent crossings (oscillation detection)
            if self._prev_pos is not None:
                prev_past = self._capture_direction * (self._prev_pos - self._capture_goal) >= 0
                curr_past = self._capture_direction * (pos - self._capture_goal) >= 0
                if prev_past != curr_past:
                    self._crossing_count += 1

        # ── OVERSHOOT — only track after first goal crossing ─────────
        if self._crossed_goal:
            excursion = self._capture_direction * (pos - self._capture_goal)
            if excursion > self._os_max_steps:
                self._os_max_steps = excursion

        # ── SETTLING — check if within band ──────────────────────────
        settle_band = SETTLE_BAND_PCT * STEP_AMPLITUDE  # = 10 steps
        distance_from_goal = abs(pos - self._capture_goal)

        if distance_from_goal <= settle_band:
            if self._in_band_since is None:
                self._in_band_since = now
            else:
                time_in_band_ms = (now - self._in_band_since) * 1000
                if time_in_band_ms >= SETTLE_CONFIRM_MS:
                    if not self._settled:
                        self._settled  = True
                        # BUG 4 FIX: Use confirmation-END time, not first-entry time
                        self._t_settle = now - self._capture_t0
        else:
            # Left the band — reset confirmation window
            self._in_band_since = None

        # ── POST-SETTLE SAMPLES for SSE ──────────────────────────────
        if self._settled:
            self._post_settle_samples.append(abs(pos - self._capture_goal))
            if len(self._post_settle_samples) >= 3:
                self._finalize_metrics("settled")
                self._prev_pos = pos
                return

        self._prev_pos = pos
        self._update_metric_display()

    def _finalize_metrics(self, reason: str):
        """Compute and store final metric values. Called exactly once per capture.

        reason: "settled" | "window_closed" | "timeout"
        """
        if self._metrics_finalized:
            return
        self._metrics_finalized = True
        self._capture_active    = False
        self._capture_timer.stop()

        # Show capture-end vertical line on graph
        self._capture_end_vline.setVisible(True)

        # ── OVERSHOOT — always divide by STEP_AMPLITUDE, never computed ──
        os_pct = (self._os_max_steps / STEP_AMPLITUDE) * 100.0

        # ── SANITY CHECK — physically impossible values ──────────────
        if os_pct > 200.0:
            self._metric_error_msg = (
                f"Overshoot {os_pct:.1f}% is physically impossible. "
                "Amplitude computation error. Retrigger step test."
            )
            self._update_metric_display()
            return

        # ── RISE TIME ────────────────────────────────────────────────
        self._final_os_pct = os_pct
        self._final_rise_s = self._t_rise  # None if undershoot

        # ── SETTLING TIME ────────────────────────────────────────────
        if self._settled and self._t_settle is not None:
            self._final_settle_ms = self._t_settle * 1000.0
        elif reason == "window_closed":
            self._final_settle_ms = None  # did not settle on outbound leg
        else:
            self._final_settle_ms = CAPTURE_TIMEOUT_S * 1000.0  # timeout

        # ── SSE ──────────────────────────────────────────────────────
        if len(self._post_settle_samples) >= 3:
            self._final_sse = sum(self._post_settle_samples) / len(self._post_settle_samples)
        else:
            self._final_sse = None  # insufficient post-settle data

        self._final_reason = reason
        self._update_metric_display()

        # Fire advisor after 200ms for deliberate feel
        QTimer.singleShot(200, self._refresh_advisor)

    def _show_metric_error(self, msg: str):
        """Display a metric computation error across all metric rows."""
        self._metric_error_msg = msg
        self._update_metric_display()

    # ── Metric display ────────────────────────────────────────────────

    def _update_metric_display(self):
        """Refresh the four metric label+badge pairs.

        Three states:
        1. Error detected     → all rows show error
        2. Finalized OK       → show _final_* values
        3. Capture active     → show running progress
        4. Idle (no capture)  → show "—" / "waiting…"
        """
        # ── Helper for styling ──
        def _set_row(val_lbl, badge_lbl, val_text, val_color, badge_text, badge_color):
            val_lbl.setText(val_text)
            val_lbl.setStyleSheet(
                f"color: {val_color}; font-family: Consolas; font-size: 12px; font-weight: bold;"
            )
            badge_lbl.setText(badge_text)
            badge_lbl.setStyleSheet(
                f"color: {badge_color}; background: #161b22; border: 1px solid {badge_color};"
                " border-radius: 3px; padding: 1px 6px; font-size: 10px;"
            )

        def _set_row_waiting(val_lbl, badge_lbl):
            _set_row(val_lbl, badge_lbl, "—", "#8b949e", "waiting…", "#484f58")

        def _set_row_active(val_lbl, badge_lbl, val_text, badge_text):
            _set_row(val_lbl, badge_lbl, val_text, "#58a6ff", badge_text, "#58a6ff")

        # ── STATE 1: Metric error ────────────────────────────────────
        if self._metric_error_msg is not None:
            _set_row(self._overshoot_val, self._overshoot_badge,
                     "ERROR", "#f85149", "metric error", "#f85149")
            _set_row(self._rise_val, self._rise_badge,
                     "ERROR", "#f85149", "metric error", "#f85149")
            _set_row(self._settle_val, self._settle_badge,
                     "ERROR", "#f85149", "retrigger", "#f85149")
            _set_row(self._sse_val, self._sse_badge,
                     "ERROR", "#f85149", "retrigger", "#f85149")
            return

        # ── STATE 2: Metrics finalized ───────────────────────────────
        if self._metrics_finalized and self._final_os_pct is not None:
            timeout_suffix = " (timeout)" if self._final_reason == "timeout" else ""

            # — Overshoot —
            pct = self._final_os_pct
            if pct < OS_THRESHOLD_LOW:
                color, status = "#2ea043", "✓ nominal"
            elif pct < OS_THRESHOLD_MED:
                color, status = "#2ea043", "✓ low"
            elif pct < OS_THRESHOLD_HIGH:
                color, status = "#e3b341", "⚠ moderate"
            else:
                color, status = "#f85149", "✗ high"
            _set_row(self._overshoot_val, self._overshoot_badge,
                     f"{pct:.1f} %{timeout_suffix}", color, status, color)

            # — Rise Time —
            if self._final_rise_s is not None:
                rt = self._final_rise_s
                if rt < RISE_FAST_S:
                    color, status = "#2ea043", "✓ fast"
                elif rt < RISE_SLOW_S:
                    color, status = "#e3b341", "⚠ moderate"
                else:
                    color, status = "#f85149", "✗ slow"
                _set_row(self._rise_val, self._rise_badge,
                         f"{rt:.3f} s{timeout_suffix}", color, status, color)
            else:
                # Undershoot — servo never reached goal
                _set_row(self._rise_val, self._rise_badge,
                         "N/A", "#e3b341", "undershoot", "#e3b341")

            # — Settling Time —
            if self._final_settle_ms is not None:
                ms = self._final_settle_ms
                if ms < SETTLE_FAST_MS:
                    color, status = "#2ea043", "✓ fast"
                elif ms < SETTLE_SLOW_MS:
                    color, status = "#e3b341", "⚠ moderate"
                else:
                    color, status = "#f85149", "✗ slow"
                _set_row(self._settle_val, self._settle_badge,
                         f"{ms:.0f} ms{timeout_suffix}", color, status, color)
            else:
                _set_row(self._settle_val, self._settle_badge,
                         "—", "#f85149", "did not settle", "#f85149")

            # — SSE —
            if self._final_sse is not None:
                sse = self._final_sse
                if sse < SSE_THRESHOLD_LOW:
                    color, status = "#2ea043", "✓ good"
                elif sse < SSE_THRESHOLD_HIGH:
                    color, status = "#e3b341", "⚠ moderate"
                else:
                    color, status = "#f85149", "✗ high"
                _set_row(self._sse_val, self._sse_badge,
                         f"{sse:.1f} steps{timeout_suffix}", color, status, color)
            else:
                _set_row(self._sse_val, self._sse_badge,
                         "< 3 samples", "#e3b341", "⚠ insufficient", "#e3b341")
            return

        # ── STATE 3: Capture active (show running progress) ──────────
        if self._capture_active:
            # Overshoot — show running value if goal crossed
            if self._crossed_goal:
                running_pct = (self._os_max_steps / STEP_AMPLITUDE) * 100.0
                if running_pct < OS_THRESHOLD_MED:
                    color = "#2ea043"
                elif running_pct < OS_THRESHOLD_HIGH:
                    color = "#e3b341"
                else:
                    color = "#f85149"
                _set_row(self._overshoot_val, self._overshoot_badge,
                         f"{running_pct:.1f} %", color, "measuring…", "#58a6ff")
            else:
                _set_row_active(self._overshoot_val, self._overshoot_badge,
                                "moving…", "in transit")

            # Rise — show time if crossed, else "rising…"
            if self._t_rise is not None:
                _set_row(self._rise_val, self._rise_badge,
                         f"{self._t_rise:.3f} s", "#2ea043", "✓ crossed", "#2ea043")
            else:
                _set_row_active(self._rise_val, self._rise_badge,
                                "rising…", "in transit")

            # Settling — show if settled, else "settling…"
            if self._settled and self._t_settle is not None:
                ms = self._t_settle * 1000.0
                _set_row(self._settle_val, self._settle_badge,
                         f"{ms:.0f} ms", "#2ea043", "✓ settled", "#2ea043")
            else:
                _set_row_active(self._settle_val, self._settle_badge,
                                "settling…", "in progress")

            # SSE — show "measuring…" if settled, else "—"
            if self._settled:
                _set_row_active(self._sse_val, self._sse_badge,
                                "measuring…", "in progress")
            else:
                _set_row_waiting(self._sse_val, self._sse_badge)
            return

        # ── STATE 4: Idle ────────────────────────────────────────────
        _set_row_waiting(self._overshoot_val, self._overshoot_badge)
        _set_row_waiting(self._rise_val,      self._rise_badge)
        _set_row_waiting(self._settle_val,    self._settle_badge)
        _set_row_waiting(self._sse_val,       self._sse_badge)

    # ══════════════════════════════════════════════════════════════════
    # TUNING ADVISOR — first-match-only rules with sanity check
    # ══════════════════════════════════════════════════════════════════

    def _compute_suggestions(self) -> dict | None:
        """Analyse step-response metrics and return concrete PID advice.

        Gate: returns None unless metrics are finalized with valid values.
        Uses _active_gains (hardware values), NOT spinbox values.

        Rules are evaluated in order — FIRST matching rule fires, rest skipped.
        Interaction guard: never increase P when overshoot > OS_THRESHOLD_MED.

        Returns a dict with keys:
            new_p, new_i, new_d  — suggested gains
            message              — rule message
            highlight_p/i/d      — booleans for which gains changed
            changed              — list of changed gain names
        Or None if metrics aren't ready.
        """
        if not self._metrics_finalized:
            return None
        if self._metric_error_msg is not None:
            return None  # don't advise on bad data

        os_pct = self._final_os_pct
        rise_s = self._final_rise_s     # None if undershoot
        settle_ms = self._final_settle_ms
        sse_steps = self._final_sse     # None if insufficient data
        crossings = self._crossing_count

        if os_pct is None:
            return None

        # Read gains from hardware (NOT spinboxes)
        p, i, d = self._active_gains
        new_p, new_i, new_d = p, i, d
        reason = None
        changed = []

        # ── Helper: proportional delta (min 2, clamped) ──
        def pdelta(val: int, factor: float) -> int:
            return max(int(val * factor), 2)

        # ── UNDERSHOOT SPECIAL CASE ──────────────────────────────────
        if rise_s is None:
            # Servo never reached goal — pure undershoot
            delta_p = max(int(p * 0.30), 5)
            new_p = min(p + delta_p, 254)
            return {
                "new_p": new_p, "new_i": i, "new_d": d,
                "message": "Servo did not reach goal — increase P significantly",
                "highlight_p": new_p != p, "highlight_i": False, "highlight_d": False,
                "changed": ["P"] if new_p != p else [],
            }

        # ── RULES 1–6: First match only (elif chain) ────────────────

        # Rule 1: Oscillation (≥3 crossings + high OS)
        if crossings >= 3 and os_pct > OS_THRESHOLD_HIGH:
            delta_p = pdelta(p, 0.20)
            delta_d = pdelta(d, 0.25)
            new_p = max(p - delta_p, 1)
            new_d = min(d + delta_d, 254)
            reason = "Oscillation detected — reduce P, increase D"
            changed = ["P", "D"]

        # Rule 2: Fast approach + high OS → increase D only
        elif os_pct > OS_THRESHOLD_HIGH and rise_s < 0.30:
            delta_d = pdelta(d, 0.25)
            new_d = min(d + delta_d, 254)
            new_p = p  # P unchanged
            reason = "Fast approach, weak damping — increase D"
            changed = ["D"]

        # Rule 3: General high OS (rise_s >= 0.30)
        elif os_pct > OS_THRESHOLD_HIGH:
            delta_p = pdelta(p, 0.15)
            delta_d = pdelta(d, 0.20)
            new_p = max(p - delta_p, 1)
            new_d = min(d + delta_d, 254)
            reason = "General over-gain — reduce P, increase D"
            changed = ["P", "D"]

        # Rule 4: Moderate overshoot (MED < os <= HIGH)
        elif os_pct > OS_THRESHOLD_MED:
            delta_d = pdelta(d, 0.12)
            new_d = min(d + delta_d, 254)
            new_p = p  # P unchanged
            reason = "Moderate overshoot — increase D"
            changed = ["D"]

        # Rule 5: Sluggish response (INTERACTION GUARD: skip if OS > MED)
        elif rise_s > 0.80 and os_pct <= OS_THRESHOLD_MED:
            delta_p = pdelta(p, 0.20)
            new_p = min(p + delta_p, 254)
            reason = "Sluggish response — increase P"
            changed = ["P"]

        # Rule 6: Slightly slow (INTERACTION GUARD: skip if OS > MED)
        elif 0.35 < rise_s <= 0.80 and os_pct <= OS_THRESHOLD_MED:
            delta_p = pdelta(p, 0.12)
            new_p = min(p + delta_p, 254)
            reason = "Slightly slow — increase P"
            changed = ["P"]

        # ── RULES 7–8: SSE rules (only if sse_steps available) ───────
        # These can fire IN ADDITION to rules 1-4, but NOT alongside 5-6
        # (because rules 5-6 only fire when OS <= MED, and if SSE is also
        # high then we should address P first, not I)
        if reason is None and sse_steps is not None:
            # Rule 7: Large SSE
            if sse_steps > SSE_THRESHOLD_HIGH:
                new_i = min(i + 2, 10)
                reason = "Large steady-state error — increase I"
                changed = ["I"]
            # Rule 8: Moderate SSE
            elif sse_steps > SSE_THRESHOLD_MED:
                new_i = min(i + 1, 10)
                reason = "Minor residual error — increase I"
                changed = ["I"]

        # ── RULE 9: No rule matched — well-tuned ────────────────────
        if reason is None:
            reason = "Response is well-tuned — no changes needed"
            changed = []

        return {
            "new_p": new_p, "new_i": new_i, "new_d": new_d,
            "message": reason,
            "highlight_p": new_p != p, "highlight_i": new_i != i, "highlight_d": new_d != d,
            "changed": changed,
        }

    def _refresh_advisor(self):
        """Update the advisor panel after metrics are finalized."""
        # During transient: stable message, no advice yet
        if self._capture_active and not self._metrics_finalized:
            self._advisor_label.setText(
                "<span style='color:#58a6ff'>⏳ Waiting for step response…"
                "  Advice will appear once all metrics are computed.</span>"
            )
            self._advisor_apply_btn.setEnabled(False)
            self._suggested_pid = None
            return

        # If metric error occurred, show error and no suggestion
        if self._metric_error_msg is not None:
            self._advisor_label.setText(
                f"<span style='color:#f85149'>⚠ {self._metric_error_msg}</span><br>"
                "<span style='color:#8b949e'>No gain suggestion — retrigger step test.</span>"
            )
            self._advisor_label.setStyleSheet("color: #f85149; font-size: 11px;")
            self._advisor_apply_btn.setEnabled(False)
            self._suggested_pid = None
            return

        suggestion = self._compute_suggestions()

        if suggestion is None:
            self._advisor_label.setText("Run a step test to receive tuning suggestions.")
            self._advisor_label.setStyleSheet("color: #8b949e; font-size: 11px;")
            self._advisor_apply_btn.setEnabled(False)
            self._suggested_pid = None
            return

        p, i, d = self._active_gains
        new_p = suggestion["new_p"]
        new_i = suggestion["new_i"]
        new_d = suggestion["new_d"]
        message = suggestion["message"]

        any_change = (new_p, new_i, new_d) != (p, i, d)

        lines = []

        # Current gains
        lines.append(f"<b>Current:</b>&nbsp;&nbsp; P={p}&nbsp;&nbsp; I={i}&nbsp;&nbsp; D={d}")

        # Suggested gains (with highlighting)
        if any_change:
            p_str = f"<b style='color:#ffd700'>{new_p}</b>" if suggestion["highlight_p"] else str(new_p)
            i_str = f"<b style='color:#ffd700'>{new_i}</b>" if suggestion["highlight_i"] else str(new_i)
            d_str = f"<b style='color:#ffd700'>{new_d}</b>" if suggestion["highlight_d"] else str(new_d)
            lines.append(f"<b>Suggested:</b>&nbsp;&nbsp; P={p_str}&nbsp;&nbsp; I={i_str}&nbsp;&nbsp; D={d_str}")
        else:
            lines.append("<b>Suggested:</b>&nbsp;&nbsp; No changes needed")

        # Reason
        lines.append(f"<b>Reason:</b>&nbsp;&nbsp; {message}")

        self._advisor_label.setText("<br>".join(lines))

        if not any_change:
            self._advisor_label.setStyleSheet("color: #2ea043; font-size: 11px;")
        else:
            self._advisor_label.setStyleSheet("color: #c9d1d9; font-size: 11px;")

        if any_change:
            self._suggested_pid = (new_p, new_i, new_d)
            self._advisor_apply_btn.setEnabled(True)
        else:
            self._suggested_pid = None
            self._advisor_apply_btn.setEnabled(False)

    def _apply_suggestion(self):
        """Load the suggested P/I/D into the spinboxes."""
        if self._suggested_pid is None:
            return
        p, i, d = self._suggested_pid
        self._p_spin.setValue(p)
        self._i_spin.setValue(i)
        self._d_spin.setValue(d)
        self._advisor_apply_btn.setEnabled(False)
        self._advisor_label.setText(
            f"<b style='color:#2ea043'>✔ Staged: P={p}  I={i}  D={d}</b><br>"
            "<span style='color:#8b949e'>Click "
            "<b>Write to Servo (saved to EEPROM)</b> to commit.</span>"
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
            self._graph_t0 = time.monotonic()
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
            p = self._p_spin.value()
            i = self._i_spin.value()
            d = self._d_spin.value()
            self.write_pid_requested.emit(self._servo_id, p, i, d)
            # Update active gains on successful write
            self._active_gains = (p, i, d)
            self._spinboxes_unwritten = False
            self._update_sync_indicator()

    def _restore_defaults(self):
        self._p_spin.setValue(32)
        self._i_spin.setValue(0)
        self._d_spin.setValue(16)

    def _trigger_step_test(self):
        """Emit a +STEP_AMPLITUDE goal, then return after 1 s."""
        if self._servo_id < 0:
            QMessageBox.information(self, "No Servo", "Select a servo in the dropdown first.")
            return

        # Block re-trigger if capture in progress
        if self._capture_active and not self._metrics_finalized:
            self.statusBar().showMessage("⚠ Step test already in progress", 3000) if hasattr(self, 'statusBar') else None
            return

        # Check for unwritten gains before testing
        if self._spinboxes_unwritten:
            msg = QMessageBox(self)
            msg.setWindowTitle("Gains Not Written")
            msg.setText(
                "Spinbox values differ from servo hardware.\n"
                "Write gains before testing, or the advisor\n"
                "will analyze the wrong response."
            )
            msg.setIcon(QMessageBox.Warning)
            write_test_btn = msg.addButton("Write && Test", QMessageBox.AcceptRole)
            test_anyway_btn = msg.addButton("Test Anyway", QMessageBox.ActionRole)
            cancel_btn = msg.addButton("Cancel", QMessageBox.RejectRole)
            msg.setDefaultButton(cancel_btn)
            msg.exec()

            clicked = msg.clickedButton()
            if clicked == cancel_btn:
                return
            elif clicked == write_test_btn:
                # Write gains first, then proceed to test
                p = self._p_spin.value()
                i = self._i_spin.value()
                d = self._d_spin.value()
                self.write_pid_requested.emit(self._servo_id, p, i, d)
                self._active_gains = (p, i, d)
                self._spinboxes_unwritten = False
                self._update_sync_indicator()
            # else: test_anyway_btn — proceed without writing

        # Reset the step response graph before firing
        self._reset_step_plot()

        # Emit signal — main_window handles read→compute→write sequence
        self.step_test_requested.emit(self._servo_id, STEP_AMPLITUDE)
        self._step_test_btn.setEnabled(False)
        QTimer.singleShot(1200, lambda: self._step_test_btn.setEnabled(self._servo_id >= 0))

    def _reset_step_plot(self):
        """Clear step response plot and enter step response mode."""
        self._step_pos_buf.clear()
        self._step_goal_buf.clear()
        self._step_t0 = time.monotonic()
        self._step_active = True
        self._curve_pos.setData([], [])
        self._curve_goal.setData([], [])
        self._goal_hline.setVisible(False)
        self._settle_region.setVisible(False)
        self._capture_end_vline.setVisible(False)
        self._reset_capture_state()

        # Auto-exit step response mode after capture timeout + margin
        QTimer.singleShot(int((CAPTURE_TIMEOUT_S + 2.0) * 1000), self._exit_step_mode)

    def _exit_step_mode(self):
        """Return to normal sliding-window plot mode after step test completes."""
        self._step_active = False

    def _clear_plot(self):
        self._pos_buf.clear()
        self._goal_buf.clear()
        self._step_pos_buf.clear()
        self._step_goal_buf.clear()
        self._step_active = False
        self._curve_pos.setData([], [])
        self._curve_goal.setData([], [])
        self._goal_hline.setVisible(False)
        self._capture_end_vline.setVisible(False)
        self._capture_timer.stop()
        self._reset_capture_state()