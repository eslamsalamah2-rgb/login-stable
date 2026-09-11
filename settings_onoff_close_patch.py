"""Settings ON/OFF switches + program close shortcut.

This is a UI/runtime-control patch only:
- boolean Settings are shown as ON/OFF switches instead of True/False text boxes
- adds program_close_hotkey, default Ctrl+Q
- adds an "إغلاق البرنامج" button inside Settings
- keeps startup manual by default; no auto work starts when the app opens
"""

import json
import os

import customtkinter as ctk
import keyboard

from config import CONFIG_FILE
from gui import DEFAULT_RUNTIME_SETTINGS
from selection_launcher import SelectionAwareLauncher

try:
    import drop_settings_patch
except Exception:
    drop_settings_patch = None


_ORIGINAL_SELECTION_INIT = SelectionAwareLauncher.__init__
_ORIGINAL_APPLY_RUNTIME_SETTINGS = SelectionAwareLauncher.apply_runtime_settings

CONTROL_DEFAULTS = {
    "program_close_hotkey": "ctrl+q",
    "manual_start_required": True,
    "auto_start_post_login_on_startup": False,
}

CONTROL_GROUP_TITLE = "Setting Keys / أزرار التشغيل"
CONTROL_GROUP = (
    CONTROL_GROUP_TITLE,
    "اختصارات التشغيل والإيقاف والإغلاق. الاختيارات ON/OFF تظهر كسويتش بدل True/False.",
    (
        ("program_start_hotkey", "زر Start من الكيبورد"),
        ("program_stop_hotkey", "زر Stop من الكيبورد"),
        ("program_close_hotkey", "اختصار إغلاق البرنامج بالكامل"),
        ("inventory_open_hotkey", "زر فتح الشنطة داخل اللعبة"),
        ("post_sash_i_press_key", "الزر اللي يتضغط بعد Sash"),
        ("manual_start_required", "تشغيل يدوي فقط عند فتح البرنامج"),
        ("auto_start_post_login_on_startup", "تشغيل أوامر الدخول تلقائيًا عند فتح البرنامج"),
    ),
)

PRESERVE_FROM_SETTINGS_FILE = (
    "program_start_hotkey",
    "program_stop_hotkey",
    "program_close_hotkey",
    "inventory_open_hotkey",
    "post_sash_i_press_key",
    "manual_start_required",
    "auto_start_post_login_on_startup",
    "auto_scan_open_pages",
)


def _read_settings_file_raw():
    if not os.path.exists(CONFIG_FILE):
        return {}
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)
        return data if isinstance(data, dict) else {}
    except Exception as error:
        print(f"Settings ON/OFF raw load failed: {error}")
        return {}


def _install_defaults_and_group():
    DEFAULT_RUNTIME_SETTINGS.update(CONTROL_DEFAULTS)

    if drop_settings_patch is None:
        return

    try:
        groups = []
        replaced = False
        for group in getattr(drop_settings_patch, "SETTINGS_GROUPS", ()):
            if group and group[0] == CONTROL_GROUP_TITLE:
                groups.append(CONTROL_GROUP)
                replaced = True
            else:
                groups.append(group)
        if not replaced:
            groups.insert(0, CONTROL_GROUP)
        drop_settings_patch.SETTINGS_GROUPS = tuple(groups)
    except Exception as error:
        print(f"Could not install ON/OFF key settings group: {error}")


def _runtime_text(self, key, default=""):
    try:
        value = self.get_runtime_setting(key, default)
    except Exception:
        value = default
    text = str(value if value is not None else "").strip()
    return text or str(default or "").strip()


def _bool_value(value, default=False):
    if isinstance(value, bool):
        return value
    text = str(value if value is not None else "").strip().lower()
    if text in {"1", "true", "yes", "on", "enabled", "enable"}:
        return True
    if text in {"0", "false", "no", "off", "disabled", "disable"}:
        return False
    return bool(default)


def _runtime_bool(self, key, default=False):
    try:
        return _bool_value(self.get_runtime_setting(key, default), default)
    except Exception:
        return bool(default)


