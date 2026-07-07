"""
E1B — Telemetry Latency Measurement
=====================================
Measures the wall-clock time for one complete telemetry read cycle
(ReadPosition + ReadSpeed + ReadLoad + ReadVoltage + ReadTemperature +
 ReadCurrent + IsMoving — exactly as _read_telemetry_locked() does).

Tests at both 115200 and 1000000 baud, 100 trials each.
Uses time.perf_counter() for sub-ms precision.

Usage:
    python e1b_telemetry_latency.py --port COM3 --servo-id 1
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
    """Connect using the same pattern as _HardwareWorker.connect_device()."""
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


def measure_single_telemetry_read(servo: ST3215, sid: int) -> float | None:
    """
    Time one full telemetry read cycle — exact replica of
    _HardwareWorker._read_telemetry_locked() in servo_backend.py.

    Returns latency in milliseconds, or None on failure.
    """
    servo.portHandler.is_using = False

    t_start = time.perf_counter()

    try:
        pos = servo.ReadPosition(sid)
        spd_tpl = servo.ReadSpeed(sid)
        spd = spd_tpl[0] if isinstance(spd_tpl, tuple) else spd_tpl
        load = servo.ReadLoad(sid)
        volt = servo.ReadVoltage(sid)
        temp = servo.ReadTemperature(sid)
        cur = servo.ReadCurrent(sid)
        mov = servo.IsMoving(sid)
    except Exception:
        servo.portHandler.is_using = False
        return None

    t_end = time.perf_counter()

    if pos is None:
        return None

    return (t_end - t_start) * 1000.0  # convert to milliseconds


def run_trials(servo: ST3215, sid: int, n_trials: int) -> list[float]:
    """Run n_trials telemetry reads, return list of latency values (ms)."""
    latencies = []
    failures = 0

    for trial in range(n_trials):
        lat = measure_single_telemetry_read(servo, sid)
        if lat is not None:
            latencies.append(lat)
        else:
            failures += 1
        # Small inter-trial delay to prevent bus saturation
        time.sleep(0.005)

    if failures > 0:
        print(f"    ({failures}/{n_trials} reads failed)")

    return latencies


def main():
    parser = argparse.ArgumentParser(
        description="E1B: Telemetry Latency Measurement"
    )
    parser.add_argument("--port", required=True, help="Serial port (e.g. COM3)")
    parser.add_argument("--servo-id", type=int, default=1, help="Servo ID")
    parser.add_argument("--trials", type=int, default=100,
                        help="Number of trials per baud rate")
    args = parser.parse_args()

    baud_rates = [115200, 1000000]

    print(f"\n{'='*60}")
    print(f"E1B — Telemetry Latency Measurement")
    print(f"Port: {args.port}  Servo: #{args.servo_id}  Trials: {args.trials}")
    print(f"{'='*60}\n")

    all_results = []

    for baud in baud_rates:
        print(f"--- Testing at {baud:,} bps ---")
        servo = connect_servo(args.port, baud)

        if not servo.PingServo(args.servo_id):
            print(f"  WARNING: Cannot ping servo #{args.servo_id} at {baud} bps")
            servo.portHandler.closePort()
            continue

        # Warm-up: 5 reads to stabilize
        for _ in range(5):
            measure_single_telemetry_read(servo, args.servo_id)
            time.sleep(0.01)

        print(f"  Running {args.trials} trials ...")
        latencies = run_trials(servo, args.servo_id, args.trials)
        servo.portHandler.closePort()

        if latencies:
            mean_lat = statistics.mean(latencies)
            std_lat = statistics.stdev(latencies) if len(latencies) > 1 else 0
            min_lat = min(latencies)
            max_lat = max(latencies)
            median_lat = statistics.median(latencies)

            print(f"  Results: mean={mean_lat:.2f}ms ± {std_lat:.2f}ms  "
                  f"min={min_lat:.2f}ms  max={max_lat:.2f}ms  "
                  f"median={median_lat:.2f}ms")

            for i, lat in enumerate(latencies):
                all_results.append({
                    "baud_rate": baud,
                    "servo_id": args.servo_id,
                    "trial": i + 1,
                    "latency_ms": round(lat, 4),
                    "mean_ms": round(mean_lat, 4),
                    "std_ms": round(std_lat, 4),
                    "min_ms": round(min_lat, 4),
                    "max_ms": round(max_lat, 4),
                })
        else:
            print(f"  ERROR: All reads failed at {baud} bps")

        print()
        time.sleep(1.0)  # let port fully release before reconnecting

    # Save CSV
    out_dir = os.path.dirname(__file__)
    csv_path = os.path.join(out_dir, "telemetry_latency.csv")
    fieldnames = [
        "baud_rate", "servo_id", "trial", "latency_ms",
        "mean_ms", "std_ms", "min_ms", "max_ms",
    ]

    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(all_results)

    print(f"CSV saved: {csv_path}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
