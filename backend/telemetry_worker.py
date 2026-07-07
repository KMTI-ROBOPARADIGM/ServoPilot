"""TelemetryWorker — QThread that polls servos at a configurable rate.

FILE: backend/telemetry_worker.py
PURPOSE: Runs in a dedicated QThread to periodically read telemetry data
         (position, speed, load, voltage, temperature, current, moving)
         from every connected servo. Emits telemetry_update signals which
         are consumed by the main window and distributed to all widgets.
CALLED BY: (Currently wired but timer-based polling in main_window is used instead)
CALLS INTO: _HardwareWorker._read_telemetry_locked (servo_backend.py)
"""

from PySide6.QtCore import QThread, Signal, QMutex, QMutexLocker  # [PySide6] Threading primitives


class TelemetryWorker(QThread):
    """Threaded telemetry poller — reads servo data at configurable Hz.
    TYPE: User-defined QThread subclass | FILE: backend/telemetry_worker.py
    CALLED BY: (optional — main_window currently uses QTimer-based polling)
    EMITS: telemetry_update(servo_id, data_dict)
    """

    telemetry_update = Signal(int, dict)  # (servo_id, data)

    def __init__(self, backend_worker, parent=None):
        """Initialise with a reference to the _HardwareWorker instance.
        TYPE: User-defined | CALLED BY: Constructor
        ARGS: backend_worker — _HardwareWorker instance from servo_backend.py
        """
        super().__init__(parent)
        self._worker   = backend_worker   # _HardwareWorker [USER, servo_backend.py]
        self._mutex    = QMutex()          # [PySide6] Protects _ids and _hz
        self._ids: list[int] = []
        self._hz: float = 20.0
        self._running = False

    # ── public API (thread-safe) ─────────────────────────────────────
    def set_servo_ids(self, ids: list):
        """Set the list of servo IDs to poll.
        TYPE: User-defined | CALLED BY: External caller after servos found
        """
        with QMutexLocker(self._mutex):
            self._ids = list(ids)

    def set_rate(self, hz: float):
        """Set the polling rate (1–50 Hz).
        TYPE: User-defined | CALLED BY: External caller (e.g., rate slider)
        """
        with QMutexLocker(self._mutex):
            self._hz = max(1.0, min(50.0, hz))

    def stop(self):
        """Stop the polling loop and wait for the thread to finish.
        TYPE: User-defined | CALLED BY: Cleanup on disconnect/close
        CALLS: QThread.wait() [PySide6]
        """
        self._running = False
        self.wait(2000)

    # ── QThread.run ──────────────────────────────────────────────────
    def run(self):
        """Main polling loop — reads telemetry for each servo and emits signals.
        TYPE: User-defined (overrides QThread.run) | CALLED BY: QThread framework
              when thread.start() is called
        CALLS: _HardwareWorker._read_telemetry_locked() [USER, servo_backend.py]
        EMITS: telemetry_update(servo_id, data_dict) for each servo
        """
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
