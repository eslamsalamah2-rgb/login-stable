"""Final UI controls + runtime key settings.

What this patch does:
- keeps the main toolbar clean by hiding account Select All / Clear Selection buttons
- restores Select All / Clear All / Save inside Drop/Use/Sash item selector windows
- keeps item thumbnails in those selector windows
- adds editable keyboard keys to Settings: Start, Stop, inventory open key, post-Sash key
- prevents automatic post-login work when the program is opened; user must press Start/8

This patch is UI/runtime-control only. It does not touch Login typing or Login
recovery logic.
"""

import os
import time

import customtkinter as ctk
import keyboard
import pydirectinput
from PIL import Image

from gui import DEFAULT_RUNTIME_SETTINGS
from selection_launcher import SelectionAwareLauncher
from tasks.post_login_command_runner import PostLoginCommandRunner
from tasks.post_login_modules.post_sash_final_actions import PostSashFinalActionsModule

try:
    import drop_settings_patch
except Exception:
    drop_settings_patch = None

try:
    import item_selection_patch
except Exception:
    item_selection_patch = None

try:
    import compact_item_selector_ui_patch
except Exception:
    compact_item_selector_ui_patch = None


_ORIGINAL_SELECTION_INIT = SelectionAwareLauncher.__init__
_ORIGINAL_APPLY_RUNTIME_SETTINGS = SelectionAwareLauncher.apply_runtime_settings
_ORIGINAL_START_IF_READY = PostLoginCommandRunner.start_if_ready
_ORIGINAL_PRESS_I_TWICE = PostSashFinalActionsModule._press_i_twice
_ORIGINAL_SCAN_OPEN = getattr(SelectionAwareLauncher, "scan_existing_open_pages", None)
_ORIGINAL_START_FROM_BEGINNING = SelectionAwareLauncher.start_from_beginning

THUMBNAIL_SIZE = 32

CONTROL_KEY_DEFAULTS = {
    "program_start_hotkey": "8",
    "program_stop_hotkey": "9",
    "inventory_open_hotkey": "i",
    "post_sash_i_press_key": "i",
    "manual_start_required": True,
    "auto_start_post_login_on_startup": False,
}

CONTROL_KEYS_GROUP = (
    "Setting Keys / أزرار التشغيل",
    "أي زرار مهم في البرنامج تقدر تغيره من هنا. بعد الحفظ الهوتكي الجديد يشتغل فورًا.",
    (
        ("program_start_hotkey", "زر Start من الكيبورد - الافتراضي 8"),
        ("program_stop_hotkey", "زر Stop من الكيبورد - الافتراضي 9"),
        ("inventory_open_hotkey", "زر فتح الشنطة داخل اللعبة - الافتراضي i"),
        ("post_sash_i_press_key", "الزر اللي يتضغط بعد Sash بعدد مرتين - الافتراضي i"),
        ("manual_start_required", "منع التشغيل التلقائي عند فتح البرنامج - True يعني لازم تضغط Start"),
        ("auto_start_post_login_on_startup", "تشغيل أوامر الدخول تلقائيًا عند فتح البرنامج - خليه False"),
    ),
)


def _install_control_key_defaults():
    DEFAULT_RUNTIME_SETTINGS.update(CONTROL_KEY_DEFAULTS)

    if drop_settings_patch is None:
        return

    try:
        groups = list(drop_settings_patch.SETTINGS_GROUPS)
        if not any(group[0] == CONTROL_KEYS_GROUP[0] for group in groups):
            groups.insert(0, CONTROL_KEYS_GROUP)
            drop_settings_patch.SETTINGS_GROUPS = tuple(groups)
    except Exception as error:
        print(f"Could not install key settings group: {error}")


def _runtime_bool(self, key, default=False):
    value = None
    try:
        value = self.get_runtime_setting(key, default)
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


def _runtime_text(self, key, default=""):
    try:
        value = self.get_runtime_setting(key, default)
    except Exception:
        value = default
    text = str(value if value is not None else "").strip()
    return text or str(default or "").strip()


def _hide_widget(widget):
    if widget is None:
        return
    for method_name in ("pack_forget", "grid_forget", "place_forget"):
        try:
            getattr(widget, method_name)()
            return
        except Exception:
            pass


def _configure_widget(widget, **kwargs):
    if widget is None:
        return
    try:
        widget.configure(**kwargs)
    except Exception:
        pass