def _is_bool_setting(key):
    if key in {"manual_start_required", "auto_start_post_login_on_startup"}:
        return True
    return isinstance(DEFAULT_RUNTIME_SETTINGS.get(key), bool)


def _coerce_value(self, key, raw):
    if _is_bool_setting(key):
        return _bool_value(raw, DEFAULT_RUNTIME_SETTINGS.get(key, False))
    try:
        return self._coerce_runtime_setting(key, raw)
    except Exception:
        text = str(raw).strip()
        try:
            if "." in text:
                return float(text)
            return int(text)
        except Exception:
            return text


def _add_entry_row(body, label_text, value):
    row = ctk.CTkFrame(body)
    row.pack(fill="x", padx=6, pady=3)

    ctk.CTkLabel(
        row,
        text=label_text,
        width=405,
        anchor="w",
        font=("Segoe UI", 12),
    ).pack(side="left", padx=(8, 4), pady=6)

    entry = ctk.CTkEntry(row, width=135, height=30)
    entry.pack(side="right", padx=(4, 8), pady=6)
    entry.insert(0, str(value if value is not None else ""))
    return entry


def _add_switch_row(body, label_text, value):
    row = ctk.CTkFrame(body)
    row.pack(fill="x", padx=6, pady=3)

    ctk.CTkLabel(
        row,
        text=label_text,
        width=405,
        anchor="w",
        font=("Segoe UI", 12),
    ).pack(side="left", padx=(8, 4), pady=6)

    var = ctk.BooleanVar(value=_bool_value(value))
    state_label = ctk.CTkLabel(row, text="ON" if var.get() else "OFF", width=42, font=("Segoe UI", 12, "bold"))
    state_label.pack(side="right", padx=(0, 8), pady=6)

    def sync_label():
        state_label.configure(text="ON" if var.get() else "OFF")

    switch = ctk.CTkSwitch(
        row,
        text="",
        width=58,
        variable=var,
        onvalue=True,
        offvalue=False,
        command=sync_label,
    )
    switch.pack(side="right", padx=(4, 2), pady=6)
    return var


def _setting_value(self, key):
    try:
        return self.runtime_settings.get(key, self.get_runtime_setting(key))
    except Exception:
        try:
            return self.get_runtime_setting(key)
        except Exception:
            return DEFAULT_RUNTIME_SETTINGS.get(key, "")


def _settings_groups():
    if drop_settings_patch is not None:
        try:
            return tuple(drop_settings_patch.SETTINGS_GROUPS)
        except Exception:
            pass
    return (CONTROL_GROUP,)


