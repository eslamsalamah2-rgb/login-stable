"""Safe modular merge layer for post-login workers.

This patch does not merge the old google2 app. It only adds a small module
runner hook so each future task can be added as an isolated worker.
"""

from gui import DEFAULT_RUNTIME_SETTINGS
from selection_launcher import SelectionAwareLauncher
from tasks.input_lock import AutomationInputLock
from tasks.post_login_command_runner import PostLoginCommandRunner
from tasks.post_login_modules.registry import (
    has_enabled_post_login_modules,
    run_enabled_post_login_modules,
)

try:
    import existing_pages_settings_patch
except Exception:
    existing_pages_settings_patch = None


_ORIGINAL_HAS_ENABLED_WORK_MODULE = PostLoginCommandRunner._has_enabled_work_module
_ORIGINAL_RUN_ACCOUNT_COMMANDS = PostLoginCommandRunner._run_account_commands


MERGE_SETTING_DEFAULTS = {
    "enable_inventory_probe": False,
    "inventory_probe_save_debug_image": True,
    "inventory_probe_debug_dir": "logs/inventory_probe",
}

MERGE_SETTING_LABELS = {
    "enable_inventory_probe": "Inventory Probe - التقاط صورة نافذة الحساب الحالي فقط",
    "inventory_probe_save_debug_image": "Inventory Probe - حفظ صورة Debug",
    "inventory_probe_debug_dir": "Inventory Probe - مجلد صور Debug",
}


def _install_merge_settings():
    DEFAULT_RUNTIME_SETTINGS.update(MERGE_SETTING_DEFAULTS)

    if existing_pages_settings_patch is not None:
        try:
            existing_pages_settings_patch.SETTING_LABELS.update(MERGE_SETTING_LABELS)
        except Exception:
            pass


def _has_enabled_work_module_with_merge(self):
    try:
        if has_enabled_post_login_modules(self.launcher):
            return True
    except Exception as error:
        print(f"Post-login module enabled check failed: {error}")

    return _ORIGINAL_HAS_ENABLED_WORK_MODULE(self)


def _run_account_commands_with_modules(self, index, session):
    """Run debug mode as before, but real mode through isolated modules."""
    try:
        if self._debug_only():
            return _ORIGINAL_RUN_ACCOUNT_COMMANDS(self, index, session)

        pid = session.get("pid")
        page_name = session.get("page_name", "")
        self.current_index = index

        with AutomationInputLock.hold("PostLoginCommandRunner.real_modules"):
            activated, activate_reason = self._activate_account_window(index, session)
            if not activated:
                return activate_reason

            current_gate = self.gate.account_ready(index)
            if not current_gate.ok:
                return current_gate.reason

            print(
                "Post-login real module gate OK - "
                f"account={index + 1} - pid={pid} - name={page_name!r}"
            )

            result = run_enabled_post_login_modules(self.launcher, index, session)
            if result != "OK":
                return result

            print(
                "Post-login real modules finished - "
                f"account={index + 1} - pid={pid}"
            )
            self._set_status(
                f"أوامر الدخول: الحساب {index + 1} تم تنفيذ موديولات الدمج عليه"
            )
            return "OK"

    except Exception as error:
        print(f"Post-login merged module step error - account={index + 1}: {error}")
        return "POST_LOGIN_MERGE_MODULE_ERROR"


def apply_post_login_module_merge_patch():
    _install_merge_settings()

    PostLoginCommandRunner._has_enabled_work_module = _has_enabled_work_module_with_merge
    PostLoginCommandRunner._run_account_commands = _run_account_commands_with_modules

    print("Post-login module merge patch active: modular workers enabled")


apply_post_login_module_merge_patch()
