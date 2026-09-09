from dataclasses import dataclass, field

from tasks.memory_reader import ConquerMemoryReader


@dataclass
class LoginGateResult:
    ok: bool
    reason: str = "READY"
    account_index: int | None = None
    ready_indices: list[int] = field(default_factory=list)


class LoginPriorityGate:
    """Single authority that decides whether post-login work may run.

    Login/Health is the controller. Post-login command modules are workers.
    A worker may execute only when this gate says the current account is READY.
    """

    def __init__(self, launcher):
        self.launcher = launcher

    # ---------------------------------------------------------------
    # Global priority
    # ---------------------------------------------------------------

    def login_priority_active(self):
        if getattr(self.launcher, "is_running", False):
            return True, "LOGIN_SEQUENCE_RUNNING"

        pause_event = getattr(self.launcher, "monitor_pause_event", None)
        if pause_event is not None:
            try:
                if pause_event.is_set():
                    return True, "LOGIN_MONITOR_PAUSED"
            except Exception:
                pass

        pause_requested = getattr(self.launcher, "pause_requested", False)
        if pause_requested:
            return True, "USER_PAUSE_REQUESTED"

        return False, "OK"

    # ---------------------------------------------------------------
    # Selection
    # ---------------------------------------------------------------

    def selected_indices(self):
        try:
            if hasattr(self.launcher, "_selected_indices"):
                return list(self.launcher._selected_indices())
        except Exception:
            pass

        try:
            return sorted(int(i) for i in self.launcher.active_sessions.keys())
        except Exception:
            return []

    def account_is_recovering(self, index):
        try:
            with self.launcher.recovering_accounts_lock:
                return index in self.launcher.recovering_accounts
        except Exception:
            return False

    # ---------------------------------------------------------------
    # Health checks
    # ---------------------------------------------------------------

    def read_health(self, pid):
        try:
            if hasattr(self.launcher, "_read_health"):
                return self.launcher._read_health(pid)
        except Exception as error:
            print(f"LoginPriorityGate health read failed via launcher - PID {pid}: {error}")

        reader = None
        try:
            reader = ConquerMemoryReader(pid)
            return reader.read_name() or "", reader.read_state()
        except Exception as error:
            print(f"LoginPriorityGate health read failed - PID {pid}: {error}")
            return None, None
        finally:
            if reader is not None:
                try:
                    reader.close()
                except Exception:
                    pass

    def account_ready(self, index):
        priority_active, priority_reason = self.login_priority_active()
        if priority_active:
            return LoginGateResult(False, priority_reason, index)

        if self.account_is_recovering(index):
            return LoginGateResult(False, "RECOVERING", index)

        session = self.launcher.active_sessions.get(index)
        if not session:
            return LoginGateResult(False, "NO_SESSION", index)

        pid = session.get("pid")
        if not pid:
            return LoginGateResult(False, "NO_PID", index)

        live_pids = set(ConquerMemoryReader.list_conquer_pids())
        if pid not in live_pids:
            return LoginGateResult(False, "PID_MISSING", index)

        try:
            detector = getattr(self.launcher, "window_disconnect_detector", None)
            if detector is not None and detector.has_disconnect_dialog(pid):
                return LoginGateResult(False, "DISCONNECTED_DIALOG", index)
        except Exception as error:
            print(f"LoginPriorityGate disconnect check failed - account {index + 1}: {error}")

        current_name, current_state = self.read_health(pid)
        if current_name is None or current_state is None:
            return LoginGateResult(False, "MEMORY_READ_FAILED", index)

        expected_name = session.get("page_name", "")
        if not expected_name and 0 <= index < len(self.launcher.accounts_data):
            expected_name = self.launcher.accounts_data[index].get("character_name", "")

        if expected_name and current_name != expected_name:
            return LoginGateResult(
                False,
                f"NAME_MISMATCH({current_name!r}!={expected_name!r})",
                index,
            )

        healthy_state = session.get("healthy_state")
        if healthy_state is None:
            return LoginGateResult(False, "BASELINE_PENDING", index)

        try:
            if hasattr(self.launcher, "_state_requires_timer") and self.launcher._state_requires_timer(current_state):
                return LoginGateResult(False, f"TIMER_REQUIRED_FOR_STATE({current_state})", index)
        except Exception:
            pass

        if current_state != healthy_state:
            return LoginGateResult(
                False,
                f"STATE_MISMATCH({current_state}!={healthy_state})",
                index,
            )

        return LoginGateResult(True, "READY", index)

    def all_selected_ready(self):
        priority_active, priority_reason = self.login_priority_active()
        if priority_active:
            return LoginGateResult(False, priority_reason, None)

        selected = self.selected_indices()
        if not selected:
            return LoginGateResult(False, "NO_SELECTED_ACCOUNTS", None)

        ready = []
        for index in selected:
            result = self.account_ready(index)
            if not result.ok:
                result.ready_indices = ready
                return result
            ready.append(index)

        return LoginGateResult(True, "READY", None, ready)