def _open_settings_window_onoff(self):
    window = ctk.CTkToplevel(self.app)
    window.title("Settings")
    window.geometry("670x670")
    window.transient(self.app)
    window.grab_set()

    ctk.CTkLabel(
        window,
        text="Settings",
        font=("Segoe UI", 22, "bold"),
    ).pack(pady=(12, 3))

    ctk.CTkLabel(
        window,
        text="الأزرار والاختصارات والأوقات. قيم ON/OFF تظهر كسويتش واضح.",
        font=("Segoe UI", 12),
        text_color="#cfcfcf",
    ).pack(pady=(0, 8))

    body = ctk.CTkScrollableFrame(window, height=505)
    body.pack(fill="both", expand=True, padx=14, pady=(0, 10))

    entries = {}
    switches = {}

    for title, note, items in _settings_groups():
        section = ctk.CTkFrame(body, fg_color="#263238")
        section.pack(fill="x", padx=6, pady=(9, 5))
        ctk.CTkLabel(
            section,
            text=title,
            font=("Segoe UI", 16, "bold"),
            anchor="w",
        ).pack(fill="x", padx=10, pady=(7, 1))
        ctk.CTkLabel(
            section,
            text=note,
            font=("Segoe UI", 11),
            text_color="#d6d6d6",
            anchor="w",
            wraplength=590,
        ).pack(fill="x", padx=10, pady=(0, 7))

        for key, label in items:
            value = _setting_value(self, key)
            if _is_bool_setting(key):
                switches[key] = _add_switch_row(body, label, value)
            else:
                entries[key] = _add_entry_row(body, label, value)

    def save_window_settings():
        changed = {}
        for key, entry in entries.items():
            changed[key] = _coerce_value(self, key, entry.get())
        for key, var in switches.items():
            changed[key] = bool(var.get())

        # This instruction is the safe default: no automatic work on app open.
        if "manual_start_required" not in changed:
            changed["manual_start_required"] = True
        if "auto_start_post_login_on_startup" not in changed:
            changed["auto_start_post_login_on_startup"] = False

        self.runtime_settings.update(changed)
        self.apply_runtime_settings()
        self.save_settings()
        print(f"ON/OFF settings updated: {changed}")
        self.set_status("تم حفظ Settings")
        window.destroy()

    buttons = ctk.CTkFrame(window, fg_color="transparent")
    buttons.pack(fill="x", padx=14, pady=(0, 12))

    ctk.CTkButton(
        buttons,
        text="إغلاق البرنامج",
        width=130,
        height=34,
        fg_color="#8b0000",
        hover_color="#a00000",
        command=self.close_program,
    ).pack(side="left", padx=5)

    ctk.CTkButton(buttons, text="حفظ", width=95, height=34, command=save_window_settings).pack(side="right", padx=5)
    ctk.CTkButton(buttons, text="إلغاء", width=95, height=34, command=window.destroy).pack(side="right", padx=5)


def _bind_close_hotkey(self):
    key = _runtime_text(self, "program_close_hotkey", "ctrl+q")

    try:
        old_handle = getattr(self, "_program_close_hotkey_handle", None)
        if old_handle is not None:
            keyboard.remove_hotkey(old_handle)
    except Exception:
        pass

    if not key:
        return

    try:
        self._program_close_hotkey_handle = keyboard.add_hotkey(
            key,
            lambda: self.app.after(0, self.close_program),
        )
        print(f"Close hotkey active: {key}")
    except Exception as error:
        print(f"Could not bind Close hotkey {key!r}: {error}")


def _apply_runtime_settings_with_close_hotkey(self):
    result = _ORIGINAL_APPLY_RUNTIME_SETTINGS(self)
    try:
        _bind_close_hotkey(self)
    except Exception as error:
        print(f"Close hotkey apply failed: {error}")
    return result


def _selection_init_with_onoff_settings(self):
    raw_before = _read_settings_file_raw()
    _ORIGINAL_SELECTION_INIT(self)

    # Older UI patch forced these two values on every startup. Restore the
    # saved values after it runs so Settings remains truly editable.
    changed = False
    try:
        for key in PRESERVE_FROM_SETTINGS_FILE:
            if key in raw_before:
                self.runtime_settings[key] = _coerce_value(self, key, raw_before[key])
                changed = True

        if "program_close_hotkey" not in self.runtime_settings:
            self.runtime_settings["program_close_hotkey"] = "ctrl+q"
            changed = True

        if "manual_start_required" not in self.runtime_settings:
            self.runtime_settings["manual_start_required"] = True
            changed = True

        if "auto_start_post_login_on_startup" not in self.runtime_settings:
            self.runtime_settings["auto_start_post_login_on_startup"] = False
            changed = True

        if changed:
            self.apply_runtime_settings()
            self.save_settings()
        else:
            _bind_close_hotkey(self)
    except Exception as error:
        print(f"Settings ON/OFF init restore failed: {error}")


def apply_settings_onoff_close_patch():
    _install_defaults_and_group()
    SelectionAwareLauncher.apply_runtime_settings = _apply_runtime_settings_with_close_hotkey
    SelectionAwareLauncher.open_settings_window = _open_settings_window_onoff
    SelectionAwareLauncher.__init__ = _selection_init_with_onoff_settings
    print("Settings ON/OFF close patch active: switches + close hotkey")


apply_settings_onoff_close_patch()
