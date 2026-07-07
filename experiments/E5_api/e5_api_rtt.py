"""
E5 — API RTT (Round-Trip Time) Measurement
=============================================
Measures REST and WebSocket round-trip times against ServoPilot's
actual FastAPI server running at http://127.0.0.1:8765.

ACTUAL ENDPOINTS (from backend/api_server.py):
  REST:  POST http://127.0.0.1:8765/servos/{servo_id}/position
         body: {"position": int, "speed": int?}
  WS:    ws://127.0.0.1:8765/ws/telemetry
         send: {"command": "set_position", "id": int, "position": int}

Prerequisites:
  1) ServoPilot must be running
  2) API server must be started (click "API ▶" in status bar)
  3) At least one servo must be connected

Usage:
    python e5_api_rtt.py --servo-id 1 --trials 50
"""

import sys
import os
import time
import csv
import json
import argparse
import statistics

try:
    import requests
except ImportError:
    print("ERROR: requests not installed. Run: pip install requests")
    sys.exit(1)

try:
    import websocket  # websocket-client package
except ImportError:
    print("ERROR: websocket-client not installed. Run: pip install websocket-client")
    sys.exit(1)


BASE_URL = "http://127.0.0.1:8765"
WS_URL = "ws://127.0.0.1:8765/ws/telemetry"


def test_rest_rtt(servo_id: int, n_trials: int) -> list[float]:
    """
    Measure REST API RTT by POST-ing to /servos/{servo_id}/position.
    This is the actual endpoint from api_server.py.
    JSON body matches PositionCommand model: {"position": int, "speed": int?}
    """
    url = f"{BASE_URL}/servos/{servo_id}/position"
    latencies = []

    # Verify server is reachable
    try:
        r = requests.get(f"{BASE_URL}/servos", timeout=5)
        if r.status_code != 200:
            print(f"  WARNING: Server returned {r.status_code}")
    except Exception as e:
        print(f"  ERROR: Cannot reach API server: {e}")
        return []

    print(f"  REST: {n_trials} trials to {url} ... ", end="", flush=True)

    for i in range(n_trials):
        # Alternate position to keep servo moving slightly
        pos = 2048 + (10 if i % 2 == 0 else -10)
        payload = {"position": pos, "speed": 1000}

        t0 = time.perf_counter()
        try:
            r = requests.post(url, json=payload, timeout=5)
        except Exception:
            continue
        t1 = time.perf_counter()

        if r.status_code == 200:
            latencies.append((t1 - t0) * 1000.0)  # ms

        time.sleep(0.02)  # prevent flooding

    if latencies:
        print(f"mean={statistics.mean(latencies):.2f}ms ± "
              f"{statistics.stdev(latencies):.2f}ms" if len(latencies) > 1 else "")
    else:
        print("ALL FAILED")

    return latencies


def test_websocket_rtt(servo_id: int, n_trials: int) -> list[float]:
    """
    Measure WebSocket RTT by connecting to /ws/telemetry and sending
    set_position commands. Measures time from send to next received message.

    The WS endpoint from api_server.py accepts:
    {"command": "set_position", "id": int, "position": int}
    and broadcasts telemetry at 10 Hz.
    """
    latencies = []

    print(f"  WS:   {n_trials} trials to {WS_URL} ... ", end="", flush=True)

    try:
        ws = websocket.create_connection(WS_URL, timeout=5)
    except Exception as e:
        print(f"ERROR: Cannot connect to WebSocket: {e}")
        return []

    # Drain initial telemetry messages
    ws.settimeout(2.0)
    try:
        for _ in range(3):
            ws.recv()
    except Exception:
        pass

    for i in range(n_trials):
        pos = 2048 + (10 if i % 2 == 0 else -10)
        cmd = json.dumps({
            "command": "set_position",
            "id": servo_id,
            "position": pos,
        })

        t0 = time.perf_counter()
        try:
            ws.send(cmd)
            # Wait for next telemetry broadcast (arrives at 10 Hz)
            ws.settimeout(1.0)
            response = ws.recv()
            t1 = time.perf_counter()
            latencies.append((t1 - t0) * 1000.0)
        except Exception:
            pass

        time.sleep(0.02)

    ws.close()

    if latencies:
        print(f"mean={statistics.mean(latencies):.2f}ms ± "
              f"{statistics.stdev(latencies):.2f}ms" if len(latencies) > 1 else "")
    else:
        print("ALL FAILED")

    return latencies


def main():
    parser = argparse.ArgumentParser(description="E5: API RTT Measurement")
    parser.add_argument("--servo-id", type=int, default=1)
    parser.add_argument("--trials", type=int, default=50)
    args = parser.parse_args()

    print(f"\n{'='*60}")
    print(f"E5 — API Round-Trip Time Measurement")
    print(f"Servo: #{args.servo_id}  Trials: {args.trials}")
    print(f"{'='*60}\n")

    all_results = []

    # ── REST RTT ──────────────────────────────────────────────────
    rest_lats = test_rest_rtt(args.servo_id, args.trials)
    for i, lat in enumerate(rest_lats):
        all_results.append({
            "method": "REST",
            "endpoint": f"POST /servos/{args.servo_id}/position",
            "trial": i + 1,
            "rtt_ms": round(lat, 4),
            "mean_ms": round(statistics.mean(rest_lats), 4) if rest_lats else "",
            "std_ms": round(statistics.stdev(rest_lats), 4) if len(rest_lats) > 1 else "",
        })

    # ── WebSocket RTT ─────────────────────────────────────────────
    ws_lats = test_websocket_rtt(args.servo_id, args.trials)
    for i, lat in enumerate(ws_lats):
        all_results.append({
            "method": "WebSocket",
            "endpoint": "ws://127.0.0.1:8765/ws/telemetry",
            "trial": i + 1,
            "rtt_ms": round(lat, 4),
            "mean_ms": round(statistics.mean(ws_lats), 4) if ws_lats else "",
            "std_ms": round(statistics.stdev(ws_lats), 4) if len(ws_lats) > 1 else "",
        })

    # ── Save CSV ──────────────────────────────────────────────────
    out_dir = os.path.dirname(__file__)
    csv_path = os.path.join(out_dir, "rtt_log.csv")
    fieldnames = ["method", "endpoint", "trial", "rtt_ms", "mean_ms", "std_ms"]

    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(all_results)

    # ── Summary ───────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"SUMMARY")
    if rest_lats:
        print(f"  REST:      {statistics.mean(rest_lats):7.2f} ± "
              f"{statistics.stdev(rest_lats):.2f} ms" if len(rest_lats) > 1
              else f"  REST: {rest_lats[0]:.2f} ms")
    if ws_lats:
        print(f"  WebSocket: {statistics.mean(ws_lats):7.2f} ± "
              f"{statistics.stdev(ws_lats):.2f} ms" if len(ws_lats) > 1
              else f"  WebSocket: {ws_lats[0]:.2f} ms")
    print(f"  CSV saved: {csv_path}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
