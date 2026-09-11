"""Final stability cleanup layer before EXE build.

Safe changes only:
- redact usernames/passwords from console + file log output
- add a no-progress watchdog around post-login command execution
- keep image assets external and check important asset paths at startup
- write a small settings/schema snapshot to logs for future maintenance
- support the accidental client_update.png.png asset name without breaking client_update.png

This patch is intentionally additive. It does not change Login order, Recovery
order, Drop, Use, Sash, or item matching logic.
"""

import builtins
import glob
import os
import re
import threading
import time

from gui import DEFAULT_RUNTIME_SETTINGS
from selection_launcher import SelectionAwareLauncher
from tasks.post_login_command_runner import PostLoginCommandRunner
from tasks.post_login_message_task import PostLoginMessageTask


STABILITY_DEFAULTS = {
    # Keep sensitive account data out of logs sent for debugging.
    "privacy_redact_logs_enabled": True,
    # Last-resort protection against silent loops/stalls during post-login work.
    "post_login_no_progress_watchdog_enabled": True,
    "post_login_no_progress_timeout_seconds": 240.0,
    # Maintenance helpers. They only write local logs, never GitHub.
    "maintenance_asset_check_enabled": True,
    "maintenance_write_schema_snapshot": True,
}

DEFAULT_RUNTIME_SETTINGS.update(STABILITY_DEFAULTS)

_LAST_LAUNCHER = None
_ACTIVE_RUNNER = None
_ORIGINAL_PRINT = builtins.print
_ORIGINAL_SELECTION_INIT = SelectionAwareLauncher.__init__
_ORIGINAL_RUN_ACCOUNT_COMMANDS = PostLoginCommandRunner._run_account_commands
_ORIGINAL_START_IF_READY = PostLoginCommandRunner.start_if_ready
_ORIGINAL_MESSAGE_INIT = PostLoginMessageTask.__init__


# ---------------------------------------------------------------------------
# Generic settings helpers
# ---------------------------------------------------------------------------


def _bool_value(value, default=False):
    if isinstance(value, bool):
        return value
    text = str(value if value is not None else "").strip().lower()
    if text in {"1", "true", "yes", "on", "enabled", "enable"}:
        return True
    if text in {"0", "false", "no", "off", "disabled", "disable"}:
        return False
    return bool(default)


def _runtime_setting(owner, key, default=None):
    try:
        if owner is not None and hasattr(owner, "get_runtime_setting"):
            return owner.get_runtime_setting(key, default)
    except Exception:
        pass
    try:
        if owner is not None and hasattr(owner, "launcher"):
            return owner.launcher.get_runtime_setting(key, default)
    except Exception:
        pass
    try:
        if _LAST_LAUNCHER is not None:
            return _LAST_LAUNCHER.get_runtime_setting(key, default)
    except Exception:
        pass
    return DEFAULT_RUNTIME_SETTINGS.get(key, default)


def _runtime_bool(owner, key, default=False):
    return _bool_value(_runtime_setting(owner, key, default), default)


def _runtime_float(owner, key, default, minimum=None, maximum=None):
    try:
        value = float(_runtime_setting(owner, key, default))
    except Exception:
        value = float(default)
    if minimum is not None:
        value = max(float(minimum), value)
    if maximum is not None:
        value = min(float(maximum), value)
    return value


# ---------------------------------------------------------------------------
# Log privacy guard
# ---------------------------------------------------------------------------


def _mask_username(value):
    text = str(value or "")
    if not text:
        return ""
    if len(text) <= 2:
        return "*" * len(text)
    if len(text) <= 5:
        return text[0] + "*" * (len(text) - 1)
    return text[0] + "*" * (len(text) - 2) + text[-1]


def _redact_text(text):
    if text is None:
        return text

    value = str(text)

    # username='abc' / username="abc"
    def repl_user_quoted(match):
        return f"{match.group(1)}{match.group(2)}{_mask_username(match.group(3))}{match.group(2)}"

    value = re.sub(
        r"(?i)\b(username|user_name|login_name)\s*=\s*(['\"])(.*?)(\2)",
        repl_user_quoted,
        value,
    )

    # username=abc without quotes.
    def repl_user_plain(match):
        return f"{match.group(1)}={_mask_username(match.group(2))}"

    value = re.sub(
        r"(?i)\b(username|user_name|login_name)\s*=\s*([^\s,;]+)",
        repl_user_plain,
        value,
    )

    # password='abc' / password=abc
    value = re.sub(
        r"(?i)\b(password|pass|pwd)\s*=\s*(['\"])(.*?)(\2)",
        lambda m: f"{m.group(1)}={m.group(2)}***{m.group(2)}",
        value,
    )
    value = re.sub(
        r"(?i)\b(password|pass|pwd)\s*=\s*([^\s,;]+)",
        lambda m: f"{m.group(1)}=***",
        value,
    )

    # Login credentials entered for USER on target PID ...
    value = re.sub(
        r"(Login credentials entered for\s+)(\S+)(\s+on target PID)",
        lambda m: m.group(1) + _mask_username(m.group(2)) + m.group(3),
        value,
    )

    return value


