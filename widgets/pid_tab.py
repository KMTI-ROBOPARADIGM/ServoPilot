"""PIDTab — Tab 3: PID tuning controls + step-response mini-plot."""

import time
from collections import deque
import pyqtgraph as pg
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QGroupBox, QLabel, QSpinBox, QPushButton, QMessageBox,
    QSizePolicy,
)
from PySide6.QtCore import Signal, Qt


pg.setConfigOptions(antialias=True, background="#0d1117", foreground="#c9d1d9")


class PIDTab(QWidget):
    """PID gain controls + live step-response graph."""

    read_pid_requested   = Signal(int)              # servo_id
    write_pid_requested  = Signal(int, int, int, int)  # id, P, I, D

    def __init__(self, parent=None):
        super().__init__(parent)
        self._servo_id = -1
        self._pos_buf  = deque(maxlen=2000)
        self._goal_buf = deque(maxlen=2000)
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

        desc = QLabel(
            "Adjust P/I/D gains, write to RAM for instant effect, "
            "or write to EEPROM to persist across reboots."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #8b949e; font-size: 11px;")
        left.addWidget(desc)

        # Gain spinboxes
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

        # Action buttons
        btn_box = QGroupBox("Actions")
        btn_v = QVBoxLayout(btn_box)

        self._read_btn = QPushButton("📖  Read from Servo")
        self._read_btn.clicked.connect(self._read_pid)
        btn_v.addWidget(self._read_btn)

        self._write_ram_btn = QPushButton("✍  Write to RAM (temporary)")
        self._write_ram_btn.setObjectName("btn_warn")
        self._write_ram_btn.clicked.connect(self._write_ram)
        btn_v.addWidget(self._write_ram_btn)

        self._write_eeprom_btn = QPushButton("💾  Write to EEPROM (permanent)")
        self._write_eeprom_btn.setObjectName("btn_danger")
        self._write_eeprom_btn.clicked.connect(self._write_eeprom)
        btn_v.addWidget(self._write_eeprom_btn)

        self._defaults_btn = QPushButton("↺  Restore Defaults  (P=32 I=0 D=16)")
        self._defaults_btn.setObjectName("btn_flat")
        self._defaults_btn.clicked.connect(self._restore_defaults)
        btn_v.addWidget(self._defaults_btn)

        left.addWidget(btn_box)
        left.addStretch()

        self._info_lbl = QLabel("No servo selected")
        self._info_lbl.setStyleSheet("color: #8b949e; font-size: 11px;")
        left.addWidget(self._info_lbl)

        root.addLayout(left, stretch=1)

        # ─ Right: step-response mini-plot ────────────────────────────
        plot_box = QGroupBox("Step Response (live)")
        plot_v = QVBoxLayout(plot_box)

        self._plot = pg.PlotWidget()
        self._plot.setLabel("left", "Position (steps)")
        self._plot.setLabel("bottom", "Time (s)")
        self._plot.showGrid(x=True, y=True, alpha=0.15)
        self._plot.addLegend(offset=(10, 10))

        self._curve_pos  = self._plot.plot(
            [], [], pen=pg.mkPen("#00ff88", width=2), name="Actual"
        )
        self._curve_goal = self._plot.plot(
            [], [], pen=pg.mkPen("#238636", width=2, style=Qt.DashLine), name="Goal"
        )
        plot_v.addWidget(self._plot)

        clr_btn = QPushButton("Clear Plot")
        clr_btn.setObjectName("btn_flat")
        clr_btn.clicked.connect(self._clear_plot)
        plot_v.addWidget(clr_btn)

        root.addWidget(plot_box, stretch=2)

    # ── Public API ────────────────────────────────────────────────────
    def set_servo(self, servo_id: int):
        self._servo_id = servo_id
        self._info_lbl.setText(f"Selected: Servo #{servo_id}")
        self._t0 = time.monotonic()
        self._clear_plot()

    def update_telemetry(self, servo_id: int, data: dict, goal_pos: int = None):
        if servo_id != self._servo_id:
            return
        t = time.monotonic() - self._t0
        self._pos_buf.append((t, data.get("position", 0)))
        if goal_pos is not None:
            self._goal_buf.append((t, goal_pos))
        # refresh
        if self._pos_buf:
            xs = [p[0] for p in self._pos_buf]
            ys = [p[1] for p in self._pos_buf]
            self._curve_pos.setData(xs, ys)
        if self._goal_buf:
            xs = [p[0] for p in self._goal_buf]
            ys = [p[1] for p in self._goal_buf]
            self._curve_goal.setData(xs, ys)

    def set_pid_values(self, p: int, i: int, d: int):
        self._p_spin.setValue(p)
        self._i_spin.setValue(i)
        self._d_spin.setValue(d)

    # ── Internals ─────────────────────────────────────────────────────
    def _read_pid(self):
        if self._servo_id < 0:
            return
        self.read_pid_requested.emit(self._servo_id)

    def _write_ram(self):
        if self._servo_id < 0:
            return
        self.write_pid_requested.emit(
            self._servo_id, self._p_spin.value(),
            self._i_spin.value(), self._d_spin.value()
        )

    def _write_eeprom(self):
        if self._servo_id < 0:
            return
        reply = QMessageBox.question(
            self, "Write to EEPROM",
            "This will permanently save P/I/D gains to EEPROM.\n"
            "Are you sure?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self.write_pid_requested.emit(
                self._servo_id, self._p_spin.value(),
                self._i_spin.value(), self._d_spin.value()
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
