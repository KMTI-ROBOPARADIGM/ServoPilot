"""api_server — FastAPI REST + WebSocket server for ServoPilot.

Runs in a daemon thread via uvicorn. All servo interaction goes through
the ApiBridge to avoid touching Qt or serial directly.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from typing import Dict, List, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from backend.api_bridge import ApiBridge

logger = logging.getLogger("servo_api")

# ── Pydantic models ──────────────────────────────────────────────────

class PositionCommand(BaseModel):
    position: int
    speed: Optional[int] = None

class TorqueCommand(BaseModel):
    enable: bool

class ModeCommand(BaseModel):
    mode: str  # "position", "wheel", "pwm", "step"

class SyncMoveItem(BaseModel):
    id: int
    position: int


# ── App factory ──────────────────────────────────────────────────────

def create_app(bridge: ApiBridge) -> FastAPI:
    app = FastAPI(
        title="ServoPilot API",
        description="REST + WebSocket API for ST3215 servo control",
        version="1.0.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Auth dependency ──────────────────────────────────────────

    def _check_key(x_api_key: Optional[str] = Header(None)):
        expected = bridge.get_api_key()
        if expected and x_api_key != expected:
            raise HTTPException(status_code=403, detail="Invalid API key")

    # ── REST Endpoints ───────────────────────────────────────────

    @app.get("/servos", tags=["Servos"])
    def list_servos(x_api_key: Optional[str] = Header(None)):
        _check_key(x_api_key)
        ids = bridge.get_connected_servos()
        telem = bridge.get_telemetry()
        result = []
        for sid in ids:
            data = telem.get(sid, {})
            result.append({
                "id": sid,
                "position": data.get("position", 0),
                "velocity": data.get("velocity", 0),
                "load": data.get("load", 0),
                "voltage": data.get("voltage", 0),
                "temperature": data.get("temperature", 0),
                "current": data.get("current", 0),
                "moving": data.get("moving", False),
            })
        return {"servos": result, "count": len(ids)}

    @app.get("/servos/{servo_id}/state", tags=["Servos"])
    def get_servo_state(servo_id: int, x_api_key: Optional[str] = Header(None)):
        _check_key(x_api_key)
        data = bridge.get_telemetry(servo_id)
        if not data:
            raise HTTPException(404, f"Servo {servo_id} not found or no data")
        return {
            "id": servo_id,
            "position": data.get("position", 0),
            "velocity": data.get("velocity", 0),
            "load": data.get("load", 0),
            "voltage": data.get("voltage", 0),
            "temperature": data.get("temperature", 0),
            "current": data.get("current", 0),
            "moving": data.get("moving", False),
            "timestamp": data.get("timestamp", 0),
        }

    @app.post("/servos/{servo_id}/position", tags=["Control"])
    def set_position(servo_id: int, cmd: PositionCommand,
                     x_api_key: Optional[str] = Header(None)):
        _check_key(x_api_key)
        command = {"action": "set_position", "id": servo_id,
                   "position": cmd.position}
        if cmd.speed is not None:
            command["speed"] = cmd.speed
        bridge.push_command(command)
        return {"status": "queued", "servo_id": servo_id,
                "position": cmd.position}

    @app.post("/servos/{servo_id}/torque", tags=["Control"])
    def set_torque(servo_id: int, cmd: TorqueCommand,
                   x_api_key: Optional[str] = Header(None)):
        _check_key(x_api_key)
        bridge.push_command({"action": "set_torque", "id": servo_id,
                             "enable": cmd.enable})
        return {"status": "queued", "servo_id": servo_id,
                "torque": cmd.enable}

    @app.post("/servos/{servo_id}/mode", tags=["Control"])
    def set_mode(servo_id: int, cmd: ModeCommand,
                 x_api_key: Optional[str] = Header(None)):
        _check_key(x_api_key)
        mode_map = {"position": 0, "wheel": 1, "pwm": 2, "step": 3}
        mode_int = mode_map.get(cmd.mode.lower(), 0)
        bridge.push_command({"action": "set_mode", "id": servo_id,
                             "mode": mode_int})
        return {"status": "queued", "servo_id": servo_id, "mode": cmd.mode}

    @app.post("/servos/home", tags=["Control"])
    def home_servos(x_api_key: Optional[str] = Header(None)):
        _check_key(x_api_key)
        bridge.push_command({"action": "home"})
        return {"status": "queued"}

    @app.post("/servos/emergency_stop", tags=["Safety"])
    def emergency_stop(x_api_key: Optional[str] = Header(None)):
        _check_key(x_api_key)
        bridge.push_command({"action": "emergency_stop"})
        return {"status": "queued"}

    @app.get("/servos/groups", tags=["Groups"])
    def list_groups(x_api_key: Optional[str] = Header(None)):
        _check_key(x_api_key)
        return {"groups": bridge.get_groups()}

    @app.post("/servos/groups/{name}/sync_move", tags=["Groups"])
    def sync_move_group(name: str, items: List[SyncMoveItem],
                        x_api_key: Optional[str] = Header(None)):
        _check_key(x_api_key)
        positions = {item.id: item.position for item in items}
        bridge.push_command({"action": "sync_move", "positions": positions})
        return {"status": "queued", "group": name, "positions": positions}

    # ── WebSocket ────────────────────────────────────────────────

    @app.websocket("/ws/telemetry")
    async def ws_telemetry(ws: WebSocket):
        await ws.accept()
        bridge.add_ws_client(ws)
        try:
            # Start a background task to stream telemetry
            stream_task = asyncio.create_task(_stream_telemetry(ws, bridge))
            # Listen for incoming commands
            while True:
                try:
                    raw = await ws.receive_text()
                    msg = json.loads(raw)
                    cmd = msg.get("command")
                    if cmd == "set_position":
                        bridge.push_command({
                            "action": "set_position",
                            "id": msg.get("id"),
                            "position": msg.get("position"),
                        })
                    elif cmd == "set_torque":
                        bridge.push_command({
                            "action": "set_torque",
                            "id": msg.get("id"),
                            "enable": msg.get("enable", True),
                        })
                    elif cmd == "emergency_stop":
                        bridge.push_command({"action": "emergency_stop"})
                    elif cmd == "home":
                        bridge.push_command({"action": "home"})
                except json.JSONDecodeError:
                    pass
        except WebSocketDisconnect:
            pass
        finally:
            stream_task.cancel()
            bridge.remove_ws_client(ws)

    return app


async def _stream_telemetry(ws: WebSocket, bridge: ApiBridge):
    """Send telemetry at ~10 Hz to a single WebSocket client."""
    try:
        while True:
            telem = bridge.get_telemetry()
            if telem:
                msg = {
                    "timestamp": time.time(),
                    "servos": {
                        str(sid): {
                            "position": d.get("position", 0),
                            "velocity": d.get("velocity", 0),
                            "load": d.get("load", 0),
                            "voltage": d.get("voltage", 0),
                            "temperature": d.get("temperature", 0),
                            "current": d.get("current", 0),
                        }
                        for sid, d in telem.items()
                    },
                }
                await ws.send_json(msg)
            await asyncio.sleep(0.1)  # 10 Hz
    except Exception:
        pass  # client disconnected


# ── Server lifecycle ─────────────────────────────────────────────────

_server_thread: Optional[threading.Thread] = None
_server_instance = None


def start_server(bridge: ApiBridge, host: str = "127.0.0.1", port: int = 8765):
    """Start the FastAPI server in a daemon thread."""
    global _server_thread, _server_instance

    if bridge.server_running:
        return

    import uvicorn

    app = create_app(bridge)

    config = uvicorn.Config(
        app, host=host, port=port,
        log_level="warning",
        access_log=False,
    )
    _server_instance = uvicorn.Server(config)

    def _run():
        bridge.server_running = True
        _server_instance.run()
        bridge.server_running = False

    _server_thread = threading.Thread(target=_run, daemon=True, name="api-server")
    _server_thread.start()
    logger.info(f"API server started on http://{host}:{port}")


def stop_server(bridge: ApiBridge):
    """Signal the uvicorn server to shut down."""
    global _server_instance
    if _server_instance:
        _server_instance.should_exit = True
        _server_instance = None
    bridge.server_running = False
    logger.info("API server stopped")
