import threading


class TargetWindowContext:
    """Thread-safe shared PID for the Conquer page automation is allowed to touch."""

    _lock = threading.Lock()
    _pid = None

    @classmethod
    def set_pid(cls, pid):
        with cls._lock:
            cls._pid = int(pid) if pid else None

    @classmethod
    def get_pid(cls):
        with cls._lock:
            return cls._pid

    @classmethod
    def clear(cls):
        with cls._lock:
            cls._pid = None
