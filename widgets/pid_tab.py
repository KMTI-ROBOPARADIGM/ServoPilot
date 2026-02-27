"""PIDTab — Tab 3: PID tuning controls + step-response mini-plot
with live Settling Time & Overshoot metrics panel.

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
    QComboBox, QFrame, QSizePolicy,
)
from PySide6.QtCore import Signal, Qt, QTimer

pg.setConfigOptions(antialias=True, background="#0d1117", foreground="#c9d1d9")

# ── Metric algorithm constants ─────────────────────────────────────────────────
STEP_THRESHOLD    = 20       # positions steps that count as a "step command"
SETTLE_BAND_PCT   = 0.05     # ±5 % of step amplitude = settled band
SETTLE_MIN_STEPS  = 3        # minimum band width in steps regardless of amplitude
SETTLE_DURATION   = 0.30     # seconds position must stay in band to be "settled"
SS_WINDOW_S       = 1.0      # seconds of data to average for steady-state error


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
        self._build_ui()
        self._reset_metrics_state()

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

        left.addWidget(gain_box)

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
        self._plot.enableAutoRange(axis=pg.ViewBox.XAxis, enable=True)
        self._plot.enableAutoRange(axis=pg.ViewBox.YAxis, enable=True)
        self._plot.setMouseEnabled(x=True, y=True)

        self._curve_pos  = self._plot.plot(
            [], [], pen=pg.mkPen("#00ff88", width=2.5), name="Actual"
        )
        self._curve_goal = self._plot.plot(
            [], [], pen=pg.mkPen("#ffd700", width=2, style=Qt.DashLine), name="Goal"
        )
        # Settle band region (shown after step detected)
        self._settle_region = pg.LinearRegionItem(
            values=[0, 0], orientation="horizontal",
            brush=pg.mkBrush(40, 180, 100, 25),
            pen=pg.mkPen("#28a745", width=1, style=Qt.DotLine),
            movable=False,
        )
        self._settle_region.setVisible(False)
        self._plot.addItem(self._settle_region)

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

        self._overshoot_val,   self._overshoot_badge   = _metric_row(metrics_grid, 2, "Peak Overshoot")
        self._settle_val,      self._settle_badge       = _metric_row(metrics_grid, 3, "Settling Time")
        self._ss_error_val,    self._ss_error_badge     = _metric_row(metrics_grid, 4, "Steady-State Error")

        hint = QLabel("Metrics update automatically after a goal position step ≥ 20 steps.")
        hint.setStyleSheet("color: #484f58; font-size: 10px;")
        hint.setWordWrap(True)
        metrics_grid.addWidget(hint, 5, 0, 1, 3)

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

    def update_telemetry(self, servo_id: int, data: dict, goal_pos: int = None):
        if servo_id != self._servo_id:
            return
        t = time.monotonic() - self._t0
        pos = data.get("position", 0)
        self._pos_buf.append((t, pos))
        if goal_pos is not None:
            self._goal_buf.append((t, goal_pos))
            self._detect_and_track_step(t, pos, goal_pos)

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
        self._p_spin.setValue(p)
        self._i_spin.setValue(i)
        self._d_spin.setValue(d)
        if self._servo_id >= 0:
            self._info_lbl.setText(f"ID: {self._servo_id}  ✓ P={p} I={i} D={d}")

    # ── Step metrics engine ───────────────────────────────────────────

    def _reset_metrics_state(self):
        """Reset all step tracking state (called on clear / servo change)."""
        self._last_goal           = None   # last known goal position
        self._step_start_t        = None   # time of last step event
        self._step_start_pos      = None   # actual position at step time
        self._step_goal           = None   # new goal after step
        self._step_amp            = None   # |new_goal - pos_at_step|
        self._step_dir            = 0      # +1 (forward) or -1 (backward)
        # Overshoot/crossing tracking (all measured post-goal-crossing)
        self._crossed_goal        = False  # has the servo first reached the goal?
        self._past_goal           = False  # currently on the overshoot side?
        self._max_overshoot_steps = 0.0    # max steps PAST the goal (true overshoot)
        self._goal_crossings      = 0      # number of times goal line crossed (0=not yet, 1=first reach, 2+=ringing)
        self._rise_time_s         = None   # time from step to first goal crossing
        # Settle state
        self._settled             = False
        self._settled_since       = None
        self._settle_time_s       = None
        self._ss_error            = None
        self._settle_band         = None

        self._settle_region.setVisible(False)
        self._suggested_pid  = None
        self._update_metric_display()

    def _detect_and_track_step(self, t: float, pos: int, goal: int):
        """Called every telemetry tick to detect steps and compute metrics."""
        # ── Step detection ───────────────────────────────────────────
        if self._last_goal is not None:
            delta = abs(goal - self._last_goal)
            if delta >= STEP_THRESHOLD:
                # New step — reset all tracking
                self._step_start_t        = t
                self._step_start_pos      = pos
                self._step_goal           = goal
                self._step_amp            = max(abs(goal - pos), SETTLE_MIN_STEPS)
                self._step_dir            = 1 if goal > pos else -1
                self._crossed_goal        = False
                self._past_goal           = False
                self._max_overshoot_steps = 0.0
                self._goal_crossings      = 0
                self._rise_time_s         = None
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

        self._last_goal = goal

        # ── If no step yet, nothing to compute ───────────────────────
        if self._step_start_t is None:
            return

        # ── True overshoot + rise time tracking ───────────────────────
        # Only count exceedance PAST the goal AFTER the servo first crosses it.
        # Also track each back-and-forth crossing to detect oscillation.
        past_signed = self._step_dir * (pos - self._step_goal)   # +ve = past goal

        if not self._crossed_goal:
            if past_signed >= 0:
                self._crossed_goal    = True
                self._past_goal       = True
                self._goal_crossings  = 1
                self._rise_time_s     = t - self._step_start_t
        else:
            # Count goal-line crossings (back-and-forth = ringing)
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
                    self._settle_time_s = self._settled_since - self._step_start_t
            else:
                # Left band — reset settle timer
                self._settled_since = None

        # ── Steady-state error (once settled) ────────────────────────
        # Only include samples from AFTER settling was confirmed (avoid
        # contaminating the average with in-transit or pre-settle data).
        if self._settled and self._settled_since is not None:
            ss_cutoff = self._settled_since + SETTLE_DURATION
            ss_window = [
                p[1] for p in self._pos_buf
                if p[0] >= ss_cutoff
            ]
            if len(ss_window) >= 3:  # need at least 3 samples for a meaningful mean
                self._ss_error = sum(abs(p - self._step_goal) for p in ss_window) / len(ss_window)

        self._update_metric_display()
        self._refresh_advisor()

    def _update_metric_display(self):
        """Refresh the three metric label+badge pairs."""
        # ── Overshoot ────────────────────────────────────────────────
        # Show 0% (✓ none) once the goal has been crossed — correct baseline.
        # Show '—' before any step occurs.
        if self._step_amp is not None and self._step_amp > 0:
            if self._crossed_goal:
                pct = (self._max_overshoot_steps / self._step_amp) * 100.0
                self._overshoot_val.setText(f"{pct:.1f} %")
                if pct < 5:
                    color, status = "#2ea043", "✓ none"
                elif pct < 15:
                    color, status = "#e3b341", "⚠ moderate"
                else:
                    color, status = "#f85149", "✗ high"
            else:
                # Servo hasn't reached the goal yet — show transit status
                pct = None
                self._overshoot_val.setText("moving…")
                color, status = "#58a6ff", "in transit"
            self._overshoot_val.setStyleSheet(
                f"color: {color}; font-family: Consolas; font-size: 12px; font-weight: bold;"
            )
            self._overshoot_badge.setText(status)
            self._overshoot_badge.setStyleSheet(
                f"color: {color}; background: #161b22; border: 1px solid {color};"
                " border-radius: 3px; padding: 1px 6px; font-size: 10px;"
            )
        else:
            self._overshoot_val.setText("—")
            self._overshoot_val.setStyleSheet("color: #8b949e; font-family: Consolas; font-size: 12px; font-weight: bold;")
            self._overshoot_badge.setText("waiting…")
            self._overshoot_badge.setStyleSheet("color: #484f58; background: #161b22; border: 1px solid #30363d; border-radius: 3px; padding: 1px 6px; font-size: 10px;")

        # ── Settling time ────────────────────────────────────────────
        if self._settle_time_s is not None:
            self._settle_val.setText(f"{self._settle_time_s:.2f} s")
            if self._settle_time_s < 0.5:
                color, status = "#2ea043", "✓ fast"
            elif self._settle_time_s < 1.5:
                color, status = "#e3b341", "⚠ moderate"
            else:
                color, status = "#f85149", "✗ slow"
            self._settle_val.setStyleSheet(
                f"color: {color}; font-family: Consolas; font-size: 12px; font-weight: bold;"
            )
            self._settle_badge.setText(status)
            self._settle_badge.setStyleSheet(
                f"color: {color}; background: #161b22; border: 1px solid {color};"
                " border-radius: 3px; padding: 1px 6px; font-size: 10px;"
            )
        elif self._step_start_t is not None and not self._settled:
            self._settle_val.setText("settling…")
            self._settle_val.setStyleSheet("color: #58a6ff; font-family: Consolas; font-size: 12px; font-weight: bold;")
            self._settle_badge.setText("in progress")
            self._settle_badge.setStyleSheet("color: #58a6ff; background: #161b22; border: 1px solid #1f6feb; border-radius: 3px; padding: 1px 6px; font-size: 10px;")
        else:
            self._settle_val.setText("—")
            self._settle_val.setStyleSheet("color: #8b949e; font-family: Consolas; font-size: 12px; font-weight: bold;")
            self._settle_badge.setText("waiting…")
            self._settle_badge.setStyleSheet("color: #484f58; background: #161b22; border: 1px solid #30363d; border-radius: 3px; padding: 1px 6px; font-size: 10px;")

        # ── Steady-state error ───────────────────────────────────────
        if self._ss_error is not None:
            self._ss_error_val.setText(f"{self._ss_error:.1f} steps")
            if self._ss_error < 5:
                color, status = "#2ea043", "✓ good"
            elif self._ss_error < 15:
                color, status = "#e3b341", "⚠ moderate"
            else:
                color, status = "#f85149", "✗ high"
            self._ss_error_val.setStyleSheet(
                f"color: {color}; font-family: Consolas; font-size: 12px; font-weight: bold;"
            )
            self._ss_error_badge.setText(status)
            self._ss_error_badge.setStyleSheet(
                f"color: {color}; background: #161b22; border: 1px solid {color};"
                " border-radius: 3px; padding: 1px 6px; font-size: 10px;"
            )
        elif self._settled:
            self._ss_error_val.setText("computing…")
            self._ss_error_val.setStyleSheet("color: #58a6ff; font-family: Consolas; font-size: 12px; font-weight: bold;")
            self._ss_error_badge.setText("in progress")
            self._ss_error_badge.setStyleSheet("color: #58a6ff; background: #161b22; border: 1px solid #1f6feb; border-radius: 3px; padding: 1px 6px; font-size: 10px;")
        else:
            self._ss_error_val.setText("—")
            self._ss_error_val.setStyleSheet("color: #8b949e; font-family: Consolas; font-size: 12px; font-weight: bold;")
            self._ss_error_badge.setText("waiting…")
            self._ss_error_badge.setStyleSheet("color: #484f58; background: #161b22; border: 1px solid #30363d; border-radius: 3px; padding: 1px 6px; font-size: 10px;")

    # ── Tuning Advisor engine ─────────────────────────────────────────

    def _compute_suggestions(self) -> list[dict]:
        """
        Analyse SETTLED step-response metrics and emit concrete, tested PID advice.

        Gate: returns [] unless fully settled and SS-error has enough samples.

        ── Key metrics used ──

        os_pct        : % of step size the servo went PAST the goal (true overshoot).
        rise_time_s   : time from step command to first goal crossing.
                        Short rise + high OS   → fast approach, D too low to brake.
                        Long rise + low OS     → slow approach, P too low.
        settle_time_s : time until pos stays within ±5% of step for 300 ms.
        goal_crossings: 1=first reach, 3+=ringing (odd=currently past goal).
        ss_error      : mean |pos-goal| sampled only after settling is confirmed.

        ── Delta sizing strategy ──
        Deltas are ~15% of the current gain value (min 2), so changes are
        meaningful at low gains (P=16) and proportionally larger at high gains
        (P=64), avoiding over- and under-correction regardless of starting gains.

        ── Interaction guard ──
        os_high=True blocks any P-increase suggestions (never simultaneously
        tell the user to decrease AND increase P).
        """
        if not self._settled:
            return []
        if self._step_amp is None or self._step_amp == 0:
            return []
        if self._settle_time_s is None or self._ss_error is None:
            return []

        p = self._p_spin.value()
        i = self._i_spin.value()
        d = self._d_spin.value()

        os_pct  = (self._max_overshoot_steps / self._step_amp) * 100.0
        st_s    = self._settle_time_s
        rt_s    = self._rise_time_s   # None if servo never reached goal
        sse     = self._ss_error
        rings   = self._goal_crossings  # 1=first arrival, 3+=oscillating

        suggestions: list[dict] = []
        os_high = False  # interaction guard

        # ── Helper: proportional delta (15% of value, minimum 2, clamped) ──
        def pdelta(val: int, factor: float = 0.15, min_d: int = 2) -> int:
            return max(min_d, round(val * factor))

        # ── Symptom A: True oscillation (crosses goal 3+ times) ──────────
        # Servo rings back and forth — P is much too high or D very low.
        if rings >= 3 and os_pct > 10:
            os_high = True
            dp = -min(pdelta(p, 0.20), p - 4)    # reduce P by 20%, keep P ≥ 4
            dd = min(pdelta(d, 0.25), 255 - d)   # raise D by 25%
            suggestions.append({
                "symptom": f"Oscillation / ringing detected ({rings} goal crossings, {os_pct:.1f}% overshoot)",
                "icon": "🔴",
                "dp": dp, "di": 0, "dd": dd,
                "why": (
                    f"Servo crossed the goal {rings} times before settling — classic P over-gain.\n"
                    f"Reduce P by {abs(dp)} (from {p} to {p+dp}) to lower drive force, and\n"
                    f"raise D by {dd} (from {d} to {d+dd}) to add braking. Strong fix needed."
                ),
            })

        # ── Symptom B: High single overshoot ────────────────────────
        elif os_pct > 15:
            os_high = True
            if rt_s is not None and rt_s < 0.3:
                # Fast rise + large overshoot → P is fine, D is the culprit
                dd = min(pdelta(d, 0.25), 255 - d)
                dp = 0
                why = (
                    f"Servo reached the goal quickly ({rt_s:.2f}s) but overshot by {os_pct:.1f}%.\n"
                    f"P ({p}) is working well — D is too low to brake the final approach.\n"
                    f"Raise D by {dd} (from {d} to {d+dd})."
                )
            else:
                # Moderate/slow rise + high overshoot → both P and D need adjustment
                dp = -min(pdelta(p, 0.15), p - 4)
                dd = min(pdelta(d, 0.20), 255 - d)
                why = (
                    f"Servo overshot by {os_pct:.1f}% of the step size.\n"
                    f"Reduce P by {abs(dp)} (from {p} to {p+dp}) and\n"
                    f"raise D by {dd} (from {d} to {d+dd}) to brake the approach."
                )
            suggestions.append({
                "symptom": f"High overshoot ({os_pct:.1f}%)",
                "icon": "🔴", "dp": dp, "di": 0, "dd": dd, "why": why,
            })

        # ── Symptom C: Moderate overshoot ───────────────────────────
        elif os_pct > 5:
            dd = min(max(2, round(d * 0.12)), 255 - d)  # ~12% D increase
            suggestions.append({
                "symptom": f"Moderate overshoot ({os_pct:.1f}%)",
                "icon": "🟡",
                "dp": 0, "di": 0, "dd": dd,
                "why": (
                    f"Small overshoot — servo response is mostly good.\n"
                    f"Raise D by {dd} (from {d} to {d+dd}) to soften the overshoot.\n"
                    f"Leave P ({p}) unchanged — speed is already acceptable."
                ),
            })

        # ── Symptom D: Sluggish approach (only when OS is safe to ignore) ──
        # Use rise time if available (more precise); fall back to settle time.
        if not os_high:
            # Detect slow approach via rise time (preferred) or settle time (fallback)
            slow_approach = (
                (rt_s is not None and rt_s > 0.8) or
                (rt_s is None and st_s > 1.5)
            )
            moderate_approach = (
                not slow_approach and (
                    (rt_s is not None and rt_s > 0.35) or
                    (rt_s is None and st_s > 0.5)
                )
            )

            if slow_approach:
                dp = min(pdelta(p, 0.20), 255 - p)  # raise P by 20%
                rt_str = f"{rt_s:.2f}s" if rt_s is not None else f"settle={st_s:.2f}s"
                suggestions.append({
                    "symptom": f"Sluggish response (rise {rt_str})",
                    "icon": "🔴",
                    "dp": dp, "di": 0, "dd": 0,
                    "why": (
                        f"Servo takes {rt_str} to reach the goal — P ({p}) is too low.\n"
                        f"Raise P by {dp} (from {p} to {p+dp}) for stronger drive.\n"
                        f"Overshoot is only {os_pct:.1f}% so increasing P is safe."
                    ),
                })
            elif moderate_approach:
                dp = min(pdelta(p, 0.12), 255 - p)  # raise P by 12%
                rt_str = f"{rt_s:.2f}s" if rt_s is not None else f"settle={st_s:.2f}s"
                suggestions.append({
                    "symptom": f"Slightly slow response (rise {rt_str})",
                    "icon": "🟡",
                    "dp": dp, "di": 0, "dd": 0,
                    "why": (
                        f"Response is a bit slow (rise {rt_str}). A small P increase\n"
                        f"of {dp} (from {p} to {p+dp}) will tighten it without causing overshoot."
                    ),
                })

        # ── Symptom E: Steady-state error ────────────────────────────
        # Only act on SS error ≥ 5 steps (smaller amounts may be sensor noise)
        if sse > 10:
            di = min(2, max(0, 10 - i))    # hard cap at I=10 for ST3215
            if di > 0:
                suggestions.append({
                    "symptom": f"Steady-state error: {sse:.1f} steps from goal",
                    "icon": "🔴",
                    "dp": 0, "di": di, "dd": 0,
                    "why": (
                        f"Servo rests {sse:.0f} steps short of the goal after settling.\n"
                        f"Raise I by {di} (from {i} to {i+di}) to accumulate force\n"
                        f"and close the residual error. Keep I ≤ 10 (ST3215 limit)."
                    ),
                })
            else:
                suggestions.append({
                    "symptom": f"Steady-state error: {sse:.1f} steps (I at safe cap)",
                    "icon": "🟠",
                    "dp": 0, "di": 0, "dd": 0,
                    "why": (
                        f"I is already at 10 (max safe for ST3215). Residual error\n"
                        "is likely due to mechanical friction or the dead-band setting.\n"
                        "Try decreasing CW/CCW Dead Band registers (addr 26/27)."
                    ),
                })
        elif sse > 5:
            di = min(1, max(0, 10 - i))
            if di > 0:
                suggestions.append({
                    "symptom": f"Small steady-state error ({sse:.1f} steps)",
                    "icon": "🟡",
                    "dp": 0, "di": di, "dd": 0,
                    "why": f"Minor residual error. Raise I by {di} (from {i} to {i+di}) to trim it.",
                })

        # ── All good! ────────────────────────────────────────────────
        if not suggestions:
            rt_str = f"{rt_s:.2f}s" if rt_s is not None else "n/a"
            suggestions.append({
                "symptom": "Response is well-tuned!",
                "icon": "✅",
                "dp": 0, "di": 0, "dd": 0,
                "why": (
                    f"Overshoot: {os_pct:.1f}% ✓   Rise: {rt_str} ✓   "
                    f"Settling: {st_s:.2f}s ✓   SS error: {sse:.1f} steps ✓\n"
                    "Current PID values are working well. No changes needed."
                ),
            })

        return suggestions

    def _refresh_advisor(self):
        """Update the advisor panel. Shows 'settling' during transient."""
        # During transient: stable message, no advice yet
        if self._step_start_t is not None and not self._settled:
            self._advisor_label.setText(
                "<span style='color:#58a6ff'>⏳ Settling in progress…"
                "  Advice will appear once the response is complete.</span>"
            )
            self._advisor_apply_btn.setEnabled(False)
            self._suggested_pid = None
            return

        suggestions = self._compute_suggestions()

        if not suggestions:
            self._advisor_label.setText("Run a step test to receive tuning suggestions.")
            self._advisor_label.setStyleSheet("color: #8b949e; font-size: 11px;")
            self._advisor_apply_btn.setEnabled(False)
            self._suggested_pid = None
            return

        p = self._p_spin.value()
        i = self._i_spin.value()
        d = self._d_spin.value()

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

        self._advisor_label.setText("<br>".join(lines))

        if all_ok:
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
            f"<b style='color:#2ea043'>\u2714 Staged: P={p}  I={i}  D={d}</b><br>"
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
            self.write_pid_requested.emit(
                self._servo_id, self._p_spin.value(),
                self._i_spin.value(), self._d_spin.value(),
            )

    def _restore_defaults(self):
        self._p_spin.setValue(32)
        self._i_spin.setValue(0)
        self._d_spin.setValue(16)

    def _trigger_step_test(self):
        """Emit a +200-step goal, then return after 1 s."""
        if self._servo_id < 0:
            QMessageBox.information(self, "No Servo", "Select a servo in the dropdown first.")
            return
        # We don't know current pos here — emit signal and let main_window handle it
        # We pass a sentinel (servo_id, +200) — main_window interprets as relative
        self.step_test_requested.emit(self._servo_id, 200)
        self._step_test_btn.setEnabled(False)
        QTimer.singleShot(1200, lambda: self._step_test_btn.setEnabled(self._servo_id >= 0))

    def _clear_plot(self):
        self._pos_buf.clear()
        self._goal_buf.clear()
        self._curve_pos.setData([], [])
        self._curve_goal.setData([], [])
        self._reset_metrics_state()
