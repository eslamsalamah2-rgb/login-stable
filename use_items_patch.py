"""Enable the Use stage after Drop without touching the stable Login flow.

Use stage order inside post-login modules:
Revive -> Ensure Inventory Open -> Drop -> Use

Use item images are external only:
    assets/use_items/*.png
"""

import os

from gui import DEFAULT_RUNTIME_SETTINGS
from selection_launcher import SelectionAwareLauncher
from tasks.post_login_modules.inventory_use_worker import InventoryUseWorkerModule

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


USE_SETTING_DEFAULTS = {
    "enable_inventory_use_worker": True,
    "inventory_use_templates_dir": os.path.join("assets", "use_items"),
    "inventory_use_match_threshold": 0.88,
    "inventory_use_max_items_per_account": 20,
    "inventory_use_right_clicks_per_item": 1,
    "inventory_use_click_delay": 0.10,
    "inventory_use_after_use_delay": 0.25,
    "inventory_use_save_debug_image": False,
    "inventory_use_debug_dir": "logs/inventory_use_worker",
}

USE_SETTING_LABELS = {
    "enable_inventory_use_worker": "enable_inventory_use_worker | Use - استخدام العناصر بعد الدروب",
    "inventory_use_templates_dir": "inventory_use_templates_dir | مجلد صور عناصر اليوز",
    "inventory_use_match_threshold": "inventory_use_match_threshold | حساسية مطابقة عناصر اليوز",
    "inventory_use_max_items_per_account": "inventory_use_max_items_per_account | أقصى عدد عناصر Use لكل حساب في الدورة",
    "inventory_use_right_clicks_per_item": "inventory_use_right_clicks_per_item | عدد كليكات يمين على كل عنصر Use - الافتراضي 1",
    "inventory_use_click_delay": "inventory_use_click_delay | تأخير قبل/بعد كليك يمين Use/ثانية",
    "inventory_use_after_use_delay": "inventory_use_after_use_delay | انتظار بعد استخدام كل Item قبل السكان التالي/ثانية",
    "inventory_use_save_debug_image": "inventory_use_save_debug_image | حفظ صور Debug قبل Use",
    "inventory_use_debug_dir": "inventory_use_debug_dir | مجلد صور Debug للـ Use",
}

USE_SETTINGS_GROUP = (
    "Setting Use",
    "مرحلة اليوز بعد الدروب: يعمل Scan على الشنطة ويضغط كليك يمين على الصور الموجودة في assets/use_items.",
    (
        ("inventory_use_max_items_per_account", "أقصى عدد Items يعمل عليها Use في الحساب"),
        ("inventory_use_right_clicks_per_item", "عدد كليكات يمين على كل Item - خليه 1"),
        ("inventory_use_click_delay", "تأخير قبل/بعد كليك يمين Use / ثانية"),
        ("inventory_use_after_use_delay", "انتظار بعد استخدام كل Item قبل السكان التالي / ثانية"),
    ),
)

_ORIGINAL_SELECTION_INIT = SelectionAwareLauncher.__init__


def _install_use_defaults():
    DEFAULT_RUNTIME_SETTINGS.update(USE_SETTING_DEFAULTS)

    if existing_pages_settings_patch is not None:
        try:
            existing_pages_settings_patch.SETTING_LABELS.update(USE_SETTING_LABELS)
        except Exception:
            pass


def _install_use_module_order():
    if registry is None:
        return
    try:
        classes = list(registry.MODULE_CLASSES)
        if InventoryUseWorkerModule not in classes:
            classes.append(InventoryUseWorkerModule)
            registry.MODULE_CLASSES = tuple(classes)
    except Exception as error:
        print(f"Could not install Use module order: {error}")


def _install_use_settings_group():
    if drop_settings_patch is None:
        return
    try:
        groups = list(drop_settings_patch.SETTINGS_GROUPS)
        if not any(group[0] == USE_SETTINGS_GROUP[0] for group in groups):
            groups.append(USE_SETTINGS_GROUP)
            drop_settings_patch.SETTINGS_GROUPS = tuple(groups)
    except Exception as error:
        print(f"Could not install Use settings group: {error}")


def _selection_init_with_use_defaults(self):
    _ORIGINAL_SELECTION_INIT(self)

    changed = False
    try:
        for key, value in USE_SETTING_DEFAULTS.items():
            if key not in self.runtime_settings:
                self.runtime_settings[key] = value
                changed = True
        if changed:
            self.apply_runtime_settings()
            self.save_settings()
    except Exception as error:
        print(f"Could not apply Use defaults: {error}")


_install_use_defaults()
_install_use_module_order()
_install_use_settings_group()
SelectionAwareLauncher.__init__ = _selection_init_with_use_defaults

print("Use items patch active: Use worker after Drop, external images in assets/use_items")
