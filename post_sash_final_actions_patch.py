"""Register the final actions stage after Sash.

Post-login order becomes:
Revive -> Ensure Inventory Open -> Drop -> Use -> Sash -> Final Actions

Final Actions:
- Press I twice by default.
- Right-click once at a configurable client coordinate.

This patch only affects post-login command modules. Login remains isolated.
"""

from gui import DEFAULT_RUNTIME_SETTINGS
from selection_launcher import SelectionAwareLauncher
from tasks.post_login_modules.post_sash_final_actions import PostSashFinalActionsModule

try:
    import existing_pages_settings_patch
except Exception:
    existing_pages_settings_patch = None

try:
    import drop_settings_patch
except Exception:
    drop_settings_patch = None

try:
    from tasks.post_login_modules import registry
except Exception:
    registry = None


POST_SASH_FINAL_DEFAULTS = {
    "enable_post_sash_final_actions": True,
    "post_sash_i_press_count": 2,
    "post_sash_i_press_delay": 0.20,
    "post_sash_after_i_delay": 0.30,
    "post_sash_right_click_enabled": True,
    "post_sash_right_click_x": 900,
    "post_sash_right_click_y": 500,
    "post_sash_right_click_delay": 0.10,
    "post_sash_after_right_click_delay": 0.20,
}

POST_SASH_FINAL_LABELS = {
    "enable_post_sash_final_actions": "enable_post_sash_final_actions | تشغيل آخر خطوة بعد Sash",
    "post_sash_i_press_count": "post_sash_i_press_count | عدد ضغطات زر I بعد Sash",
    "post_sash_i_press_delay": "post_sash_i_press_delay | تأخير بين ضغطات I / ثانية",
    "post_sash_after_i_delay": "post_sash_after_i_delay | انتظار بعد ضغطات I وقبل كليك يمين / ثانية",
    "post_sash_right_click_enabled": "post_sash_right_click_enabled | تشغيل كليك يمين بعد ضغطات I",
    "post_sash_right_click_x": "post_sash_right_click_x | مكان الكليك اليمين X داخل نافذة اللعبة",
    "post_sash_right_click_y": "post_sash_right_click_y | مكان الكليك اليمين Y داخل نافذة اللعبة",
    "post_sash_right_click_delay": "post_sash_right_click_delay | انتظار قبل كليك يمين / ثانية",
    "post_sash_after_right_click_delay": "post_sash_after_right_click_delay | انتظار بعد كليك يمين قبل الحساب التالي / ثانية",
}

POST_SASH_FINAL_GROUP = (
    "Setting After Sash",
    "آخر خطوتين قبل الانتقال للحساب التالي: ضغط I مرتين ثم كليك يمين في مكان تختاره داخل النافذة.",
    (
        ("post_sash_i_press_count", "عدد ضغطات زر I بعد Sash - الافتراضي 2"),
        ("post_sash_i_press_delay", "تأخير بين ضغطات I / ثانية"),
        ("post_sash_after_i_delay", "انتظار بعد ضغطات I وقبل كليك يمين / ثانية"),
        ("post_sash_right_click_enabled", "تشغيل كليك يمين بعد ضغطات I"),
        ("post_sash_right_click_x", "مكان الكليك اليمين X داخل نافذة اللعبة"),
        ("post_sash_right_click_y", "مكان الكليك اليمين Y داخل نافذة اللعبة"),
        ("post_sash_right_click_delay", "انتظار قبل كليك يمين / ثانية"),
        ("post_sash_after_right_click_delay", "انتظار بعد كليك يمين قبل الحساب التالي / ثانية"),
    ),
)

_ORIGINAL_SELECTION_INIT = SelectionAwareLauncher.__init__


def _install_defaults():
    DEFAULT_RUNTIME_SETTINGS.update(POST_SASH_FINAL_DEFAULTS)

    if existing_pages_settings_patch is not None:
        try:
            existing_pages_settings_patch.SETTING_LABELS.update(POST_SASH_FINAL_LABELS)
        except Exception:
            pass


def _install_module_order():
    if registry is None:
        return
    try:
        classes = list(registry.MODULE_CLASSES)
        if PostSashFinalActionsModule not in classes:
            classes.append(PostSashFinalActionsModule)
            registry.MODULE_CLASSES = tuple(classes)
    except Exception as error:
        print(f"Could not install post-sash final module: {error}")


def _install_settings_group():
    if drop_settings_patch is None:
        return
    try:
        groups = list(drop_settings_patch.SETTINGS_GROUPS)
        if not any(group[0] == POST_SASH_FINAL_GROUP[0] for group in groups):
            groups.append(POST_SASH_FINAL_GROUP)
            drop_settings_patch.SETTINGS_GROUPS = tuple(groups)
    except Exception as error:
        print(f"Could not install post-sash final settings group: {error}")


def _selection_init_with_post_sash_defaults(self):
    _ORIGINAL_SELECTION_INIT(self)

    changed = False
    try:
        for key, value in POST_SASH_FINAL_DEFAULTS.items():
            if key not in self.runtime_settings:
                self.runtime_settings[key] = value
                changed = True
        if changed:
            self.apply_runtime_settings()
            self.save_settings()
    except Exception as error:
        print(f"Could not apply post-sash final defaults: {error}")


_install_defaults()
_install_module_order()
_install_settings_group()
SelectionAwareLauncher.__init__ = _selection_init_with_post_sash_defaults

print("Post-sash final actions patch active: press I twice then right-click before next account")
