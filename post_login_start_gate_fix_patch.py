"""Make Start run post-login commands after Login, but never on app startup.

Problem fixed:
- The top Start button could start Login, then leave post-login commands idle.
- If all selected pages were already open, top Start could report Login state but
  not enter Drop/Use/Sash.

Rules kept:
- Program startup may scan pages and update lamps only.
- Real Drop/Use/Sash starts only after the user presses Start/hotkey.
- Login stays the controller; post-login work runs only after READY gate.
"""

from gui import DEFAULT_RUNTIME_SETTINGS
from selection_launcher import SelectionAwareLauncher


_ORIGINAL_SELECTION_INIT = SelectionAwareLauncher.__init__
_ORIGINAL_START_FROM_BEGINNING = SelectionAwareLauncher.start_from_beginning
_ORIGINAL_RESUME_PROCESSING = SelectionAwareLauncher.resume_processing
_ORIGINAL_PROCESS_ACCOUNTS = SelectionAwareLauncher.process_accounts

DEFAULT_RUNTIME_SETTINGS.update({
    "manual_start_required": True,
    "auto_start_post_login_on_startup": False,
    "enable_post_login_commands": True,
    "post_login_debug_only": False,
    "enable_inventory_ensure_open": True,
    "enable_inventory_drop_worker": True,
})


def _runtime_bool(launcher, key, default=False):
    try:
        value = launcher.get_runtime_setting(key, default)
    except Exception:
        value = default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on", "enabled"}:
        return True
    if text in {"0", "false", "no", "off", "disabled"}:
        return False
    return bool(default)


def _prepare_real_post_login_settings(launcher):
    """Enable the real command gate without touching timings or item selections."""
    changed = False
    wanted = {
        "manual_start_required": True,
        "auto_start_post_login_on_startup": False,
        "enable_post_login_commands": True,
        "post_login_debug_only": False,
        "enable_inventory_ensure_open": True,
        "enable_inventory_drop_worker": True,
    }

    try:
        for key, value in wanted.items():
            if launcher.runtime_settings.get(key) != value:
                launcher.runtime_settings[key] = value
                changed = True

        if changed:
            try:
                launcher.apply_runtime_settings()
            except Exception:
                pass
            launcher.save_settings()
            print("POST_LOGIN_START_GATE settings prepared for real Drop/Use/Sash")
    except Exception as error:
        print(f"POST_LOGIN_START_GATE settings prepare failed: {error}")


def _start_runner_after_manual_start(launcher, reason):
    if not getattr(launcher, "_post_login_manual_start_requested", False):
        print(f"POST_LOGIN_START_GATE skipped - no manual Start flag - reason={reason}")
        return False

    runner = getattr(launcher, "post_login_runner", None)
    if runner is None:
        print(f"POST_LOGIN_START_GATE skipped - runner missing - reason={reason}")
        try:
            launcher.set_status("أوامر الدخول غير جاهزة")
        except Exception:
            pass
        return False

    _prepare_real_post_login_settings(launcher)

    try:
        print(f"POST_LOGIN_START_GATE starting runner - reason={reason}")
        return runner.start_if_ready(reason)
    except Exception as error:
        print(f"POST_LOGIN_START_GATE runner start failed - reason={reason} - {error}")
        return False


def _schedule_runner_after_manual_start(launcher, reason, delay_ms=700):
    try:
        launcher.app.after(
            int(delay_ms),
            lambda: _start_runner_after_manual_start(launcher, reason),
        )
        print(f"POST_LOGIN_START_GATE scheduled - reason={reason} - delay={delay_ms}ms")
        return True
    except Exception as error:
        print(f"POST_LOGIN_START_GATE schedule failed - reason={reason} - {error}")
        return False


def _selection_init_with_post_login_gate(self):
    _ORIGINAL_SELECTION_INIT(self)

    try:
        self._post_login_manual_start_requested = False
    except Exception:
        pass

    # Make the visible top Start smart: if accounts need Login it opens them;
    # if they are already READY it starts Drop/Use/Sash.
    try:
        top_start = getattr(self, "top_start_button", None)
        if top_start is not None:
            top_start.configure(command=self.resume_processing)
    except Exception as error:
        print(f"POST_LOGIN_START_GATE could not bind top Start button: {error}")

    try:
        self.runtime_settings["manual_start_required"] = True
        self.runtime_settings["auto_start_post_login_on_startup"] = False
        self.runtime_settings["enable_post_login_commands"] = True
        self.runtime_settings["post_login_debug_only"] = False
        self.runtime_settings["enable_inventory_ensure_open"] = True
        self.runtime_settings["enable_inventory_drop_worker"] = True
        self.save_settings()
    except Exception:
        pass


def _start_from_beginning_with_post_login_gate(self):
    self._post_login_manual_start_requested = True
    print("POST_LOGIN_START_GATE manual Start pressed - start_from_beginning")

    result = _ORIGINAL_START_FROM_BEGINNING(self)

    # If no new Login pages were needed, process_accounts will not run, so start
    # the runner directly after the READY gate check.
    try:
        if not getattr(self, "is_running", False):
            _schedule_runner_after_manual_start(self, "manual_start_existing_pages_ready", 500)
    except Exception:
        pass

    return result


def _resume_processing_with_post_login_gate(self):
    self._post_login_manual_start_requested = True
    print("POST_LOGIN_START_GATE manual Start pressed - resume_processing")

    result = _ORIGINAL_RESUME_PROCESSING(self)

    # The original resume hook may also schedule this. Duplicate calls are safe;
    # the runner ignores them if it is already running.
    _schedule_runner_after_manual_start(self, "manual_start_or_resume", 700)
    return result


def _process_accounts_with_post_login_gate(self, *args, **kwargs):
    try:
        return _ORIGINAL_PROCESS_ACCOUNTS(self, *args, **kwargs)
    finally:
        if getattr(self, "_post_login_manual_start_requested", False):
            _schedule_runner_after_manual_start(self, "login_sequence_finished_start_post_login", 900)


SelectionAwareLauncher.__init__ = _selection_init_with_post_login_gate
SelectionAwareLauncher.start_from_beginning = _start_from_beginning_with_post_login_gate
SelectionAwareLauncher.resume_processing = _resume_processing_with_post_login_gate
SelectionAwareLauncher.process_accounts = _process_accounts_with_post_login_gate

print("Post-login start gate fix active: Start triggers Drop/Use/Sash after Login, startup does not")
