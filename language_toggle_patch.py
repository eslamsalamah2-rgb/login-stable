"""Arabic/English runtime language toggle for the GUI.

UI-only patch:
- adds عربي / English buttons on the main window
- saves selected language in settings.json as program_language
- translates visible widget text and common status messages
- does not change Login, Recovery, Drop, Use, Sash, or any image logic
"""

import re

import customtkinter as ctk

from gui import DEFAULT_RUNTIME_SETTINGS, SimpleLauncher
from selection_launcher import SelectionAwareLauncher


_ORIGINAL_SELECTION_INIT = SelectionAwareLauncher.__init__
_ORIGINAL_SET_STATUS = SimpleLauncher.set_status
_ORIGINAL_OPEN_SETTINGS = SelectionAwareLauncher.open_settings_window
_ORIGINAL_OPEN_ITEM_SELECTOR = getattr(SelectionAwareLauncher, "open_item_selector", None)
_ORIGINAL_APPLY_RUNTIME_SETTINGS = SelectionAwareLauncher.apply_runtime_settings

DEFAULT_RUNTIME_SETTINGS.update({"program_language": "ar"})

AR_TO_EN = {
    "عربي": "Arabic",
    "إنجليزي": "English",
    "إعدادات": "Settings",
    "Settings": "Settings",
    "حفظ": "Save",
    "إلغاء": "Cancel",
    "إغلاق": "Close",
    "إغلاق البرنامج": "Close Program",
    "اختيار الكل": "Select All",
    "إلغاء الكل": "Clear All",
    "إلغاء التحديد": "Clear Selection",
    "تحديد الكل": "Select All",
    "إضافة حساب": "Add Account",
    "حفظ الحسابات": "Save Accounts",
    "Drop Items": "Drop Items",
    "Use Items": "Use Items",
    "Sash Items": "Sash Items",
    "No Rev": "No Rev",
    "Rev": "Rev",
    "Rev Here": "Rev Here",
    "Sash": "Sash",
    "Startup Scan جاهز": "Startup Scan Ready",
    "جاهز - اضغط Start للتشغيل": "Ready - press Start to run",
    "تم حفظ Settings": "Settings saved",
    "تم حفظ Settings / Setting Drop": "Settings saved",
    "فشل حفظ اختيار الـ Items": "Failed to save item selection",
    "تشغيل يدوي فقط عند فتح البرنامج": "Manual start only when program opens",
    "تشغيل أوامر الدخول تلقائيًا عند فتح البرنامج": "Auto-run post-login commands on startup",
    "زر Start من الكيبورد": "Keyboard Start key",
    "زر Stop من الكيبورد": "Keyboard Stop key",
    "اختصار إغلاق البرنامج بالكامل": "Close program hotkey",
    "زر فتح الشنطة داخل اللعبة": "Inventory open key in game",
    "الزر اللي يتضغط بعد Sash": "Key pressed after Sash",
    "Setting Keys / أزرار التشغيل": "Settings Keys / Controls",
    "Setting Login Input / كتابة الدخول": "Login Input Settings",
    "Login Settings - ثابت": "Login Settings - Stable",
    "Setting Drop": "Drop Settings",
    "Setting Use": "Use Settings",
    "Setting Sash": "Sash Settings",
    "Setting After Sash": "After Sash Settings",
    "الأزرار والاختصارات والأوقات. قيم ON/OFF تظهر كسويتش واضح.": "Keys, shortcuts, and timings. ON/OFF values appear as switches.",
    "اختار العناصر المطلوبة واضغط حفظ. الاختيار عام على كل الحسابات.": "Choose the required items and press Save. The selection applies to all accounts.",
    "مفيش صور في الفولدر ده. حط صور الـ Items وافتح النافذة تاني.": "No images in this folder. Add item images and reopen this window.",
}

EN_TO_AR = {value: key for key, value in AR_TO_EN.items()}
EN_TO_AR.update({
    "Settings Keys / Controls": "Setting Keys / أزرار التشغيل",
    "Login Input Settings": "Setting Login Input / كتابة الدخول",
    "Login Settings - Stable": "Login Settings - ثابت",
    "Drop Settings": "Setting Drop",
    "Use Settings": "Setting Use",
    "Sash Settings": "Setting Sash",
    "After Sash Settings": "Setting After Sash",
})