def _clean_main_toolbar(self):
    # دول اللي المستخدم قصد عليهم: أزرار تحديد/إلغاء تحديد الحسابات من واجهة البرنامج الخارجية.
    _hide_widget(getattr(self, "select_all_button", None))
    _hide_widget(getattr(self, "clear_selection_button", None))

    # أزرار أوامر الدخول اليدوية اتشالت؛ Start هو بوابة التشغيل، وStop هو زر الإيقاف.
    _hide_widget(getattr(self, "start_commands_button", None))
    _hide_widget(getattr(self, "stop_commands_button", None))

    # أدوات Debug/Scan القديمة مش لازمة في الشريط اليومي.
    for attr in (
        "inventory_probe_test_button",
        "backup_button",
        "scan_open_pages_button",
    ):
        _hide_widget(getattr(self, attr, None))

    _hide_widget(getattr(self, "open_pages_panel", None))

    for attr, width in (
        ("start_fresh_button", 108),
        ("pause_button", 102),
        ("resume_button", 102),
        ("settings_button", 82),
        ("add_account_button", 105),
        ("save_accounts_button", 105),
        ("drop_item_selector_button", 105),
        ("use_item_selector_button", 105),
        ("sash_item_selector_button", 105),
    ):
        _configure_widget(getattr(self, attr, None), width=width, height=32)

    try:
        self.app.geometry("1020x690")
        self.app.minsize(900, 600)
    except Exception:
        pass


def _update_hotkey_button_texts(self):
    start_key = _runtime_text(self, "program_start_hotkey", "8")
    stop_key = _runtime_text(self, "program_stop_hotkey", "9")

    _configure_widget(getattr(self, "start_fresh_button", None), text=f"Start {start_key}")
    _configure_widget(getattr(self, "resume_button", None), text=f"استكمال {start_key}")
    _configure_widget(getattr(self, "pause_button", None), text=f"Stop {stop_key}")


def _register_runtime_hotkeys(self):
    start_key = _runtime_text(self, "program_start_hotkey", "8")
    stop_key = _runtime_text(self, "program_stop_hotkey", "9")

    if start_key and stop_key and start_key.lower() == stop_key.lower():
        print(f"Runtime hotkeys invalid: Start and Stop are the same ({start_key!r}); Stop changed to '9'")
        stop_key = "9" if start_key.lower() != "9" else "ctrl+9"
        try:
            self.runtime_settings["program_stop_hotkey"] = stop_key
            self.save_settings()
        except Exception:
            pass

    try:
        keyboard.unhook_all_hotkeys()
    except Exception as error:
        print(f"Runtime hotkey cleanup warning: {error}")

    installed = []

    if start_key:
        try:
            keyboard.add_hotkey(start_key, lambda: self.app.after(0, self.resume_processing))
            installed.append(("start", start_key))
        except Exception as error:
            print(f"Could not bind Start hotkey {start_key!r}: {error}")

    if stop_key:
        try:
            keyboard.add_hotkey(stop_key, lambda: self.app.after(0, self.pause_processing))
            installed.append(("stop", stop_key))
        except Exception as error:
            print(f"Could not bind Stop hotkey {stop_key!r}: {error}")

    _update_hotkey_button_texts(self)
    print(f"Runtime hotkeys active: {installed}")


def _apply_runtime_settings_with_hotkeys(self):
    result = _ORIGINAL_APPLY_RUNTIME_SETTINGS(self)
    try:
        _register_runtime_hotkeys(self)
    except Exception as error:
        print(f"Runtime hotkey apply failed: {error}")
    return result


def _start_if_ready_no_startup_auto(self, reason="manual"):
    launcher = getattr(self, "launcher", None)
    reason_text = str(reason or "")

    if reason_text == "startup_ready_scan":
        allow = False
        try:
            allow = _runtime_bool(launcher, "auto_start_post_login_on_startup", False)
        except Exception:
            allow = False

        if not allow:
            print("Post-login startup auto-start skipped - waiting for Start button/hotkey")
            try:
                launcher.set_status("جاهز - اضغط Start للتشغيل")
            except Exception:
                pass
            return False

    return _ORIGINAL_START_IF_READY(self, reason)


def _scan_open_manual_only(self):
    if _ORIGINAL_SCAN_OPEN is None:
        return None

    if _runtime_bool(self, "manual_start_required", True) and not getattr(self, "_allow_manual_scan_open", False):
        print("Auto Scan Open skipped - manual_start_required=True")
        return None

    return _ORIGINAL_SCAN_OPEN(self)


