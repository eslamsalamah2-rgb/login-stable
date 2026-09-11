"""Clean Settings UI for Drop timing without cluttering Login settings.

The normal Settings window used to show every runtime key, including image
thresholds/detection accuracy values.  This patch replaces the Settings window
with a small grouped editor:
- Login settings: only stable startup timings.
- Setting Drop: only timing/speed values that the user may tune while testing.

Detection thresholds stay in code/settings.json internally, but they are hidden
from the UI to keep the file/window clean.
"""

import customtkinter as ctk

from selection_launcher import SelectionAwareLauncher


SETTINGS_GROUPS = (
    (
        "Login Settings - ثابت",
        "أوقات تشغيل الدخول فقط. لا يوجد هنا أي دقة صور أو Threshold.",
        (
            ("start_game_timeout", "وقت البحث عن زر Start Game بالثواني"),
            ("new_pid_timeout", "وقت انتظار صفحة Conquer الجديدة بالثواني"),
            ("start_game_attempts", "عدد محاولات فتح اللانشر لو Start Game فشل"),
        ),
    ),
    (
        "Setting Drop",
        "أوقات وسرعة الدروب فقط. عدّلها للتسريع أو التهدئة بدون لمس Login.",
        (
            ("inventory_open_wait_seconds", "انتظار بعد ضغط زر فتح الشنطة قبل التأكد"),
            ("inventory_drop_click_delay", "تأخير بين ضغطات الدروب داخل نفس النقطة"),
            ("inventory_drop_after_drop_delay", "انتظار بعد الرمية قبل البحث عن Yes / السكان التالي"),
            ("inventory_drop_confirm_yes_timeout", "أقصى وقت انتظار ظهور زر Yes بعد الرمية"),
            ("post_login_account_delay_seconds", "انتظار بعد انتهاء الحساب قبل الانتقال للحساب التالي"),
            ("post_login_round_delay_seconds", "انتظار بعد انتهاء كل الحسابات قبل دورة جديدة"),
            ("inventory_drop_max_items_per_account", "أقصى عدد عناصر يرميها من الحساب في الدورة"),
            ("inventory_drop_target_margin_x", "هامش نقطة الرمي من أقصى اليمين بالبكسل"),
            ("inventory_drop_target_margin_y", "هامش نقطة الرمي من أقصى فوق بالبكسل"),
        ),
    ),
)


HIDDEN_WORDS = (
    "threshold",
    "match_threshold",
    "near_threshold",
    "دقة",
    "حساسية",
)


def _is_hidden_accuracy_key(key, label):
    text = f"{key} {label}".lower()
    return any(word.lower() in text for word in HIDDEN_WORDS)


def _setting_value(self, key):
    try:
        return self.runtime_settings.get(key, self.get_runtime_setting(key))
    except Exception:
        try:
            return self.get_runtime_setting(key)
        except Exception:
            return ""


def _coerce_value(self, key, raw):
    try:
        return self._coerce_runtime_setting(key, raw)
    except Exception:
        text = str(raw).strip()
        lower = text.lower()
        if lower in {"true", "yes", "on", "1"}:
            return True
        if lower in {"false", "no", "off", "0"}:
            return False
        try:
            if "." in text:
                return float(text)
            return int(text)
        except Exception:
            return text


def _add_entry_row(body, label_text, value):
    row = ctk.CTkFrame(body)
    row.pack(fill="x", padx=6, pady=4)

    ctk.CTkLabel(
        row,
        text=label_text,
        width=360,
        anchor="w",
        font=("Segoe UI", 13),
    ).pack(side="left", padx=(8, 4), pady=7)

    entry = ctk.CTkEntry(row, width=115)
    entry.pack(side="right", padx=(4, 8), pady=7)
    entry.insert(0, str(value))
    return entry


def _open_clean_settings_window(self):
    window = ctk.CTkToplevel(self.app)
    window.title("Settings")
    window.geometry("620x620")
    window.transient(self.app)
    window.grab_set()

    ctk.CTkLabel(
        window,
        text="Settings",
        font=("Segoe UI", 22, "bold"),
    ).pack(pady=(14, 4))

    ctk.CTkLabel(
        window,
        text="الدقة والـThreshold مخفيين من هنا. التعديل الحالي للأوقات فقط.",
        font=("Segoe UI", 13),
        text_color="#cfcfcf",
    ).pack(pady=(0, 10))

    body = ctk.CTkScrollableFrame(window, height=455)
    body.pack(fill="both", expand=True, padx=16, pady=(0, 12))

    entries = {}
    for title, note, items in SETTINGS_GROUPS:
        section = ctk.CTkFrame(body, fg_color="#263238")
        section.pack(fill="x", padx=6, pady=(10, 6))
        ctk.CTkLabel(
            section,
            text=title,
            font=("Segoe UI", 17, "bold"),
            anchor="w",
        ).pack(fill="x", padx=10, pady=(8, 1))
        ctk.CTkLabel(
            section,
            text=note,
            font=("Segoe UI", 12),
            text_color="#d6d6d6",
            anchor="w",
        ).pack(fill="x", padx=10, pady=(0, 8))

        for key, label in items:
            if _is_hidden_accuracy_key(key, label):
                continue
            entries[key] = _add_entry_row(body, label, _setting_value(self, key))

    def save_window_settings():
        changed = {}
        for key, entry in entries.items():
            changed[key] = _coerce_value(self, key, entry.get())

        self.runtime_settings.update(changed)
        self.apply_runtime_settings()
        self.save_settings()
        print(f"Clean settings updated: {changed}")
        self.set_status("تم حفظ Settings / Setting Drop")
        window.destroy()

    buttons = ctk.CTkFrame(window, fg_color="transparent")
    buttons.pack(fill="x", padx=16, pady=(0, 14))
    ctk.CTkButton(buttons, text="حفظ", height=38, command=save_window_settings).pack(side="right", padx=6)
    ctk.CTkButton(buttons, text="إلغاء", height=38, command=window.destroy).pack(side="right", padx=6)


SelectionAwareLauncher.open_settings_window = _open_clean_settings_window

print("Drop settings patch active: clean Settings window with Setting Drop timings only")
