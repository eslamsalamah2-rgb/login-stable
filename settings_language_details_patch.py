"""Full Arabic/English translation for Settings details.

UI-only patch:
- when program_language = en, Settings section titles, notes, and every field
  description are shown in English
- when program_language = ar, the original Arabic text is kept
- works for Settings windows opened after switching language
- does not touch Login, Recovery, Drop, Use, Sash, image matching, or execution order
"""

from selection_launcher import SelectionAwareLauncher

try:
    import drop_settings_patch
except Exception:
    drop_settings_patch = None

try:
    import language_toggle_patch as langui
except Exception:
    langui = None


_ORIGINAL_OPEN_SETTINGS = SelectionAwareLauncher.open_settings_window
_ORIGINAL_APPLY_LANGUAGE_TO_UI = getattr(SelectionAwareLauncher, "apply_language_to_ui", None)
_ORIGINAL_LANG_MODULE_APPLY = getattr(langui, "_apply_language_to_ui", None) if langui else None

# Snapshot after all current settings modules have registered their groups.
_AR_SETTINGS_GROUPS = tuple(getattr(drop_settings_patch, "SETTINGS_GROUPS", ())) if drop_settings_patch else ()

TITLE_EN = {
    "Setting Keys / أزرار التشغيل": "Key Settings / Controls",
    "Login Settings - ثابت": "Login Settings - Stable",
    "Setting Login Input / كتابة الدخول": "Login Input Settings",
    "Setting Drop": "Drop Settings",
    "Setting Use": "Use Settings",
    "Setting Sash": "Sash Settings",
    "Setting After Sash": "After Sash Settings",
}

NOTE_EN = {
    "اختصارات التشغيل والإيقاف والإغلاق. الاختيارات ON/OFF تظهر كسويتش بدل True/False.":
        "Start, stop, close, and control shortcuts. ON/OFF options are shown as switches instead of True/False text boxes.",
    "أوقات وتشغيل الدخول فقط. لا يوجد هنا أي دقة صور أو Threshold.":
        "Login startup and retry timing only. Image accuracy and thresholds are hidden here.",
    "تحكم في كتابة اليوزر والباسورد فقط. الإحداثيات جاية من صورة Account/Password، والـ Offset يزحزح الكليك يمين/شمال أو فوق/تحت.":
        "Controls username/password typing only. Coordinates come from the Account/Password image; offsets move the click left/right/up/down.",
    "أوقات وسرعة أوامر الدخول بعد نجاح Login فقط. عدّلها بدون لمس Login.":
        "Post-login Drop timing only. Adjust these without changing Login.",
    "مرحلة اليوز بعد الدروب: يعمل Scan على الشنطة ويضغط كليك يمين على الصور الموجودة في assets/use_items.":
        "Use stage after Drop: scans the inventory and right-clicks items matched from assets/use_items.",
    "مرحلة Sash بعد Use: تفتح Sash بالزر، تعمل Scan على الشنطة، وتنقل الصور الموجودة في assets/sash_items بـ Alt + Click.":
        "Sash stage after Use: opens Sash, scans the inventory, and transfers matched assets/sash_items with Alt + Click.",
    "آخر خطوتين قبل الانتقال للحساب التالي: ضغط I مرتين ثم كليك يمين في مكان تختاره داخل النافذة.":
        "Final actions before moving to the next account: press the configured key, then right-click at the selected in-window position.",
    "الأزرار والاختصارات والأوقات. قيم ON/OFF تظهر كسويتش واضح.":
        "Keys, shortcuts, and timings. ON/OFF values appear as clear switches.",
}