def _touch_runner_progress(reason="log"):
    runner = _ACTIVE_RUNNER
    if runner is None:
        return
    try:
        if not getattr(runner, "_command_watchdog_active", False):
            return
        runner._last_command_progress_at = time.monotonic()
        runner._last_command_progress_reason = str(reason)
    except Exception:
        pass


def _safe_print(*args, **kwargs):
    try:
        if _runtime_bool(_LAST_LAUNCHER, "privacy_redact_logs_enabled", True):
            args = tuple(_redact_text(arg) for arg in args)
    except Exception:
        pass

    try:
        joined = " ".join(str(arg) for arg in args)
        if any(word in joined for word in ("Post-login", "Inventory", "Sash", "Drop", "Use")):
            _touch_runner_progress("print")
    except Exception:
        pass

    return _ORIGINAL_PRINT(*args, **kwargs)


# ---------------------------------------------------------------------------
# Post-login no-progress watchdog
# ---------------------------------------------------------------------------


def _watchdog_timeout_seconds(runner):
    return _runtime_float(
        getattr(runner, "launcher", None),
        "post_login_no_progress_timeout_seconds",
        240.0,
        minimum=30.0,
        maximum=3600.0,
    )


def _watchdog_enabled(runner):
    return _runtime_bool(
        getattr(runner, "launcher", None),
        "post_login_no_progress_watchdog_enabled",
        True,
    )


def _watchdog_loop(runner):
    while True:
        try:
            if not runner.is_running():
                return
            if runner.stop_event.is_set():
                return
            if not _watchdog_enabled(runner):
                time.sleep(1.0)
                continue

            if not getattr(runner, "_command_watchdog_active", False):
                time.sleep(1.0)
                continue

            last = float(getattr(runner, "_last_command_progress_at", time.monotonic()))
            elapsed = time.monotonic() - last
            timeout = _watchdog_timeout_seconds(runner)

            if elapsed >= timeout:
                account_index = getattr(runner, "_command_watchdog_account_index", None)
                account_text = "?" if account_index is None else str(int(account_index) + 1)
                reason = getattr(runner, "_last_command_progress_reason", "unknown")
                print(
                    "NO_PROGRESS_WATCHDOG triggered - "
                    f"account={account_text} - elapsed={elapsed:.1f}s - "
                    f"timeout={timeout:.1f}s - last_progress={reason}"
                )
                try:
                    runner.stop_event.set()
                    runner._set_status(
                        f"Watchdog أوقف أوامر الدخول: مفيش تقدم {elapsed:.0f} ثانية"
                    )
                except Exception:
                    pass
                return

        except Exception as error:
            try:
                print(f"NO_PROGRESS_WATCHDOG error: {error}")
            except Exception:
                pass
            return

        time.sleep(1.0)


def _ensure_watchdog_thread(runner):
    try:
        thread = getattr(runner, "_no_progress_watchdog_thread", None)
        if thread is not None and thread.is_alive():
            return
        thread = threading.Thread(
            target=_watchdog_loop,
            args=(runner,),
            name="NoProgressWatchdog",
            daemon=True,
        )
        runner._no_progress_watchdog_thread = thread
        thread.start()
    except Exception as error:
        print(f"Could not start no-progress watchdog: {error}")


def _start_if_ready_with_watchdog(self, *args, **kwargs):
    result = _ORIGINAL_START_IF_READY(self, *args, **kwargs)
    if result:
        _ensure_watchdog_thread(self)
    return result


def _run_account_commands_with_progress_guard(self, index, session):
    global _ACTIVE_RUNNER
    old_active_runner = _ACTIVE_RUNNER
    _ACTIVE_RUNNER = self

    try:
        self._command_watchdog_active = True
        self._command_watchdog_account_index = index
        self._last_command_progress_at = time.monotonic()
        self._last_command_progress_reason = "account_command_start"
        _ensure_watchdog_thread(self)
        return _ORIGINAL_RUN_ACCOUNT_COMMANDS(self, index, session)
    finally:
        try:
            self._last_command_progress_at = time.monotonic()
            self._last_command_progress_reason = "account_command_finished"
            self._command_watchdog_active = False
        except Exception:
            pass
        _ACTIVE_RUNNER = old_active_runner


# ---------------------------------------------------------------------------
# Asset compatibility/check + local maintenance snapshots
# ---------------------------------------------------------------------------


def _message_init_with_asset_compat(self, *args, **kwargs):
    _ORIGINAL_MESSAGE_INIT(self, *args, **kwargs)
    try:
        current = self.templates.get(self.CLIENT_UPDATE)
        if current and not os.path.exists(current):
            for alternative in (
                os.path.join("assets", "client_update.png.png"),
                os.path.join("assets", "update_required.png"),
                os.path.join("assets", "client_update_required.png"),
            ):
                if os.path.exists(alternative):
                    self.templates[self.CLIENT_UPDATE] = alternative
                    print(f"Client update image fallback active: {alternative}")
                    break
    except Exception as error:
        print(f"Client update image compatibility check failed: {error}")


