"""
E2A — Bus Utilization Measurement
===================================
Measures what fraction of wall-clock time the serial bus is actively
occupied by servo transactions.

Tests with 1, 2, 3, 4 servos (uses the servo IDs found on the bus).
If fewer physical servos exist, simulates by re-reading the same servo
multiple times per cycle to model the timing of N-servo polling.

Usage:
    python e2a_bus_utilization.py --port COM3 --baud 1000000 --duration 10
"""

import sys
import os
import time
import csv
import argparse

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


def single_telemetry_read_timed(servo: ST3215, sid: int) -> float:
    """
    Do one full telemetry read (same as _read_telemetry_locked),
    return the elapsed bus time in seconds.
    """
    servo.portHandler.is_using = False
    t0 = time.perf_counter()
    try:
        servo.ReadPosition(sid)
        servo.ReadSpeed(sid)
        servo.ReadLoad(sid)
        servo.ReadVoltage(sid)
        servo.ReadTemperature(sid)
        servo.ReadCurrent(sid)
        servo.IsMoving(sid)
    except Exception:
        servo.portHandler.is_using = False
    t1 = time.perf_counter()
    return t1 - t0


def measure_bus_utilization(servo: ST3215, servo_ids: list[int],
                            n_simulated: int, duration_s: float) -> dict:
    """
    Measure bus utilization for n_simulated servos over duration_s seconds.

    If len(servo_ids) < n_simulated, we cycle through available IDs
    to simulate the timing cost of polling N servos.
    """
    total_bus_time = 0.0
    total_reads = 0
    wall_start = time.perf_counter()

    print(f"  Testing {n_simulated} servo(s) for {duration_s}s ... ", end="", flush=True)

    while (time.perf_counter() - wall_start) < duration_s:
        # One polling cycle: read N servos
        for i in range(n_simulated):
            sid = servo_ids[i % len(servo_ids)]
            bus_time = single_telemetry_read_timed(servo, sid)
            total_bus_time += bus_time
            total_reads += 1

    wall_elapsed = time.perf_counter() - wall_start
    utilization = (total_bus_time / wall_elapsed) * 100.0 if wall_elapsed > 0 else 0

    print(f"bus_time={total_bus_time:.2f}s, wall={wall_elapsed:.2f}s, "
          f"util={utilization:.1f}%, reads={total_reads}")

    return {
        "n_servos": n_simulated,
        "wall_time_s": round(wall_elapsed, 3),
        "bus_time_s": round(total_bus_time, 3),
        "utilization_pct": round(utilization, 2),
        "total_reads": total_reads,
        "reads_per_second": round(total_reads / wall_elapsed, 2),
    }


def main():
    parser = argparse.ArgumentParser(description="E2A: Bus Utilization")
    parser.add_argument("--port", required=True)
    parser.add_argument("--baud", type=int, default=1000000)
    parser.add_argument("--duration", type=float, default=10.0)
    args = parser.parse_args()

    print(f"\n{'='*60}")
    print(f"E2A — Bus Utilization Measurement")
    print(f"Port: {args.port}  Baud: {args.baud}")
    print(f"{'='*60}\n")

    servo = connect_servo(args.port, args.baud)

    # Discover servos on the bus
    print("Scanning for servos ... ", end="", flush=True)
    found_ids = servo.ListServos()
    print(f"found: {found_ids}")

    if not found_ids:
        print("ERROR: No servos found!")
        servo.portHandler.closePort()
        sys.exit(1)

    test_counts = [1, 2, 3, 4]
    results = []

    for n in test_counts:
        stats = measure_bus_utilization(servo, found_ids, n, args.duration)
        stats["baud_rate"] = args.baud
        stats["physical_servos"] = len(found_ids)
        results.append(stats)
        time.sleep(0.5)

    servo.portHandler.closePort()

    # Save CSV
    out_dir = os.path.dirname(__file__)
    csv_path = os.path.join(out_dir, "bus_utilization.csv")
    fieldnames = [
        "baud_rate", "physical_servos", "n_servos",
        "wall_time_s", "bus_time_s", "utilization_pct",
        "total_reads", "reads_per_second",
    ]

    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(results)

    print(f"\nCSV saved: {csv_path}")


if __name__ == "__main__":
    main()
