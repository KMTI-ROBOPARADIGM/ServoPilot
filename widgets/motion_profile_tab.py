"""MotionProfileTab — Tab 6: Waypoint-based trajectory editor + preview."""

import csv
import json
import numpy as np
import pyqtgraph as pg
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QTableWidget, QTableWidgetItem, QPushButton,
    QLabel, QCheckBox, QGroupBox, QHeaderView,
    QAbstractItemView, QFileDialog, QSizePolicy,
    QSpinBox, QComboBox, QMessageBox,
)
from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QColor


pg.setConfigOptions(antialias=True, background="#0d1117", foreground="#c9d1d9")

_SERVO_COLORS = [
    "#58a6ff", "#3fb950", "#f78166", "#d2a8ff",
    "#ffa657", "#39d353", "#ff7b72", "#79c0ff",
]


class MotionProfileTab(QWidget):
    """Waypoint table + trajectory preview + execute controls."""

    # Single servo execution (backward compat)
    execute_requested       = Signal(int, list, bool)   # servo_id, waypoints, loop
    # Multi-servo group execution
    execute_group_requested = Signal(list, list, bool)   # servo_ids, waypoints, loop
    stop_requested          = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._servo_id = -1
        self._all_servos: list[int] = []
        self._groups: dict[str, set[int]] = {}
        self._current_servo_ids: list[int] = []  # servos in current target
        self._is_group = False
        self._build_ui()

    # ── Build UI ─────────────────────────────────────────────────────
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
            "Define waypoint sequences for individual servos or groups. "
            "Select a target below, then add/edit waypoints."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #8b949e; font-size: 11px;")
        left.addWidget(desc)

        # Target selector
        target_row = QHBoxLayout()
        target_row.addWidget(QLabel("Target:"))
        self._target_combo = QComboBox()
        self._target_combo.setFixedHeight(28)
        self._target_combo.addItem("— select servo or group —")
        self._target_combo.currentIndexChanged.connect(self._on_target_changed)
        target_row.addWidget(self._target_combo, stretch=1)
        left.addLayout(target_row)

        # Waypoint table (starts with single-servo columns)
        self._table = QTableWidget()
        self._table.setColumnCount(4)
        self._table.setHorizontalHeaderLabels(
            ["Position", "Speed", "Accel", "Delay (s)"]
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

        # Load/Save/Export
        btn_row2 = QHBoxLayout()
        self._load_btn = QPushButton("📂 Load")
        self._load_btn.setObjectName("btn_flat")
        self._load_btn.setToolTip("Load profile from JSON, CSV, or Python script")
        self._load_btn.clicked.connect(self._load_profile)
        btn_row2.addWidget(self._load_btn)

        self._save_btn = QPushButton("💾 Save")
        self._save_btn.setObjectName("btn_flat")
        self._save_btn.clicked.connect(self._save_profile)
        btn_row2.addWidget(self._save_btn)

        self._export_py_btn = QPushButton("🐍 Export Python")
        self._export_py_btn.setObjectName("btn_flat")
        self._export_py_btn.setToolTip("Export as standalone Python script")
        self._export_py_btn.clicked.connect(self._export_python)
        btn_row2.addWidget(self._export_py_btn)

        left.addLayout(btn_row2)

        # Execute controls
        exec_box = QGroupBox("Execute")
        exec_v = QVBoxLayout(exec_box)

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
        self._add_row()
        self._add_row(pos=1024)
        self._update_preview()

    # ── Public API ────────────────────────────────────────────────────

    def set_servo(self, servo_id: int):
        self._servo_id = servo_id

    def add_servo(self, servo_id: int):
        """Register a newly connected servo."""
        if servo_id not in self._all_servos:
            self._all_servos.append(servo_id)
            self._all_servos.sort()
            self._rebuild_target_combo()

    def clear_servos(self):
        """Called on disconnect."""
        self._all_servos.clear()
        self._rebuild_target_combo()

    def set_groups(self, groups: dict):
        """Update groups from the Sync Control tab. Called by main_window."""
        self._groups = {name: set(ids) for name, ids in groups.items()}
        self._rebuild_target_combo()

    # ── Target selector ──────────────────────────────────────────────

    def _rebuild_target_combo(self):
        self._target_combo.blockSignals(True)
        old_text = self._target_combo.currentText()
        self._target_combo.clear()
        self._target_combo.addItem("— select servo or group —")

        # Individual servos
        for sid in self._all_servos:
            self._target_combo.addItem(
                f"Servo {sid}",
                {"type": "servo", "ids": [sid]}
            )

        # Groups from Sync tab
        for name, ids in self._groups.items():
            sorted_ids = sorted(ids)
            ids_str = ", ".join(str(i) for i in sorted_ids)
            self._target_combo.addItem(
                f"Group: {name} [{ids_str}]",
                {"type": "group", "ids": sorted_ids, "name": name}
            )

        # Try to restore previous selection
        idx = self._target_combo.findText(old_text)
        if idx >= 0:
            self._target_combo.setCurrentIndex(idx)
        self._target_combo.blockSignals(False)

    def _on_target_changed(self, index: int):
        data = self._target_combo.currentData()
        if not data:
            self._current_servo_ids = []
            self._is_group = False
            return
        ids = data.get("ids", [])
        self._current_servo_ids = ids
        self._is_group = data.get("type") == "group" and len(ids) > 1
        self._rebuild_table_columns()

    # ── Dynamic table columns ────────────────────────────────────────

    def _rebuild_table_columns(self):
        """Rebuild table columns based on current target."""
        self._table.blockSignals(True)
        self._table.setRowCount(0)

        if self._is_group:
            # Multi-servo: Servo1 Pos | Servo2 Pos | ... | Speed | Accel | Delay
            headers = [f"#{sid} Pos" for sid in self._current_servo_ids]
            headers += ["Speed", "Accel", "Delay (s)"]
            self._table.setColumnCount(len(headers))
            self._table.setHorizontalHeaderLabels(headers)
        else:
            # Single servo: Position | Speed | Accel | Delay
            self._table.setColumnCount(4)
            self._table.setHorizontalHeaderLabels(
                ["Position", "Speed", "Accel", "Delay (s)"]
            )

        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._table.blockSignals(False)

        # Add default rows
        self._add_row()
        self._add_row(pos=1024)
        self._update_preview()

    # ── Row manipulation ─────────────────────────────────────────────

    def _add_row(self, pos=2048, speed=1000, acc=50, delay=0.5):
        self._table.blockSignals(True)
        row = self._table.rowCount()
        self._table.insertRow(row)

        if self._is_group:
            # Multi-servo: per-servo position columns + Speed/Accel/Delay
            n_servos = len(self._current_servo_ids)
            for c in range(n_servos):
                self._table.setItem(row, c, QTableWidgetItem(str(pos)))
            self._table.setItem(row, n_servos,     QTableWidgetItem(str(speed)))
            self._table.setItem(row, n_servos + 1, QTableWidgetItem(str(acc)))
            self._table.setItem(row, n_servos + 2, QTableWidgetItem(str(delay)))
        else:
            # Single servo
            for col, val in enumerate([pos, speed, acc, delay]):
                self._table.setItem(row, col, QTableWidgetItem(str(val)))

        self._table.blockSignals(False)

    def _dup_row(self):
        row = self._table.currentRow()
        if row < 0:
            return
        cols = self._table.columnCount()
        vals = []
        for c in range(cols):
            item = self._table.item(row, c)
            vals.append(item.text() if item else "")
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
        cols = self._table.columnCount()
        for col in range(cols):
            a_item = self._table.item(a, col)
            b_item = self._table.item(b, col)
            a_val = a_item.text() if a_item else ""
            b_val = b_item.text() if b_item else ""
            self._table.setItem(a, col, QTableWidgetItem(b_val))
            self._table.setItem(b, col, QTableWidgetItem(a_val))

    # ── Get waypoints ────────────────────────────────────────────────

    def _get_waypoints(self) -> list:
        """Extract waypoints from the table.

        Returns:
          Single-servo: [{"position": int, "speed": int, "accel": int, "delay": float}]
          Multi-servo:  [{"positions": {sid: pos}, "speed": int, "accel": int, "delay": float}]
        """
        wps = []

        if self._is_group:
            n_servos = len(self._current_servo_ids)
            for row in range(self._table.rowCount()):
                try:
                    positions = {}
                    for i, sid in enumerate(self._current_servo_ids):
                        item = self._table.item(row, i)
                        if item and item.text().strip():
                            positions[sid] = int(item.text())
                    speed = int(self._table.item(row, n_servos).text())
                    accel = int(self._table.item(row, n_servos + 1).text())
                    delay = float(self._table.item(row, n_servos + 2).text())
                    wps.append({
                        "positions": positions,
                        "speed": speed,
                        "accel": accel,
                        "delay": delay,
                    })
                except (ValueError, AttributeError):
                    pass
        else:
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

    # ── Execute ──────────────────────────────────────────────────────

    def _execute(self):
        wps = self._get_waypoints()
        if not wps:
            QMessageBox.warning(self, "Empty", "Add at least one waypoint.")
            return

        loop = self._loop_cb.isChecked()

        if self._is_group:
            self.execute_group_requested.emit(
                self._current_servo_ids, wps, loop
            )
        else:
            # Single servo
            sid = self._current_servo_ids[0] if self._current_servo_ids else self._servo_id
            if sid < 0:
                QMessageBox.warning(self, "No Servo", "Select a target first.")
                return
            self.execute_requested.emit(sid, wps, loop)

    # ── Preview ──────────────────────────────────────────────────────

    def _update_preview(self):
        self._plot.clear()
        self._plot.addLegend()
        wps = self._get_waypoints()
        if not wps:
            return

        if self._is_group:
            # Multi-servo preview: one curve per servo
            for i, sid in enumerate(self._current_servo_ids):
                t = 0.0
                times = []
                positions = []
                for wp in wps:
                    pos = wp.get("positions", {}).get(sid, 2048)
                    times.append(t)
                    positions.append(pos)
                    t += wp.get("delay", 0.5)

                if not times:
                    continue

                color = _SERVO_COLORS[i % len(_SERVO_COLORS)]
                pen = pg.mkPen(color, width=2)
                self._plot.plot(
                    times, positions, pen=pen,
                    symbol="o", symbolSize=7,
                    symbolPen=color, symbolBrush=color,
                    name=f"Servo #{sid}",
                )
        else:
            # Single servo preview
            t = 0.0
            times = [t]
            positions = [wps[0]["position"]]
            for wp in wps:
                t += wp["delay"]
                times.append(t)
                positions.append(wp["position"])
            pen = pg.mkPen("#58a6ff", width=2)
            self._plot.plot(
                times, positions, pen=pen,
                symbol="o", symbolSize=8,
                symbolPen="#58a6ff", symbolBrush="#1f6feb",
                name="Goal Position",
            )

    # ── Save / Load (JSON for multi-servo, CSV backward compat) ──────

    def _save_profile(self):
        wps = self._get_waypoints()
        if not wps:
            QMessageBox.warning(self, "Empty", "Add waypoints first.")
            return

        if self._is_group:
            path, _ = QFileDialog.getSaveFileName(
                self, "Save Profile", "profile.json", "JSON (*.json)"
            )
            if not path:
                return
            data = {
                "servo_ids": self._current_servo_ids,
                "waypoints": wps,
            }
            # Convert dict keys to str for JSON
            for wp in data["waypoints"]:
                if "positions" in wp:
                    wp["positions"] = {str(k): v for k, v in wp["positions"].items()}
            with open(path, "w") as f:
                json.dump(data, f, indent=2)
            QMessageBox.information(self, "Saved", f"Profile saved:\n{path}")
        else:
            path, _ = QFileDialog.getSaveFileName(
                self, "Save Profile", "profile.csv", "CSV (*.csv)"
            )
            if not path:
                return
            with open(path, "w", newline="") as f:
                w = csv.writer(f)
                w.writerow(["position", "speed", "accel", "delay"])
                for wp in wps:
                    w.writerow([wp["position"], wp["speed"], wp["accel"], wp["delay"]])

    def _load_profile(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Load Profile", "",
            "All Supported (*.json *.csv *.py);;JSON (*.json);;CSV (*.csv);;Python (*.py)"
        )
        if not path:
            return

        if path.endswith(".json"):
            self._load_json_profile(path)
        elif path.endswith(".py"):
            self._load_python_profile(path)
        else:
            self._load_csv_profile(path)
        self._update_preview()

    def _load_json_profile(self, path: str):
        """Load multi-servo JSON profile."""
        try:
            with open(path) as f:
                data = json.load(f)
            servo_ids = data.get("servo_ids", [])
            waypoints = data.get("waypoints", [])

            if not servo_ids or not waypoints:
                QMessageBox.warning(self, "Invalid", "No servos/waypoints in file.")
                return

            # Find or set the matching group in combo
            found = False
            for i in range(self._target_combo.count()):
                d = self._target_combo.itemData(i)
                if d and sorted(d.get("ids", [])) == sorted(servo_ids):
                    self._target_combo.setCurrentIndex(i)
                    found = True
                    break

            if not found:
                QMessageBox.warning(
                    self, "Group Not Found",
                    f"No group with servos {servo_ids}.\n"
                    "Create a matching group in Sync Control first."
                )
                return

            # Populate table
            self._table.setRowCount(0)
            n_servos = len(self._current_servo_ids)
            for wp in waypoints:
                positions = wp.get("positions", {})
                row = self._table.rowCount()
                self._table.insertRow(row)
                for j, sid in enumerate(self._current_servo_ids):
                    pos = positions.get(str(sid), positions.get(sid, 2048))
                    self._table.setItem(row, j, QTableWidgetItem(str(pos)))
                self._table.setItem(row, n_servos,     QTableWidgetItem(str(wp.get("speed", 1000))))
                self._table.setItem(row, n_servos + 1, QTableWidgetItem(str(wp.get("accel", 50))))
                self._table.setItem(row, n_servos + 2, QTableWidgetItem(str(wp.get("delay", 0.5))))

        except Exception as e:
            QMessageBox.critical(self, "Load Error", str(e))

    def _load_csv_profile(self, path: str):
        """Load single-servo CSV profile."""
        try:
            with open(path, newline="") as f:
                reader = csv.DictReader(f)
                if self._is_group:
                    QMessageBox.information(
                        self, "CSV Profile",
                        "CSV profiles are single-servo. Select a single servo target."
                    )
                    return
                self._table.setRowCount(0)
                for r in reader:
                    self._add_row(
                        int(r.get("position", 2048)),
                        int(r.get("speed", 1000)),
                        int(r.get("accel", 50)),
                        float(r.get("delay", 0.5)),
                    )
        except Exception as e:
            QMessageBox.critical(self, "Load Error", str(e))

    def _load_python_profile(self, path: str):
        """Load a motion profile from an exported Python script.

        Parses SERVO_IDS and WAYPOINTS variables from the script.
        """
        try:
            with open(path, "r", encoding="utf-8") as f:
                source = f.read()

            # Extract SERVO_IDS and WAYPOINTS using safe eval
            import re
            import ast

            ids_match = re.search(r'^SERVO_IDS\s*=\s*(\[.*?\])', source, re.MULTILINE)
            wp_match = re.search(
                r'^WAYPOINTS\s*=\s*(\[.*?^\])', source,
                re.MULTILINE | re.DOTALL
            )

            if not wp_match:
                QMessageBox.warning(self, "Parse Error",
                    "Could not find WAYPOINTS list in the Python script.")
                return

            waypoints_raw = ast.literal_eval(wp_match.group(1))
            servo_ids = ast.literal_eval(ids_match.group(1)) if ids_match else []

            if not waypoints_raw:
                QMessageBox.warning(self, "Empty", "WAYPOINTS list is empty.")
                return

            # Detect single vs multi-servo
            is_multi = "positions" in waypoints_raw[0]

            if is_multi and servo_ids:
                # Find matching group in combo
                found = False
                for i in range(self._target_combo.count()):
                    d = self._target_combo.itemData(i)
                    if d and sorted(d.get("ids", [])) == sorted(servo_ids):
                        self._target_combo.setCurrentIndex(i)
                        found = True
                        break
                if not found:
                    QMessageBox.warning(self, "Group Not Found",
                        f"No group with servos {servo_ids}.\n"
                        "Create a matching group in Sync Control first.")
                    return

                self._table.setRowCount(0)
                n_servos = len(self._current_servo_ids)
                for wp in waypoints_raw:
                    positions = wp.get("positions", {})
                    row = self._table.rowCount()
                    self._table.insertRow(row)
                    for j, sid in enumerate(self._current_servo_ids):
                        pos = positions.get(sid, positions.get(str(sid), 2048))
                        self._table.setItem(row, j, QTableWidgetItem(str(pos)))
                    self._table.setItem(row, n_servos,     QTableWidgetItem(str(wp.get("speed", wp.get("velocity", 1000)))))
                    self._table.setItem(row, n_servos + 1, QTableWidgetItem(str(wp.get("accel", 50))))
                    self._table.setItem(row, n_servos + 2, QTableWidgetItem(str(wp.get("delay", wp.get("time", 0.5)))))
            else:
                # Single servo
                if self._is_group:
                    QMessageBox.information(self, "Single-Servo Script",
                        "This script is single-servo. Select a single servo target.")
                    return
                self._table.setRowCount(0)
                for wp in waypoints_raw:
                    self._add_row(
                        wp.get("position", 2048),
                        wp.get("speed", wp.get("velocity", 1000)),
                        wp.get("accel", 50),
                        wp.get("delay", wp.get("time", 0.5)),
                    )

            QMessageBox.information(self, "Loaded",
                f"Loaded {len(waypoints_raw)} waypoints from Python script.")

        except Exception as e:
            QMessageBox.critical(self, "Load Error", f"Failed to parse script:\n{e}")

    # ── Python export ────────────────────────────────────────────────

    def _export_python(self):
        """Export current waypoints as a standalone Python script."""
        wps = self._get_waypoints()
        if not wps:
            QMessageBox.warning(self, "Empty", "Add waypoints first.")
            return

        servo_ids = self._current_servo_ids if self._current_servo_ids else [self._servo_id]
        if servo_ids[0] < 0:
            QMessageBox.warning(self, "No Servo", "Select a target first.")
            return

        path, _ = QFileDialog.getSaveFileName(
            self, "Export Python Script", "motion_profile.py", "Python (*.py)"
        )
        if not path:
            return

        multi = self._is_group
        loop = self._loop_cb.isChecked()

        lines = [
            '#!/usr/bin/env python3',
            '"""',
            'ServoPilot Motion Profile — exported script',
            f'Servo IDs: {servo_ids}',
            f'Waypoints: {len(wps)}',
            f'Loop: {loop}',
            '"""',
            '',
            'import time',
            'import sys',
            'import os',
            '',
            '# Add st3215 to path if needed',
            'sys.path.insert(0, os.path.join(os.path.dirname(__file__), "st3215"))',
            'from st3215 import ST3215',
            '',
            '',
            f'SERVO_IDS = {servo_ids}',
            'PORT = "COM8"       # <-- Change to your serial port',
            'BAUD = 1_000_000',
            '',
            'WAYPOINTS = [',
        ]

        for wp in wps:
            if multi:
                pos = wp.get("positions", {})
                lines.append(
                    f'    {{"positions": {pos}, '
                    f'"speed": {wp.get("speed", 1000)}, '
                    f'"accel": {wp.get("accel", 50)}, '
                    f'"delay": {wp.get("delay", 0.5)}}},'
                )
            else:
                lines.append(
                    f'    {{"position": {wp["position"]}, '
                    f'"speed": {wp.get("speed", 1000)}, '
                    f'"accel": {wp.get("accel", 50)}, '
                    f'"delay": {wp.get("delay", 0.5)}}},'
                )
        lines.append(']')
        lines.append('')
        lines.append('')
        lines.append('def main():')
        lines.append('    servo = ST3215(PORT)')
        lines.append('    servo.portHandler.baudrate = BAUD')
        lines.append('    print(f"Running profile on servos {SERVO_IDS}...")')
        lines.append('')

        if loop:
            lines.append('    while True:')
            indent = '        '
        else:
            indent = '    '

        lines.append(f'{indent}for i, wp in enumerate(WAYPOINTS):')
        if multi:
            lines.append(f'{indent}    for sid, pos in wp["positions"].items():')
            lines.append(f'{indent}        servo.MoveTo(int(sid), int(pos), speed=wp["speed"], acc=wp["accel"])')
        else:
            lines.append(f'{indent}    for sid in SERVO_IDS:')
            lines.append(f'{indent}        servo.MoveTo(sid, wp["position"], speed=wp["speed"], acc=wp["accel"])')
        lines.append(f'{indent}    time.sleep(wp["delay"])')
        lines.append('')
        lines.append('    print("Done.")')
        lines.append('')
        lines.append('')
        lines.append('if __name__ == "__main__":')
        lines.append('    main()')
        lines.append('')

        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
            QMessageBox.information(self, "Exported",
                f"Python script exported:\n{path}")
        except OSError as e:
            QMessageBox.critical(self, "Export Error", str(e))
