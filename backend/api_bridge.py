"""api_bridge — Thread-safe data bridge between FastAPI server and Qt app.

The API thread reads telemetry and pushes commands via this bridge.
The Qt main window writes telemetry and polls commands.
All access is protected by a threading.Lock.
"""

from __future__ import annotations

import queue
import threading
import time
from typing import Any, Dict, List, Optional


class ApiBridge:
    """Singleton-like thread-safe bridge shared by FastAPI and Qt."""

    def __init__(self):
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
        with self._lock:
            self._telemetry[servo_id] = {
                **data,
                "timestamp": time.time(),
            }

    def get_telemetry(self, servo_id: int = None) -> dict:
        with self._lock:
            if servo_id is not None:
                return dict(self._telemetry.get(servo_id, {}))
            return {sid: dict(d) for sid, d in self._telemetry.items()}

    # ── Servo list (written by Qt, read by API) ────────────────────

    def set_connected_servos(self, ids: list):
        with self._lock:
            self._connected_servos = list(ids)

    def get_connected_servos(self) -> list:
        with self._lock:
            return list(self._connected_servos)

    # ── Goal positions (written by Qt, read by API) ────────────────

    def set_goal_positions(self, goals: dict):
        with self._lock:
            self._goal_positions.update(goals)

    def get_goal_positions(self) -> dict:
        with self._lock:
            return dict(self._goal_positions)

    # ── Home positions (written by Qt, read by API) ────────────────

    def set_home_positions(self, homes: dict):
        with self._lock:
            self._home_positions = dict(homes)

    def get_home_positions(self) -> dict:
        with self._lock:
            return dict(self._home_positions)

    # ── Groups (written by Qt, read by API) ────────────────────────

    def set_groups(self, groups: dict):
        with self._lock:
            self._groups = dict(groups)

    def get_groups(self) -> dict:
        with self._lock:
            return dict(self._groups)

    # ── Commands (written by API, read by Qt) ──────────────────────

    def push_command(self, cmd: dict):
        """Push a command for the Qt main window to execute."""
        self.command_queue.put(cmd)

    def poll_commands(self) -> List[dict]:
        """Non-blocking poll of all pending commands."""
        cmds = []
        while True:
            try:
                cmds.append(self.command_queue.get_nowait())
            except queue.Empty:
                break
        return cmds

    # ── API key ────────────────────────────────────────────────────

    def set_api_key(self, key: Optional[str]):
        with self._lock:
            self._api_key = key if key else None

    def get_api_key(self) -> Optional[str]:
        with self._lock:
            return self._api_key

    # ── WebSocket clients ──────────────────────────────────────────

    def add_ws_client(self, ws):
        with self._ws_lock:
            self._ws_clients.append(ws)

    def remove_ws_client(self, ws):
        with self._ws_lock:
            try:
                self._ws_clients.remove(ws)
            except ValueError:
                pass

    def get_ws_clients(self) -> list:
        with self._ws_lock:
            return list(self._ws_clients)

    # ── Server state ───────────────────────────────────────────────

    @property
    def server_running(self) -> bool:
        return self._server_running

    @server_running.setter
    def server_running(self, val: bool):
        self._server_running = val
