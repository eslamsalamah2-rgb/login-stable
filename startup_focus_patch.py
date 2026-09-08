import time

from maintenance_launcher import MaintenanceAwareLauncher
from selection_launcher import SelectionAwareLauncher
from tasks.memory_reader import ConquerMemoryReader
from tasks.target_window_context import TargetWindowContext


_original_run_account = MaintenanceAwareLauncher.run_account
_original_process_accounts = SelectionAwareLauncher.process_accounts


def _patched_run_account(self, *args, **kwargs):
    """Recover the same account if login input failed after a focus interruption."""
    result, page_name = _original_run_account(self, *args, **kwargs)

    if result == "LOGIN_FIELDS_ERROR":
        pid = TargetWindowContext.get_pid()
        print(
            f"Login input failed while opening account - target PID {pid}; "
            "closing that page and retrying the same account"
        )
        if pid:
            ConquerMemoryReader.terminate_conquer_pid(pid)
            time.sleep(1.0)
        return "PAGE_TIMEOUT_RETRY", None

    return result, page_name


def _patched_process_accounts(self, *args, **kwargs):
    """Do not let the health monitor compete with Start/Login input work."""
    monitor_was_paused = self.monitor_pause_event.is_set()

    if not monitor_was_paused:
        self.monitor_pause_event.set()
        print("Health monitor paused during Start/Login input sequence")

    try:
        return _original_process_accounts(self, *args, **kwargs)
    finally:
        if not monitor_was_paused and not self.pause_requested:
            self.monitor_pause_event.clear()
            print("Health monitor resumed after Start/Login input sequence")


MaintenanceAwareLauncher.run_account = _patched_run_account
SelectionAwareLauncher.process_accounts = _patched_process_accounts