AR_REPLACEMENTS = (
    ("جاري", "Running"),
    ("تم", "Done"),
    ("فشل", "Failed"),
    ("الحساب", "Account"),
    ("كتابة اليوزر والباسورد", "typing username and password"),
    ("الضغط على Log In", "pressing Log In"),
    ("في انتظار تغير اسم الشخصية في Memory", "waiting for character name in Memory"),
    ("تم طلب الإيقاف الفوري بزر", "Immediate stop requested by key"),
    ("اضغط Start للتشغيل", "press Start to run"),
    ("جاهز", "Ready"),
    ("متوقف مؤقتًا", "Paused"),
    ("تم حفظ", "Saved"),
    ("صفحات مفتوحة", "open pages"),
    ("الصفحات المفتوحة", "open pages"),
    ("اللمبات", "lamps"),
    ("الأوامر", "commands"),
    ("التشغيل", "run"),
)

EN_REPLACEMENTS = tuple((en, ar) for ar, en in AR_REPLACEMENTS)


def _normalize_lang(value):
    text = str(value or "ar").strip().lower()
    if text in {"en", "eng", "english", "إنجليزي"}:
        return "en"
    return "ar"


def _language(self):
    try:
        return _normalize_lang(self.get_runtime_setting("program_language", "ar"))
    except Exception:
        return "ar"


def _set_language(self, lang):
    lang = _normalize_lang(lang)
    try:
        self.runtime_settings["program_language"] = lang
        self.save_settings()
    except Exception as error:
        print(f"Language save failed: {error}")

    _apply_language_to_ui(self)
    try:
        self.set_status("تم تغيير اللغة" if lang == "ar" else "Language changed")
    except Exception:
        pass


def _translate_exact_or_replace(text, lang):
    if text is None:
        return text
    original = str(text)
    if not original:
        return original

    if lang == "en":
        if original in AR_TO_EN:
            return AR_TO_EN[original]
        # Common dynamic button labels.
        match = re.match(r"^(ابدأ|استكمال|إيقاف)\s*(.*)$", original)
        if match:
            base = {"ابدأ": "Start", "استكمال": "Resume", "إيقاف": "Stop"}.get(match.group(1), match.group(1))
            return (base + " " + match.group(2)).strip()
        result = original
        for ar, en in AR_REPLACEMENTS:
            result = result.replace(ar, en)
        return result

    # Arabic mode.
    if original in EN_TO_AR:
        return EN_TO_AR[original]
    match = re.match(r"^(Start|Resume|Stop)\s*(.*)$", original, re.IGNORECASE)
    if match:
        base = {"start": "ابدأ", "resume": "استكمال", "stop": "إيقاف"}.get(match.group(1).lower(), match.group(1))
        return (base + " " + match.group(2)).strip()
    result = original
    for en, ar in EN_REPLACEMENTS:
        result = result.replace(en, ar)
    return result


def _translate_text(text, lang):
    try:
        return _translate_exact_or_replace(text, lang)
    except Exception:
        return text


def _walk_widgets(widget):
    yield widget
    try:
        children = widget.winfo_children()
    except Exception:
        children = []
    for child in children:
        yield from _walk_widgets(child)


def _configure_text(widget, text):
    try:
        widget.configure(text=text)
    except Exception:
        pass


def _apply_language_to_widget_tree(root, lang):
    for widget in _walk_widgets(root):
        try:
            current = widget.cget("text")
        except Exception:
            continue

        if current is None:
            continue

        # Store the first real text as the source. For dynamic buttons/statuses,
        # exact translation also works when the source was already English.
        try:
            source = getattr(widget, "_language_source_text", None)
            if source is None or str(source).strip() == "":
                source = current
                setattr(widget, "_language_source_text", source)
        except Exception:
            source = current

        _configure_text(widget, _translate_text(source, lang))


