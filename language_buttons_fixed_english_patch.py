"""Keep the language switch button labels always in English.

User request:
- The Arabic language button must always say "Arabic".
- The English language button must always say "English".
- This is UI-only and does not touch Login, Recovery, Drop, Use, Sash, or assets.
"""

from selection_launcher import SelectionAwareLauncher

try:
    import language_toggle_patch
except Exception:
    language_toggle_patch = None


_ORIGINAL_SELECTION_INIT = SelectionAwareLauncher.__init__
_ORIGINAL_APPLY_LANGUAGE = getattr(SelectionAwareLauncher, "apply_language_to_ui", None)
_ORIGINAL_SET_LANGUAGE = getattr(SelectionAwareLauncher, "set_language", None)


def _force_language_button_labels(self):
    """Force only the two language switch labels to stay English."""
    for attr, text in (
        ("language_ar_button", "Arabic"),
        ("language_en_button", "English"),
    ):
        widget = getattr(self, attr, None)
        if widget is None:
            continue
        try:
            # Avoid future generic translation using an Arabic source label.
            setattr(widget, "_language_source_text", text)
        except Exception:
            pass
        try:
            widget.configure(text=text)
        except Exception:
            pass


def _install_translation_overrides():
    """Prevent the generic translator from turning Arabic/English into Arabic script."""
    if language_toggle_patch is None:
        return
    try:
        language_toggle_patch.EN_TO_AR["Arabic"] = "Arabic"
        language_toggle_patch.EN_TO_AR["English"] = "English"
        language_toggle_patch.AR_TO_EN["عربي"] = "Arabic"
        language_toggle_patch.AR_TO_EN["إنجليزي"] = "English"
    except Exception as error:
        print(f"Language button fixed-English override warning: {error}")


def _apply_language_keep_buttons_english(self):
    if _ORIGINAL_APPLY_LANGUAGE is not None:
        result = _ORIGINAL_APPLY_LANGUAGE(self)
    else:
        result = None
    _force_language_button_labels(self)
    try:
        self.app.after(50, lambda: _force_language_button_labels(self))
    except Exception:
        pass
    return result


def _set_language_keep_buttons_english(self, lang):
    if _ORIGINAL_SET_LANGUAGE is not None:
        result = _ORIGINAL_SET_LANGUAGE(self, lang)
    else:
        result = None
    _force_language_button_labels(self)
    try:
        self.app.after(50, lambda: _force_language_button_labels(self))
        self.app.after(150, lambda: _force_language_button_labels(self))
    except Exception:
        pass
    return result


def _selection_init_keep_language_buttons_english(self):
    _ORIGINAL_SELECTION_INIT(self)
    _force_language_button_labels(self)
    try:
        if getattr(self, "language_ar_button", None) is not None:
            self.language_ar_button.configure(command=lambda: self.set_language("ar"))
        if getattr(self, "language_en_button", None) is not None:
            self.language_en_button.configure(command=lambda: self.set_language("en"))
    except Exception as error:
        print(f"Could not patch language button commands: {error}")


def apply_language_buttons_fixed_english_patch():
    _install_translation_overrides()
    SelectionAwareLauncher.__init__ = _selection_init_keep_language_buttons_english
    SelectionAwareLauncher.apply_language_to_ui = _apply_language_keep_buttons_english
    SelectionAwareLauncher.set_language = _set_language_keep_buttons_english
    print("Language buttons fixed-English patch active: buttons always show Arabic / English")


apply_language_buttons_fixed_english_patch()
