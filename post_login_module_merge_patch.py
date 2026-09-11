"""Safe modular merge layer for post-login workers.

This patch does not merge the old google2 app. It only adds a small module
runner hook so each post-login task remains an isolated worker under Login.
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
    "inventory_probe_save_debug_image": False,
    "inventory_probe_debug_dir": "logs/inventory_probe",
    "enable_inventory_ensure_open": True,
    "inventory_open_hotkey": "i",
    "inventory_open_attempts": 2,
    "inventory_open_wait_seconds": 0.50,
    "inventory_open_strict": False,
    "inventory_open_probe_save_debug_image": False,
    "inventory_open_probe_debug_dir": "logs/inventory_open_probe",
    "enable_inventory_grid_probe": False,
    "inventory_grid_probe_save_debug_image": False,
    "inventory_grid_probe_debug_dir": "logs/inventory_grid_probe",
    "enable_inventory_item_probe": False,
    "inventory_item_templates_dir": "assets/drop_items",
    "inventory_item_match_threshold": 0.72,
    "inventory_item_probe_save_debug_image": False,
    "inventory_item_probe_debug_dir": "logs/inventory_item_probe",
    "enable_inventory_drop_worker": True,
    "inventory_drop_templates_dir": "assets/drop_items",
    "inventory_drop_match_threshold": 0.88,
    "inventory_drop_max_items_per_account": 40,
    "inventory_drop_clicks_per_point": 2,
    # سرعة الدروب الأساسية. كانت 0.01 وده سريع جدًا؛ 0.10 يعني عُشر ثانية بين الضغطات.
    "inventory_drop_click_delay": 0.10,
    # انتظار بعد كل رمية كاملة قبل السكان التالي، لتقليل اللخبطة في الصفحة/الرسائل.
    "inventory_drop_after_drop_delay": 0.15,
    "inventory_drop_target_mode": "top_right",
    "inventory_drop_target_margin_x": 1,
    "inventory_drop_target_margin_y": 1,
    "inventory_drop_target_x_fraction": 0.50,
    "inventory_drop_target_y_fraction": 0.45,
    "inventory_drop_confirm_yes_enabled": True,
    "inventory_drop_confirm_yes_threshold": 0.72,
    "inventory_drop_confirm_yes_timeout": 1.20,
    "inventory_drop_confirm_yes_strict": False,
    "inventory_drop_confirm_yes_paths": "",
    "inventory_drop_save_debug_image": False,
    "inventory_drop_debug_dir": "logs/inventory_drop_worker",
}

MERGE_SETTING_LABELS = {
    "enable_inventory_probe": "enable_inventory_probe | Inventory Probe - التقاط صورة كاملة لنافذة الحساب الحالي",
    "inventory_probe_save_debug_image": "inventory_probe_save_debug_image | Inventory Probe - حفظ صورة كاملة Debug",
    "inventory_probe_debug_dir": "inventory_probe_debug_dir | Inventory Probe - مجلد الصور الكاملة",
    "enable_inventory_ensure_open": "enable_inventory_ensure_open | فتح الشنطة تلقائيًا إذا كانت مقفولة",
    "inventory_open_hotkey": "inventory_open_hotkey | زر فتح الشنطة داخل اللعبة",
    "inventory_open_attempts": "inventory_open_attempts | عدد محاولات فتح الشنطة",
    "inventory_open_wait_seconds": "inventory_open_wait_seconds | انتظار بعد ضغط زر الشنطة/ثانية",
    "inventory_open_strict": "inventory_open_strict | إيقاف الحساب إذا لم تفتح الشنطة",
    "inventory_open_probe_save_debug_image": "inventory_open_probe_save_debug_image | حفظ صور اختبار فتح الشنطة",
    "inventory_open_probe_debug_dir": "inventory_open_probe_debug_dir | مجلد صور اختبار فتح الشنطة",
    "enable_inventory_grid_probe": "enable_inventory_grid_probe | Grid Probe - تحديد خانات الشنطة 5x8",
    "inventory_grid_probe_save_debug_image": "inventory_grid_probe_save_debug_image | Grid Probe - حفظ صورة عليها مربعات الخانات",
    "inventory_grid_probe_debug_dir": "inventory_grid_probe_debug_dir | Grid Probe - مجلد صور الخانات",
    "enable_inventory_item_probe": "enable_inventory_item_probe | Item Probe - التعرف على العناصر من صور assets/drop_items",
    "inventory_item_templates_dir": "inventory_item_templates_dir | مجلد صور العناصر المطلوب التعرف عليها",
    "inventory_item_match_threshold": "inventory_item_match_threshold | حساسية مطابقة صور العناصر",
    "inventory_item_probe_save_debug_image": "inventory_item_probe_save_debug_image | حفظ صورة Debug لمطابقة العناصر",
    "inventory_item_probe_debug_dir": "inventory_item_probe_debug_dir | مجلد صور Debug للعناصر",
    "enable_inventory_drop_worker": "enable_inventory_drop_worker | Drop - رمي العناصر المطابقة فقط",
    "inventory_drop_templates_dir": "inventory_drop_templates_dir | مجلد صور عناصر الدروب",
    "inventory_drop_match_threshold": "inventory_drop_match_threshold | حساسية الدروب - أعلى أمانًا",
    "inventory_drop_max_items_per_account": "inventory_drop_max_items_per_account | أقصى عدد عناصر مطابقة يتم رميها قبل الحساب التالي",
    "inventory_drop_clicks_per_point": "inventory_drop_clicks_per_point | عدد الضغطات على الخانة ومكان الرمي",
    "inventory_drop_click_delay": "inventory_drop_click_delay | سرعة الدروب: وقت بين كل ضغطة والتانية/ثانية - مثال 0.10 أو 0.20",
    "inventory_drop_after_drop_delay": "inventory_drop_after_drop_delay | انتظار بعد كل رمية كاملة قبل السكان التالي/ثانية",
    "inventory_drop_target_mode": "inventory_drop_target_mode | وضع مكان الرمي: top_right أو fraction",
    "inventory_drop_target_margin_x": "inventory_drop_target_margin_x | هامش الرمي من يمين النافذة بالبكسل",
    "inventory_drop_target_margin_y": "inventory_drop_target_margin_y | هامش الرمي من أعلى النافذة بالبكسل",
    "inventory_drop_target_x_fraction": "inventory_drop_target_x_fraction | مكان الرمي أفقيًا كنسبة من عرض النافذة",
    "inventory_drop_target_y_fraction": "inventory_drop_target_y_fraction | مكان الرمي رأسيًا كنسبة من ارتفاع النافذة",
    "inventory_drop_confirm_yes_enabled": "inventory_drop_confirm_yes_enabled | الضغط على Yes بعد الدروب",
    "inventory_drop_confirm_yes_threshold": "inventory_drop_confirm_yes_threshold | حساسية صورة Yes",
    "inventory_drop_confirm_yes_timeout": "inventory_drop_confirm_yes_timeout | مدة انتظار Yes/ثانية",
    "inventory_drop_confirm_yes_strict": "inventory_drop_confirm_yes_strict | إيقاف الحساب إذا لم يتم ضغط Yes",
    "inventory_drop_confirm_yes_paths": "inventory_drop_confirm_yes_paths | مسارات إضافية لصورة Yes",
    "inventory_drop_save_debug_image": "inventory_drop_save_debug_image | حفظ صور Debug قبل/بعد الدروب",
    "inventory_drop_debug_dir": "inventory_drop_debug_dir | مجلد صور Debug للدروب",
}


# إعدادات تتفرض عند الضغط على Drop Scan أو عند بداية البرنامج علشان المرحلة الحالية تفضل Drop.
# لا نضع فيها سرعات الدروب؛ السرعات تبقى قابلة للتعديل من Settings ولا يتم مسح تعديل المستخدم كل تشغيل.
DROP_TEST_FORCED_SETTINGS = {
    "enable_post_login_commands": True,
    "post_login_debug_only": False,
    "enable_inventory_probe": False,
    "enable_inventory_ensure_open": True,
    "enable_inventory_grid_probe": False,
    "enable_inventory_item_probe": False,
    "enable_inventory_drop_worker": True,
    "post_login_account_delay_seconds": 0.10,
    "post_login_round_delay_seconds": 0.25,
}

DROP_SPEED_MIGRATIONS = {
    "inventory_drop_click_delay": (0.01, 0.10),
    "inventory_drop_after_drop_delay": (0.0, 0.15),
}


# للاحتفاظ باسم المتغير القديم في أي لوج/كود خارجي، لكنه لم يعد يمسح سرعات المستخدم.
DROP_TEST_PRESET = dict(DROP_TEST_FORCED_SETTINGS)


def _install_merge_settings():
    DEFAULT_RUNTIME_SETTINGS.update(MERGE_SETTING_DEFAULTS)

    if existing_pages_settings_patch is not None:
        try:
            existing_pages_settings_patch.SETTING_LABELS.update(MERGE_SETTING_LABELS)
        except Exception:
            pass


def _apply_default_settings_without_overwriting_user_speed(self):
    for key, value in MERGE_SETTING_DEFAULTS.items():
        if key not in self.runtime_settings:
            self.runtime_settings[key] = value

    for key, (old_value, new_value) in DROP_SPEED_MIGRATIONS.items():
        raw = self.runtime_settings.get(key, None)
        should_migrate = raw is None
        if not should_migrate:
            try:
                should_migrate = abs(float(raw) - float(old_value)) < 0.000001
            except Exception:
                should_migrate = True
        if should_migrate:
            self.runtime_settings[key] = new_value


def _apply_inventory_grid_settings(self, reason="startup", start_runner=False):
    """Prepare the program for the current fast rescan-drop test.

    Drop execution rescans after every item, but visual debug probes are disabled
    so it does not waste time saving images while dropping. Drop speed remains
    editable from Settings and is not overwritten by this preset.
    """
    try:
        _apply_default_settings_without_overwriting_user_speed(self)
        self.runtime_settings.update(DROP_TEST_FORCED_SETTINGS)
        self.apply_runtime_settings()
        self.save_settings()
        print(
            "Inventory Rescan-Drop preset applied - "
            f"reason={reason} - forced={DROP_TEST_FORCED_SETTINGS} - "
            f"click_delay={self.runtime_settings.get('inventory_drop_click_delay')} - "
            f"after_drop_delay={self.runtime_settings.get('inventory_drop_after_drop_delay')}"
        )
        self.set_status("Drop جاهز: السرعة قابلة للتعديل من Settings")
    except Exception as error:
        print(f"Inventory Drop preset failed: {error}")
        self.set_status("فشل تجهيز اختبار Drop")
        return

    if not start_runner:
        return

    runner = getattr(self, "post_login_runner", None)
    if runner is None:
        self.set_status("اختبار Drop جاهز، لكن أوامر الدخول غير جاهزة")
        return

    try:
        self.app.after(300, lambda: runner.start_if_ready("inventory_fast_rescan_drop_button"))
    except Exception as error:
        print(f"Could not start Inventory Drop test: {error}")


def _apply_inventory_probe_test_preset(self):
    _apply_inventory_grid_settings(
        self,
        reason="fast_rescan_drop_button",
        start_runner=True,
    )


def _add_inventory_probe_test_button(self):
    try:
        controls = self.resume_button.master
        self.inventory_probe_test_button = ctk.CTkButton(
            controls,
            text="Drop Scan",
            width=115,
            height=40,
            fg_color="#6b4f00",
            hover_color="#806000",
            command=lambda: self.start_inventory_probe_test(),
        )
        self.inventory_probe_test_button.pack(side="left", padx=6, pady=10)
    except Exception as error:
        print(f"Could not add Inventory Drop test button: {error}")


def _selection_init_with_probe_button(self):
    _ORIGINAL_SELECTION_INIT(self)
    _add_inventory_probe_test_button(self)

    try:
        self.app.after(
            200,
            lambda: _apply_inventory_grid_settings(
                self,
                reason="auto_startup_for_current_test",
                start_runner=False,
            ),
        )
    except Exception as error:
        print(f"Could not auto-apply Inventory Drop settings: {error}")


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

            # Let long real modules observe key 9 immediately. The keyboard/UI
            # handler sets this event through runner.request_stop().
            try:
                self.launcher.post_login_stop_event = self.stop_event
            except Exception:
                pass

            result = run_enabled_post_login_modules(self.launcher, index, session)

            try:
                if hasattr(self.launcher, "post_login_stop_event"):
                    delattr(self.launcher, "post_login_stop_event")
            except Exception:
                pass

            if result == "STOP_REQUESTED" or self.stop_event.is_set():
                print(
                    "Post-login real modules stopped by user - "
                    f"account={index + 1} - pid={pid}"
                )
                self._set_status("أوامر الدخول اتوقفت بزر 9")
                return "OK"

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
