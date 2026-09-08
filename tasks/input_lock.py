import threading
from contextlib import contextmanager


class AutomationInputLock:
    """Single shared lock for every mouse/keyboard critical section.

    Future merged features must use this lock before moving the mouse,
    clicking, or typing so they cannot interrupt Login/Recovery actions.
    """

    _lock = threading.RLock()
    _owner = None

    @classmethod
    @contextmanager
    def hold(cls, owner="input"):
        cls._lock.acquire()
        previous_owner = cls._owner
        cls._owner = owner
        try:
            yield
        finally:
            cls._owner = previous_owner
            cls._lock.release()

    @classmethod
    def owner(cls):
        return cls._owner
