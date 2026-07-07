"""ControlTableTab — Tab 4: Full ST3215 register map viewer/editor.

FILE: widgets/control_table_tab.py
PURPOSE: Displays all hardware registers (from REGISTER_MAP in servo_backend.py)
         in a table with address, name, current value, access mode, and description.
         Users can double-click writable registers to edit values and write them back.
CALLED BY: main_window._build_central() → ControlTableTab()
EMITS SIGNALS: read_requested(int), write_requested(int, int, int)
               — consumed by main_window._wire_widgets → backend.read_all_registers/write_register
KEY METHODS:
  • __init__           — builds table UI [USER-DEFINED]
  • set_servo(id)      — set the active servo [CALLED BY: main_window._on_servo_selected]
  • populate_registers — fill table with read data [CALLED BY: backend.registers_read signal]
  • _on_cell_changed   — detect edits and emit write_requested [triggered by table edit]
USES: QTableWidget, QTableWidgetItem [PySide6]
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QTableWidget, QTableWidgetItem, QPushButton,
    QLabel, QHeaderView, QAbstractItemView, QMessageBox,
)
from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QColor, QBrush, QFont


class ControlTableTab(QWidget):
    """Display and edit the full ST3215 register map."""

    read_requested  = Signal(int)          # servo_id
    write_requested = Signal(int, int, int)  # servo_id, addr, value

    def __init__(self, parent=None):
        super().__init__(parent)
        self._servo_id = -1
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # ─ Title / buttons ─────────────────────────────────────────
        hdr = QHBoxLayout()
        title = QLabel("Control Table — ST3215 Register Map")
        title.setStyleSheet(
            "color: #58a6ff; font-size: 14px; font-weight: bold; letter-spacing: 1px;"
        )
        hdr.addWidget(title)
        hdr.addStretch()

        self._read_btn = QPushButton("📖  Read All")
        self._read_btn.clicked.connect(self._read_all)
        hdr.addWidget(self._read_btn)

        self._write_btn = QPushButton("✍  Write Selected")
        self._write_btn.setObjectName("btn_warn")
        self._write_btn.clicked.connect(self._write_selected)
        hdr.addWidget(self._write_btn)

        root.addLayout(hdr)

        # ─ Info ─────────────────────────────────────────────────────
        info = QLabel(
            "Double-click a RW cell to edit its value, then click Write Selected to apply."
        )
        info.setStyleSheet("color: #8b949e; font-size: 11px;")
        root.addWidget(info)

        # ─ Table ────────────────────────────────────────────────────
        self._table = QTableWidget()
        self._table.setColumnCount(5)
        self._table.setHorizontalHeaderLabels(
            ["Addr (hex)", "Name", "Value", "Access", "Description"]
        )
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        hdr_h = self._table.horizontalHeader()
        hdr_h.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hdr_h.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hdr_h.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        hdr_h.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        hdr_h.setSectionResizeMode(4, QHeaderView.Stretch)
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QAbstractItemView.DoubleClicked)
        root.addWidget(self._table, stretch=1)

        self._status_lbl = QLabel("No servo selected")
        self._status_lbl.setStyleSheet("color: #8b949e; font-size: 11px;")
        root.addWidget(self._status_lbl)

    # ── Public API ────────────────────────────────────────────────────
    def set_servo(self, servo_id: int):
        self._servo_id = servo_id
        self._status_lbl.setText(f"Servo #{servo_id} — click Read All to refresh")

    def populate_registers(self, servo_id: int, reg_list: list):
        """Called with backend.registers_read result."""
        if servo_id != self._servo_id:
            return
        self._table.setRowCount(0)
        mono = QFont("Consolas", 10)
        ro_color = QColor("#21262d")
        rw_color = QColor("#1c2128")
        disabled_fg = QColor("#484f58")

        for reg in reg_list:
            row = self._table.rowCount()
            self._table.insertRow(row)

            addr_item = QTableWidgetItem(f"0x{reg['addr']:02X}")
            addr_item.setFont(mono)
            addr_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
            self._table.setItem(row, 0, addr_item)

            name_item = QTableWidgetItem(reg["name"])
            name_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
            self._table.setItem(row, 1, name_item)

            val_str = str(reg["value"]) if reg["value"] is not None else "—"
            val_item = QTableWidgetItem(val_str)
            val_item.setFont(mono)
            val_item.setData(Qt.UserRole, reg["addr"])
            if reg["access"] == "R":
                val_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
                val_item.setForeground(QBrush(disabled_fg))
            else:
                val_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsEditable)
                val_item.setForeground(QBrush(QColor("#c9d1d9")))
            self._table.setItem(row, 2, val_item)

            acc_item = QTableWidgetItem(reg["access"])
            acc_item.setTextAlignment(Qt.AlignCenter)
            acc_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
            if reg["access"] == "R":
                acc_item.setForeground(QBrush(disabled_fg))
            else:
                acc_item.setForeground(QBrush(QColor("#2ea043")))
            self._table.setItem(row, 3, acc_item)

            desc_item = QTableWidgetItem(reg["desc"])
            desc_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
            desc_item.setForeground(QBrush(QColor("#8b949e")))
            self._table.setItem(row, 4, desc_item)

            # Row background
            bg = rw_color if reg["access"] == "RW" else ro_color
            for col in range(5):
                item = self._table.item(row, col)
                if item:
                    item.setBackground(QBrush(bg))

        self._status_lbl.setText(f"Servo #{servo_id} — {len(reg_list)} registers loaded")

    # ── Internals ─────────────────────────────────────────────────────
    def _read_all(self):
        if self._servo_id < 0:
            return
        self.read_requested.emit(self._servo_id)
        self._status_lbl.setText("Reading …")

    def _write_selected(self):
        if self._servo_id < 0:
            return
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            QMessageBox.information(
                self, "Nothing selected",
                "Select one or more RW rows to write."
            )
            return
        for idx in rows:
            row = idx.row()
            acc_item = self._table.item(row, 3)
            if acc_item and acc_item.text() != "RW":
                continue
            val_item = self._table.item(row, 2)
            addr_item = self._table.item(row, 0)
            if not val_item or not addr_item:
                continue
            try:
                addr = int(addr_item.text(), 16)
                val  = int(val_item.text())
            except ValueError:
                continue
            self.write_requested.emit(self._servo_id, addr, val)
