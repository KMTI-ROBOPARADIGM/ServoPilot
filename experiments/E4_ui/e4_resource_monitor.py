"""
E4 — CPU and RAM Measurement Script
======================================
Monitors the ServoPilot process resource usage using psutil.
Records CPU%, RAM (MB), and timestamp every second for 60s.

Run this TWICE:
  1) With telemetry OFF (baseline) — start ServoPilot, connect, but DON'T start graph
  2) With telemetry ON at max frequency — start graph, set poll rate to max

Usage:
    python e4_resource_monitor.py --label baseline --duration 60
    python e4_resource_monitor.py --label under_load --duration 60
"""

import sys
import os
import time
import csv
import argparse

try:
    import psutil
except ImportError:
    print("ERROR: psutil not installed. Run: pip install psutil")
    sys.exit(1)


def find_servopilot_process() -> psutil.Process | None:
    """
    Find the running ServoPilot process.
    ServoPilot is launched via main.py, so we look for a Python process
    whose command line includes 'main.py' or 'ServoPilot'.
    """
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            cmdline = proc.info.get("cmdline") or []
            cmdline_str = " ".join(cmdline).lower()
            # Match the project's main.py or any reference to servo-insight
            if ("main.py" in cmdline_str and "servo" in cmdline_str) or \
               "servopilot" in cmdline_str or \
               "servo-insight" in cmdline_str:
                return proc
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return None


def main():
    parser = argparse.ArgumentParser(description="E4: CPU/RAM Monitor")
    parser.add_argument("--label", required=True,
                        help="'baseline' or 'under_load'")
    parser.add_argument("--duration", type=int, default=60,
                        help="Monitor duration in seconds")
    parser.add_argument("--pid", type=int, default=None,
                        help="Manually specify the PID of ServoPilot")
    args = parser.parse_args()

    print(f"\n{'='*60}")
    print(f"E4 — Resource Monitor ({args.label})")
    print(f"{'='*60}\n")

    # Find or use specified process
    if args.pid:
        try:
            proc = psutil.Process(args.pid)
        except psutil.NoSuchProcess:
            print(f"ERROR: No process with PID {args.pid}")
            sys.exit(1)
    else:
        print("Searching for ServoPilot process ... ", end="", flush=True)
        proc = find_servopilot_process()
        if proc is None:
            print("NOT FOUND")
            print("\nMake sure ServoPilot is running (python main.py)")
            print("Or specify --pid manually")
            sys.exit(1)
        print(f"found PID={proc.pid}")

    print(f"Process: {proc.name()} [PID={proc.pid}]")
    print(f"Recording for {args.duration}s ...\n")

    rows = []
    start_time = time.time()

    # Pre-call cpu_percent to initialize (first call always returns 0)
    proc.cpu_percent(interval=None)
    time.sleep(0.5)

    for i in range(args.duration):
        try:
            cpu = proc.cpu_percent(interval=1.0)
            mem_info = proc.memory_info()
            ram_mb = mem_info.rss / (1024 * 1024)

            rows.append({
                "timestamp_s": i + 1,
                "cpu_pct": round(cpu, 2),
                "ram_mb": round(ram_mb, 2),
            })

            print(f"  [{i+1:3d}/{args.duration}] CPU={cpu:5.1f}%  "
                  f"RAM={ram_mb:.1f} MB")

        except psutil.NoSuchProcess:
            print(f"\n  Process terminated at t={i+1}s!")
            break

    # Save CSV
    out_dir = os.path.dirname(__file__)
    csv_path = os.path.join(out_dir, f"resource_{args.label}.csv")

    fieldnames = ["timestamp_s", "cpu_pct", "ram_mb"]
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    # Compute averages
    if rows:
        avg_cpu = sum(r["cpu_pct"] for r in rows) / len(rows)
        avg_ram = sum(r["ram_mb"] for r in rows) / len(rows)
        max_cpu = max(r["cpu_pct"] for r in rows)
        max_ram = max(r["ram_mb"] for r in rows)

        print(f"\n{'='*60}")
        print(f"  Average CPU: {avg_cpu:.1f}%  (max: {max_cpu:.1f}%)")
        print(f"  Average RAM: {avg_ram:.1f} MB  (max: {max_ram:.1f} MB)")
        print(f"  CSV saved: {csv_path}")
        print(f"{'='*60}")


if __name__ == "__main__":
    main()
