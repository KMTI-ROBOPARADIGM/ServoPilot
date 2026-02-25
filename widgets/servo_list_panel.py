"""ServoListPanel — left dock widget for port selection and servo discovery."""

import serial.tools.list_ports
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QSizePolicy, QFrame, QAbstractItemView,
)
from PySide6.QtCore import Signal, Qt, QTimer
from PySide6.QtGui import QColor, QFont


BAUD_OPTIONS = [
    ("1 000 000", 1_000_000),
    ("500 000",   500_000),
    ("250 000",   250_000),
    ("128 000",   128_000),
    ("115 200",   115_200),
    ("57 600",    57_600),
    ("38 400",    38_400),
]


class ServoListPanel(QWidget):
    """Left dock: port/baud selector, Scan + Connect, servo table."""

    servo_selected       = Signal(int)        # servo id
    connect_requested    = Signal(str, int)   # (port, baudrate)
    disconnect_requested = Signal()
    scan_requested       = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._connected = False
        self._servos: dict[int, dict] = {}   # id → info dict
        self._build_ui()
        self._refresh_ports()
        # auto-refresh port list every 2 s
        self._port_timer = QTimer(self)
        self._port_timer.timeout.connect(self._refresh_ports)
        self._port_timer.start(2000)

    # ── Build UI ─────────────────────────────────────────────────────
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        # ─ Title ───────────────────────────────────────────────────
        title = QLabel("SERVO DEVICES")
        title.setAlignment(Qt.AlignCenter)
        f = QFont("Segoe UI", 10, QFont.Bold)
        title.setFont(f)
        title.setStyleSheet("color: #58a6ff; letter-spacing: 2px; padding: 4px;")
        layout.addWidget(title)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color: #30363d;")
        layout.addWidget(sep)

        # ─ Port row ────────────────────────────────────────────────
        port_row = QHBoxLayout()
        self._port_combo = QComboBox()
        self._port_combo.setToolTip("Serial port")
        self._port_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        port_row.addWidget(QLabel("Port:"))
        port_row.addWidget(self._port_combo)

        self._refresh_btn = QPushButton("↺")
        self._refresh_btn.setObjectName("btn_flat")
        self._refresh_btn.setFixedWidth(32)
        self._refresh_btn.setToolTip("Refresh port list")
        self._refresh_btn.setStyleSheet("font-size: 16px; font-weight: bold; padding: 0px;")
        self._refresh_btn.clicked.connect(self._refresh_ports)
        port_row.addWidget(self._refresh_btn)
        layout.addLayout(port_row)

        # ─ Baud row ─────────────────────────────────────────────────
        baud_row = QHBoxLayout()
        self._baud_combo = QComboBox()
        for label, val in BAUD_OPTIONS:
            self._baud_combo.addItem(label, val)
        self._baud_combo.setCurrentIndex(0)   # 1 M default
        baud_row.addWidget(QLabel("Baud:"))
        baud_row.addWidget(self._baud_combo)
        layout.addLayout(baud_row)

        # ─ Connect/Disconnect buttons ───────────────────────────────
        btn_row = QHBoxLayout()
        self._connect_btn = QPushButton("Connect")
        self._connect_btn.setObjectName("btn_success")
        self._connect_btn.clicked.connect(self._on_connect)
        btn_row.addWidget(self._connect_btn)

        self._disconnect_btn = QPushButton("Disconnect")
        self._disconnect_btn.setObjectName("btn_danger")
        self._disconnect_btn.setEnabled(False)
        self._disconnect_btn.clicked.connect(self._on_disconnect)
        btn_row.addWidget(self._disconnect_btn)
        layout.addLayout(btn_row)

        # ─ Scan button ──────────────────────────────────────────────
        self._scan_btn = QPushButton("🔍  Scan for Servos")
        self._scan_btn.setEnabled(False)
        self._scan_btn.setToolTip("Scan IDs 0–253 on the bus")
        self._scan_btn.clicked.connect(self._on_scan)
        layout.addWidget(self._scan_btn)

        # ─ Connection status label ──────────────────────────────────
        self._status_lbl = QLabel("Disconnected")
        self._status_lbl.setAlignment(Qt.AlignCenter)
        self._status_lbl.setStyleSheet(
            "color: #8b949e; font-size: 11px; padding: 2px;"
        )
        layout.addWidget(self._status_lbl)

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.HLine)
        sep2.setStyleSheet("color: #30363d;")
        layout.addWidget(sep2)

        # ─ Servo count ──────────────────────────────────────────────
        self._count_lbl = QLabel("No servos found")
        self._count_lbl.setAlignment(Qt.AlignCenter)
        self._count_lbl.setStyleSheet("color: #8b949e; font-size: 11px;")
        layout.addWidget(self._count_lbl)

        # ─ Servo table ──────────────────────────────────────────────
        self._table = QTableWidget()
        self._table.setColumnCount(7)
        self._table.setHorizontalHeaderLabels(
            ["ID", "Model", "FW", "Baud", "Temp °C", "Volt V", "Status"]
        )
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.Stretch)
        hdr.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self._table.verticalHeader().setVisible(False)
        self._table.itemSelectionChanged.connect(self._on_row_changed)
        layout.addWidget(self._table, stretch=1)

    # ── Slots ─────────────────────────────────────────────────────────
    def _refresh_ports(self):
        current = self._port_combo.currentText()
        self._port_combo.blockSignals(True)
        self._port_combo.clear()
        ports = sorted(serial.tools.list_ports.comports(), key=lambda p: p.device)
        for p in ports:
            self._port_combo.addItem(f"{p.device} — {p.description[:30]}", p.device)
        if not ports:
            self._port_combo.addItem("No ports found", "")
        # try to restore previous selection
        for i in range(self._port_combo.count()):
            if current in self._port_combo.itemText(i):
                self._port_combo.setCurrentIndex(i)
                break
        self._port_combo.blockSignals(False)

    def _on_connect(self):
        port = self._port_combo.currentData()
        if not port:
            return
        baud = self._baud_combo.currentData()
        self.connect_requested.emit(port, baud)

    def _on_disconnect(self):
        self.disconnect_requested.emit()

    def _on_scan(self):
        self.scan_requested.emit()
        self._scan_btn.setText("Scanning…")
        self._scan_btn.setEnabled(False)

    def _on_row_changed(self):
        rows = self._table.selectedItems()
        if rows:
            row = self._table.currentRow()
            sid = int(self._table.item(row, 0).text())
            self.servo_selected.emit(sid)

    # ── Public update API ────────────────────────────────────────────
    def on_connected(self):
        self._connected = True
        self._connect_btn.setEnabled(False)
        self._disconnect_btn.setEnabled(True)
        self._scan_btn.setEnabled(True)
        self._status_lbl.setText("● Connected")
        self._status_lbl.setStyleSheet("color: #2ea043; font-size: 11px; font-weight: bold;")

    def on_disconnected(self):
        self._connected = False
        self._connect_btn.setEnabled(True)
        self._disconnect_btn.setEnabled(False)
        self._scan_btn.setEnabled(False)
        self._scan_btn.setText("🔍  Scan for Servos")
        self._status_lbl.setText("Disconnected")
        self._status_lbl.setStyleSheet("color: #8b949e; font-size: 11px;")
        self._table.setRowCount(0)
        self._servos.clear()
        self._count_lbl.setText("No servos found")

    def on_connection_failed(self, msg: str):
        self._status_lbl.setText(f"✗ {msg[:40]}")
        self._status_lbl.setStyleSheet("color: #f85149; font-size: 11px;")

    def on_servos_found(self, ids: list):
        self._scan_btn.setText("🔍  Scan for Servos")
        self._scan_btn.setEnabled(True)
        self._servos = {sid: {} for sid in ids}
        self._count_lbl.setText(f"{len(ids)} servo{'s' if len(ids)!=1 else ''} found")
        self._table.setRowCount(0)
        for sid in sorted(ids):
            row = self._table.rowCount()
            self._table.insertRow(row)
            self._table.setItem(row, 0, QTableWidgetItem(str(sid)))
            self._table.setItem(row, 1, QTableWidgetItem("ST3215"))
            self._table.setItem(row, 2, QTableWidgetItem("—"))
            self._table.setItem(row, 3, QTableWidgetItem("1M"))
            self._table.setItem(row, 4, QTableWidgetItem("—"))
            self._table.setItem(row, 5, QTableWidgetItem("—"))
            status_item = QTableWidgetItem("OK")
            status_item.setForeground(QColor("#2ea043"))
            self._table.setItem(row, 6, status_item)
        # auto-select first
        if ids:
            self._table.selectRow(0)

    def update_telemetry(self, servo_id: int, data: dict):
        for row in range(self._table.rowCount()):
            if int(self._table.item(row, 0).text()) == servo_id:
                temp = data.get("temperature", 0)
                volt = data.get("voltage", 0.0)
                self._table.item(row, 4).setText(f"{temp}")
                self._table.item(row, 5).setText(f"{volt:.1f}")
                # colour-code temperature
                if temp >= 70:
                    self._table.item(row, 4).setForeground(QColor("#f85149"))
                elif temp >= 55:
                    self._table.item(row, 4).setForeground(QColor("#f0c000"))
                else:
                    self._table.item(row, 4).setForeground(QColor("#2ea043"))
                break

    def get_current_baud(self) -> int:
        return self._baud_combo.currentData()

    def get_current_port(self) -> str:
        return self._port_combo.currentData() or ""
