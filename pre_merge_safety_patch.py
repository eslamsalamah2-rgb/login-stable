"""Pre-merge hardening utilities.

Low-risk safeguards before larger feature merges:
- persistent log file
- startup/manual local JSON backup
- shared mouse/keyboard input lock
- future feature flags in settings.json
"""

import builtins
import os
import shutil
import sys
import time
import traceback
from datetime import datetime

import customtkinter as ctk

from gui import DEFAULT_RUNTIME_SETTINGS, SimpleLauncher
from selection_launcher import SelectionAwareLauncher
from tasks.input_lock import AutomationInputLock
from tasks.start_game_task import StartGameTask
from tasks.login_task import LoginTask
from tasks.login_button_task import LoginButtonTask
from tasks.post_login_message_task import PostLoginMessageTask

try:
    import existing_pages_settings_patch
except Exception:
    existing_pages_settings_patch = None


_LOG_INSTALLED = False
_ORIGINAL_PRINT = builtins.print
_ORIGINAL_EXCEPTHOOK = sys.excepthook
_ORIGINAL_COERCE = SimpleLauncher._coerce_runtime_setting
_ORIGINAL_SELECTION_INIT = SelectionAwareLauncher.__init__
_ORIGINAL_START_GAME_START = StartGameTask.start
_ORIGINAL_LOGIN_START = LoginTask.start
_ORIGINAL_LOGIN_REWRITE_PASSWORD = LoginTask.rewrite_password
_ORIGINAL_LOGIN_BUTTON_START = LoginButtonTask.start
_ORIGINAL_PRESS_OK = PostLoginMessageTask.press_ok

FEATURE_DEFAULTS = {
    "auto_scan_open_pages": True,
    "enable_monster_scan": False,
    "enable_auto_drop": False,
    "enable_movement": False,
    "enable_feature_merge_test_mode": True,
}

FEATURE_LABELS = {
    "auto_scan_open_pages": "Scan Open تلقائي عند تشغيل البرنامج",
    "enable_monster_scan": "تفعيل Monster Scan بعد الدمج",
    "enable_auto_drop": "تفعيل Auto Drop بعد الدمج",
    "enable_movement": "تفعيل الحركة/الهجوم بعد الدمج",
    "enable_feature_merge_test_mode": "Merge Test Mode - تشغيل الميزات الجديدة بحذر",
}

BACKUP_FILES = ("accounts.json", "settings.json", "credentials.json")


def _as_bool(value, default=False):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on", "y", "enable", "enabled"}:
        return True
    if text in {"0", "false", "no", "off", "n", "disable", "disabled"}:
        return False
    return bool(default)


def _timestamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _install_file_logger():
    global _LOG_INSTALLED
    if _LOG_INSTALLED:
        return
    _LOG_INSTALLED = True
    os.makedirs("logs", exist_ok=True)
    log_path = os.path.join("logs", "app.log")

    def safe_print(*args, **kwargs):
        _ORIGINAL_PRINT(*args, **kwargs)
        try:
            text = " ".join(str(arg) for arg in args)
            with open(log_path, "a", encoding="utf-8") as file:
                file.write(f"[{_timestamp()}] {text}\n")
        except Exception:
            pass

    def safe_excepthook(exc_type, exc_value, exc_traceback):
        try:
            with open(log_path, "a", encoding="utf-8") as file:
                file.write(f"[{_timestamp()}] UNHANDLED EXCEPTION\n")
                traceback.print_exception(exc_type, exc_value, exc_traceback, file=file)
                file.write("\n")
        except Exception:
            pass
        _ORIGINAL_EXCEPTHOOK(exc_type, exc_value, exc_traceback)

    builtins.print = safe_print
    sys.excepthook = safe_excepthook
    print(f"File logger active: {log_path}")


def _backup_local_json_files(reason="manual"):
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = os.path.join("backups", f"{reason}_{stamp}")
    copied = []

    for filename in BACKUP_FILES:
        if not os.path.exists(filename):
            continue
        os.makedirs(backup_dir, exist_ok=True)
        shutil.copy2(filename, os.path.join(backup_dir, filename))
        copied.append(filename)

    if copied:
        print(f"Backup created - reason={reason} - dir={backup_dir} - files={copied}")
    else:
        print(f"Backup skipped - reason={reason} - no local JSON files found")
    return backup_dir, copied


