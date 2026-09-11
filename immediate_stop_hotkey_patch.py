"""Immediate Stop hotkey reliability patch.

Problem fixed:
- The Stop hotkey could feel delayed because the old binding waited for Tk/app
  callbacks while a worker was busy.

Safe behavior:
- The keyboard callback sets stop/pause flags immediately from the hook thread.
- The normal UI pause flow is still scheduled afterward for status/UI cleanup.
- A small polling fallback watches the configured Stop key as a backup.
- Settings stay editable through program_stop_hotkey.
"""

import threading
import time

import keyboard

from selection_launcher import SelectionAwareLauncher
from tasks.post_login_command_runner import PostLoginCommandRunner


_ORIGINAL_SELECTION_INIT = SelectionAwareLauncher.__init__
_ORIGINAL_APPLY_RUNTIME_SETTINGS = SelectionAwareLauncher.apply_runtime_settings
_ORIGINAL_PAUSE_PROCESSING = SelectionAwareLauncher.pause_processing
_ORIGINAL_CLOSE_PROGRAM = SelectionAwareLauncher.close_program
_ORIGINAL_RUNNER_REQUEST_STOP = PostLoginCommandRunner.request_stop


def _runtime_text(launcher, key, default=""):
    try:
        value = launcher.get_runtime_setting(key, default)
    except Exception:
        value = default
    text = str(value if value is not None else "").strip()
    return text or str(default or "").strip()


def _signal_stop_now(launcher, reason="immediate_stop"):
    """Set every stop flag immediately. No waiting for UI/main thread."""
    try:
        launcher.pause_requested = True
    except Exception:
        pass

    try:
        launcher.monitor_pause_event.set()
    except Exception:
        pass

    try:
        event = getattr(launcher, "post_login_stop_event", None)
        if event is not None:
            event.set()
    except Exception:
        pass

    runner = getattr(launcher, "post_login_runner", None)
    if runner is not None:
        try:
            runner.stop_event.set()
        except Exception:
            pass
        try:
            runner._command_watchdog_active = False
        except Exception:
            pass

    now = time.monotonic()
    last = float(getattr(launcher, "_last_immediate_stop_log_at", 0.0) or 0.0)
    if now - last >= 0.35:
        try:
            launcher._last_immediate_stop_log_at = now
        except Exception:
            pass
        print(f"IMMEDIATE_STOP signal set - reason={reason}")


def _schedule_normal_pause(launcher, reason="immediate_stop"):
    def run_pause():
        try:
            _ORIGINAL_PAUSE_PROCESSING(launcher)
        except Exception as error:
            print(f"IMMEDIATE_STOP normal pause failed - reason={reason} - {error}")

    try:
        launcher.app.after(0, run_pause)
    except Exception:
        run_pause()


def _stop_hotkey_callback(launcher, key_name):
    _signal_stop_now(launcher, f"stop_hotkey_{key_name}")
    _schedule_normal_pause(launcher, f"stop_hotkey_{key_name}")


def _remove_old_immediate_hotkeys(launcher):
    handles = list(getattr(launcher, "_immediate_stop_hotkey_handles", []) or [])
    for handle in handles:
        try:
            keyboard.remove_hotkey(handle)
        except Exception:
            pass
    try:
        launcher._immediate_stop_hotkey_handles = []
    except Exception:
        pass


def _stop_key_variants(key):
    key = str(key or "").strip()
    if not key:
        return []

    variants = [key]
    if key.lower() == "9":
        # Main keyboard 9 + numpad 9. Some machines report numpad separately.
        variants.extend(["num 9", "num9"])

    unique = []
    seen = set()
    for item in variants:
        lower = item.lower()
        if lower in seen:
            continue
        seen.add(lower)
        unique.append(item)
    return unique


