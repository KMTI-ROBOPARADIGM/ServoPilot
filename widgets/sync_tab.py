"""SyncTab — Servo Group / Sync Write control panel.

Lets the user:
  1. Create named servo groups  (e.g. "Left Arm", "Wrist")
  2. Assign any subset of connected servos to a group
  3. Set individual goal positions via sliders + spinboxes
  4. Fire ALL positions in one hardware sync-write packet with a single click

The tab emits a single `sync_write_requested` signal carrying a dict
{servo_id: position} that main_window wires to backend.sync_write_positions().
"""

from __future__ import annotations
import json
import os
from pathlib import Path
from typing import Dict, Set

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QGroupBox, QLabel, QPushButton, QListWidget, QListWidgetItem,
    QScrollArea, QFrame, QSlider, QSpinBox, QCheckBox,
    QInputDialog, QMessageBox, QSizePolicy,
)
from PySide6.QtCore import Qt, Signal, Slot, QTimer
from PySide6.QtGui import QFont


class _ServoRow(QWidget):
    """One row in the position editor: servo ID label + slider + spinbox + read button."""

    position_changed = Signal(int, int)   # (servo_id, new_pos)
    read_requested   = Signal(int)        # servo_id

    def __init__(self, servo_id: int, parent: QWidget | None = None):
        super().__init__(parent)
        self.servo_id = servo_id

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(8)

        # Servo ID badge
        badge = QLabel(f"#{servo_id:>3}")
        badge.setFixedWidth(36)
        badge.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        badge.setStyleSheet(
            "color: #58a6ff; font-family: Consolas; font-size: 12px; font-weight: bold;"
        )
        layout.addWidget(badge)

        # Slider 0-4095
        self._slider = QSlider(Qt.Horizontal)
        self._slider.setRange(0, 4095)
        self._slider.setValue(2048)
        self._slider.setSingleStep(10)
        self._slider.setPageStep(100)
        self._slider.setTickPosition(QSlider.TicksBelow)
        self._slider.setTickInterval(512)
        self._slider.setMinimumWidth(200)
        layout.addWidget(self._slider, stretch=1)

        # Spinbox
        self._spin = QSpinBox()
        self._spin.setRange(0, 4095)
        self._spin.setValue(2048)
        self._spin.setFixedWidth(72)
        self._spin.setAlignment(Qt.AlignRight)
        layout.addWidget(self._spin)

        # Degree hint (0-4095 ≈ 0-360°)
        self._deg_lbl = QLabel("180.0°")
        self._deg_lbl.setFixedWidth(50)
        self._deg_lbl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self._deg_lbl.setStyleSheet("color: #8b949e; font-size: 11px;")
        layout.addWidget(self._deg_lbl)

        # Read current button
        read_btn = QPushButton("↺")
        read_btn.setObjectName("btn_flat")
        read_btn.setFixedSize(28, 28)
        read_btn.setToolTip("Read current position from servo")
        read_btn.clicked.connect(lambda: self.read_requested.emit(self.servo_id))
        layout.addWidget(read_btn)

        # Wire slider ↔ spinbox
        self._slider.valueChanged.connect(self._on_slider)
        self._spin.valueChanged.connect(self._on_spin)
        self._updating = False

    def _on_slider(self, v: int):
        if self._updating:
            return
        self._updating = True
        self._spin.setValue(v)
        self._updating = False
        self._deg_lbl.setText(f"{v / 4095 * 360:.1f}°")
        self.position_changed.emit(self.servo_id, v)

    def _on_spin(self, v: int):
        if self._updating:
            return
        self._updating = True
        self._slider.setValue(v)
        self._updating = False
        self._deg_lbl.setText(f"{v / 4095 * 360:.1f}°")
        self.position_changed.emit(self.servo_id, v)

    def set_position(self, pos: int):
        """Programmatically set the position (e.g. from a 'Read Current' response)."""
        self._updating = True
        self._slider.setValue(pos)
        self._spin.setValue(pos)
        self._deg_lbl.setText(f"{pos / 4095 * 360:.1f}°")
        self._updating = False

    @property
    def position(self) -> int:
        return self._spin.value()