def _external_asset_report():
    required = (
        os.path.join("assets", "start_game.PNG"),
        os.path.join("assets", "login_fields.png"),
        os.path.join("assets", "login_button.png"),
        os.path.join("assets", "ok_button.png"),
        os.path.join("assets", "fps_anchor.png"),
    )
    optional_any = (
        ("client_update", (
            os.path.join("assets", "client_update.png"),
            os.path.join("assets", "client_update.png.png"),
        )),
        ("invalid_account_id", (
            os.path.join("assets", "invalid_account_id.png"),
            os.path.join("assets", "failed_invalid_account_id.png"),
            os.path.join("assets", "invalid_id.png"),
        )),
        ("password_length_error", (
            os.path.join("assets", "password_length_error.png"),
            os.path.join("assets", "password_10_14.png"),
        )),
        ("inventory_open", (
            os.path.join("assets", "inventory_open.png"),
            os.path.join("assets", "inventory_open_anchor.png"),
        )),
        ("sash_button", (
            os.path.join("assets", "sash_button.png"),
        )),
        ("sash_next", (
            os.path.join("assets", "sash_next.png"),
            os.path.join("assets", "SashNext.png"),
        )),
    )

    missing_required = [path for path in required if not os.path.exists(path)]
    missing_optional = [name for name, paths in optional_any if not any(os.path.exists(path) for path in paths)]

    return missing_required, missing_optional


def _write_maintenance_files(launcher):
    try:
        os.makedirs("logs", exist_ok=True)
    except Exception:
        return

    if _runtime_bool(launcher, "maintenance_write_schema_snapshot", True):
        try:
            import drop_settings_patch
            groups = getattr(drop_settings_patch, "SETTINGS_GROUPS", ())
            with open(os.path.join("logs", "settings_schema_snapshot.txt"), "w", encoding="utf-8") as file:
                file.write("ZERO BOT settings schema snapshot\n")
                file.write("Generated locally at startup. Do not upload logs.\n\n")
                for title, note, items in groups:
                    file.write(f"[{title}]\n")
                    file.write(f"{note}\n")
                    for key, label in items:
                        file.write(f"- {key}: {label}\n")
                    file.write("\n")
        except Exception as error:
            print(f"Settings schema snapshot failed: {error}")

    if _runtime_bool(launcher, "maintenance_asset_check_enabled", True):
        try:
            missing_required, missing_optional = _external_asset_report()
            with open(os.path.join("logs", "external_assets_check.txt"), "w", encoding="utf-8") as file:
                file.write("ZERO BOT external assets check\n")
                file.write("Images stay outside EXE. Put/edit them in assets\\...\n\n")
                file.write("Drop items: assets\\drop_items\\*.png\n")
                file.write("Use items: assets\\use_items\\*.png\n")
                file.write("Sash items: assets\\sash_items\\*.png\n\n")
                file.write("Missing required files:\n")
                for path in missing_required:
                    file.write(f"- {path}\n")
                if not missing_required:
                    file.write("- none\n")
                file.write("\nMissing optional feature images:\n")
                for name in missing_optional:
                    file.write(f"- {name}\n")
                if not missing_optional:
                    file.write("- none\n")
                file.write("\nCurrent item-template counts:\n")
                for folder in ("drop_items", "use_items", "sash_items"):
                    count = len(glob.glob(os.path.join("assets", folder, "*.png")))
                    file.write(f"- assets\\{folder}: {count}\n")

            if missing_required:
                print("External asset check warning - missing required files: " + ", ".join(missing_required))
        except Exception as error:
            print(f"External asset check failed: {error}")


def _selection_init_with_final_cleanup(self):
    global _LAST_LAUNCHER
    _ORIGINAL_SELECTION_INIT(self)
    _LAST_LAUNCHER = self

    changed = False
    try:
        for key, value in STABILITY_DEFAULTS.items():
            if key not in self.runtime_settings:
                self.runtime_settings[key] = value
                changed = True
        if changed:
            self.apply_runtime_settings()
            self.save_settings()
    except Exception as error:
        print(f"Stability defaults apply failed: {error}")

    _write_maintenance_files(self)


# ---------------------------------------------------------------------------
# Install
# ---------------------------------------------------------------------------


builtins.print = _safe_print
PostLoginMessageTask.__init__ = _message_init_with_asset_compat
PostLoginCommandRunner.start_if_ready = _start_if_ready_with_watchdog
PostLoginCommandRunner._run_account_commands = _run_account_commands_with_progress_guard
SelectionAwareLauncher.__init__ = _selection_init_with_final_cleanup

print("Final stability cleanup patch active: log privacy, no-progress watchdog, asset checks")