def _refresh_top_start_stop_text(self):
    lang = _language(self)
    try:
        start_key = str(self.get_runtime_setting("program_start_hotkey", "8") or "8")
        stop_key = str(self.get_runtime_setting("program_stop_hotkey", "9") or "9")
    except Exception:
        start_key, stop_key = "8", "9"

    if lang == "en":
        start_text = f"Start {start_key}"
        stop_text = f"Stop {stop_key}"
    else:
        start_text = f"ابدأ {start_key}"
        stop_text = f"إيقاف {stop_key}"

    for attr, text in (("top_start_button", start_text), ("top_stop_button", stop_text)):
        widget = getattr(self, attr, None)
        if widget is not None:
            try:
                setattr(widget, "_language_source_text", text)
                widget.configure(text=text)
            except Exception:
                pass


def _refresh_language_buttons(self):
    lang = _language(self)
    ar_btn = getattr(self, "language_ar_button", None)
    en_btn = getattr(self, "language_en_button", None)
    try:
        if ar_btn is not None:
            ar_btn.configure(fg_color="#1f6aa5" if lang == "ar" else "#3a3a3a")
        if en_btn is not None:
            en_btn.configure(fg_color="#1f6aa5" if lang == "en" else "#3a3a3a")
    except Exception:
        pass


def _apply_language_to_ui(self):
    lang = _language(self)
    try:
        _apply_language_to_widget_tree(self.app, lang)
    except Exception as error:
        print(f"Language apply warning: {error}")

    _refresh_top_start_stop_text(self)
    _refresh_language_buttons(self)

    try:
        self.app.title("ZERO BOT Manager" if lang == "en" else "مدير ZERO BOT")
    except Exception:
        pass


def _add_language_buttons(self):
    try:
        holder = ctk.CTkFrame(self.app, fg_color="transparent")
        holder.place(relx=1.0, x=-14, y=15, anchor="ne")
        self.language_buttons_frame = holder

        self.language_ar_button = ctk.CTkButton(
            holder,
            text="عربي",
            width=70,
            height=31,
            command=lambda: _set_language(self, "ar"),
        )
        self.language_ar_button.pack(side="left", padx=(0, 6))

        self.language_en_button = ctk.CTkButton(
            holder,
            text="English",
            width=82,
            height=31,
            command=lambda: _set_language(self, "en"),
        )
        self.language_en_button.pack(side="left")
    except Exception as error:
        print(f"Could not add language buttons: {error}")


def _set_status_translated(self, text):
    lang = _language(self)
    return _ORIGINAL_SET_STATUS(self, _translate_text(str(text), lang))


def _open_settings_translated(self):
    result = _ORIGINAL_OPEN_SETTINGS(self)
    try:
        self.app.after(80, lambda: _apply_language_to_ui(self))
    except Exception:
        pass
    return result


def _open_item_selector_translated(self, stage):
    if _ORIGINAL_OPEN_ITEM_SELECTOR is None:
        return None
    result = _ORIGINAL_OPEN_ITEM_SELECTOR(self, stage)
    try:
        self.app.after(80, lambda: _apply_language_to_ui(self))
    except Exception:
        pass
    return result


def _apply_runtime_settings_language(self):
    result = _ORIGINAL_APPLY_RUNTIME_SETTINGS(self)
    try:
        _apply_language_to_ui(self)
    except Exception:
        pass
    return result


def _selection_init_with_language(self):
    _ORIGINAL_SELECTION_INIT(self)
    try:
        if "program_language" not in self.runtime_settings:
            self.runtime_settings["program_language"] = "ar"
            self.save_settings()
    except Exception:
        pass
    _add_language_buttons(self)
    _apply_language_to_ui(self)


def apply_language_toggle_patch():
    SimpleLauncher.set_status = _set_status_translated
    SelectionAwareLauncher.apply_runtime_settings = _apply_runtime_settings_language
    SelectionAwareLauncher.open_settings_window = _open_settings_translated
    if _ORIGINAL_OPEN_ITEM_SELECTOR is not None:
        SelectionAwareLauncher.open_item_selector = _open_item_selector_translated
    SelectionAwareLauncher.__init__ = _selection_init_with_language
    SelectionAwareLauncher.apply_language_to_ui = _apply_language_to_ui
    SelectionAwareLauncher.set_language = _set_language
    print("Language toggle patch active: Arabic/English UI saved in settings")


apply_language_toggle_patch()
