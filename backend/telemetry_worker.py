"""TelemetryWorker — QThread that polls servos at a configurable rate.

Emits `telemetry_update(servo_id, data_dict)` for each active servo.
"""

from PySide6.QtCore import QThread, Signal, QMutex, QMutexLocker


class TelemetryWorker(QThread):
    """
    Poll telemetry for a list of servo IDs at `hz` Hz.
    Reads are done through a shared ServoBackend worker reference.
    """

    telemetry_update = Signal(int, dict)  # (servo_id, data)

    def __init__(self, backend_worker, parent=None):
        super().__init__(parent)
        self._worker   = backend_worker   # _HardwareWorker
        self._mutex    = QMutex()
        self._ids: list[int] = []
        self._hz: float = 20.0
        self._running = False

    # ── public API (thread-safe) ─────────────────────────────────────
    def set_servo_ids(self, ids: list):
        with QMutexLocker(self._mutex):
            self._ids = list(ids)

    def set_rate(self, hz: float):
        with QMutexLocker(self._mutex):
            self._hz = max(1.0, min(50.0, hz))

    def stop(self):
        self._running = False
        self.wait(2000)

    # ── QThread.run ──────────────────────────────────────────────────
    def run(self):
        self._running = True
        while self._running:
            with QMutexLocker(self._mutex):
                ids = list(self._ids)
                hz  = self._hz

            for sid in ids:
                if not self._running:
                    break
                data = self._worker._read_telemetry_locked(sid)
                if data:
                    self.telemetry_update.emit(sid, data)

            interval = 1.0 / hz
            # Sleep in small chunks so stop() has low latency
            slept = 0.0
            while self._running and slept < interval:
                self.msleep(20)
                slept += 0.020
