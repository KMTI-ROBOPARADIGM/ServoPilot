"""ServoPilot — Entry Point.

FILE: main.py
PURPOSE: Application entry point. Initializes the Qt application framework,
         configures global settings (DPI, font, app metadata), creates the
         main window, and starts the event loop.
CALLED BY: OS / command line (python main.py)
CALLS INTO: main_window.ServoPilotMainWindow
"""

import sys                          # [STDLIB] System-specific parameters and functions
import os                           # [STDLIB] OS path manipulation

# Allow running from any working directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication  # [PySide6] Core application class — manages event loop, widgets, and app-level settings
from PySide6.QtCore import Qt               # [PySide6] Qt namespace — contains enums/flags (e.g. HighDpiScaleFactorRoundingPolicy)
from PySide6.QtGui import QFont             # [PySide6] Font class — used to set the default application font
from main_window import ServoPilotMainWindow  # [USER-DEFINED] The main application window class (from main_window.py)


def main():
    """
    ┌─────────────────────────────────────────────────────────────────────┐
    │ FUNCTION: main()                                                    │
    │ TYPE: User-defined (top-level function)                             │
    │ FILE: main.py                                                       │
    │ CALLED BY: if __name__ == "__main__" guard at bottom of this file   │
    │ CALLS:                                                              │
    │   • QApplication.setHighDpiScaleFactorRoundingPolicy() — [PySide6] │
    │     Configures how fractional DPI scaling is handled                │
    │   • QApplication() — [PySide6] Creates the application instance    │
    │   • app.setApplicationName/Version/OrganizationName — [PySide6]    │
    │     Sets metadata used by Qt for settings storage, window titles   │
    │   • QFont() — [PySide6] Creates a font object                     │
    │   • app.setFont() — [PySide6] Sets the global default font        │
    │   • ServoPilotMainWindow() — [USER-DEFINED, main_window.py]        │
    │     Creates the main application window with all tabs/docks/backend│
    │   • window.show() — [PySide6] Makes the window visible on screen  │
    │   • app.exec() — [PySide6] Starts the Qt event loop (blocks until │
    │     the app exits)                                                  │
    │   • sys.exit() — [STDLIB] Exits the process with the return code  │
    │ PURPOSE: Bootstrap the entire ServoPilot application               │
    └─────────────────────────────────────────────────────────────────────┘
    """
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