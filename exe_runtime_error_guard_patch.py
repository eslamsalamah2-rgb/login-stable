"""Make hidden EXE worker failures visible instead of silently stopping.

PyInstaller's --windowed mode has no console. An exception inside the worker
thread can therefore look like: Start Game opens, then nothing happens. This
patch preserves the existing workflow and only catches/logs unexpected errors,
updates the GUI status, and resets the running flag so the user can retry.
"""

from __future__ import annotations

import traceback
from pathlib import Path

from selection_launcher import SelectionAwareLauncher


_ORIGINAL_PROCESS_ACCOUNTS = SelectionAwareLauncher.process_accounts
_ORIGINAL_START = SelectionAwareLauncher.start_from_beginning
_ORIGINAL_RESUME = getattr(SelectionAwareLauncher, "resume_processing", None)


def _write_runtime_error(stage: str) -> None:
    try:
        log_dir = Path.cwd() / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        with (log_dir / "runtime_error.log").open("a", encoding="utf-8") as stream:
            stream.write("\n" + "=" * 70 + "\n")
            stream.write(f"Login runtime error: {stage}\n")
            stream.write(traceback.format_exc())
            stream.write("\n")
    except Exception:
        pass


def _set_error_status(self, stage: str, error: BaseException) -> None:
    try:
        self.is_running = False
    except Exception:
        pass
    try:
        self.pause_requested = False
    except Exception:
        pass
    try:
        self.set_status(f"خطأ في {stage}: {error} - راجع logs\\runtime_error.log")
    except Exception:
        pass
    print(f"EXE runtime error captured - stage={stage} - {error}")


def _process_accounts_guarded(self, *args, **kwargs):
    try:
        return _ORIGINAL_PROCESS_ACCOUNTS(self, *args, **kwargs)
    except Exception as error:
        _write_runtime_error("process_accounts")
        _set_error_status(self, "تشغيل الحسابات", error)
        return None


def _start_guarded(self, *args, **kwargs):
    try:
        return _ORIGINAL_START(self, *args, **kwargs)
    except Exception as error:
        _write_runtime_error("start_from_beginning")
        _set_error_status(self, "Start", error)
        return None


def _resume_guarded(self, *args, **kwargs):
    try:
        return _ORIGINAL_RESUME(self, *args, **kwargs)
    except Exception as error:
        _write_runtime_error("resume_processing")
        _set_error_status(self, "Resume", error)
        return None


SelectionAwareLauncher.process_accounts = _process_accounts_guarded
SelectionAwareLauncher.start_from_beginning = _start_guarded
if _ORIGINAL_RESUME is not None:
    SelectionAwareLauncher.resume_processing = _resume_guarded

print("EXE runtime error guard active: worker failures are logged instead of disappearing")
