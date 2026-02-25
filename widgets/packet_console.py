"""PacketConsole — bottom-dock hex packet logger and raw sender."""

from datetime import datetime
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTextEdit,
    QPushButton, QLineEdit, QLabel, QSpinBox,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QColor, QTextCursor


class PacketConsole(QWidget):
    """Bottom dock: timestamped log + raw hex packet sender."""

    raw_send_requested = Signal(int, bytes)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(4)

        # ─ Controls row ─────────────────────────────────────────────
        ctrl = QHBoxLayout()

        ctrl.addWidget(QLabel("ID:"))
        self._id_spin = QSpinBox()
        self._id_spin.setRange(0, 253)
        self._id_spin.setFixedWidth(52)
        ctrl.addWidget(self._id_spin)

        ctrl.addWidget(QLabel("Hex:"))
        self._hex_edit = QLineEdit()
        self._hex_edit.setPlaceholderText("e.g.  FF FF 01 04 03 1E 00 ...")
        self._hex_edit.setFont(QFont("Consolas", 11))
        self._hex_edit.returnPressed.connect(self._send)
        ctrl.addWidget(self._hex_edit, stretch=1)

        send_btn = QPushButton("Send")
        send_btn.setObjectName("btn_warn")
        send_btn.setFixedWidth(60)
        send_btn.clicked.connect(self._send)
        ctrl.addWidget(send_btn)

        clear_btn = QPushButton("Clear")
        clear_btn.setObjectName("btn_flat")
        clear_btn.setFixedWidth(60)
        clear_btn.clicked.connect(self._clear)
        ctrl.addWidget(clear_btn)

        layout.addLayout(ctrl)

        # ─ Log area ─────────────────────────────────────────────────
        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setLineWrapMode(QTextEdit.NoWrap)
        self._log.setFont(QFont("Consolas", 10))
        self._log.setMaximumHeight(160)
        layout.addWidget(self._log)

    def _send(self):
        raw_hex = self._hex_edit.text().strip().replace(" ", "")
        if not raw_hex:
            return
        try:
            data = bytes.fromhex(raw_hex)
        except ValueError:
            self.append_log("[ERROR] Invalid hex string", error=True)
            return
        sid = self._id_spin.value()
        self.raw_send_requested.emit(sid, data)
        self.append_log(f"[TX] ID={sid}  {' '.join(f'{b:02X}' for b in data)}")

    def _clear(self):
        self._log.clear()

    def append_log(self, message: str, error: bool = False, rx: bool = False):
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        if error:
            colour = "#f85149"
        elif rx:
            colour = "#58a6ff"
        elif "[TX]" in message:
            colour = "#ffa657"
        else:
            colour = "#00ff88" if "[CONNECT]" in message or "OK" in message else "#8b949e"
        html = (
            f'<span style="color:#484f58">[{ts}]</span> '
            f'<span style="color:{colour}">{message}</span>'
        )
        self._log.append(html)
        self._log.moveCursor(QTextCursor.End)
