"""MonitorTab — Tab 1: Live telemetry dashboard + servo control."""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QSlider, QSpinBox, QComboBox,
    QGroupBox, QLCDNumber, QFrame, QSizePolicy,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QColor


class _LCDPanel(QWidget):
    """Labelled LCD number with a coloured border."""

    def __init__(self, label: str, obj_name: str, units: str = "", parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        title = QLabel(label)
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("color: #8b949e; font-size: 10px; font-weight: bold; letter-spacing: 1px;")
        layout.addWidget(title)

        self.lcd = QLCDNumber(7)
        self.lcd.setObjectName(obj_name)
        self.lcd.setSegmentStyle(QLCDNumber.Flat)
        self.lcd.setMinimumHeight(54)
        layout.addWidget(self.lcd)

        if units:
            ulbl = QLabel(units)
            ulbl.setAlignment(Qt.AlignCenter)
            ulbl.setStyleSheet("color: #484f58; font-size: 10px;")
            layout.addWidget(ulbl)

    def set_value(self, v):
        if isinstance(v, float):
            self.lcd.display(f"{v:.2f}")
        else:
            self.lcd.display(str(v))


class MonitorTab(QWidget):
    """Live telemetry + goal position + speed + torque controls."""

    goal_position_changed = Signal(int, int)   # (servo_id, position)
    goal_speed_changed    = Signal(int, int)   # (servo_id, speed)
    acceleration_changed  = Signal(int, int)   # (servo_id, acc)
    torque_toggled        = Signal(int, bool)  # (servo_id, on)
    mode_changed          = Signal(int, int)   # (servo_id, mode)
    rate_changed          = Signal(float)      # hz

    def __init__(self, parent=None):
        super().__init__(parent)
        self._servo_id: int = -1
        self._block_slider = False
        self._build_ui()

    # ── Build UI ─────────────────────────────────────────────────────
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(8)

        # ── No servo selected banner ─────────────────────────────────
        self._banner = QLabel("← Select a servo from the device list to begin monitoring")
        self._banner.setAlignment(Qt.AlignCenter)
        self._banner.setStyleSheet(
            "color: #484f58; font-size: 14px; border: 2px dashed #30363d;"
            "border-radius: 8px; padding: 20px; margin: 10px;"
        )
        root.addWidget(self._banner)

        # ── Main content (hidden until servo selected) ───────────────
        self._content = QWidget()
        cv = QVBoxLayout(self._content)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(8)

        # heading
        self._title_lbl = QLabel("Servo #—")
        self._title_lbl.setStyleSheet(
            "color: #58a6ff; font-size: 14px; font-weight: bold; letter-spacing: 1px;"
        )
        cv.addWidget(self._title_lbl)

        # ── Telemetry LCD panels ─────────────────────────────────────
        lcd_box = QGroupBox("Live Telemetry")
        lcd_layout = QHBoxLayout(lcd_box)
        lcd_layout.setSpacing(10)

        self._pos_lcd  = _LCDPanel("POSITION",    "lcd_position",    "steps")
        self._vel_lcd  = _LCDPanel("VELOCITY",    "lcd_velocity",    "step/s")
        self._load_lcd = _LCDPanel("LOAD",        "lcd_load",        "%")
        self._volt_lcd = _LCDPanel("VOLTAGE",     "lcd_voltage",     "V")
        self._temp_lcd = _LCDPanel("TEMPERATURE", "lcd_temperature", "°C")
        self._cur_lcd  = _LCDPanel("CURRENT",     "lcd_current",     "mA")

        for p in [self._pos_lcd, self._vel_lcd, self._load_lcd,
                  self._volt_lcd, self._temp_lcd, self._cur_lcd]:
            lcd_layout.addWidget(p)

        cv.addWidget(lcd_box)

        # ── Moving indicator ─────────────────────────────────────────
        mov_row = QHBoxLayout()
        mov_row.addStretch()
        mov_lbl = QLabel("Moving:")
        mov_lbl.setStyleSheet("color: #8b949e;")
        mov_row.addWidget(mov_lbl)
        self._moving_dot = QLabel("●")
        self._moving_dot.setStyleSheet("color: #484f58; font-size: 18px;")
        mov_row.addWidget(self._moving_dot)
        mov_row.addStretch()
        cv.addLayout(mov_row)

        # ── Controls ─────────────────────────────────────────────────
        ctrl_row = QHBoxLayout()
        ctrl_row.setSpacing(10)

        # Goal Position group
        gp_box = QGroupBox("Goal Position")
        gp_v = QVBoxLayout(gp_box)
        self._pos_slider = QSlider(Qt.Horizontal)
        self._pos_slider.setRange(0, 4095)
        self._pos_slider.setValue(2048)
        self._pos_slider.setToolTip("0–4095")
        self._pos_slider.valueChanged.connect(self._slider_changed)
        gp_v.addWidget(self._pos_slider)

        pos_spin_row = QHBoxLayout()
        self._pos_spin = QSpinBox()
        self._pos_spin.setRange(0, 4095)
        self._pos_spin.setValue(2048)
        self._pos_spin.setFixedWidth(80)
        self._pos_spin.valueChanged.connect(self._spinbox_changed)
        pos_spin_row.addWidget(QLabel("Value:"))
        pos_spin_row.addWidget(self._pos_spin)
        pos_spin_row.addStretch()
        self._send_pos_btn = QPushButton("Send ▶")
        self._send_pos_btn.setObjectName("btn_success")
        self._send_pos_btn.clicked.connect(self._send_position)
        pos_spin_row.addWidget(self._send_pos_btn)
        gp_v.addLayout(pos_spin_row)
        ctrl_row.addWidget(gp_box, stretch=3)

        # Right panel: Speed / Acc / Mode
        ctl2_box = QGroupBox("Motor Control")
        ctl2_grid = QGridLayout(ctl2_box)

        ctl2_grid.addWidget(QLabel("Speed (step/s):"), 0, 0)
        self._speed_spin = QSpinBox()
        self._speed_spin.setRange(0, 3400)
        self._speed_spin.setValue(1000)
        self._speed_spin.setFixedWidth(80)
        self._speed_btn = QPushButton("Set")
        self._speed_btn.setFixedWidth(50)
        self._speed_btn.clicked.connect(self._send_speed)
        ctl2_grid.addWidget(self._speed_spin, 0, 1)
        ctl2_grid.addWidget(self._speed_btn,  0, 2)

        ctl2_grid.addWidget(QLabel("Accel (×100 s²):"), 1, 0)
        self._acc_spin = QSpinBox()
        self._acc_spin.setRange(0, 254)
        self._acc_spin.setValue(50)
        self._acc_spin.setFixedWidth(80)
        self._acc_btn = QPushButton("Set")
        self._acc_btn.setFixedWidth(50)
        self._acc_btn.clicked.connect(self._send_acc)
        ctl2_grid.addWidget(self._acc_spin, 1, 1)
        ctl2_grid.addWidget(self._acc_btn,  1, 2)

        ctl2_grid.addWidget(QLabel("Mode:"), 2, 0)
        self._mode_combo = QComboBox()
        for m in ["0 – Position", "1 – Wheel", "2 – PWM", "3 – Step"]:
            self._mode_combo.addItem(m)
        self._mode_btn = QPushButton("Set")
        self._mode_btn.setFixedWidth(50)
        self._mode_btn.clicked.connect(self._send_mode)
        ctl2_grid.addWidget(self._mode_combo, 2, 1)
        ctl2_grid.addWidget(self._mode_btn,   2, 2)

        ctrl_row.addWidget(ctl2_box, stretch=2)
        cv.addLayout(ctrl_row)

        # ── Torque + Rate ─────────────────────────────────────────────
        bot_row = QHBoxLayout()
        self._torque_btn = QPushButton("⚡ Torque ON")
        self._torque_btn.setObjectName("btn_success")
        self._torque_btn.setCheckable(True)
        self._torque_btn.setChecked(False)
        self._torque_btn.toggled.connect(self._torque_toggled)
        bot_row.addWidget(self._torque_btn)

        bot_row.addStretch()

        bot_row.addWidget(QLabel("Poll rate:"))
        self._rate_combo = QComboBox()
        for r in ["10 Hz", "20 Hz", "30 Hz", "50 Hz"]:
            self._rate_combo.addItem(r, float(r.split()[0]))
        self._rate_combo.setCurrentIndex(1)   # 20 Hz
        self._rate_combo.currentIndexChanged.connect(
            lambda _: self.rate_changed.emit(self._rate_combo.currentData())
        )
        bot_row.addWidget(self._rate_combo)
        cv.addLayout(bot_row)

        root.addWidget(self._content)
        self._content.setVisible(False)

    # ── API ───────────────────────────────────────────────────────────
    def set_servo(self, servo_id: int):
        self._servo_id = servo_id
        self._banner.setVisible(False)
        self._content.setVisible(True)
        self._title_lbl.setText(f"Servo #{servo_id}")

    def clear_servo(self):
        self._servo_id = -1
        self._banner.setVisible(True)
        self._content.setVisible(False)

    def update_telemetry(self, servo_id: int, data: dict):
        if servo_id != self._servo_id:
            return
        self._pos_lcd.set_value(data.get("position", 0))
        self._vel_lcd.set_value(data.get("velocity", 0))
        self._load_lcd.set_value(round(data.get("load", 0.0), 1))
        self._volt_lcd.set_value(round(data.get("voltage", 0.0), 2))
        self._temp_lcd.set_value(data.get("temperature", 0))
        self._cur_lcd.set_value(round(data.get("current", 0.0), 1))
        moving = data.get("moving", False)
        self._moving_dot.setStyleSheet(
            f"color: {'#2ea043' if moving else '#484f58'}; font-size: 18px;"
        )

    # ── Internal ──────────────────────────────────────────────────────
    def _slider_changed(self, val):
        self._block_slider = True
        self._pos_spin.setValue(val)
        self._block_slider = False

    def _spinbox_changed(self, val):
        if not self._block_slider:
            self._pos_slider.setValue(val)

    def _send_position(self):
        if self._servo_id >= 0:
            self.goal_position_changed.emit(self._servo_id, self._pos_spin.value())

    def _send_speed(self):
        if self._servo_id >= 0:
            self.goal_speed_changed.emit(self._servo_id, self._speed_spin.value())

    def _send_acc(self):
        if self._servo_id >= 0:
            self.acceleration_changed.emit(self._servo_id, self._acc_spin.value())

    def _send_mode(self):
        if self._servo_id >= 0:
            self.mode_changed.emit(self._servo_id, self._mode_combo.currentIndex())

    def _torque_toggled(self, checked: bool):
        if self._servo_id >= 0:
            self.torque_toggled.emit(self._servo_id, checked)
            self._torque_btn.setText("⚡ Torque ON" if checked else "⚡ Torque OFF")