def _start_from_beginning_with_manual_scan_flag(self):
    # Start هو الإذن الوحيد للتشغيل/الفحص. نسمح بفحص داخلي أثناء ضغط Start فقط لو الكود احتاجه لاحقًا.
    self._allow_manual_scan_open = True
    try:
        return _ORIGINAL_START_FROM_BEGINNING(self)
    finally:
        try:
            self._allow_manual_scan_open = False
        except Exception:
            pass


def _press_configured_inventory_key(self):
    count = self._int_setting("post_sash_i_press_count", 2, minimum=0, maximum=5)
    key = _runtime_text(self.launcher, "post_sash_i_press_key", _runtime_text(self.launcher, "inventory_open_hotkey", "i"))
    delay = self._float_setting("post_sash_i_press_delay", 0.20, minimum=0.0, maximum=2.0)
    after_delay = self._float_setting("post_sash_after_i_delay", 0.30, minimum=0.0, maximum=3.0)

    for index in range(count):
        if self._stop_requested():
            return False
        print(f"Post-sash final action: press {key} {index + 1}/{count}")
        try:
            pydirectinput.press(key)
        except Exception as error:
            print(f"Post-sash final action key press failed: key={key!r} - {error}")
            return False
        if delay > 0 and not self._sleep_interruptible(delay):
            return False

    if after_delay > 0 and not self._sleep_interruptible(after_delay):
        return False
    return not self._stop_requested()


def _stage_images(stage):
    if item_selection_patch is None:
        return []
    try:
        return item_selection_patch._list_stage_images(stage)
    except Exception:
        return []


def _load_selection_data():
    if compact_item_selector_ui_patch is not None:
        try:
            return compact_item_selector_ui_patch.load_item_selections_default_all()
        except Exception:
            pass
    if item_selection_patch is not None:
        try:
            return item_selection_patch.load_item_selections()
        except Exception:
            pass
    return {}


def _save_selection_data(data):
    if compact_item_selector_ui_patch is not None:
        try:
            return compact_item_selector_ui_patch.save_item_selections_with_seen(data)
        except Exception:
            pass
    if item_selection_patch is not None:
        try:
            return item_selection_patch.save_item_selections(data)
        except Exception:
            pass
    return False


def _refresh_item_labels(self):
    for module in (compact_item_selector_ui_patch, item_selection_patch):
        if module is None:
            continue
        try:
            module._refresh_item_button_labels(self)
            return
        except Exception:
            continue


def _set_all_vars(vars_by_name, value):
    for var in vars_by_name.values():
        try:
            var.set(bool(value))
        except Exception:
            pass


def _load_thumb(path):
    try:
        image = Image.open(path).convert("RGBA")
        return ctk.CTkImage(light_image=image, dark_image=image, size=(THUMBNAIL_SIZE, THUMBNAIL_SIZE))
    except Exception:
        return None


