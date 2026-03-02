"""GraphTab — Tab 2: Real-time pyqtgraph multi-trace plotter."""

import time
import csv
from collections import deque
from typing import Dict

import numpy as np
import pyqtgraph as pg
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
    QCheckBox, QListWidget, QListWidgetItem, QPushButton,
    QLabel, QSlider, QSpinBox, QAbstractItemView,
)
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QColor
from styles.dark_theme import TRACE_COLORS


pg.setConfigOptions(antialias=True, background="#0d1117", foreground="#c9d1d9")

METRICS = ["Position", "Goal Position", "Velocity", "Load", "Voltage", "Temperature", "Current"]

# Throttle graph redraw — only repaint every N ms regardless of telemetry rate
_REPAINT_MS = 80   # ~12 fps: smooth but not CPU-heavy


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
        self._dirty    = False         # set True when new data arrives; cleared after repaint

        self._repaint_timer = QTimer(self)
        self._repaint_timer.setInterval(_REPAINT_MS)
        self._repaint_timer.timeout.connect(self._conditional_repaint)
        self._repaint_timer.start()

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

        # Servo selector — multi-select (Ctrl+click) to overlay multiple servos
        servo_box = QGroupBox("Servos to Plot")
        servo_v = QVBoxLayout(servo_box)
        self._servo_list = QListWidget()
        self._servo_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self._servo_list.setMaximumHeight(120)
        self._servo_list.itemSelectionChanged.connect(self._on_servo_selection_changed)
        servo_v.addWidget(self._servo_list)
        hint = QLabel("Ctrl+click to overlay multiple")
        hint.setStyleSheet("color: #484f58; font-size: 10px;")
        hint.setAlignment(Qt.AlignCenter)
        servo_v.addWidget(hint)
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
        self._plot.showGrid(x=True, y=True, alpha=0.2)
        self._plot.getAxis("bottom").setStyle(tickFont=pg.QtGui.QFont("Consolas", 9))
        self._plot.getAxis("left").setStyle(tickFont=pg.QtGui.QFont("Consolas", 9))
        # Smooth rendering — no downsampling (causes jitter/aliasing on live data)
        self._plot.setDownsampling(auto=False)
        self._plot.setClipToView(True)
        # Allow Y-axis to auto-range; X is controlled manually
        self._plot.enableAutoRange(axis=pg.ViewBox.YAxis, enable=True)
        self._plot.setAutoVisible(y=True)
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
        # Auto-select this servo only if nothing is currently selected
        if self._servo_list.selectedItems() == []:
            self._servo_list.setCurrentRow(self._servo_list.count() - 1)

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

        self._dirty = True   # flag for timer-based repaint

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

    def _on_servo_selection_changed(self):
        """When user switches which servo to display, clear existing curves so
        they get recreated for the newly-selected servo."""
        self._plot.clear()
        self._curves.clear()
        if self._running:
            self._plot.addLegend(offset=(10, 10))
        self._dirty = True

    def _conditional_repaint(self):
        """Called by timer every _REPAINT_MS ms. Only redraws when new data exists."""
        if self._dirty and self._running:
            self._refresh_plot()
            self._dirty = False

    def _refresh_plot(self):
        now = time.monotonic() - self._t0
        x_min = max(0.0, now - self._window)

        # All selected servos
        selected_items = self._servo_list.selectedItems()
        if not selected_items:
            return
        selected_ids = [str(item.data(Qt.UserRole)) for item in selected_items]
        multi = len(selected_ids) > 1

        # Collect all visible Y values to set a tight, useful Y range
        all_ys = []

        for servo_idx, selected_id in enumerate(selected_ids):
            for metric, cb in self._metric_checks.items():
                if not cb.isChecked():
                    continue
                if metric not in self._data:
                    continue
                if selected_id not in self._data[metric]:
                    continue
                pts = self._data[metric][selected_id]
                base_color = TRACE_COLORS.get(metric, "#ffffff")

                # Shift hue slightly for each servo so same-metric traces
                # from different servos are distinguishable
                if multi:
                    c = QColor(base_color)
                    h, s, l, a = c.getHslF()
                    h = (h + servo_idx * 0.12) % 1.0
                    c.setHslF(h, s, l, a)
                    color = c
                else:
                    color = base_color

                key = f"{metric}_{selected_id}"

                # Use numpy for fast filtering
                if len(pts) == 0:
                    continue
                arr = np.array(pts)
                mask = arr[:, 0] >= x_min
                xs = arr[mask, 0]
                ys = arr[mask, 1]
                if len(xs) == 0:
                    continue

                all_ys.extend(ys.tolist())

                name = f"{metric} [#{selected_id}]" if multi else f"{metric} [ID {selected_id}]"
                if key not in self._curves:
                    style = Qt.DashLine if metric == "Goal Position" else Qt.SolidLine
                    pen = pg.mkPen(color=color, width=2, style=style)
                    self._curves[key] = self._plot.plot(xs, ys, pen=pen, name=name)
                else:
                    self._curves[key].setData(xs, ys)

        # Lock X to rolling window
        self._plot.setXRange(x_min, now, padding=0)

        # Smart Y auto-range: fit tightly to visible data with small padding
        if all_ys:
            y_lo = min(all_ys)
            y_hi = max(all_ys)
            span = y_hi - y_lo
            if span < 1.0:          # flat signal — give it some breathing room
                span = max(1.0, abs(y_lo) * 0.1 + 1.0)
                padding = span * 0.5
            else:
                padding = span * 0.08   # 8% padding top and bottom
            self._plot.setYRange(y_lo - padding, y_hi + padding, padding=0)

    def _update_visible_curves(self):
        # remove hidden metric curves from the plot
        for metric, cb in self._metric_checks.items():
            if not cb.isChecked():
                for key in list(self._curves.keys()):
                    if key.startswith(metric + "_"):
                        self._plot.removeItem(self._curves.pop(key))

    def _export_csv(self):
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        import collections

        # ── Only export the servo currently shown on the graph ──────────
        selected_items = self._servo_list.selectedItems()
        if not selected_items:
            QMessageBox.information(self, "No Servo Selected",
                                    "Select a servo in the graph panel first.")
            return
        selected_id = str(selected_items[0].data(Qt.UserRole))

        if not self._data:
            QMessageBox.information(self, "No Data", "No telemetry recorded yet.")
            return

        path, _ = QFileDialog.getSaveFileName(
            self, f"Export Servo {selected_id} Telemetry",
            f"servo_{selected_id}_telemetry.csv", "CSV Files (*.csv)"
        )
        if not path:
            return

        # ── Build a time-indexed dict of all metric values ──────────────
        # Structure: {time_rounded → {metric: value}}
        time_data: dict = collections.defaultdict(dict)

        all_metrics = ["Position", "Goal Position", "Velocity",
                       "Load", "Voltage", "Temperature", "Current"]

        for metric in all_metrics:
            if metric in self._data and selected_id in self._data[metric]:
                for t, v in self._data[metric][selected_id]:
                    t_key = round(t, 3)
                    time_data[t_key][metric] = v

        if not time_data:
            QMessageBox.information(self, "No Data",
                                    f"No recorded data for Servo {selected_id}.")
            return

        # ── Write wide-format CSV with error column ─────────────────────
        fieldnames = [
            "time_s", "servo_id",
            "position", "goal_position", "error",
            "velocity", "load_pct", "voltage_V",
            "temperature_C", "current_mA",
        ]
        rows = []
        for t_key in sorted(time_data.keys()):
            d = time_data[t_key]
            pos  = d.get("Position",      None)
            goal = d.get("Goal Position", None)
            err  = round(goal - pos, 1) if (pos is not None and goal is not None) else None
            rows.append({
                "time_s":        t_key,
                "servo_id":      selected_id,
                "position":      pos,
                "goal_position": goal,
                "error":         err,
                "velocity":      d.get("Velocity",    None),
                "load_pct":      d.get("Load",        None),
                "voltage_V":     d.get("Voltage",     None),
                "temperature_C": d.get("Temperature", None),
                "current_mA":    d.get("Current",     None),
            })

        with open(path, "w", newline="") as f:
            # Header comment
            f.write(f"# ServoPilot Telemetry Export — Servo ID {selected_id}\n")
            f.write(f"# error = goal_position - position  (positive = undershoot, negative = overshoot)\n")
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            w.writerows(rows)

        QMessageBox.information(
            self, "Export Complete",
            f"Saved {len(rows)} rows for Servo {selected_id}\nto: {path}"
        )
