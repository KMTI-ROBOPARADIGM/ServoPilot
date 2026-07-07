"""
E2B — Latency Scaling Measurement
====================================
Measures round-trip telemetry latency as a function of servo count.
Demonstrates how per-cycle latency increases linearly with N servos.

Usage:
    python e2b_latency_scaling.py --port COM3 --baud 1000000
"""

import sys
import os
import time
import csv
import argparse
import statistics

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from st3215.st3215 import ST3215
from st3215.port_handler import PortHandler
from st3215.protocol_packet_handler import protocol_packet_handler
from st3215.group_sync_write import GroupSyncWrite
from st3215.values import STS_ACC

import threading


def connect_servo(port: str, baudrate: int) -> ST3215:
    ph = PortHandler(port)
    ph.baudrate = baudrate
    if not ph.openPort():
        raise OSError(f"Could not open port: {port}")
    servo = ST3215.__new__(ST3215)
    servo.portHandler = ph
    protocol_packet_handler.__init__(servo, ph)
    servo.groupSyncWrite = GroupSyncWrite(servo, STS_ACC, 7)
    servo.lock = threading.Lock()
    return servo


def full_cycle_read(servo: ST3215, sid: int):
    """Full telemetry read for one servo (7 register reads)."""
    servo.portHandler.is_using = False
    servo.ReadPosition(sid)
    servo.ReadSpeed(sid)
    servo.ReadLoad(sid)
    servo.ReadVoltage(sid)
    servo.ReadTemperature(sid)
    servo.ReadCurrent(sid)
    servo.IsMoving(sid)


def measure_cycle_latency(servo: ST3215, servo_ids: list[int],
                          n_simulated: int, n_trials: int) -> list[float]:
    """
    Measure the total time to read telemetry from n_simulated servos.
    Returns list of cycle latencies in ms.
    """
    latencies = []
    for _ in range(n_trials):
        t0 = time.perf_counter()
        for i in range(n_simulated):
            sid = servo_ids[i % len(servo_ids)]
            full_cycle_read(servo, sid)
        t1 = time.perf_counter()
        latencies.append((t1 - t0) * 1000.0)
        time.sleep(0.005)
    return latencies


def main():
    parser = argparse.ArgumentParser(description="E2B: Latency Scaling")
    parser.add_argument("--port", required=True)
    parser.add_argument("--baud", type=int, default=1000000)
    parser.add_argument("--trials", type=int, default=50)
    args = parser.parse_args()

    print(f"\n{'='*60}")
    print(f"E2B — Latency Scaling Measurement")
    print(f"{'='*60}\n")

    servo = connect_servo(args.port, args.baud)
    found_ids = servo.ListServos()
    print(f"Found servos: {found_ids}")

    if not found_ids:
        print("ERROR: No servos found!")
        servo.portHandler.closePort()
        sys.exit(1)

    test_counts = [1, 2, 3, 4]
    results = []

    for n in test_counts:
        print(f"  Testing {n} servo(s), {args.trials} trials ... ", end="", flush=True)
        lats = measure_cycle_latency(servo, found_ids, n, args.trials)
        mean_lat = statistics.mean(lats)
        std_lat = statistics.stdev(lats) if len(lats) > 1 else 0
        print(f"mean={mean_lat:.2f}ms ± {std_lat:.2f}ms")

        for i, lat in enumerate(lats):
            results.append({
                "baud_rate": args.baud,
                "n_servos": n,
                "trial": i + 1,
                "cycle_latency_ms": round(lat, 4),
                "mean_ms": round(mean_lat, 4),
                "std_ms": round(std_lat, 4),
            })

    servo.portHandler.closePort()

    out_dir = os.path.dirname(__file__)
    csv_path = os.path.join(out_dir, "latency_scaling.csv")
    fieldnames = ["baud_rate", "n_servos", "trial",
                  "cycle_latency_ms", "mean_ms", "std_ms"]

    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(results)

    print(f"\nCSV saved: {csv_path}")


if __name__ == "__main__":
    main()
