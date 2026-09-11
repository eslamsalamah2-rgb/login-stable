"""Safe modular merge layer for post-login workers.

This patch does not merge the old google2 app. It only adds a small module
runner hook so each future task can be added as an isolated worker.
"""

import customtkinter as ctk

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


_ORIGINAL_SELECTION_INIT = SelectionAwareLauncher.__init__
_ORIGINAL_HAS_ENABLED_WORK_MODULE = PostLoginCommandRunner._has_enabled_work_module
_ORIGINAL_RUN_ACCOUNT_COMMANDS = PostLoginCommandRunner._run_account_commands


MERGE_SETTING_DEFAULTS = {
    "enable_inventory_probe": False,
    "inventory_probe_save_debug_image": True,
    "inventory_probe_debug_dir": "logs/inventory_probe",
}

MERGE_SETTING_LABELS = {
    "enable_inventory_probe": "enable_inventory_probe | Inventory Probe - التقاط صورة نافذة الحساب الحالي فقط",
    "inventory_probe_save_debug_image": "inventory_probe_save_debug_image | Inventory Probe - حفظ صورة Debug",
    "inventory_probe_debug_dir": "inventory_probe_debug_dir | Inventory Probe - مجلد صور Debug",
}


PROBE_TEST_PRESET = {
    "enable_post_login_commands": True,
    "post_login_debug_only": False,
    "enable_inventory_probe": True,
    "inventory_probe_save_debug_image": True,
}


def _install_merge_settings():
    DEFAULT_RUNTIME_SETTINGS.update(MERGE_SETTING_DEFAULTS)

    if existing_pages_settings_patch is not None:
        try:
            existing_pages_settings_patch.SETTING_LABELS.update(MERGE_SETTING_LABELS)
        except Exception:
            pass


def _apply_inventory_probe_test_preset(self):
    """One-click setup for the first real merge test.

    This avoids asking the user to hunt for raw setting names. It switches out
    of background Test Mode and enables only the safe InventoryProbe module.
    """
    try:
        self.runtime_settings.update(PROBE_TEST_PRESET)
        self.apply_runtime_settings()
        self.save_settings()
        print(f"Inventory Probe test preset applied: {PROBE_TEST_PRESET}")
        self.set_status("تم تجهيز اختبار InventoryProbe - تشغيل Capture للحساب الحالي فقط")
    except Exception as error:
        print(f"Inventory Probe preset failed: {error}")
        self.set_status("فشل تجهيز اختبار InventoryProbe")
        return

    runner = getattr(self, "post_login_runner", None)
    if runner is None:
        self.set_status("InventoryProbe جاهز، لكن أوامر الدخول غير جاهزة")
        return

    try:
        self.app.after(300, lambda: runner.start_if_ready("inventory_probe_test_button"))
    except Exception as error:
        print(f"Could not start Inventory Probe test: {error}")


def _add_inventory_probe_test_button(self):
    try:
        controls = self.resume_button.master
        self.inventory_probe_test_button = ctk.CTkButton(
            controls,
            text="Probe Test",
            width=115,
            height=40,
            fg_color="#6b4f00",
            hover_color="#806000",
            command=lambda: self.start_inventory_probe_test(),
        )
        self.inventory_probe_test_button.pack(side="left", padx=6, pady=10)
    except Exception as error:
        print(f"Could not add Inventory Probe test button: {error}")


def _selection_init_with_probe_button(self):
    _ORIGINAL_SELECTION_INIT(self)
    _add_inventory_probe_test_button(self)


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

    SelectionAwareLauncher.start_inventory_probe_test = _apply_inventory_probe_test_preset
    SelectionAwareLauncher.__init__ = _selection_init_with_probe_button
    PostLoginCommandRunner._has_enabled_work_module = _has_enabled_work_module_with_merge
    PostLoginCommandRunner._run_account_commands = _run_account_commands_with_modules

    print("Post-login module merge patch active: modular workers enabled")


apply_post_login_module_merge_patch()