KEY_EN_LABELS = {
    # Key/control settings.
    "program_start_hotkey": "Keyboard Start key",
    "program_stop_hotkey": "Keyboard Stop key",
    "program_close_hotkey": "Close program hotkey",
    "inventory_open_hotkey": "In-game inventory open key",
    "post_sash_i_press_key": "Key pressed after Sash",
    "manual_start_required": "Manual start only when the program opens",
    "auto_start_post_login_on_startup": "Auto-run post-login commands when the program opens",

    # Stable login/startup.
    "start_game_timeout": "Time to search for the Start Game button / seconds",
    "new_pid_timeout": "Time to wait for the new Conquer window / seconds",
    "start_game_attempts": "Launcher retry attempts if Start Game fails",
    "login_account_max_open_attempts": "Open/login attempts before skipping this account",

    # Login input.
    "login_type_interval": "Delay between each username/password character / seconds",
    "login_input_pause": "Safe internal keyboard delay for Login",
    "login_username_clear_presses": "Backspace count to clear the username field",
    "login_password_clear_presses": "Backspace count to clear the password field during retry",
    "login_backspace_delay": "Delay between Backspace presses / seconds",
    "login_after_username_click_delay": "Delay after clicking the username field before clearing",
    "login_username_right_arrow_enabled": "After username click: press Right Arrow before clearing - ON/OFF",
    "login_username_right_arrow_count": "Right Arrow press count after clicking username",
    "login_username_right_arrow_delay": "Delay between Right Arrow presses / seconds",
    "login_after_username_right_arrow_delay": "Delay after Right Arrow presses before Backspace / seconds",
    "login_after_username_clear_delay": "Delay after clearing username before typing",
    "login_after_username_type_delay": "Delay after typing username before clicking password",
    "login_after_password_click_delay": "Delay after clicking password field before typing",
    "login_after_password_type_delay": "Delay after typing password before pressing Log In",
    "login_click_focus_delay": "Small delay after moving mouse before click",
    "login_username_click_offset_x": "Username click offset X in pixels - negative moves left",
    "login_username_click_offset_y": "Username click offset Y in pixels",
    "login_password_click_offset_x": "Password click offset X in pixels - negative moves left",
    "login_password_click_offset_y": "Password click offset Y in pixels",
    "login_password_clear_offset_x": "Password clear-click offset X in pixels",
    "login_password_clear_offset_y": "Password clear-click offset Y in pixels",

    # Drop.
    "post_login_account_budget_seconds": "Time budget per account for post-login commands / seconds",
    "inventory_open_wait_seconds": "Delay after pressing the inventory key before checking it",
    "inventory_drop_clicks_per_point": "Drop clicks per point - 1 single click, 2 double click",
    "inventory_drop_click_delay": "Delay between Drop clicks on the same point",
    "inventory_drop_after_drop_delay": "Delay after dropping before Yes / next scan",
    "inventory_drop_confirm_yes_timeout": "Maximum wait time for Yes after dropping",
    "post_login_account_delay_seconds": "Delay after finishing one account before the next account",
    "post_login_round_delay_seconds": "Delay after finishing all accounts before the next round",
    "inventory_drop_max_items_per_account": "Maximum Drop items per account per round",
    "inventory_drop_target_margin_x": "Drop target margin from far right / pixels",
    "inventory_drop_target_margin_y": "Drop target margin from top / pixels",

    # Use.
    "inventory_use_max_items_per_account": "Maximum Use items per account",
    "inventory_use_right_clicks_per_item": "Right-click count on each Use item - keep it 1",
    "inventory_use_click_delay": "Delay before/after Use right-click / seconds",
    "inventory_use_after_use_delay": "Delay after using each item before the next scan / seconds",

    # Sash.
    "inventory_sash_max_items_per_account": "Maximum items transferred to Sash per account",
    "inventory_sash_click_delay": "Delay before/after Sash click / seconds",
    "inventory_sash_open_wait_seconds": "Delay after pressing the Sash button / seconds",
    "inventory_sash_after_transfer_delay": "Delay after transferring each item before the next scan / seconds",
    "inventory_sash_mouse_clear_x": "Mouse clear position X after transfer",
    "inventory_sash_mouse_clear_y": "Mouse clear position Y after transfer",
    "inventory_sash_next_enabled": "Use Sash Next page when page 1 is full - ON/OFF",
    "inventory_sash_next_wait_seconds": "Delay after clicking Sash Next / seconds",
    "inventory_sash_stuck_repeat_limit": "Same-item repeat count before treating Sash page as full",
    "inventory_sash_disable_after_next_no_change": "Disable Sash for this account in the current run if no change after Next - ON/OFF",

    # After Sash.
    "post_sash_i_press_count": "Number of key presses after Sash - default 2",
    "post_sash_i_press_delay": "Delay between key presses / seconds",
    "post_sash_after_i_delay": "Delay after key presses before right-click / seconds",
    "post_sash_right_click_enabled": "Enable right-click after key presses",
    "post_sash_right_click_x": "Right-click X position inside the game window",
    "post_sash_right_click_y": "Right-click Y position inside the game window",
    "post_sash_right_click_delay": "Delay before right-click / seconds",
    "post_sash_after_right_click_delay": "Delay after right-click before next account / seconds",
}

EXTRA_TEXT_EN = {
    "Settings": "Settings",
    "الإعدادات": "Settings",
    "الأزرار والاختصارات والأوقات. قيم ON/OFF تظهر كسويتش واضح.":
        "Keys, shortcuts, and timings. ON/OFF values appear as clear switches.",
    "الأزرار والاختصارات والأوقات. قيم ON/OFF تظهر كسويتش بدل True/False.":
        "Keys, shortcuts, and timings. ON/OFF values appear as switches instead of True/False.",
    "الأزرار والاختصارات والأوقات. قيم ON/OFF تظهر كسويتش واضح.":
        "Keys, shortcuts, and timings. ON/OFF values appear as clear switches.",
    "حفظ": "Save",
    "إلغاء": "Cancel",
    "إغلاق": "Close",
    "إغلاق البرنامج": "Close Program",
}


