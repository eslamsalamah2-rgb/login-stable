"""Translate remaining main-window Arabic labels when English is selected.

UI-only patch. It extends the language dictionary and forces a late refresh so
widgets created by previous UI patches also switch language.
"""

import customtkinter as ctk

from selection_launcher import SelectionAwareLauncher

try:
    import language_toggle_patch as lang
except Exception:
    lang = None


_ORIGINAL_SELECTION_INIT = SelectionAwareLauncher.__init__

EXTRA_AR_TO_EN = {
    # Main toolbar / account rows.
    "اختيار الصفحة": "Choose Page",
    "الصفحة اختيار": "Choose Page",
    "اختار الصفحة": "Choose Page",
    "اختر الصفحة": "Choose Page",
    "+ إضافة حساب": "Add Account +",
    "إضافة حساب +": "Add Account +",
    "حساب إضافة +": "Add Account +",
    "حساب جديد": "New Account",
    "حفظ الحسابات": "Save Accounts",
    "مسار الصفحة": "Page Path",
    "المسار": "Path",
    "اسم الحساب": "Account Name",
    "اليوزر": "Username",
    "الباسورد": "Password",
    "الاسم": "Name",

    # Table headers.
    "الحالة": "Status",
    "حاله": "Status",
    "اسم الشخصية من Memory": "Character Name from Memory",
    "الاسم الشخصية من Memory": "Character Name from Memory",
    "Memory الاسم الشخصية من": "Character Name from Memory",
    "الشخصية": "Character",
    "رقم": "No.",
    "الحساب": "Account",

    # Common small Arabic statuses/labels that can remain after mixed UI edits.
    "جاهز": "Ready",
    "غير جاهز": "Not Ready",
    "مفتوح": "Open",
    "مقفول": "Closed",
    "موجود": "Found",
    "غير موجود": "Not Found",
    "تشغيل": "Run",
    "إيقاف": "Stop",
    "ابدأ": "Start",
    "استكمال": "Resume",
    "إغلاق الكل": "Close All",
    "الصفحات المفتوحة": "Open Pages",
    "الصفحات الجانبية": "Open Pages",
    "الشخصيات الجانبية": "Open Characters",
}


def _install_extra_translations():
    if lang is None:
        print("Remaining labels language patch warning: language_toggle_patch unavailable")
        return

    try:
        lang.AR_TO_EN.update(EXTRA_AR_TO_EN)
        for ar_text, en_text in EXTRA_AR_TO_EN.items():
            lang.EN_TO_AR[en_text] = ar_text

        # Extra phrase replacements for labels that are composed dynamically.
        extra_replacements = (
            ("اختيار الصفحة", "Choose Page"),
            ("اختر الصفحة", "Choose Page"),
            ("إضافة حساب", "Add Account"),
            ("اسم الشخصية", "Character Name"),
            ("من Memory", "from Memory"),
            ("الحالة", "Status"),
            ("مسار", "Path"),
        )
        existing = list(getattr(lang, "AR_REPLACEMENTS", ()))
        for item in extra_replacements:
            if item not in existing:
                existing.append(item)
        lang.AR_REPLACEMENTS = tuple(existing)
        lang.EN_REPLACEMENTS = tuple((en, ar) for ar, en in lang.AR_REPLACEMENTS)
    except Exception as error:
        print(f"Remaining labels translation install failed: {error}")


def _current_lang(self):
    try:
        if lang is not None:
            return lang._language(self)
    except Exception:
        pass
    try:
        return str(self.get_runtime_setting("program_language", "ar")).lower()
    except Exception:
        return "ar"


def _refresh_remaining_labels_now(self):
    if lang is None:
        return
    try:
        # Some widgets were created before their Arabic labels existed in the
        # dictionary. Clear only the language source for known remaining labels,
        # then run the normal translator again.
        for widget in lang._walk_widgets(self.app):
            try:
                text = str(widget.cget("text") or "")
            except Exception:
                continue
            source = str(getattr(widget, "_language_source_text", "") or "")
            if text in EXTRA_AR_TO_EN or source in EXTRA_AR_TO_EN:
                try:
                    setattr(widget, "_language_source_text", source or text)
                except Exception:
                    pass
        self.apply_language_to_ui()
    except Exception as error:
        print(f"Remaining labels language refresh failed: {error}")


def _selection_init_with_remaining_labels(self):
    _ORIGINAL_SELECTION_INIT(self)
    _install_extra_translations()
    _refresh_remaining_labels_now(self)
    try:
        self.app.after(150, lambda: _refresh_remaining_labels_now(self))
        self.app.after(700, lambda: _refresh_remaining_labels_now(self))
        self.app.after(1400, lambda: _refresh_remaining_labels_now(self))
    except Exception:
        pass


_install_extra_translations()
SelectionAwareLauncher.__init__ = _selection_init_with_remaining_labels

print("Remaining labels language patch active: Choose Page/Add Account/table headers translated")