def _patched_coerce_runtime_setting(self, key, value):
    if isinstance(DEFAULT_RUNTIME_SETTINGS.get(key), bool):
        return _as_bool(value, DEFAULT_RUNTIME_SETTINGS.get(key))
    return _ORIGINAL_COERCE(self, key, value)


def _wrap_with_input_lock(method, owner):
    def wrapper(self, *args, **kwargs):
        with AutomationInputLock.hold(owner):
            print(f"Input lock acquired: {owner}")
            try:
                return method(self, *args, **kwargs)
            finally:
                print(f"Input lock released: {owner}")
    return wrapper


def _create_backup_now(self):
    backup_dir, copied = _backup_local_json_files("manual")
    if copied:
        self.set_status(f"Backup تم - {len(copied)} ملف في {backup_dir}")
    else:
        self.set_status("Backup: لا توجد ملفات JSON محلية للحفظ")


def _selection_init_with_pre_merge_safety(self):
    original_after = None

    # existing_pages_settings_patch schedules the startup Scan Open during __init__.
    # Intercept that schedule so the new Settings flag can turn auto-scan off.
    try:
        original_after = self.app.after

        def guarded_after(delay_ms, callback=None, *args):
            callback_name = getattr(callback, "__name__", "")
            if (
                int(delay_ms) == 900
                and callback_name == "_scan_existing_open_pages"
                and not self.feature_enabled("auto_scan_open_pages", True)
            ):
                print("Auto Scan Open skipped by setting")
                return None
            return original_after(delay_ms, callback, *args)

        self.app.after = guarded_after
    except Exception:
        pass

    try:
        _ORIGINAL_SELECTION_INIT(self)
    finally:
        if original_after is not None:
            try:
                self.app.after = original_after
            except Exception:
                pass

    if not getattr(self, "_startup_backup_done", False):
        self._startup_backup_done = True
        try:
            _backup_local_json_files("startup")
        except Exception as error:
            print(f"Startup backup failed: {error}")

    try:
        controls = self.resume_button.master
        self.backup_button = ctk.CTkButton(
            controls,
            text="Backup",
            width=95,
            height=40,
            command=self.create_backup_now,
        )
        self.backup_button.pack(side="right", padx=6, pady=10)
    except Exception as error:
        print(f"Could not add Backup button: {error}")


def _install_feature_settings():
    DEFAULT_RUNTIME_SETTINGS.update(FEATURE_DEFAULTS)
    if existing_pages_settings_patch is not None:
        try:
            existing_pages_settings_patch.SETTING_LABELS.update(FEATURE_LABELS)
        except Exception:
            pass


def feature_enabled(self, key, default=False):
    return _as_bool(self.get_runtime_setting(key, default), default)


def apply_pre_merge_safety_patch():
    _install_file_logger()
    _install_feature_settings()

    SimpleLauncher._coerce_runtime_setting = _patched_coerce_runtime_setting
    SimpleLauncher.feature_enabled = feature_enabled
    SelectionAwareLauncher.create_backup_now = _create_backup_now
    SelectionAwareLauncher.__init__ = _selection_init_with_pre_merge_safety

    StartGameTask.start = _wrap_with_input_lock(_ORIGINAL_START_GAME_START, "StartGameTask.start")
    LoginTask.start = _wrap_with_input_lock(_ORIGINAL_LOGIN_START, "LoginTask.start")
    LoginTask.rewrite_password = _wrap_with_input_lock(
        _ORIGINAL_LOGIN_REWRITE_PASSWORD,
        "LoginTask.rewrite_password",
    )
    LoginButtonTask.start = _wrap_with_input_lock(
        _ORIGINAL_LOGIN_BUTTON_START,
        "LoginButtonTask.start",
    )
    PostLoginMessageTask.press_ok = _wrap_with_input_lock(
        _ORIGINAL_PRESS_OK,
        "PostLoginMessageTask.press_ok",
    )

    print("Pre-merge safety patch active: logging, backups, input lock, feature flags")


apply_pre_merge_safety_patch()