def _current_language(self):
    if langui is not None and hasattr(langui, "_language"):
        try:
            return langui._language(self)
        except Exception:
            pass
    try:
        value = self.get_runtime_setting("program_language", "ar")
    except Exception:
        value = "ar"
    return "en" if str(value).strip().lower() in {"en", "eng", "english"} else "ar"


def _english_label_for(key, label):
    return KEY_EN_LABELS.get(key, EXTRA_TEXT_EN.get(label, str(label)))


def _groups_for_language(language):
    if language != "en":
        return _AR_SETTINGS_GROUPS

    translated = []
    for group in _AR_SETTINGS_GROUPS:
        if not group or len(group) < 3:
            translated.append(group)
            continue
        title, note, items = group
        title_en = TITLE_EN.get(title, EXTRA_TEXT_EN.get(title, str(title)))
        note_en = NOTE_EN.get(note, EXTRA_TEXT_EN.get(note, str(note)))
        items_en = tuple((key, _english_label_for(key, label)) for key, label in items)
        translated.append((title_en, note_en, items_en))
    return tuple(translated)


def _install_language_dictionary():
    if langui is None:
        return

    ar_to_en = {}
    ar_to_en.update(TITLE_EN)
    ar_to_en.update(NOTE_EN)
    ar_to_en.update(EXTRA_TEXT_EN)

    # Add every Arabic field label currently registered in Settings.
    for group in _AR_SETTINGS_GROUPS:
        if not group or len(group) < 3:
            continue
        _title, _note, items = group
        for key, label in items:
            ar_to_en[str(label)] = _english_label_for(key, label)

    try:
        langui.AR_TO_EN.update(ar_to_en)
        langui.AR_TO_EN["Settings"] = "Settings"
        langui.AR_TO_EN["الإعدادات"] = "Settings"

        # Important: force Arabic title back when switching from English.
        langui.EN_TO_AR.update({en: ar for ar, en in ar_to_en.items()})
        langui.EN_TO_AR["Settings"] = "الإعدادات"
        langui.EN_TO_AR["Key Settings / Controls"] = "Setting Keys / أزرار التشغيل"
        langui.EN_TO_AR["Login Input Settings"] = "Setting Login Input / كتابة الدخول"
        langui.EN_TO_AR["Login Settings - Stable"] = "Login Settings - ثابت"
        langui.EN_TO_AR["Drop Settings"] = "Setting Drop"
        langui.EN_TO_AR["Use Settings"] = "Setting Use"
        langui.EN_TO_AR["Sash Settings"] = "Setting Sash"
        langui.EN_TO_AR["After Sash Settings"] = "Setting After Sash"
    except Exception as error:
        print(f"Settings language dictionary install failed: {error}")


def _apply_language_to_all_open_windows(self):
    if _ORIGINAL_LANG_MODULE_APPLY is not None:
        try:
            _ORIGINAL_LANG_MODULE_APPLY(self)
        except Exception as error:
            print(f"Settings language base apply warning: {error}")
    elif _ORIGINAL_APPLY_LANGUAGE_TO_UI is not None:
        try:
            _ORIGINAL_APPLY_LANGUAGE_TO_UI(self)
        except Exception:
            pass

    if langui is None or not hasattr(langui, "_apply_language_to_widget_tree"):
        return

    language = _current_language(self)
    try:
        langui._apply_language_to_widget_tree(self.app, language)
        for child in self.app.winfo_children():
            try:
                langui._apply_language_to_widget_tree(child, language)
            except Exception:
                pass
    except Exception as error:
        print(f"Settings language full apply warning: {error}")


def _open_settings_language_aware(self):
    _install_language_dictionary()
    old_groups = getattr(drop_settings_patch, "SETTINGS_GROUPS", None) if drop_settings_patch else None
    try:
        if drop_settings_patch is not None:
            drop_settings_patch.SETTINGS_GROUPS = _groups_for_language(_current_language(self))
        result = _ORIGINAL_OPEN_SETTINGS(self)
    finally:
        try:
            if drop_settings_patch is not None and old_groups is not None:
                drop_settings_patch.SETTINGS_GROUPS = old_groups
        except Exception:
            pass

    try:
        self.app.after(60, lambda: _apply_language_to_all_open_windows(self))
        self.app.after(180, lambda: _apply_language_to_all_open_windows(self))
    except Exception:
        pass
    return result


def apply_settings_language_details_patch():
    _install_language_dictionary()

    if langui is not None:
        try:
            langui._apply_language_to_ui = _apply_language_to_all_open_windows
        except Exception:
            pass

    SelectionAwareLauncher.apply_language_to_ui = _apply_language_to_all_open_windows
    SelectionAwareLauncher.open_settings_window = _open_settings_language_aware

    print("Settings language details patch active: Settings labels switch Arabic/English")


apply_settings_language_details_patch()