def _bind_immediate_stop_hotkey(launcher):
    _remove_old_immediate_hotkeys(launcher)

    key = _runtime_text(launcher, "program_stop_hotkey", "9")
    handles = []

    for variant in _stop_key_variants(key):
        try:
            handle = keyboard.add_hotkey(
                variant,
                lambda v=variant, l=launcher: _stop_hotkey_callback(l, v),
                suppress=False,
                trigger_on_release=False,
            )
            handles.append(handle)
        except Exception as error:
            print(f"IMMEDIATE_STOP could not bind {variant!r}: {error}")

    try:
        launcher._immediate_stop_hotkey_handles = handles
    except Exception:
        pass

    if handles:
        print(f"Immediate Stop hotkey active: {key} - handles={len(handles)}")
    else:
        print(f"Immediate Stop hotkey not active: {key}")


def _poll_stop_key_loop(launcher):
    last_signal_at = 0.0

    while not bool(getattr(launcher, "_immediate_stop_poll_closed", False)):
        try:
            key = _runtime_text(launcher, "program_stop_hotkey", "9")
            pressed = False
            for variant in _stop_key_variants(key):
                try:
                    if keyboard.is_pressed(variant):
                        pressed = True
                        break
                except Exception:
                    continue

            if pressed:
                now = time.monotonic()
                if now - last_signal_at >= 0.45:
                    last_signal_at = now
                    _signal_stop_now(launcher, "stop_key_polling_fallback")
                    _schedule_normal_pause(launcher, "stop_key_polling_fallback")
                time.sleep(0.16)
            else:
                time.sleep(0.05)
        except Exception as error:
            print(f"Immediate Stop polling stopped: {error}")
            return


def _ensure_stop_poll_thread(launcher):
    try:
        thread = getattr(launcher, "_immediate_stop_poll_thread", None)
        if thread is not None and thread.is_alive():
            return
        launcher._immediate_stop_poll_closed = False
        thread = threading.Thread(
            target=_poll_stop_key_loop,
            args=(launcher,),
            name="ImmediateStopPoll",
            daemon=True,
        )
        launcher._immediate_stop_poll_thread = thread
        thread.start()
        print("Immediate Stop polling fallback active")
    except Exception as error:
        print(f"Could not start Immediate Stop polling fallback: {error}")


def _runner_request_stop_immediate(self, reason="manual"):
    try:
        _signal_stop_now(self.launcher, f"runner_request_stop_{reason}")
    except Exception:
        pass
    return _ORIGINAL_RUNNER_REQUEST_STOP(self, reason)


def _pause_processing_immediate(self):
    _signal_stop_now(self, "pause_processing")
    return _ORIGINAL_PAUSE_PROCESSING(self)


def _apply_runtime_settings_with_immediate_stop(self):
    result = _ORIGINAL_APPLY_RUNTIME_SETTINGS(self)
    try:
        _bind_immediate_stop_hotkey(self)
        _ensure_stop_poll_thread(self)
    except Exception as error:
        print(f"Immediate Stop apply failed: {error}")
    return result


def _close_program_with_immediate_stop_cleanup(self):
    try:
        self._immediate_stop_poll_closed = True
    except Exception:
        pass
    try:
        _remove_old_immediate_hotkeys(self)
    except Exception:
        pass
    return _ORIGINAL_CLOSE_PROGRAM(self)


def _selection_init_with_immediate_stop(self):
    _ORIGINAL_SELECTION_INIT(self)
    _bind_immediate_stop_hotkey(self)
    _ensure_stop_poll_thread(self)


PostLoginCommandRunner.request_stop = _runner_request_stop_immediate
SelectionAwareLauncher.pause_processing = _pause_processing_immediate
SelectionAwareLauncher.apply_runtime_settings = _apply_runtime_settings_with_immediate_stop
SelectionAwareLauncher.close_program = _close_program_with_immediate_stop_cleanup
SelectionAwareLauncher.__init__ = _selection_init_with_immediate_stop

print("Immediate Stop hotkey patch active: direct stop signal + polling fallback")
