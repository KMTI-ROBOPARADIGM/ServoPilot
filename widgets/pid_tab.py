"""PIDTab — Tab 3: PID tuning controls + step-response mini-plot.

Fixes applied:
  - Added an independent servo selector (QComboBox) at the top — users
    can now pick which servo to tune without changing the global selection.
  - Removed the misleading "Write to RAM (temporary)" button. On the ST3215,
    PID registers 21/22/23 live in EEPROM only — there is no RAM shadow for
    PID gains. Both old buttons sent identical data. Now there is a single
    "Write to Servo" button that performs the write correctly.
"""

import time
from collections import deque
import pyqtgraph as pg
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QGroupBox, QLabel, QSpinBox, QPushButton, QMessageBox,
    QComboBox, QFrame, QSizePolicy,
)
from PySide6.QtCore import Signal, Qt


pg.setConfigOptions(antialias=True, background="#0d1117", foreground="#c9d1d9")


class PIDTab(QWidget):
    """PID gain controls + live step-response graph."""

    read_pid_requested  = Signal(int)               # servo_id
    write_pid_requested = Signal(int, int, int, int)  # id, P, I, D

    # How many seconds of history to show in the sliding window
    WINDOW_S = 10.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self._servo_id = -1
        self._pos_buf  = deque(maxlen=5000)
        self._goal_buf = deque(maxlen=5000)
        self._t0       = time.monotonic()
        self._build_ui()

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

        # Read current values from servo
        self._read_btn = QPushButton("📖  Read from Servo")
        self._read_btn.setToolTip("Read the current P/I/D values stored on the selected servo")
        self._read_btn.clicked.connect(self._read_pid)
        btn_v.addWidget(self._read_btn)

        # Single write button — correctly labelled as permanent EEPROM write
        self._write_btn = QPushButton("💾  Write to Servo  (saved to EEPROM)")
        self._write_btn.setObjectName("btn_danger")
        self._write_btn.setToolTip(
            "Permanently saves P/I/D values to the servo's EEPROM.\n"
            "Values are applied immediately and survive power cycles.\n"
            "On ST3215, PID registers (addr 21/22/23) are EEPROM-only."
        )
        self._write_btn.clicked.connect(self._write_pid)
        btn_v.addWidget(self._write_btn)

        # Separator
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

        # ─ Right: step-response mini-plot ────────────────────────────
        plot_box = QGroupBox("Step Response (live)")
        plot_v = QVBoxLayout(plot_box)

        self._plot = pg.PlotWidget()
        self._plot.setLabel("left", "Position (steps)")
        self._plot.setLabel("bottom", "Time (s)")
        self._plot.showGrid(x=True, y=True, alpha=0.25)
        self._plot.addLegend(offset=(10, 10))
        # Keep axes auto-ranging at all times
        self._plot.enableAutoRange(axis=pg.ViewBox.XAxis, enable=True)
        self._plot.enableAutoRange(axis=pg.ViewBox.YAxis, enable=True)
        self._plot.setMouseEnabled(x=True, y=True)   # allow manual zoom-out when needed

        self._curve_pos  = self._plot.plot(
            [], [], pen=pg.mkPen("#00ff88", width=2.5), name="Actual"
        )
        # Goal line: bright yellow-orange so it pops against the dark background
        self._curve_goal = self._plot.plot(
            [], [], pen=pg.mkPen("#ffd700", width=2, style=Qt.DashLine), name="Goal"
        )
        plot_v.addWidget(self._plot)

        clr_btn = QPushButton("Clear Plot")
        clr_btn.setObjectName("btn_flat")
        clr_btn.clicked.connect(self._clear_plot)
        plot_v.addWidget(clr_btn)

        root.addWidget(plot_box, stretch=2)

    # ── Public API ────────────────────────────────────────────────────

    def set_servo(self, servo_id: int):
        """Called by main_window when global servo selection changes.
        Syncs the PID tab's combo to match, but does NOT override if the
        user has already picked a different servo in the combo."""
        # Only auto-follow global selection if user hasn't manually chosen one
        if self._servo_combo.currentData() == -1:
            self._select_servo_in_combo(servo_id)

    def add_servo(self, servo_id: int):
        """Register a discovered servo in the selector combo."""
        # Avoid duplicates
        for i in range(self._servo_combo.count()):
            if self._servo_combo.itemData(i) == servo_id:
                return
        # Remove the placeholder if present
        if self._servo_combo.count() == 1 and self._servo_combo.itemData(0) == -1:
            self._servo_combo.clear()
        self._servo_combo.addItem(f"Servo #{servo_id}", servo_id)
        # Auto-select first servo added
        if self._servo_combo.count() == 1:
            self._servo_combo.setCurrentIndex(0)

    def clear_servos(self):
        """Called on disconnect — reset the combo and internal state."""
        self._servo_combo.clear()
        self._servo_combo.addItem("— no servos found —", -1)
        self._servo_id = -1
        self._info_lbl.setText("No servo selected")
        self._clear_plot()

    def update_telemetry(self, servo_id: int, data: dict, goal_pos: int = None):
        if servo_id != self._servo_id:
            return
        t = time.monotonic() - self._t0
        self._pos_buf.append((t, data.get("position", 0)))
        if goal_pos is not None:
            self._goal_buf.append((t, goal_pos))

        # ── Sliding window: only show the last WINDOW_S seconds ──────
        t_min = t - self.WINDOW_S

        if self._pos_buf:
            xs = [p[0] for p in self._pos_buf if p[0] >= t_min]
            ys = [p[1] for p in self._pos_buf if p[0] >= t_min]
            self._curve_pos.setData(xs, ys)

        if self._goal_buf:
            xs = [p[0] for p in self._goal_buf if p[0] >= t_min]
            ys = [p[1] for p in self._goal_buf if p[0] >= t_min]
            self._curve_goal.setData(xs, ys)

        # Ensure X axis tracks the sliding window
        self._plot.setXRange(max(0.0, t - self.WINDOW_S), t + 0.5, padding=0)

        # Y-axis: auto-range but guarantee a minimum visible span of ±10 steps
        all_ys = ([p[1] for p in self._pos_buf if p[0] >= t_min] +
                  [p[1] for p in self._goal_buf if p[0] >= t_min])
        if all_ys:
            y_lo, y_hi = min(all_ys), max(all_ys)
            span = max(y_hi - y_lo, 20)          # minimum 20-step visible span
            mid  = (y_lo + y_hi) / 2
            self._plot.setYRange(mid - span / 2 - 5, mid + span / 2 + 5, padding=0)

    def set_pid_values(self, p: int, i: int, d: int):
        self._p_spin.setValue(p)
        self._i_spin.setValue(i)
        self._d_spin.setValue(d)
        # Update label to confirm the read succeeded
        if self._servo_id >= 0:
            self._info_lbl.setText(f"ID: {self._servo_id}  ✓ P={p} I={i} D={d}")


    # ── Internals ─────────────────────────────────────────────────────

    def _on_combo_changed(self, index: int):
        sid = self._servo_combo.currentData()
        if sid is None or sid == -1:
            self._servo_id = -1
            self._info_lbl.setText("No servo selected")
        else:
            self._servo_id = sid
            self._info_lbl.setText(f"ID: {sid}  — reading PID…")
            self._t0 = time.monotonic()
            self._clear_plot()
            # Auto-read current PID values from the servo so spinboxes
            # always reflect what's actually stored on the hardware.
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

    def _clear_plot(self):
        self._pos_buf.clear()
        self._goal_buf.clear()
        self._curve_pos.setData([], [])
        self._curve_goal.setData([], [])