class SyncTab(QWidget):
    """Servo Group / Sync Control tab."""

    # ── outgoing signals ──────────────────────────────────────────────
    sync_write_requested    = Signal(object)  # {servo_id: position} — must use object, not dict!
    read_position_requested = Signal(int)    # single servo_id
    torque_off_requested    = Signal(list)   # list[int] servo_ids
    homing_started          = Signal()
    homing_complete         = Signal()
    home_requested          = Signal(object)  # {servo_id: position}
    groups_changed          = Signal(dict)    # {name: [sorted ids]}

    # Path for home pose persistence
    _HOME_FILE = Path(os.path.dirname(os.path.dirname(__file__))) / "home_pose.json"

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)

        # ── state ──────────────────────────────────────────────────────
        self._all_servos: list[int]           = []   # all connected servo IDs
        self._groups: Dict[str, Set[int]]     = {}   # group_name → set of servo IDs
        self._row_widgets: Dict[int, _ServoRow] = {} # servo_id → row widget
        self._current_group: str | None       = None

        # Homing state
        self._home_positions: Dict[int, int]  = {}   # servo_id → home position
        self._home_enabled: Dict[int, bool]   = {}   # servo_id → enabled for homing
        self._latest_telemetry: Dict[int, dict] = {} # for "moving" check
        self._home_checks: Dict[int, QCheckBox] = {} # servo_id → enable checkbox
        self._home_spins: Dict[int, QSpinBox]   = {} # servo_id → home position spinbox

        self._load_home_pose()
        self._build_ui()

    # ── UI Construction ───────────────────────────────────────────────

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(4)
        root.addWidget(splitter)

        # Left panel: group list + homing
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)
        left_layout.addWidget(self._build_group_panel(), stretch=1)
        left_layout.addWidget(self._build_homing_panel())
        splitter.addWidget(left)

        # Right panel: servo assignment + position editor
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(8, 8, 8, 8)
        right_layout.setSpacing(6)

        right_layout.addWidget(self._build_assignment_panel())
        right_layout.addWidget(self._build_position_panel(), stretch=1)
        right_layout.addWidget(self._build_action_bar())

        splitter.addWidget(right)
        splitter.setSizes([240, 760])
        splitter.setStretchFactor(1, 1)

    def _build_group_panel(self) -> QWidget:
        panel = QGroupBox("GROUPS")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(6, 14, 6, 6)
        layout.setSpacing(4)
        panel.setFixedWidth(200)

        self._group_list = QListWidget()
        self._group_list.setSelectionMode(QListWidget.SingleSelection)
        self._group_list.currentTextChanged.connect(self._on_group_selected)
        self._group_list.itemDoubleClicked.connect(self._rename_group)
        layout.addWidget(self._group_list, stretch=1)

        btn_row = QHBoxLayout()
        add_btn = QPushButton("＋ Add")
        add_btn.setObjectName("btn_success")
        add_btn.setFixedHeight(26)
        add_btn.clicked.connect(self._add_group)
        btn_row.addWidget(add_btn)

        del_btn = QPushButton("🗑 Remove")
        del_btn.setObjectName("btn_danger")
        del_btn.setFixedHeight(26)
        del_btn.clicked.connect(self._remove_group)
        btn_row.addWidget(del_btn)

        layout.addLayout(btn_row)

        hint = QLabel("Double-click to rename")
        hint.setStyleSheet("color: #484f58; font-size: 10px;")
        hint.setAlignment(Qt.AlignCenter)
        layout.addWidget(hint)

        return panel

    def _build_assignment_panel(self) -> QGroupBox:
        self._assign_box = QGroupBox("ASSIGN SERVOS  (select group first)")
        assign_layout = QVBoxLayout(self._assign_box)
        assign_layout.setContentsMargins(8, 14, 8, 8)
        assign_layout.setSpacing(4)

        self._assign_scroll = QScrollArea()
        self._assign_scroll.setWidgetResizable(True)
        self._assign_scroll.setFixedHeight(90)
        self._assign_scroll.setStyleSheet(
            "QScrollArea { border: none; background: transparent; }"
        )

        self._assign_inner = QWidget()
        self._assign_inner_layout = QHBoxLayout(self._assign_inner)
        self._assign_inner_layout.setContentsMargins(0, 0, 0, 0)
        self._assign_inner_layout.setSpacing(10)
        self._assign_inner_layout.addStretch()

        self._assign_scroll.setWidget(self._assign_inner)
        assign_layout.addWidget(self._assign_scroll)

        self._no_servos_lbl = QLabel(
            "No servos connected yet — scan for servos first."
        )
        self._no_servos_lbl.setStyleSheet("color: #484f58; font-size: 11px;")
        self._no_servos_lbl.setAlignment(Qt.AlignCenter)
        assign_layout.addWidget(self._no_servos_lbl)

        return self._assign_box

    def _build_position_panel(self) -> QGroupBox:
        self._pos_box = QGroupBox("GOAL POSITIONS")
        pos_layout = QVBoxLayout(self._pos_box)
        pos_layout.setContentsMargins(6, 14, 6, 6)
        pos_layout.setSpacing(0)

        # Column headers
        header = QHBoxLayout()
        header.setContentsMargins(6, 0, 6, 4)
        for text, width, align in [
            ("Servo", 36, Qt.AlignRight),
            ("Position  (0 ─────── 4095)", 0, Qt.AlignLeft),
            ("Steps", 72, Qt.AlignRight),
            ("Angle", 50, Qt.AlignLeft),
            ("", 28, Qt.AlignCenter),
        ]:
            lbl = QLabel(text)
            lbl.setStyleSheet("color: #8b949e; font-size: 10px;")
            lbl.setAlignment(align | Qt.AlignVCenter)
            if width:
                lbl.setFixedWidth(width)
            header.addWidget(lbl, 0 if width else 1)
        pos_layout.addLayout(header)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color: #30363d;")
        pos_layout.addWidget(sep)

        # Scroll area for servo rows
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(
            "QScrollArea { border: none; background: #0d1117; }"
        )

        self._rows_container = QWidget()
        self._rows_layout = QVBoxLayout(self._rows_container)
        self._rows_layout.setContentsMargins(0, 4, 0, 4)
        self._rows_layout.setSpacing(2)

        self._empty_lbl = QLabel(
            "Select or create a group, then assign servos to see position controls here."
        )
        self._empty_lbl.setAlignment(Qt.AlignCenter)
        self._empty_lbl.setStyleSheet("color: #484f58; font-size: 11px; padding: 20px;")
        self._rows_layout.addWidget(self._empty_lbl)
        self._rows_layout.addStretch()

        scroll.setWidget(self._rows_container)
        pos_layout.addWidget(scroll, stretch=1)

        return self._pos_box

    def _build_action_bar(self) -> QWidget:
        bar = QWidget()
        bar.setStyleSheet("background: #161b22; border-top: 1px solid #30363d;")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(10)

        # Sync move (primary action)
        self._sync_btn = QPushButton("▶  Sync Move")
        self._sync_btn.setObjectName("btn_success")
        self._sync_btn.setFixedHeight(34)
        self._sync_btn.setToolTip(
            "Send all goal positions to the group's servos in ONE bus packet.\n"
            "All servos start moving simultaneously."
        )
        self._sync_btn.clicked.connect(self._fire_sync_move)
        layout.addWidget(self._sync_btn)

        # Read all current positions
        read_btn = QPushButton("↺  Read All Current")
        read_btn.setObjectName("btn_flat")
        read_btn.setFixedHeight(34)
        read_btn.setToolTip("Fill all sliders with current servo positions.")
        read_btn.clicked.connect(self._read_all_current)
        layout.addWidget(read_btn)

        # Set all to mid-point
        mid_btn = QPushButton("⟲  Set All to Centre")
        mid_btn.setObjectName("btn_flat")
        mid_btn.setFixedHeight(34)
        mid_btn.setToolTip("Set all sliders to 2048 (180°, centre position).")
        mid_btn.clicked.connect(self._set_all_centre)
        layout.addWidget(mid_btn)

        layout.addStretch()

        # Stop group
        stop_btn = QPushButton("⬛  Stop Group")
        stop_btn.setObjectName("btn_warn")
        stop_btn.setFixedHeight(34)
        stop_btn.setToolTip("Disable torque on all servos in the current group.")
        stop_btn.clicked.connect(self._stop_group)
        layout.addWidget(stop_btn)

        # Status label
        self._status_lbl = QLabel("No group selected.")
        self._status_lbl.setStyleSheet("color: #8b949e; font-size: 11px; margin-left: 10px;")
        layout.addWidget(self._status_lbl)

        return bar

    # ── Group Management ──────────────────────────────────────────────

    def _add_group(self):
        name, ok = QInputDialog.getText(
            self, "New Group", "Group name:",
            text=f"Group {len(self._groups) + 1}"
        )
        if not ok or not name.strip():
            return
        name = name.strip()
        if name in self._groups:
            QMessageBox.warning(self, "Duplicate", f"A group named '{name}' already exists.")
            return
        self._groups[name] = set()
        item = QListWidgetItem(name)
        self._group_list.addItem(item)
        self._group_list.setCurrentItem(item)
        self.groups_changed.emit(self.get_groups_dict())

    def _remove_group(self):
        item = self._group_list.currentItem()
        if item is None:
            return
        name = item.text()
        reply = QMessageBox.question(
            self, "Remove Group",
            f"Remove group '{name}'?\nServos will be unassigned but not stopped.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        del self._groups[name]
        self._group_list.takeItem(self._group_list.row(item))
        if self._current_group == name:
            self._current_group = None
            self._refresh_rows()
        self.groups_changed.emit(self.get_groups_dict())

    def _rename_group(self, item: QListWidgetItem):
        old_name = item.text()
        new_name, ok = QInputDialog.getText(
            self, "Rename Group", "New name:", text=old_name
        )
        if not ok or not new_name.strip() or new_name.strip() == old_name:
            return
        new_name = new_name.strip()
        if new_name in self._groups:
            QMessageBox.warning(self, "Duplicate", f"A group named '{new_name}' already exists.")
            return
        self._groups[new_name] = self._groups.pop(old_name)
        item.setText(new_name)
        if self._current_group == old_name:
            self._current_group = new_name
        self.groups_changed.emit(self.get_groups_dict())

    @Slot(str)
    def _on_group_selected(self, name: str):
        self._current_group = name if name else None
        self._refresh_assign_checkboxes()
        self._refresh_rows()
        grp_servos = sorted(self._groups.get(name, set())) if name else []
        if name:
            self._status_lbl.setText(
                f"Group '{name}' — {len(grp_servos)} servo(s) assigned."
            )
        else:
            self._status_lbl.setText("No group selected.")

    # ── Servo Checkbox Panel ──────────────────────────────────────────

    def _refresh_assign_checkboxes(self):
        """Rebuild the servo checkbox row for the currently selected group."""
        # Clear existing checkboxes
        while self._assign_inner_layout.count() > 1:  # keep trailing stretch
            item = self._assign_inner_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not self._all_servos:
            self._no_servos_lbl.setVisible(True)
            self._assign_scroll.setVisible(False)
            return

        self._no_servos_lbl.setVisible(False)
        self._assign_scroll.setVisible(True)

        assigned = self._groups.get(self._current_group, set()) if self._current_group else set()
        for sid in sorted(self._all_servos):
            cb = QCheckBox(f"Servo #{sid}")
            cb.setChecked(sid in assigned)
            cb.toggled.connect(lambda checked, s=sid: self._on_servo_toggled(s, checked))
            self._assign_inner_layout.insertWidget(
                self._assign_inner_layout.count() - 1, cb  # insert before stretch
            )

    def _on_servo_toggled(self, servo_id: int, checked: bool):
        if self._current_group is None:
            return
        if checked:
            self._groups[self._current_group].add(servo_id)
        else:
            self._groups[self._current_group].discard(servo_id)
        self._refresh_rows()
        grp_servos = sorted(self._groups[self._current_group])
        self._status_lbl.setText(
            f"Group '{self._current_group}' — {len(grp_servos)} servo(s) assigned."
        )
        self.groups_changed.emit(self.get_groups_dict())
        self._assign_box.setTitle(
            f"ASSIGN SERVOS  ─  {self._current_group}" if self._current_group
            else "ASSIGN SERVOS  (select group first)"
        )

    # ── Position Row Panel ────────────────────────────────────────────

    def _refresh_rows(self):
        """Rebuild the position editor rows for the current group's servos.

        IMPORTANT: _empty_lbl must NEVER be deleteLater()-ed. It is a permanent
        widget that is simply added/removed from the layout and shown/hidden.
        Calling deleteLater() on it would make it a dangling C++ pointer and
        silently crash this slot on every subsequent call.
        """
        # Remove all items from the layout. Delete _ServoRow instances but
        # keep _empty_lbl alive — just detach it from the layout.
        while self._rows_layout.count() > 0:
            item = self._rows_layout.takeAt(0)
            w = item.widget()
            if w is not None and w is not self._empty_lbl:
                w.deleteLater()   # only delete transient servo rows

        self._row_widgets.clear()

        grp = self._groups.get(self._current_group, set()) if self._current_group else set()
        members = sorted(grp)

        if not members:
            # Re-attach the empty label and show it
            self._rows_layout.addWidget(self._empty_lbl)
            self._empty_lbl.show()
            self._rows_layout.addStretch()
            self._sync_btn.setEnabled(False)
            self._pos_box.setTitle("GOAL POSITIONS")
            return

        # Hide the empty label (it's detached from layout, so just hide it)
        self._empty_lbl.hide()
        self._sync_btn.setEnabled(True)

        for idx, sid in enumerate(members):
            row = _ServoRow(sid)
            row.read_requested.connect(self.read_position_requested)
            self._rows_layout.addWidget(row)
            self._row_widgets[sid] = row
            # Subtle alternating background
            row.setStyleSheet(
                "background: #0d1117;" if idx % 2 == 1
                else "background: #161b22; border-radius: 4px;"
            )

        self._rows_layout.addStretch()
        self._pos_box.setTitle(
            f"GOAL POSITIONS  ─  {self._current_group}" if self._current_group
            else "GOAL POSITIONS"
        )


    # ── Action Bar ────────────────────────────────────────────────────

    def _fire_sync_move(self):
        if not self._row_widgets:
            self._status_lbl.setText("⚠  No servos in this group.")
            return
        payload = {sid: row.position for sid, row in self._row_widgets.items()}
        self.sync_write_requested.emit(payload)
        ids = ", ".join(f"#{sid}→{pos}" for sid, pos in payload.items())
        self._status_lbl.setText(f"✔ Sync sent: {ids}")
        # Flash button to confirm
        self._sync_btn.setEnabled(False)
        QTimer.singleShot(600, lambda: self._sync_btn.setEnabled(bool(self._row_widgets)))

    def _read_all_current(self):
        for sid in list(self._row_widgets):
            self.read_position_requested.emit(sid)

    def _set_all_centre(self):
        for row in self._row_widgets.values():
            row.set_position(2048)

    def _stop_group(self):
        if not self._row_widgets:
            self._status_lbl.setText("⚠ No servos to stop.")
            return
        ids = sorted(self._row_widgets.keys())
        self.torque_off_requested.emit(ids)
        self._status_lbl.setText(f"⬛ Torque OFF sent to {ids}")

    # ── Public API (called from main_window) ──────────────────────────

    @Slot(int)
    def add_servo(self, servo_id: int):
        """Register a newly connected servo."""
        if servo_id not in self._all_servos:
            self._all_servos.append(servo_id)
            self._all_servos.sort()
        self._refresh_assign_checkboxes()
        self._refresh_home_table()

    @Slot()
    def clear_servos(self):
        """Called on disconnect — clear all known servos and group assignments."""
        self._all_servos.clear()
        for grp in self._groups.values():
            grp.clear()
        self._row_widgets.clear()
        self._refresh_assign_checkboxes()
        self._refresh_rows()
        self._refresh_home_table()
        self._status_lbl.setText("Disconnected.")

    def get_groups_dict(self) -> dict:
        """Return groups as {name: [sorted servo_ids]} for external consumers."""
        return {name: sorted(ids) for name, ids in self._groups.items()}

    @Slot(int, int)
    def on_position_read(self, servo_id: int, pos: int):
        """Fill the row slider when a 'read current' response arrives."""
        if servo_id in self._row_widgets:
            self._row_widgets[servo_id].set_position(pos)

    @Slot(dict)
    def on_sync_write_done(self, sent: dict):
        """Optional: confirm which positions were actually written."""
        if sent:
            ids = ", ".join(f"#{k}→{v}" for k, v in sent.items())
            self._status_lbl.setText(f"✔ Confirmed: {ids}")

    def update_telemetry(self, servo_id: int, data: dict):
        """Cache latest telemetry for moving-check in homing safety dialog."""
        self._latest_telemetry[servo_id] = data

    # ── Homing ─────────────────────────────────────────────────────────

    def _build_homing_panel(self) -> QGroupBox:
        """Collapsible homing section in the left panel."""
        box = QGroupBox("🏠 Homing")
        box.setCheckable(True)
        box.setChecked(True)
        box.setStyleSheet(
            "QGroupBox { font-weight: bold; color: #58a6ff; padding-top: 14px; }"
        )
        v = QVBoxLayout(box)
        v.setContentsMargins(8, 4, 8, 8)
        v.setSpacing(4)

        # Scrollable area for per-servo home rows
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMaximumHeight(180)
        scroll.setStyleSheet("QScrollArea { border: none; }")

        self._home_container = QWidget()
        self._home_layout = QVBoxLayout(self._home_container)
        self._home_layout.setContentsMargins(0, 0, 0, 0)
        self._home_layout.setSpacing(2)
        self._home_layout.addStretch()
        scroll.setWidget(self._home_container)
        v.addWidget(scroll)

        # Buttons
        set_btn = QPushButton("📍 Set Current as Home")
        set_btn.setObjectName("btn_flat")
        set_btn.setToolTip("Read current positions from all servos and save as home pose.")
        set_btn.clicked.connect(self._set_current_as_home)
        v.addWidget(set_btn)

        home_btn = QPushButton("🏠 Home All Servos")
        home_btn.setObjectName("btn_success")
        home_btn.setToolTip("Send all enabled servos to their home positions.")
        home_btn.clicked.connect(self._home_all)
        v.addWidget(home_btn)

        self._home_status = QLabel("No servos")
        self._home_status.setStyleSheet("color: #8b949e; font-size: 10px;")
        self._home_status.setAlignment(Qt.AlignCenter)
        v.addWidget(self._home_status)

        return box

    def _refresh_home_table(self):
        """Rebuild the per-servo homing rows when servos change."""
        # Clear existing rows (keep the stretch at the end)
        while self._home_layout.count() > 1:
            item = self._home_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self._home_checks.clear()
        self._home_spins.clear()

        for sid in self._all_servos:
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(4)

            cb = QCheckBox()
            cb.setChecked(self._home_enabled.get(sid, True))
            cb.setToolTip(f"Include servo #{sid} in homing")
            cb.toggled.connect(lambda checked, s=sid: self._on_home_enable_toggled(s, checked))
            h.addWidget(cb)
            self._home_checks[sid] = cb

            lbl = QLabel(f"#{sid}")
            lbl.setFixedWidth(30)
            lbl.setStyleSheet("color: #c9d1d9; font-weight: bold; font-size: 11px;")
            h.addWidget(lbl)

            spin = QSpinBox()
            spin.setRange(0, 4095)
            spin.setValue(self._home_positions.get(sid, 2048))
            spin.setToolTip(f"Home position for servo #{sid}")
            spin.valueChanged.connect(lambda v, s=sid: self._on_home_pos_changed(s, v))
            h.addWidget(spin)
            self._home_spins[sid] = spin

            self._home_layout.insertWidget(self._home_layout.count() - 1, row)

        n = len(self._all_servos)
        self._home_status.setText(f"{n} servo{'s' if n != 1 else ''}" if n else "No servos")

    def _on_home_enable_toggled(self, servo_id: int, checked: bool):
        self._home_enabled[servo_id] = checked
        self._save_home_pose()

    def _on_home_pos_changed(self, servo_id: int, value: int):
        self._home_positions[servo_id] = value
        self._save_home_pose()

    def _set_current_as_home(self):
        """Read current positions from latest telemetry and save as home."""
        if not self._all_servos:
            self._home_status.setText("⚠ No servos connected")
            return
        count = 0
        for sid in self._all_servos:
            telem = self._latest_telemetry.get(sid)
            if telem and "position" in telem:
                pos = int(telem["position"])
                self._home_positions[sid] = pos
                self._home_enabled[sid] = True
                if sid in self._home_spins:
                    self._home_spins[sid].setValue(pos)
                if sid in self._home_checks:
                    self._home_checks[sid].setChecked(True)
                count += 1
        self._save_home_pose()
        self._home_status.setText(f"✔ Home set from {count} servo{'s' if count != 1 else ''}")

    def _home_all(self):
        """Send all enabled servos to their home positions."""
        targets = {
            sid: self._home_positions.get(sid, 2048)
            for sid in self._all_servos
            if self._home_enabled.get(sid, True)
        }
        if not targets:
            self._home_status.setText("⚠ No servos enabled for homing")
            return

        # Safety check: any servo currently moving?
        moving = [
            sid for sid in targets
            if self._latest_telemetry.get(sid, {}).get("moving", False)
        ]
        if moving:
            ids_str = ", ".join(f"#{s}" for s in moving)
            reply = QMessageBox.question(
                self, "Servos Moving",
                f"Servo(s) {ids_str} are currently moving.\n\n"
                "Proceed with homing anyway?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                self._home_status.setText("Homing cancelled.")
                return

        self.homing_started.emit()
        self.home_requested.emit(targets)

        ids_str = ", ".join(f"#{s}→{p}" for s, p in targets.items())
        self._home_status.setText(f"🏠 Homing: {ids_str}")
        self.homing_complete.emit()

    # ── Home Pose Persistence ──────────────────────────────────────────

    def _load_home_pose(self):
        """Load home positions from JSON file."""
        try:
            if self._HOME_FILE.exists():
                data = json.loads(self._HOME_FILE.read_text())
                self._home_positions = {
                    int(k): int(v) for k, v in data.get("home_positions", {}).items()
                }
                self._home_enabled = {
                    int(sid): True for sid in data.get("enabled_servos", [])
                }
                # Also mark servos NOT in enabled list as disabled
                for sid in self._home_positions:
                    if sid not in self._home_enabled:
                        self._home_enabled[sid] = False
        except Exception:
            pass  # start fresh if file is corrupt

    def _save_home_pose(self):
        """Save home positions to JSON file."""
        data = {
            "home_positions": {str(k): v for k, v in self._home_positions.items()},
            "enabled_servos": [
                sid for sid, en in self._home_enabled.items() if en
            ],
        }
        try:
            self._HOME_FILE.write_text(json.dumps(data, indent=2))
        except Exception:
            pass  # silent fail on write error
