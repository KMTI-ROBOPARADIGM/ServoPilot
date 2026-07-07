"""api_bridge — Thread-safe data bridge between FastAPI server and Qt app.

FILE: backend/api_bridge.py
PURPOSE: Provides a thread-safe communication layer between the FastAPI REST/
         WebSocket server (running in a daemon thread) and the Qt GUI (running
         in the main thread). Stores shared state (telemetry, servo lists,
         commands) behind threading.Lock for safe cross-thread access.
CALLED BY: main_window.py (creates instance), api_server.py (uses it for data)
CALLS INTO: Only stdlib (threading, queue, time) — no Qt or hardware deps.
"""

from __future__ import annotations  # [STDLIB] Enable forward reference annotations

import queue       # [STDLIB] Thread-safe FIFO queue for API→Qt commands
import threading   # [STDLIB] Lock for protecting shared state
import time        # [STDLIB] time.time() for telemetry timestamps
from typing import Any, Dict, List, Optional  # [STDLIB] Type hints


class ApiBridge:
    """Singleton-like thread-safe bridge shared by FastAPI and Qt.
    TYPE: User-defined class | FILE: backend/api_bridge.py
    CALLED BY: main_window.py → ApiBridge() created in __init__
    USED BY: api_server.py (all endpoints read/write through this bridge),
             main_window._poll_api_commands (reads command_queue),
             main_window._on_telemetry (writes telemetry),
             main_window._on_servos_found (writes servo list)
    """

    def __init__(self):
        """Initialise all shared state containers.
        TYPE: User-defined | CALLED BY: main_window.py __init__
        """
        self._lock = threading.Lock()
        self._telemetry: Dict[int, dict] = {}       # servo_id → latest data
        self._connected_servos: List[int] = []
        self._goal_positions: Dict[int, int] = {}
        self._home_positions: Dict[int, int] = {}
        self._groups: Dict[str, Dict[int, int]] = {}  # group_name → {id: pos}
        self._api_key: Optional[str] = None
        self._server_running = False

        # Commands from API → Qt (processed by QTimer in main_window)
        self.command_queue: queue.Queue = queue.Queue()

        # WebSocket client tracking
        self._ws_clients: list = []
        self._ws_lock = threading.Lock()

    # ── Telemetry (written by Qt, read by API) ─────────────────────

    def update_telemetry(self, servo_id: int, data: dict):
        """Store latest telemetry for one servo (adds timestamp).
        TYPE: User-defined | CALLED BY: main_window._on_telemetry
        """
        with self._lock:
            self._telemetry[servo_id] = {
                **data,
                "timestamp": time.time(),
            }

    def get_telemetry(self, servo_id: int = None) -> dict:
        """Read telemetry for one or all servos.
        TYPE: User-defined | CALLED BY: api_server.py GET /telemetry, WebSocket
        """
        with self._lock:
            if servo_id is not None:
                return dict(self._telemetry.get(servo_id, {}))
            return {sid: dict(d) for sid, d in self._telemetry.items()}

    # ── Servo list (written by Qt, read by API) ────────────────────

    def set_connected_servos(self, ids: list):
        """Store the list of connected servo IDs.
        TYPE: User-defined | CALLED BY: main_window._on_servos_found
        """
        with self._lock:
            self._connected_servos = list(ids)

    def get_connected_servos(self) -> list:
        """Read the list of connected servo IDs.
        TYPE: User-defined | CALLED BY: api_server.py GET /servos
        """
        with self._lock:
            return list(self._connected_servos)

    # ── Goal positions (written by Qt, read by API) ────────────────

    def set_goal_positions(self, goals: dict):
        """Store current goal positions.
        TYPE: User-defined | CALLED BY: (not yet wired — future use)
        """
        with self._lock:
            self._goal_positions.update(goals)

    def get_goal_positions(self) -> dict:
        """Read current goal positions.
        TYPE: User-defined | CALLED BY: api_server.py GET /goal_positions
        """
        with self._lock:
            return dict(self._goal_positions)

    # ── Home positions (written by Qt, read by API) ────────────────

    def set_home_positions(self, homes: dict):
        """Store home positions for all servos.
        TYPE: User-defined | CALLED BY: sync_tab homing logic
        """
        with self._lock:
            self._home_positions = dict(homes)

    def get_home_positions(self) -> dict:
        """Read home positions.
        TYPE: User-defined | CALLED BY: api_server.py GET /home
        """
        with self._lock:
            return dict(self._home_positions)

    # ── Groups (written by Qt, read by API) ────────────────────────

    def set_groups(self, groups: dict):
        """Store servo group definitions.
        TYPE: User-defined | CALLED BY: sync_tab groups_changed
        """
        with self._lock:
            self._groups = dict(groups)

    def get_groups(self) -> dict:
        """Read servo group definitions.
        TYPE: User-defined | CALLED BY: api_server.py GET /groups
        """
        with self._lock:
            return dict(self._groups)

    # ── Commands (written by API, read by Qt) ──────────────────────

    def push_command(self, cmd: dict):
        """Push a command for the Qt main window to execute.
        TYPE: User-defined | CALLED BY: api_server.py POST endpoints
        """
        self.command_queue.put(cmd)

    def poll_commands(self) -> List[dict]:
        """Non-blocking poll of all pending commands.
        TYPE: User-defined | CALLED BY: main_window._poll_api_commands (100ms timer)
        """
        cmds = []
        while True:
            try:
                cmds.append(self.command_queue.get_nowait())
            except queue.Empty:
                break
        return cmds

    # ── API key ────────────────────────────────────────────────────

    def set_api_key(self, key: Optional[str]):
        """Set an optional API key for request authentication.
        TYPE: User-defined | CALLED BY: (future use / config)
        """
        with self._lock:
            self._api_key = key if key else None

    def get_api_key(self) -> Optional[str]:
        """Read the API key.
        TYPE: User-defined | CALLED BY: api_server.py middleware
        """
        with self._lock:
            return self._api_key

    # ── WebSocket clients ──────────────────────────────────────────

    def add_ws_client(self, ws):
        """Register a WebSocket client for telemetry streaming.
        TYPE: User-defined | CALLED BY: api_server.py WebSocket endpoint on connect
        """
        with self._ws_lock:
            self._ws_clients.append(ws)

    def remove_ws_client(self, ws):
        """Unregister a WebSocket client.
        TYPE: User-defined | CALLED BY: api_server.py WebSocket endpoint on disconnect
        """
        with self._ws_lock:
            try:
                self._ws_clients.remove(ws)
            except ValueError:
                pass

    def get_ws_clients(self) -> list:
        """Get a snapshot of all active WebSocket clients.
        TYPE: User-defined | CALLED BY: api_server.py telemetry broadcast loop
        """
        with self._ws_lock:
            return list(self._ws_clients)

    # ── Server state ───────────────────────────────────────────────

    @property
    def server_running(self) -> bool:
        """Check if the API server is running.
        TYPE: User-defined property | CALLED BY: main_window.closeEvent
        """
        return self._server_running

    @server_running.setter
    def server_running(self, val: bool):
        """Set the API server running state.
        TYPE: User-defined property setter | CALLED BY: api_server start/stop
        """
        self._server_running = val
