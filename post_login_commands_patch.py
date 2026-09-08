"""Stage 1 for post-login commands.

This patch adds the command runner that starts only after selected accounts are
READY. Login/Health/Recovery always has priority over command work.
"""

import customtkinter as ctk

from gui import DEFAULT_RUNTIME_SETTINGS
from selection_launcher import SelectionAwareLauncher
from tasks.post_login_command_runner import PostLoginCommandRunner

try:
    import existing_pages_settings_patch
except Exception:
    existing_pages_settings_patch = None


_ORIGINAL_SELECTION_INIT = SelectionAwareLauncher.__init__
_ORIGINAL_PROCESS_ACCOUNTS = SelectionAwareLauncher.process_accounts
_ORIGINAL_PAUSE_PROCESSING = SelectionAwareLauncher.pause_processing
_ORIGINAL_RESUME_PROCESSING = SelectionAwareLauncher.resume_processing
_ORIGINAL_CLOSE_PROGRAM = SelectionAwareLauncher.close_program
_ORIGINAL_MARK_RECOVERY_STARTED = SelectionAwareLauncher._mark_recovery_started
_ORIGINAL_MARK_RECOVERY_FINISHED = SelectionAwareLauncher._mark_recovery_finished


COMMAND_SETTING_DEFAULTS = {
    "enable_post_login_commands": True,
    "post_login_debug_only": True,
    "post_login_recovery_max_seconds": 120.0,
    "post_login_account_delay_seconds": 1.0,
    "post_login_round_delay_seconds": 2.0,
}

COMMAND_SETTING_LABELS = {
    "enable_post_login_commands": "تفعيل أوامر الدخول بعد اكتمال Login",
    "post_login_debug_only": "أوامر الدخول Test Mode بدون ضغط/رمي",
    "post_login_recovery_max_seconds": "أقصى وقت انتظار إصلاح الحساب قبل إغلاقه/ثانية",
    "post_login_account_delay_seconds": "فاصل بين كل حساب في أوامر الدخول/ثانية",
    "post_login_round_delay_seconds": "فاصل بين دورات أوامر الدخول/ثانية",
}


def _install_command_settings():
    DEFAULT_RUNTIME_SETTINGS.update(COMMAND_SETTING_DEFAULTS)

    if existing_pages_settings_patch is not None:
        try:
            existing_pages_settings_patch.SETTING_LABELS.update(COMMAND_SETTING_LABELS)
        except Exception:
            pass


def _manual_start_commands(self):
    runner = getattr(self, "post_login_runner", None)
    if runner is None:
        self.set_status("أوامر الدخول غير جاهزة")
        return
    runner.start_if_ready("manual_button")


def _manual_stop_commands(self):
    runner = getattr(self, "post_login_runner", None)
    if runner is None:
        return
    runner.request_stop("manual_button")


def _add_command_buttons(self):
    try:
        controls = self.resume_button.master

        self.start_commands_button = ctk.CTkButton(
            controls,
            text="أوامر الدخول",
            width=125,
            height=40,
            command=lambda: self.start_post_login_commands(),
        )
        self.start_commands_button.pack(side="left", padx=6, pady=10)

        self.stop_commands_button = ctk.CTkButton(
            controls,
            text="Stop أوامر",
            width=105,
            height=40,
            fg_color="#8b0000",
            hover_color="#a00000",
            command=lambda: self.stop_post_login_commands(),
        )
        self.stop_commands_button.pack(side="left", padx=6, pady=10)

    except Exception as error:
        print(f"Could not add post-login command buttons: {error}")


def _selection_init_with_post_login_commands(self):
    _ORIGINAL_SELECTION_INIT(self)

    self.post_login_runner = PostLoginCommandRunner(self)
    _add_command_buttons(self)

    try:
        self.app.after(
            1400,
            lambda: self.post_login_runner.start_if_ready("startup_ready_scan"),
        )
    except Exception as error:
        print(f"Could not schedule post-login startup scan: {error}")


def _start_or_resume_with_commands(self):
    """Hotkey Start behavior.

    If selected accounts still need pages, start the login sequence.
    If all selected accounts are already READY, start/resume post-login commands.
    """
    runner = getattr(self, "post_login_runner", None)

    try:
        if not self.is_running and hasattr(self, "_build_incremental_start_queue"):
            selected, pending = self._build_incremental_start_queue()
            if selected and pending:
                print(
                    "Start hotkey: selected accounts need login - "
                    f"opening {[i + 1 for i in pending]}"
                )
                return self.start_from_beginning()
    except Exception as error:
        print(f"Start hotkey pending check failed: {error}")

    result = _ORIGINAL_RESUME_PROCESSING(self)

    if runner is not None:
        try:
            self.app.after(
                500,
                lambda: runner.start_if_ready("start_hotkey_8"),
            )
        except Exception as error:
            print(f"Could not start commands from Start hotkey: {error}")

    return result


def _pause_with_commands_stop(self):
    runner = getattr(self, "post_login_runner", None)
    if runner is not None:
        runner.request_stop("stop_hotkey_9_or_pause")
    return _ORIGINAL_PAUSE_PROCESSING(self)


def _process_accounts_then_commands(self):
    runner = getattr(self, "post_login_runner", None)
    if runner is not None:
        runner.pause_for_login_priority("process_accounts_start")

    try:
        return _ORIGINAL_PROCESS_ACCOUNTS(self)

    finally:
        runner = getattr(self, "post_login_runner", None)
        if runner is not None:
            try:
                self.app.after(
                    700,
                    lambda: runner.start_if_ready("process_accounts_finished"),
                )
            except Exception as error:
                print(f"Could not schedule post-login command start: {error}")


def _mark_recovery_started_with_command_pause(self, row_index):
    runner = getattr(self, "post_login_runner", None)
    if runner is not None:
        runner.pause_for_login_priority(f"recovery_started_account_{row_index + 1}")

    return _ORIGINAL_MARK_RECOVERY_STARTED(self, row_index)


def _mark_recovery_finished_with_command_resume(self, row_index):
    result = _ORIGINAL_MARK_RECOVERY_FINISHED(self, row_index)

    runner = getattr(self, "post_login_runner", None)
    if runner is not None:
        try:
            self.app.after(
                700,
                lambda: runner.start_if_ready(f"recovery_finished_account_{row_index + 1}"),
            )
        except Exception as error:
            print(f"Could not schedule commands after recovery: {error}")

    return result


def _close_program_with_commands_stop(self):
    runner = getattr(self, "post_login_runner", None)
    if runner is not None:
        runner.request_stop("program_close")
    return _ORIGINAL_CLOSE_PROGRAM(self)


def apply_post_login_commands_patch():
    _install_command_settings()

    SelectionAwareLauncher.start_post_login_commands = _manual_start_commands
    SelectionAwareLauncher.stop_post_login_commands = _manual_stop_commands
    SelectionAwareLauncher.__init__ = _selection_init_with_post_login_commands
    SelectionAwareLauncher.resume_processing = _start_or_resume_with_commands
    SelectionAwareLauncher.pause_processing = _pause_with_commands_stop
    SelectionAwareLauncher.process_accounts = _process_accounts_then_commands
    SelectionAwareLauncher._mark_recovery_started = _mark_recovery_started_with_command_pause
    SelectionAwareLauncher._mark_recovery_finished = _mark_recovery_finished_with_command_resume
    SelectionAwareLauncher.close_program = _close_program_with_commands_stop

    print("Post-login commands patch active: stage 1 runner installed")


apply_post_login_commands_patch()
