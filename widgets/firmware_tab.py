"""FirmwareTab — Tab 5: Device configuration (ID, baud, limits, offset, diagnostics).

FILE: widgets/firmware_tab.py
PURPOSE: Provides UI for configuring servo hardware settings: change servo ID,
         change baud rate, set angle limits, view diagnostic info. All changes
         are sent to servo EEPROM via backend methods.
CALLED BY: main_window._build_central() → FirmwareTab()
EMITS SIGNALS: id_change_requested(int, int), baud_change_requested(int, int),
               limits_requested(int, int, int)
               — consumed by main_window._wire_widgets → backend methods
KEY METHODS:
  • __init__           — builds config panels [USER-DEFINED]
  • set_servo(id)      — set active servo [CALLED BY: main_window._on_servo_selected]
  • update_telemetry   — show live voltage/temp [CALLED BY: main_window._on_telemetry]
USES: QSpinBox, QComboBox, QPushButton, BAUD_CODES [PySide6, servo_backend]
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QGroupBox, QLabel, QSpinBox, QPushButton, QComboBox,
    QMessageBox, QFrame,
)
from PySide6.QtCore import Signal, Qt
from backend.servo_backend import BAUD_CODES


BAUD_LABELS = [
    ("1 000 000 bps  (code 0)", 0),
    ("500 000 bps    (code 1)", 1),
    ("250 000 bps    (code 2)", 2),
    ("128 000 bps    (code 3)", 3),
    ("115 200 bps    (code 4)", 4),
    ("76 800 bps     (code 5)", 5),
    ("57 600 bps     (code 6)", 6),
    ("38 400 bps     (code 7)", 7),
]


class FirmwareTab(QWidget):
    """ID change, baudrate change, angle limits, position offset, diagnostics."""

    id_change_requested    = Signal(int, int)   # old_id, new_id
    baud_change_requested  = Signal(int, int)   # servo_id, baud_code
    limits_requested       = Signal(int, int, int)  # servo_id, min, max
    offset_requested       = Signal(int, int)   # servo_id, offset (signed)
    scan_requested         = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._servo_id = -1
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(10)

        title = QLabel("Device Configuration")
        title.setStyleSheet(
            "color: #58a6ff; font-size: 14px; font-weight: bold; letter-spacing: 1px;"
        )
        root.addWidget(title)

        cols = QHBoxLayout()
        cols.setSpacing(12)

        # ─ Column 1: ID & Baud ──────────────────────────────────────
        col1 = QVBoxLayout()

        # Change ID
        id_box = QGroupBox("Change Servo ID")
        id_grid = QGridLayout(id_box)

        id_grid.addWidget(QLabel("Current ID:"), 0, 0)
        self._old_id_spin = QSpinBox()
        self._old_id_spin.setRange(0, 253)
        id_grid.addWidget(self._old_id_spin, 0, 1)

        id_grid.addWidget(QLabel("New ID:"), 1, 0)
        self._new_id_spin = QSpinBox()
        self._new_id_spin.setRange(0, 253)
        self._new_id_spin.setValue(1)
        id_grid.addWidget(self._new_id_spin, 1, 1)

        self._change_id_btn = QPushButton("🔑  Change ID")
        self._change_id_btn.setObjectName("btn_warn")
        self._change_id_btn.clicked.connect(self._change_id)
        id_grid.addWidget(self._change_id_btn, 2, 0, 1, 2)

        warn = QLabel("⚠ ID change is permanent until changed again.")
        warn.setWordWrap(True)
        warn.setStyleSheet("color: #f0c000; font-size: 10px;")
        id_grid.addWidget(warn, 3, 0, 1, 2)

        col1.addWidget(id_box)

        # Change Baudrate
        baud_box = QGroupBox("Change Bus Baudrate")
        baud_v = QVBoxLayout(baud_box)

        self._baud_combo = QComboBox()
        for label, code in BAUD_LABELS:
            self._baud_combo.addItem(label, code)
        baud_v.addWidget(QLabel("New Baudrate:"))
        baud_v.addWidget(self._baud_combo)

        self._change_baud_btn = QPushButton("📡  Change Baudrate")
        self._change_baud_btn.setObjectName("btn_warn")
        self._change_baud_btn.clicked.connect(self._change_baud)
        baud_v.addWidget(self._change_baud_btn)

        baud_warn = QLabel(
            "⚠ After changing baud, reconnect using the new rate."
        )
        baud_warn.setWordWrap(True)
        baud_warn.setStyleSheet("color: #f0c000; font-size: 10px;")
        baud_v.addWidget(baud_warn)

        col1.addWidget(baud_box)
        col1.addStretch()
        cols.addLayout(col1)

        # ─ Column 2: Angle Limits & Position Offset ─────────────────
        col2 = QVBoxLayout()

        lim_box = QGroupBox("Angle Limits (EEPROM)")
        lim_grid = QGridLayout(lim_box)

        lim_grid.addWidget(QLabel("Min Angle (0–4095):"), 0, 0)
        self._min_spin = QSpinBox()
        self._min_spin.setRange(0, 4095)
        self._min_spin.setValue(0)
        lim_grid.addWidget(self._min_spin, 0, 1)

        lim_grid.addWidget(QLabel("Max Angle (0–4095):"), 1, 0)
        self._max_spin = QSpinBox()
        self._max_spin.setRange(0, 4095)
        self._max_spin.setValue(4095)
        lim_grid.addWidget(self._max_spin, 1, 1)

        lim_btn = QPushButton("💾  Write Limits")
        lim_btn.setObjectName("btn_warn")
        lim_btn.clicked.connect(self._write_limits)
        lim_grid.addWidget(lim_btn, 2, 0, 1, 2)

        col2.addWidget(lim_box)

        # Offset
        ofs_box = QGroupBox("Position Offset (Tare)")
        ofs_v = QVBoxLayout(ofs_box)
        ofs_desc = QLabel(
            "Add a signed offset so that mechanical center maps to step 2048."
        )
        ofs_desc.setWordWrap(True)
        ofs_desc.setStyleSheet("color: #8b949e; font-size: 10px;")
        ofs_v.addWidget(ofs_desc)

        ofs_row = QHBoxLayout()
        self._ofs_spin = QSpinBox()
        self._ofs_spin.setRange(-2047, 2047)
        self._ofs_spin.setValue(0)
        ofs_row.addWidget(QLabel("Offset:"))
        ofs_row.addWidget(self._ofs_spin)

        ofs_btn = QPushButton("Apply")
        ofs_btn.setObjectName("btn_warn")
        ofs_btn.clicked.connect(self._write_offset)
        ofs_row.addWidget(ofs_btn)
        ofs_v.addLayout(ofs_row)
        col2.addWidget(ofs_box)
        col2.addStretch()
        cols.addLayout(col2)

        # ─ Column 3: Diagnostics / Info ─────────────────────────────
        col3 = QVBoxLayout()

        info_box = QGroupBox("Servo Information")
        info_v = QVBoxLayout(info_box)

        self._info_labels: dict[str, QLabel] = {}
        for key in ["Servo ID", "Model", "Firmware", "Mode", "Temperature", "Voltage", "Status"]:
            row = QHBoxLayout()
            kl = QLabel(f"{key}:")
            kl.setStyleSheet("color: #8b949e; font-size: 11px;")
            kl.setFixedWidth(90)
            vl = QLabel("—")
            vl.setStyleSheet("color: #c9d1d9; font-size: 11px; font-weight: bold;")
            self._info_labels[key] = vl
            row.addWidget(kl)
            row.addWidget(vl)
            info_v.addLayout(row)

        col3.addWidget(info_box)
        col3.addStretch()
        cols.addLayout(col3)

        root.addLayout(cols)

        # ─ Status bar ────────────────────────────────────────────────
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color: #30363d;")
        root.addWidget(sep)

        self._status_lbl = QLabel("No servo selected")
        self._status_lbl.setStyleSheet("color: #8b949e; font-size: 11px;")
        root.addWidget(self._status_lbl)

    # ── Public API ────────────────────────────────────────────────────
    def set_servo(self, servo_id: int):
        self._servo_id = servo_id
        self._old_id_spin.setValue(servo_id)
        self._info_labels["Servo ID"].setText(str(servo_id))
        self._status_lbl.setText(f"Selected: Servo #{servo_id}")

    def update_telemetry(self, servo_id: int, data: dict):
        if servo_id != self._servo_id:
            return
        self._info_labels["Temperature"].setText(f"{data.get('temperature','—')} °C")
        self._info_labels["Voltage"].setText(f"{data.get('voltage',0.0):.1f} V")

    # ── Internals ─────────────────────────────────────────────────────
    def _change_id(self):
        if self._servo_id < 0:
            QMessageBox.warning(self, "No servo", "Select a servo first.")
            return
        old = self._old_id_spin.value()
        new = self._new_id_spin.value()
        reply = QMessageBox.question(
            self, "Change ID",
            f"Change servo ID from {old} to {new}?\n"
            "This writes to EEPROM and takes effect immediately.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self.id_change_requested.emit(old, new)

    def _change_baud(self):
        if self._servo_id < 0:
            QMessageBox.warning(self, "No servo", "Select a servo first.")
            return
        code = self._baud_combo.currentData()
        reply = QMessageBox.question(
            self, "Change Baudrate",
            f"Change servo #{self._servo_id} to {BAUD_CODES[code]} bps?\n"
            "You will need to reconnect at the new rate.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self.baud_change_requested.emit(self._servo_id, code)

    def _write_limits(self):
        if self._servo_id < 0:
            return
        lo = self._min_spin.value()
        hi = self._max_spin.value()
        if lo >= hi:
            QMessageBox.warning(self, "Invalid", "Min must be < Max.")
            return
        self.limits_requested.emit(self._servo_id, lo, hi)
        self._status_lbl.setText(f"Limits written: {lo}–{hi}")

    def _write_offset(self):
        if self._servo_id < 0:
            return
        ofs = self._ofs_spin.value()
        self.offset_requested.emit(self._servo_id, ofs)
        self._status_lbl.setText(f"Offset applied: {ofs:+d}")