def _open_item_selector_with_bottom_controls(self, stage):
    if item_selection_patch is None or stage not in item_selection_patch.STAGES:
        return

    meta = item_selection_patch.STAGES[stage]
    files = _stage_images(stage)
    data = _load_selection_data()
    selected = set(data.get(stage, []))

    # أول استخدام: كل الصور الموجودة تكون مختارة افتراضيًا.
    if files and not data.get(stage):
        selected = set(files)
        data[stage] = list(files)
        data.setdefault("_seen", {})[stage] = list(files)
        _save_selection_data(data)

    window = ctk.CTkToplevel(self.app)
    window.title(meta["button"])
    window.geometry("500x585")
    window.minsize(455, 520)
    window.transient(self.app)
    window.grab_set()

    ctk.CTkLabel(
        window,
        text=meta["title"],
        font=("Segoe UI", 17, "bold"),
    ).pack(pady=(10, 2))

    ctk.CTkLabel(
        window,
        text="اختار العناصر المطلوبة واضغط حفظ. الاختيار عام على كل الحسابات.",
        font=("Segoe UI", 12),
        text_color="#d7d7d7",
        wraplength=450,
    ).pack(padx=10, pady=(0, 4))

    summary_var = ctk.StringVar(value="")
    ctk.CTkLabel(window, textvariable=summary_var, font=("Segoe UI", 12, "bold")).pack(pady=(0, 5))

    body = ctk.CTkScrollableFrame(window, height=415)
    body.pack(fill="both", expand=True, padx=10, pady=(0, 8))

    vars_by_name = {}
    thumb_refs = []

    def update_summary():
        count = sum(1 for var in vars_by_name.values() if bool(var.get()))
        summary_var.set(f"مختار: {count} / {len(files)}")

    if not files:
        ctk.CTkLabel(
            body,
            text="مفيش صور في الفولدر ده. حط صور الـ Items وافتح النافذة تاني.",
            font=("Segoe UI", 13),
            text_color="#ffc107",
            wraplength=390,
        ).pack(padx=10, pady=20)
    else:
        for name in files:
            row = ctk.CTkFrame(body)
            row.pack(fill="x", padx=4, pady=3)

            image_path = os.path.join(meta["folder"], name)
            thumb = _load_thumb(image_path)
            if thumb is not None:
                thumb_refs.append(thumb)
                image_label = ctk.CTkLabel(row, image=thumb, text="", width=40)
            else:
                image_label = ctk.CTkLabel(row, text="NoImg", width=40)
            image_label.pack(side="left", padx=(6, 5), pady=4)

            var = ctk.BooleanVar(value=name in selected)
            vars_by_name[name] = var
            box = ctk.CTkCheckBox(
                row,
                text=name,
                variable=var,
                onvalue=True,
                offvalue=False,
                font=("Segoe UI", 12),
                command=update_summary,
            )
            box.pack(side="left", fill="x", expand=True, padx=(2, 6), pady=5)

    window._item_selector_thumb_refs = thumb_refs

    def save_stage_selection():
        current = _load_selection_data()
        current[stage] = [name for name in files if name in vars_by_name and bool(vars_by_name[name].get())]
        current.setdefault("_seen", {})[stage] = list(files)
        if _save_selection_data(current):
            print(f"Item selection saved - stage={stage} - selected={current[stage]}")
            self.set_status(f"تم حفظ {meta['button']} - المختار {len(current[stage])} من {len(files)}")
            _refresh_item_labels(self)
            window.destroy()
        else:
            self.set_status("فشل حفظ اختيار الـ Items")

    buttons = ctk.CTkFrame(window, fg_color="transparent")
    buttons.pack(fill="x", padx=10, pady=(0, 10))

    ctk.CTkButton(
        buttons,
        text="اختيار الكل",
        width=100,
        height=32,
        command=lambda: (_set_all_vars(vars_by_name, True), update_summary()),
    ).pack(side="left", padx=4)

    ctk.CTkButton(
        buttons,
        text="إلغاء الكل",
        width=100,
        height=32,
        command=lambda: (_set_all_vars(vars_by_name, False), update_summary()),
    ).pack(side="left", padx=4)

    ctk.CTkButton(buttons, text="حفظ", width=90, height=32, command=save_stage_selection).pack(side="right", padx=4)
    ctk.CTkButton(buttons, text="إغلاق", width=90, height=32, command=window.destroy).pack(side="right", padx=4)

    update_summary()


def _selection_init_with_ui_controls(self):
    _ORIGINAL_SELECTION_INIT(self)

    try:
        self.runtime_settings["manual_start_required"] = True
        self.runtime_settings["auto_start_post_login_on_startup"] = False
        self.runtime_settings["auto_scan_open_pages"] = False
        self.save_settings()
    except Exception:
        pass

    _clean_main_toolbar(self)
    _update_hotkey_button_texts(self)
    _register_runtime_hotkeys(self)


def apply_ui_controls_settings_patch():
    _install_control_key_defaults()

    SelectionAwareLauncher.apply_runtime_settings = _apply_runtime_settings_with_hotkeys
    SelectionAwareLauncher.scan_existing_open_pages = _scan_open_manual_only
    SelectionAwareLauncher.start_from_beginning = _start_from_beginning_with_manual_scan_flag
    SelectionAwareLauncher.open_item_selector = _open_item_selector_with_bottom_controls
    SelectionAwareLauncher.__init__ = _selection_init_with_ui_controls

    PostLoginCommandRunner.start_if_ready = _start_if_ready_no_startup_auto
    PostSashFinalActionsModule._press_i_twice = _press_configured_inventory_key

    print("UI controls settings patch active: key settings + manual start + restored item selector controls")


apply_ui_controls_settings_patch()
