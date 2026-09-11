"""Enable the Sash stage after Use without touching the stable Login flow.

Post-login stage order:
Revive -> Ensure Inventory Open -> Drop -> Use -> Sash

Sash uses external images only:
- assets/sash_button.png for opening the Sash panel
- assets/sash_items/*.png for items to transfer
"""

import os

from gui import DEFAULT_RUNTIME_SETTINGS
from selection_launcher import SelectionAwareLauncher
from tasks.post_login_modules.inventory_sash_worker import InventorySashWorkerModule

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


SASH_SETTING_DEFAULTS = {
    "enable_inventory_sash_worker": True,
    "inventory_sash_templates_dir": os.path.join("assets", "sash_items"),
    "inventory_sash_match_threshold": 0.88,
    "inventory_sash_button_paths": "",
    "inventory_sash_button_threshold": 0.80,
    "inventory_sash_require_button": False,
    "inventory_sash_max_items_per_account": 20,
    "inventory_sash_click_delay": 0.10,
    "inventory_sash_open_wait_seconds": 0.25,
    "inventory_sash_after_transfer_delay": 0.18,
    "inventory_sash_mouse_clear_x": 900,
    "inventory_sash_mouse_clear_y": 500,
    "inventory_sash_save_debug_image": False,
    "inventory_sash_debug_dir": "logs/inventory_sash_worker",
}

SASH_SETTING_LABELS = {
    "enable_inventory_sash_worker": "enable_inventory_sash_worker | Sash - نقل العناصر بعد Use",
    "inventory_sash_templates_dir": "inventory_sash_templates_dir | مجلد صور عناصر Sash",
    "inventory_sash_match_threshold": "inventory_sash_match_threshold | حساسية مطابقة عناصر Sash",
    "inventory_sash_button_paths": "inventory_sash_button_paths | مسارات إضافية لصورة زر Sash",
    "inventory_sash_button_threshold": "inventory_sash_button_threshold | حساسية صورة زر Sash",
    "inventory_sash_require_button": "inventory_sash_require_button | إيقاف مرحلة Sash لو زر Sash غير موجود",
    "inventory_sash_max_items_per_account": "inventory_sash_max_items_per_account | أقصى عدد Items ينقلها للـSash لكل حساب",
    "inventory_sash_click_delay": "inventory_sash_click_delay | تأخير كليك Sash / ثانية",
    "inventory_sash_open_wait_seconds": "inventory_sash_open_wait_seconds | انتظار بعد فتح Sash / ثانية",
    "inventory_sash_after_transfer_delay": "inventory_sash_after_transfer_delay | انتظار بعد Alt+Click قبل السكان التالي / ثانية",
    "inventory_sash_mouse_clear_x": "inventory_sash_mouse_clear_x | مكان إبعاد الماوس X بعد النقل",
    "inventory_sash_mouse_clear_y": "inventory_sash_mouse_clear_y | مكان إبعاد الماوس Y بعد النقل",
    "inventory_sash_save_debug_image": "inventory_sash_save_debug_image | حفظ صور Debug قبل Sash",
    "inventory_sash_debug_dir": "inventory_sash_debug_dir | مجلد صور Debug للـSash",
}

SASH_SETTINGS_GROUP = (
    "Setting Sash",
    "مرحلة Sash بعد Use: تفتح Sash بالزر، تعمل Scan على الشنطة، وتنقل الصور الموجودة في assets/sash_items بـ Alt + Click.",
    (
        ("inventory_sash_max_items_per_account", "أقصى عدد Items ينقلها للـSash في الحساب"),
        ("inventory_sash_click_delay", "تأخير قبل/بعد كليك Sash / ثانية"),
        ("inventory_sash_open_wait_seconds", "انتظار بعد الضغط على زر Sash / ثانية"),
        ("inventory_sash_after_transfer_delay", "انتظار بعد نقل كل Item قبل السكان التالي / ثانية"),
        ("inventory_sash_mouse_clear_x", "مكان إبعاد الماوس X بعد النقل"),
        ("inventory_sash_mouse_clear_y", "مكان إبعاد الماوس Y بعد النقل"),
    ),
)

_ORIGINAL_SELECTION_INIT = SelectionAwareLauncher.__init__


def _install_sash_defaults():
    DEFAULT_RUNTIME_SETTINGS.update(SASH_SETTING_DEFAULTS)

    if existing_pages_settings_patch is not None:
        try:
            existing_pages_settings_patch.SETTING_LABELS.update(SASH_SETTING_LABELS)
        except Exception:
            pass


def _install_sash_module_order():
    if registry is None:
        return
    try:
        classes = list(registry.MODULE_CLASSES)
        if InventorySashWorkerModule not in classes:
            classes.append(InventorySashWorkerModule)
            registry.MODULE_CLASSES = tuple(classes)
    except Exception as error:
        print(f"Could not install Sash module order: {error}")


def _install_sash_settings_group():
    if drop_settings_patch is None:
        return
    try:
        groups = list(drop_settings_patch.SETTINGS_GROUPS)
        if not any(group[0] == SASH_SETTINGS_GROUP[0] for group in groups):
            groups.append(SASH_SETTINGS_GROUP)
            drop_settings_patch.SETTINGS_GROUPS = tuple(groups)
    except Exception as error:
        print(f"Could not install Sash settings group: {error}")


def _selection_init_with_sash_defaults(self):
    _ORIGINAL_SELECTION_INIT(self)

    changed = False
    try:
        for key, value in SASH_SETTING_DEFAULTS.items():
            if key not in self.runtime_settings:
                self.runtime_settings[key] = value
                changed = True
        if changed:
            self.apply_runtime_settings()
            self.save_settings()
    except Exception as error:
        print(f"Could not apply Sash defaults: {error}")


_install_sash_defaults()
_install_sash_module_order()
_install_sash_settings_group()
SelectionAwareLauncher.__init__ = _selection_init_with_sash_defaults

print("Sash items patch active: Sash worker after Use, external images in assets/sash_items")
