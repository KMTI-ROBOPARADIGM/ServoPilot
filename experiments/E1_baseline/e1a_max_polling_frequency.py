"""
E1A — Max Stable Polling Frequency (Single Servo)
==================================================
Tests telemetry polling at 10, 20, 30, 40, 50, 60, 70 Hz
using the ACTUAL st3215 driver from this project.

Detects instability via COMM_RX_TIMEOUT / COMM_PORT_BUSY errors
and None-return read failures.

Usage:
    python e1a_max_polling_frequency.py --port COM3 --servo-id 1 --baud 1000000
"""

import sys
import os
import time
import csv
import argparse

# Add project root to path so we can import the actual st3215 package
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from st3215.st3215 import ST3215
from st3215.port_handler import PortHandler
from st3215.protocol_packet_handler import protocol_packet_handler
from st3215.group_sync_write import GroupSyncWrite
from st3215.values import (
    DEFAULT_BAUDRATE, COMM_SUCCESS, COMM_PORT_BUSY, COMM_RX_TIMEOUT,
    STS_ACC, STS_PRESENT_POSITION_L, STS_PRESENT_SPEED_L,
    STS_PRESENT_LOAD_L, STS_PRESENT_VOLTAGE, STS_PRESENT_TEMPERATURE,
    STS_PRESENT_CURRENT_L, STS_MOVING,
)

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


def full_telemetry_read(servo: ST3215, sid: int) -> dict | None:
    """
    Replicate _HardwareWorker._read_telemetry_locked() exactly:
    Reads position, speed, load, voltage, temperature, current, moving.
    Returns dict on success, None on any failure.
    """
    servo.portHandler.is_using = False  # reset stuck flag
    try:
        pos = servo.ReadPosition(sid)
        spd_tpl = servo.ReadSpeed(sid)
        spd = spd_tpl[0] if isinstance(spd_tpl, tuple) else spd_tpl
        load = servo.ReadLoad(sid)
        volt = servo.ReadVoltage(sid)
        temp = servo.ReadTemperature(sid)
        cur = servo.ReadCurrent(sid)
        mov = servo.IsMoving(sid)

        # If any critical read returned None → failure
        if pos is None or volt is None:
            return None

        return {
            "position":    pos    if pos    is not None else 0,
            "velocity":    spd    if spd    is not None else 0,
            "load":        load   if load   is not None else 0.0,
            "voltage":     volt   if volt   is not None else 0.0,
            "temperature": temp   if temp   is not None else 0,
            "current":     cur    if cur    is not None else 0.0,
            "moving":      bool(mov),
        }
    except Exception as e:
        servo.portHandler.is_using = False
        return None


def test_frequency(servo: ST3215, sid: int, hz: float,
                   duration_s: float = 10.0) -> dict:
    """
    Poll telemetry at `hz` Hz for `duration_s` seconds.
    Returns stats: total_reads, successes, failures, error_rate.
    """
    interval = 1.0 / hz
    total_reads = 0
    successes = 0
    failures = 0
    start_time = time.perf_counter()

    print(f"  Testing {hz} Hz for {duration_s}s ... ", end="", flush=True)

    while (time.perf_counter() - start_time) < duration_s:
        cycle_start = time.perf_counter()

        result = full_telemetry_read(servo, sid)
        total_reads += 1
        if result is not None:
            successes += 1
        else:
            failures += 1

        # Sleep to maintain target frequency
        elapsed = time.perf_counter() - cycle_start
        sleep_time = interval - elapsed
        if sleep_time > 0:
            time.sleep(sleep_time)

    actual_duration = time.perf_counter() - start_time
    actual_hz = total_reads / actual_duration if actual_duration > 0 else 0
    error_rate = (failures / total_reads * 100) if total_reads > 0 else 0

    print(f"reads={total_reads}, ok={successes}, fail={failures}, "
          f"err={error_rate:.1f}%, actual_hz={actual_hz:.1f}")

    return {
        "target_hz": hz,
        "actual_hz": round(actual_hz, 2),
        "duration_s": round(actual_duration, 2),
        "total_reads": total_reads,
        "successes": successes,
        "failures": failures,
        "error_rate_pct": round(error_rate, 2),
        "stable": error_rate < 5.0,  # <5% error = stable
    }


def main():
    parser = argparse.ArgumentParser(
        description="E1A: Max Stable Polling Frequency"
    )
    parser.add_argument("--port", required=True, help="Serial port (e.g. COM3)")
    parser.add_argument("--servo-id", type=int, default=1, help="Servo ID")
    parser.add_argument("--baud", type=int, default=1000000,
                        help="Baud rate (default: 1000000)")
    parser.add_argument("--duration", type=float, default=10.0,
                        help="Test duration per frequency (seconds)")
    args = parser.parse_args()

    test_frequencies = [10, 20, 30, 40, 50, 60, 70]

    print(f"\n{'='*60}")
    print(f"E1A — Max Stable Polling Frequency")
    print(f"Port: {args.port}  Servo: #{args.servo_id}  Baud: {args.baud}")
    print(f"{'='*60}\n")

    servo = connect_servo(args.port, args.baud)

    # Verify servo is reachable
    if not servo.PingServo(args.servo_id):
        print(f"ERROR: Cannot ping servo #{args.servo_id}")
        servo.portHandler.closePort()
        sys.exit(1)
    print(f"✓ Servo #{args.servo_id} responding\n")

    results = []
    max_stable_hz = 0

    for hz in test_frequencies:
        stats = test_frequency(servo, args.servo_id, hz, args.duration)
        stats["baud_rate"] = args.baud
        stats["servo_id"] = args.servo_id
        results.append(stats)

        if stats["stable"]:
            max_stable_hz = hz

        # Brief pause between tests to let the bus settle
        time.sleep(0.5)

    servo.portHandler.closePort()

    # Save CSV
    out_dir = os.path.dirname(__file__)
    csv_path = os.path.join(out_dir, "polling_frequency.csv")
    fieldnames = [
        "baud_rate", "servo_id", "target_hz", "actual_hz",
        "duration_s", "total_reads", "successes", "failures",
        "error_rate_pct", "stable"
    ]

    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(results)

    print(f"\n{'='*60}")
    print(f"RESULT: Max stable polling frequency = {max_stable_hz} Hz")
    print(f"        at baud rate = {args.baud} bps")
    print(f"CSV saved: {csv_path}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
