"""ServoPilot Dark Robotics Theme — professional QSS stylesheet."""


def get_stylesheet() -> str:
    return """
/* ── Global ─────────────────────────────────────────────────────── */
QWidget {
    background-color: #0d1117;
    color: #c9d1d9;
    font-family: "Segoe UI", "Arial", sans-serif;
    font-size: 12px;
    selection-background-color: #1f6feb;
    selection-color: #ffffff;
}

/* ── Main Window ─────────────────────────────────────────────────── */
QMainWindow {
    background-color: #0d1117;
}

QMainWindow::separator {
    background: #21262d;
    width: 3px;
    height: 3px;
}

/* ── Menu Bar ────────────────────────────────────────────────────── */
QMenuBar {
    background-color: #161b22;
    color: #c9d1d9;
    border-bottom: 1px solid #21262d;
    padding: 2px;
}

QMenuBar::item {
    padding: 4px 10px;
    border-radius: 4px;
}

QMenuBar::item:selected {
    background-color: #1f6feb;
    color: #ffffff;
}

QMenu {
    background-color: #161b22;
    border: 1px solid #30363d;
    border-radius: 6px;
    padding: 4px;
}

QMenu::item {
    padding: 5px 24px 5px 12px;
    border-radius: 4px;
}

QMenu::item:selected {
    background-color: #1f6feb;
    color: #ffffff;
}

QMenu::separator {
    height: 1px;
    background: #30363d;
    margin: 4px 0;
}

/* ── Status Bar ──────────────────────────────────────────────────── */
QStatusBar {
    background-color: #161b22;
    border-top: 1px solid #21262d;
    color: #8b949e;
    font-size: 11px;
}

/* ── Dock Widgets ────────────────────────────────────────────────── */
QDockWidget {
    color: #58a6ff;
    font-weight: bold;
    font-size: 12px;
    titlebar-close-icon: none;
}

QDockWidget::title {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #1c2128, stop:1 #161b22);
    padding: 6px 8px;
    border: 1px solid #30363d;
    border-bottom: 2px solid #1f6feb;
    border-radius: 4px 4px 0 0;
}

QDockWidget::close-button, QDockWidget::float-button {
    border: none;
    padding: 2px;
}

/* ── Tab Widget ──────────────────────────────────────────────────── */
QTabWidget::pane {
    border: 1px solid #30363d;
    border-top: 2px solid #1f6feb;
    background-color: #0d1117;
    border-radius: 0 4px 4px 4px;
}

QTabWidget::tab-bar {
    alignment: left;
}

QTabBar::tab {
    background: #161b22;
    color: #8b949e;
    border: 1px solid #30363d;
    border-bottom: none;
    padding: 7px 18px;
    margin-right: 2px;
    border-radius: 4px 4px 0 0;
    min-width: 100px;
    font-size: 12px;
}

QTabBar::tab:selected {
    background: #1c2128;
    color: #58a6ff;
    border-bottom: 2px solid #1f6feb;
    font-weight: bold;
}

QTabBar::tab:hover:!selected {
    background: #1c2128;
    color: #c9d1d9;
}

/* ── Group Box ───────────────────────────────────────────────────── */
QGroupBox {
    border: 1px solid #30363d;
    border-radius: 6px;
    margin-top: 12px;
    padding: 8px 6px 6px 6px;
    font-weight: bold;
    color: #58a6ff;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 6px;
    left: 10px;
    color: #58a6ff;
    font-size: 11px;
    letter-spacing: 0.5px;
}

/* ── Buttons ─────────────────────────────────────────────────────── */
QPushButton {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #1f6feb, stop:1 #1158c7);
    color: #ffffff;
    border: 1px solid #1f6feb;
    border-radius: 5px;
    padding: 5px 14px;
    font-weight: 600;
    font-size: 12px;
    min-height: 24px;
}

QPushButton:hover {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #388bfd, stop:1 #1f6feb);
    border-color: #388bfd;
}

QPushButton:pressed {
    background: #0d419d;
    border-color: #0d419d;
}

QPushButton:disabled {
    background: #21262d;
    border-color: #30363d;
    color: #484f58;
}

QPushButton#btn_danger {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #da3633, stop:1 #b12b2a);
    border-color: #da3633;
}

QPushButton#btn_danger:hover {
    background: #f85149;
    border-color: #f85149;
}

QPushButton#btn_success {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #238636, stop:1 #196127);
    border-color: #238636;
}

QPushButton#btn_success:hover {
    background: #2ea043;
    border-color: #2ea043;
}

QPushButton#btn_warn {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #9e6a03, stop:1 #6e4c02);
    border-color: #9e6a03;
    color: #f0c000;
}

QPushButton#btn_warn:hover {
    background: #bb8009;
}

/* ── Flat / Icon Buttons ─────────────────────────────────────────── */
QPushButton#btn_flat {
    background: transparent;
    border: 1px solid #30363d;
    color: #8b949e;
}

QPushButton#btn_flat:hover {
    border-color: #58a6ff;
    color: #58a6ff;
}

/* ── Toggle / Checkable Buttons ──────────────────────────────────── */
QPushButton:checked {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #238636, stop:1 #196127);
    border-color: #2ea043;
    color: #ffffff;
}

/* ── QLineEdit / QSpinBox / QDoubleSpinBox ───────────────────────── */
QLineEdit, QSpinBox, QDoubleSpinBox {
    background-color: #010409;
    border: 1px solid #30363d;
    border-radius: 4px;
    padding: 4px 8px;
    color: #c9d1d9;
    selection-background-color: #1f6feb;
    font-family: "Consolas", monospace;
}

QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {
    border: 1px solid #1f6feb;
    background: #0d1117;
}

QSpinBox::up-button, QDoubleSpinBox::up-button {
    subcontrol-origin: border;
    subcontrol-position: top right;
    width: 16px;
    border-left: 1px solid #30363d;
    background: #161b22;
    border-radius: 0 3px 0 0;
}

QSpinBox::down-button, QDoubleSpinBox::down-button {
    subcontrol-origin: border;
    subcontrol-position: bottom right;
    width: 16px;
    border-left: 1px solid #30363d;
    background: #161b22;
    border-radius: 0 0 3px 0;
}

QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {
    width: 6px;
    height: 6px;
    border-left: 3px solid transparent;
    border-right: 3px solid transparent;
    border-bottom: 5px solid #58a6ff;
    background: transparent;
}

QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {
    width: 6px;
    height: 6px;
    border-left: 3px solid transparent;
    border-right: 3px solid transparent;
    border-top: 5px solid #58a6ff;
    background: transparent;
}

/* ── Combo Box ───────────────────────────────────────────────────── */
QComboBox {
    background-color: #161b22;
    border: 1px solid #30363d;
    border-radius: 4px;
    padding: 4px 30px 4px 8px;
    color: #c9d1d9;
    min-width: 100px;
}

QComboBox:focus {
    border-color: #1f6feb;
}

QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 22px;
    border-left: 1px solid #30363d;
    background: #1c2128;
    border-radius: 0 4px 4px 0;
}

QComboBox::down-arrow {
    width: 8px;
    height: 8px;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 6px solid #58a6ff;
    background: transparent;
}

QComboBox QAbstractItemView {
    background-color: #161b22;
    border: 1px solid #30363d;
    selection-background-color: #1f6feb;
    color: #c9d1d9;
    padding: 4px;
}

/* ── Slider ──────────────────────────────────────────────────────── */
QSlider::groove:horizontal {
    height: 4px;
    background: #21262d;
    border-radius: 2px;
    margin: 0;
}

QSlider::handle:horizontal {
    background: #58a6ff;
    border: 2px solid #1f6feb;
    width: 16px;
    height: 16px;
    margin: -6px 0;
    border-radius: 8px;
}

QSlider::handle:horizontal:hover {
    background: #79c0ff;
    border-color: #388bfd;
}

QSlider::sub-page:horizontal {
    background: #1f6feb;
    border-radius: 2px;
}

/* ── Check Box ───────────────────────────────────────────────────── */
QCheckBox {
    spacing: 7px;
    color: #c9d1d9;
}

QCheckBox::indicator {
    width: 14px;
    height: 14px;
    border-radius: 3px;
    border: 1px solid #30363d;
    background: #161b22;
}

QCheckBox::indicator:checked {
    background: #1f6feb;
    border-color: #1f6feb;
    image: none;
}

QCheckBox::indicator:hover {
    border-color: #58a6ff;
}

/* ── Radio Button ────────────────────────────────────────────────── */
QRadioButton {
    spacing: 7px;
    color: #c9d1d9;
}

QRadioButton::indicator {
    width: 14px;
    height: 14px;
    border-radius: 7px;
    border: 2px solid #30363d;
    background: #161b22;
}

QRadioButton::indicator:checked {
    background: #1f6feb;
    border-color: #1f6feb;
}

/* ── Table Widget ────────────────────────────────────────────────── */
QTableWidget {
    background-color: #0d1117;
    alternate-background-color: #161b22;
    border: 1px solid #21262d;
    border-radius: 4px;
    gridline-color: #21262d;
    color: #c9d1d9;
}

QTableWidget::item {
    padding: 4px 6px;
    border: none;
}

QTableWidget::item:selected {
    background-color: #1f3a6e;
    color: #ffffff;
}

QHeaderView::section {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #1c2128, stop:1 #161b22);
    color: #58a6ff;
    padding: 5px 8px;
    border: none;
    border-right: 1px solid #30363d;
    border-bottom: 2px solid #1f6feb;
    font-weight: bold;
    font-size: 11px;
    letter-spacing: 0.5px;
}

/* ── List Widget ─────────────────────────────────────────────────── */
QListWidget {
    background-color: #0d1117;
    border: 1px solid #21262d;
    border-radius: 4px;
    color: #c9d1d9;
}

QListWidget::item {
    padding: 5px 8px;
    border-bottom: 1px solid #21262d;
}

QListWidget::item:selected {
    background-color: #1f3a6e;
    color: #ffffff;
}

QListWidget::item:hover {
    background-color: #1c2128;
}

/* ── Text Edit ───────────────────────────────────────────────────── */
QTextEdit, QPlainTextEdit {
    background-color: #010409;
    border: 1px solid #21262d;
    border-radius: 4px;
    color: #00ff88;
    font-family: "Consolas", "Lucida Console", monospace;
    font-size: 11px;
    padding: 4px;
}

/* ── Scroll Bars ─────────────────────────────────────────────────── */
QScrollBar:vertical {
    background: #161b22;
    width: 10px;
    border-radius: 5px;
    margin: 0;
}

QScrollBar::handle:vertical {
    background: #30363d;
    border-radius: 5px;
    min-height: 20px;
}

QScrollBar::handle:vertical:hover {
    background: #58a6ff;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
    background: none;
}

QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: none;
}

QScrollBar:horizontal {
    background: #161b22;
    height: 10px;
    border-radius: 5px;
}

QScrollBar::handle:horizontal {
    background: #30363d;
    border-radius: 5px;
    min-width: 20px;
}

QScrollBar::handle:horizontal:hover {
    background: #58a6ff;
}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0;
    background: none;
}

/* ── LCD Number ──────────────────────────────────────────────────── */
QLCDNumber {
    background-color: #010409;
    color: #00ff88;
    border: 1px solid #1f6feb;
    border-radius: 4px;
    padding: 2px;
}

/* ── Progress Bar ────────────────────────────────────────────────── */
QProgressBar {
    background-color: #21262d;
    border: 1px solid #30363d;
    border-radius: 4px;
    text-align: center;
    color: #c9d1d9;
    font-size: 10px;
    height: 14px;
}

QProgressBar::chunk {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #1f6feb, stop:1 #58a6ff);
    border-radius: 4px;
}

/* ── Splitter ────────────────────────────────────────────────────── */
QSplitter::handle {
    background: #21262d;
}

QSplitter::handle:horizontal {
    width: 3px;
}

QSplitter::handle:vertical {
    height: 3px;
}

/* ── Tool Tip ────────────────────────────────────────────────────── */
QToolTip {
    background-color: #1c2128;
    color: #c9d1d9;
    border: 1px solid #30363d;
    border-radius: 4px;
    padding: 4px 8px;
    font-size: 11px;
}

/* ── Specific Widget IDs ─────────────────────────────────────────── */
#lcd_position {
    color: #00ff88;
    border-color: #238636;
}

#lcd_velocity {
    color: #58a6ff;
    border-color: #1f6feb;
}

#lcd_load {
    color: #f0c000;
    border-color: #9e6a03;
}

#lcd_voltage {
    color: #da8aff;
    border-color: #8957e5;
}

#lcd_temperature {
    color: #ff7b72;
    border-color: #da3633;
}

#lcd_current {
    color: #ffa657;
    border-color: #d29922;
}

#status_indicator_ok {
    background: #238636;
    border: 2px solid #2ea043;
    border-radius: 8px;
}

#status_indicator_err {
    background: #da3633;
    border: 2px solid #f85149;
    border-radius: 8px;
}

#status_indicator_idle {
    background: #484f58;
    border: 2px solid #8b949e;
    border-radius: 8px;
}
"""


ACCENT_CYAN = "#58a6ff"
ACCENT_GREEN = "#00ff88"
ACCENT_ORANGE = "#ffa657"
ACCENT_RED = "#f85149"
ACCENT_PURPLE = "#da8aff"
ACCENT_YELLOW = "#f0c000"

TRACE_COLORS = {
    "Position":       "#00ff88",
    "Goal Position":  "#238636",
    "Velocity":       "#58a6ff",
    "Load":           "#f0c000",
    "Voltage":        "#da8aff",
    "Temperature":    "#ff7b72",
    "Current":        "#ffa657",
}
