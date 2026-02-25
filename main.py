"""ServoPilot — Entry Point."""

import sys
import os

# Allow running from any working directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from main_window import ServoPilotMainWindow


def main():
    # ── High-DPI setup (PySide6 ≥ 6.4) ─────────────────────────────
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("ServoPilot")
    app.setApplicationVersion("1.0")
    app.setOrganizationName("ServoPilot")

    # Default font
    font = QFont("Segoe UI", 10)
    app.setFont(font)

    window = ServoPilotMainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
