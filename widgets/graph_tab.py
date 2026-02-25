"""GraphTab — Tab 2: Real-time pyqtgraph multi-trace plotter."""

import time
import csv
from collections import deque
from typing import Dict

import pyqtgraph as pg
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
    QCheckBox, QListWidget, QListWidgetItem, QPushButton,
    QLabel, QSlider, QSpinBox, QAbstractItemView,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from styles.dark_theme import TRACE_COLORS


pg.setConfigOptions(antialias=True, background="#0d1117", foreground="#c9d1d9")

METRICS = ["Position", "Goal Position", "Velocity", "Load", "Voltage", "Temperature", "Current"]


class GraphTab(QWidget):
    """Real-time multi-trace plot (position / velocity / load / etc.)."""

    graph_start_requested = Signal()
    graph_stop_requested  = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._running  = False
        self._t0       = 0.0
        self._window   = 20.0         # seconds
        self._max_pts  = 10_000
        self._data: Dict[str, Dict[str, deque]] = {}  # metric → id → deque of (t,v)
        self._curves: Dict[str, Dict[str, pg.PlotDataItem]] = {}
        self._goal_pos: Dict[int, float] = {}   # servo_id → goal position
        self._build_ui()

    # ── Build UI ─────────────────────────────────────────────────────
    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)

        # ─ Left control panel ────────────────────────────────────────
        ctrl = QVBoxLayout()
        ctrl.setSpacing(6)

        # Metrics checkboxes
        met_box = QGroupBox("Metrics")
        met_v = QVBoxLayout(met_box)
        self._metric_checks: Dict[str, QCheckBox] = {}
        for m in METRICS:
            cb = QCheckBox(m)
            cb.setChecked(m in ("Position", "Goal Position"))
            color = TRACE_COLORS.get(m, "#ffffff")
            cb.setStyleSheet(f"color: {color}; font-weight: bold;")
            cb.toggled.connect(self._update_visible_curves)
            met_v.addWidget(cb)
            self._metric_checks[m] = cb
        ctrl.addWidget(met_box)

        # Servo selector
        servo_box = QGroupBox("Servos")
        servo_v = QVBoxLayout(servo_box)
        self._servo_list = QListWidget()
        self._servo_list.setSelectionMode(QAbstractItemView.MultiSelection)
        self._servo_list.setMaximumHeight(120)
        servo_v.addWidget(self._servo_list)
        ctrl.addWidget(servo_box)

        # Time window
        tw_box = QGroupBox("Time Window")
        tw_v = QVBoxLayout(tw_box)
        self._tw_slider = QSlider(Qt.Horizontal)
        self._tw_slider.setRange(5, 60)
        self._tw_slider.setValue(20)
        self._tw_slider.setTickInterval(5)
        self._tw_slider.setTickPosition(QSlider.TicksBelow)
        self._tw_lbl = QLabel("20 s")
        self._tw_lbl.setAlignment(Qt.AlignCenter)
        self._tw_slider.valueChanged.connect(self._tw_changed)
        tw_v.addWidget(self._tw_slider)
        tw_v.addWidget(self._tw_lbl)
        ctrl.addWidget(tw_box)

        # Buttons
        self._start_btn = QPushButton("▶ Start")
        self._start_btn.setObjectName("btn_success")
        self._start_btn.clicked.connect(self._toggle)
        ctrl.addWidget(self._start_btn)

        self._clear_btn = QPushButton("✕ Clear")
        self._clear_btn.setObjectName("btn_flat")
        self._clear_btn.clicked.connect(self._clear_data)
        ctrl.addWidget(self._clear_btn)

        self._export_btn = QPushButton("⬇ Export CSV")
        self._export_btn.setObjectName("btn_flat")
        self._export_btn.clicked.connect(self._export_csv)
        ctrl.addWidget(self._export_btn)

        ctrl.addStretch()
        root.addLayout(ctrl, stretch=0)

        # ─ Plot area ─────────────────────────────────────────────────
        plot_v = QVBoxLayout()
        plot_v.setSpacing(4)

        # Status bar
        self._status_lbl = QLabel("Stopped — press Start to begin recording")
        self._status_lbl.setStyleSheet("color: #8b949e; font-size: 11px;")
        plot_v.addWidget(self._status_lbl)

        # Plot widget
        self._plot = pg.PlotWidget()
        self._plot.setLabel("left", "Value")
        self._plot.setLabel("bottom", "Time (s)")
        self._plot.addLegend(offset=(10, 10))
        self._plot.showGrid(x=True, y=True, alpha=0.15)
        self._plot.getAxis("bottom").setStyle(tickFont=pg.QtGui.QFont("Consolas", 9))
        self._plot.getAxis("left").setStyle(tickFont=pg.QtGui.QFont("Consolas", 9))
        plot_v.addWidget(self._plot, stretch=1)

        root.addLayout(plot_v, stretch=1)

    # ── Public API ────────────────────────────────────────────────────
    def register_servo(self, servo_id: int):
        label = f"ID {servo_id}"
        # Check if already added
        for i in range(self._servo_list.count()):
            if self._servo_list.item(i).data(Qt.UserRole) == servo_id:
                return
        item = QListWidgetItem(label)
        item.setData(Qt.UserRole, servo_id)
        self._servo_list.addItem(item)
        item.setSelected(True)

    def update_telemetry(self, servo_id: int, data: dict, goal_pos: int = None):
        if not self._running:
            return
        t = time.monotonic() - self._t0
        if goal_pos is not None:
            self._goal_pos[servo_id] = float(goal_pos)

        value_map = {
            "Position":     data.get("position", 0),
            "Goal Position": self._goal_pos.get(servo_id, data.get("position", 0)),
            "Velocity":     data.get("velocity", 0),
            "Load":         data.get("load", 0.0),
            "Voltage":      data.get("voltage", 0.0),
            "Temperature":  data.get("temperature", 0),
            "Current":      data.get("current", 0.0),
        }

        sid_str = str(servo_id)
        for metric, val in value_map.items():
            if metric not in self._data:
                self._data[metric] = {}
            if sid_str not in self._data[metric]:
                self._data[metric][sid_str] = deque(maxlen=self._max_pts)
            self._data[metric][sid_str].append((t, val))

        self._refresh_plot()

    def clear_servos(self):
        self._servo_list.clear()
        self._data.clear()
        self._plot.clear()
        self._curves.clear()

    # ── Internals ─────────────────────────────────────────────────────
    def _toggle(self):
        if self._running:
            self._running = False
            self._start_btn.setText("▶ Start")
            self._status_lbl.setText("Stopped")
            self.graph_stop_requested.emit()
        else:
            self._running = True
            self._t0 = time.monotonic()
            self._data.clear()
            self._curves.clear()
            self._plot.clear()
            self._plot.addLegend(offset=(10, 10))
            self._start_btn.setText("⏹ Stop")
            self._status_lbl.setText("Recording …")
            self.graph_start_requested.emit()

    def _clear_data(self):
        self._data.clear()
        self._curves.clear()
        self._plot.clear()
        self._plot.addLegend(offset=(10, 10))

    def _tw_changed(self, val):
        self._window = float(val)
        self._tw_lbl.setText(f"{val} s")

    def _refresh_plot(self):
        now = time.monotonic() - self._t0
        x_min = max(0.0, now - self._window)

        # which servos are selected?
        selected_ids = {
            str(self._servo_list.item(i).data(Qt.UserRole))
            for i in range(self._servo_list.count())
            if self._servo_list.item(i).isSelected()
        }

        for metric, cb in self._metric_checks.items():
            if not cb.isChecked():
                continue
            if metric not in self._data:
                continue
            color = TRACE_COLORS.get(metric, "#ffffff")
            for sid_str, pts in self._data[metric].items():
                if sid_str not in selected_ids:
                    continue
                key = f"{metric}_{sid_str}"
                xs = [p[0] for p in pts if p[0] >= x_min]
                ys = [p[1] for p in pts if p[0] >= x_min]
                if not xs:
                    continue
                name = f"{metric} [{sid_str}]"
                if key not in self._curves:
                    style = Qt.DashLine if metric == "Goal Position" else Qt.SolidLine
                    pen = pg.mkPen(color=color, width=2, style=style)
                    self._curves[key] = self._plot.plot(
                        xs, ys, pen=pen, name=name
                    )
                else:
                    self._curves[key].setData(xs, ys)

        self._plot.setXRange(x_min, now, padding=0)

    def _update_visible_curves(self):
        # remove hidden metric curves
        for metric, cb in self._metric_checks.items():
            if not cb.isChecked():
                for key in list(self._curves.keys()):
                    if key.startswith(metric + "_"):
                        self._plot.removeItem(self._curves.pop(key))

    def _export_csv(self):
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(
            self, "Export CSV", "telemetry.csv", "CSV Files (*.csv)"
        )
        if not path:
            return
        rows = []
        for metric, sid_dict in self._data.items():
            for sid, pts in sid_dict.items():
                for t, v in pts:
                    rows.append({"time": round(t, 4), "servo": sid, "metric": metric, "value": v})
        rows.sort(key=lambda r: r["time"])
        with open(path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["time", "servo", "metric", "value"])
            w.writeheader()
            w.writerows(rows)
