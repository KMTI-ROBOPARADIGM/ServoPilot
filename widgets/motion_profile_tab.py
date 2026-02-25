"""MotionProfileTab — Tab 6: Waypoint-based trajectory editor + preview."""

import csv
import time
import pyqtgraph as pg
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QTableWidget, QTableWidgetItem, QPushButton,
    QLabel, QCheckBox, QGroupBox, QHeaderView,
    QAbstractItemView, QFileDialog, QSizePolicy,
    QSpinBox,
)
from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QColor


pg.setConfigOptions(antialias=True, background="#0d1117", foreground="#c9d1d9")


class MotionProfileTab(QWidget):
    """Waypoint table + trajectory preview + execute controls."""

    execute_requested = Signal(int, list, bool)   # servo_id, waypoints, loop
    stop_requested    = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._servo_id = -1
        self._build_ui()

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(10)

        # ─ Left: waypoint table ──────────────────────────────────────
        left = QVBoxLayout()

        title = QLabel("Motion Profile Editor")
        title.setStyleSheet(
            "color: #58a6ff; font-size: 14px; font-weight: bold; letter-spacing: 1px;"
        )
        left.addWidget(title)

        desc = QLabel(
            "Define a sequence of goal positions. "
            "Each waypoint specifies position, speed, acceleration, and dwell time."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #8b949e; font-size: 11px;")
        left.addWidget(desc)

        self._table = QTableWidget()
        self._table.setColumnCount(4)
        self._table.setHorizontalHeaderLabels(
            ["Position", "Speed (s/s)", "Accel", "Delay (s)"]
        )
        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.Stretch)
        self._table.verticalHeader().setVisible(True)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        left.addWidget(self._table, stretch=1)

        # Edit buttons
        btn_row1 = QHBoxLayout()
        self._add_btn = QPushButton("+ Add")
        self._add_btn.setObjectName("btn_success")
        self._add_btn.clicked.connect(self._add_row)
        btn_row1.addWidget(self._add_btn)

        self._dup_btn = QPushButton("⎘ Dup")
        self._dup_btn.setObjectName("btn_flat")
        self._dup_btn.clicked.connect(self._dup_row)
        btn_row1.addWidget(self._dup_btn)

        self._del_btn = QPushButton("✕ Remove")
        self._del_btn.setObjectName("btn_danger")
        self._del_btn.clicked.connect(self._del_row)
        btn_row1.addWidget(self._del_btn)

        self._up_btn = QPushButton("↑")
        self._up_btn.setObjectName("btn_flat")
        self._up_btn.setFixedWidth(30)
        self._up_btn.clicked.connect(self._move_up)
        btn_row1.addWidget(self._up_btn)

        self._dn_btn = QPushButton("↓")
        self._dn_btn.setObjectName("btn_flat")
        self._dn_btn.setFixedWidth(30)
        self._dn_btn.clicked.connect(self._move_down)
        btn_row1.addWidget(self._dn_btn)

        left.addLayout(btn_row1)

        # Load/Save
        btn_row2 = QHBoxLayout()
        self._load_btn = QPushButton("📂 Load CSV")
        self._load_btn.setObjectName("btn_flat")
        self._load_btn.clicked.connect(self._load_csv)
        btn_row2.addWidget(self._load_btn)

        self._save_btn = QPushButton("💾 Save CSV")
        self._save_btn.setObjectName("btn_flat")
        self._save_btn.clicked.connect(self._save_csv)
        btn_row2.addWidget(self._save_btn)

        left.addLayout(btn_row2)

        # Execute controls
        exec_box = QGroupBox("Execute")
        exec_v = QVBoxLayout(exec_box)

        target_row = QHBoxLayout()
        target_row.addWidget(QLabel("Target Servo ID:"))
        self._target_spin = QSpinBox()
        self._target_spin.setRange(0, 253)
        target_row.addWidget(self._target_spin)
        exec_v.addLayout(target_row)

        self._loop_cb = QCheckBox("Loop continuously")
        exec_v.addWidget(self._loop_cb)

        exec_btn_row = QHBoxLayout()
        self._exec_btn = QPushButton("▶ Execute Profile")
        self._exec_btn.setObjectName("btn_success")
        self._exec_btn.clicked.connect(self._execute)
        exec_btn_row.addWidget(self._exec_btn)

        self._stop_btn = QPushButton("⏹ Stop")
        self._stop_btn.setObjectName("btn_danger")
        self._stop_btn.clicked.connect(self.stop_requested)
        exec_btn_row.addWidget(self._stop_btn)
        exec_v.addLayout(exec_btn_row)

        left.addWidget(exec_box)

        root.addLayout(left, stretch=1)

        # ─ Right: trajectory preview ─────────────────────────────────
        right = QVBoxLayout()
        right.addWidget(QLabel("Trajectory Preview"))

        self._plot = pg.PlotWidget()
        self._plot.setLabel("left", "Position (steps)")
        self._plot.setLabel("bottom", "Time (s)")
        self._plot.showGrid(x=True, y=True, alpha=0.15)
        self._plot.addLegend()
        right.addWidget(self._plot, stretch=1)

        preview_btn = QPushButton("↻ Preview")
        preview_btn.setObjectName("btn_flat")
        preview_btn.clicked.connect(self._update_preview)
        right.addWidget(preview_btn)

        root.addLayout(right, stretch=1)

        # Seed with two example waypoints
        self._add_row(2048, 1000, 50, 1.0)
        self._add_row(1024, 1000, 50, 1.0)
        self._update_preview()

    # ── Public API ────────────────────────────────────────────────────
    def set_servo(self, servo_id: int):
        self._servo_id = servo_id
        self._target_spin.setValue(servo_id)

    # ── Internals ─────────────────────────────────────────────────────
    def _add_row(self, pos=2048, speed=1000, acc=50, delay=0.5):
        row = self._table.rowCount()
        self._table.insertRow(row)
        for col, val in enumerate([pos, speed, acc, delay]):
            self._table.setItem(row, col, QTableWidgetItem(str(val)))

    def _dup_row(self):
        row = self._table.currentRow()
        if row < 0:
            return
        vals = [self._table.item(row, c).text() for c in range(4)]
        new_row = row + 1
        self._table.insertRow(new_row)
        for c, v in enumerate(vals):
            self._table.setItem(new_row, c, QTableWidgetItem(v))

    def _del_row(self):
        row = self._table.currentRow()
        if row >= 0:
            self._table.removeRow(row)
        self._update_preview()

    def _move_up(self):
        row = self._table.currentRow()
        if row <= 0:
            return
        self._swap_rows(row, row - 1)
        self._table.selectRow(row - 1)

    def _move_down(self):
        row = self._table.currentRow()
        if row < 0 or row >= self._table.rowCount() - 1:
            return
        self._swap_rows(row, row + 1)
        self._table.selectRow(row + 1)

    def _swap_rows(self, a, b):
        for col in range(4):
            a_val = self._table.item(a, col).text()
            b_val = self._table.item(b, col).text()
            self._table.item(a, col).setText(b_val)
            self._table.item(b, col).setText(a_val)

    def _load_csv(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Load Profile", "", "CSV (*.csv)"
        )
        if not path:
            return
        with open(path, newline="") as f:
            reader = csv.DictReader(f)
            self._table.setRowCount(0)
            for r in reader:
                self._add_row(
                    int(r.get("position", 2048)),
                    int(r.get("speed", 1000)),
                    int(r.get("accel", 50)),
                    float(r.get("delay", 0.5)),
                )
        self._update_preview()

    def _save_csv(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Profile", "profile.csv", "CSV (*.csv)"
        )
        if not path:
            return
        with open(path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["position", "speed", "accel", "delay"])
            for row in range(self._table.rowCount()):
                w.writerow([
                    self._table.item(row, c).text()
                    for c in range(4)
                ])

    def _get_waypoints(self) -> list:
        wps = []
        for row in range(self._table.rowCount()):
            try:
                wps.append({
                    "position": int(self._table.item(row, 0).text()),
                    "speed":    int(self._table.item(row, 1).text()),
                    "accel":    int(self._table.item(row, 2).text()),
                    "delay":    float(self._table.item(row, 3).text()),
                })
            except (ValueError, AttributeError):
                pass
        return wps

    def _execute(self):
        wps = self._get_waypoints()
        if not wps:
            return
        sid = self._target_spin.value()
        self.execute_requested.emit(sid, wps, self._loop_cb.isChecked())

    def _update_preview(self):
        self._plot.clear()
        wps = self._get_waypoints()
        if not wps:
            return
        t = 0.0
        times = [t]
        positions = [wps[0]["position"]]
        for wp in wps:
            t += wp["delay"]
            times.append(t)
            positions.append(wp["position"])
        pen = pg.mkPen("#58a6ff", width=2)
        self._plot.plot(times, positions, pen=pen,
                        symbol="o", symbolSize=8,
                        symbolPen="#58a6ff", symbolBrush="#1f6feb",
                        name="Goal Position")
