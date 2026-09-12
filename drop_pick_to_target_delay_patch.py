"""Add a setting for the delay between clicking an item and clicking its drop target.

This patch affects only the post-login inventory Drop worker. It does not touch
Login, Recovery, Health, Use, or Sash.
"""

import time

from gui import DEFAULT_RUNTIME_SETTINGS
from selection_launcher import SelectionAwareLauncher
from tasks.post_login_modules.inventory_drop_worker import InventoryDropWorkerModule

try:
    import drop_settings_patch
except Exception:
    drop_settings_patch = None


SETTING_DEFAULTS = {
    # Seconds between the item click and the drop-target click.
    "inventory_drop_pick_to_target_delay": 0.20,
}

SETTING_GROUP = (
    "Setting Drop",
    "إعدادات مرحلة Drop، بما فيها زمن الانتظار بين اختيار الـItem والضغط على مكان إسقاطه.",
    (
        (
            "inventory_drop_pick_to_target_delay",
            "تأخير بين أخذ الـItem وتركه / ثانية",
        ),
    ),
)

_ORIGINAL_DROP_INIT = InventoryDropWorkerModule.__init__
_ORIGINAL_CLICK_POINT = InventoryDropWorkerModule._click_point


def _install_defaults_and_group():
    DEFAULT_RUNTIME_SETTINGS.update(SETTING_DEFAULTS)
    if drop_settings_patch is None:
        return
    try:
        groups = list(drop_settings_patch.SETTINGS_GROUPS)
        # Add the field to the existing Setting Drop group when possible.
        for index, group in enumerate(groups):
            if group[0] != "Setting Drop":
                continue
            title, note, fields = group
            fields = list(fields)
            if not any(item[0] == "inventory_drop_pick_to_target_delay" for item in fields):
                fields.append(SETTING_GROUP[2][0])
                groups[index] = (title, note, tuple(fields))
            drop_settings_patch.SETTINGS_GROUPS = tuple(groups)
            return
        groups.append(SETTING_GROUP)
        drop_settings_patch.SETTINGS_GROUPS = tuple(groups)
    except Exception as error:
        print(f"Drop pick-to-target setting group warning: {error}")


def _drop_init(self, *args, **kwargs):
    _ORIGINAL_DROP_INIT(self, *args, **kwargs)
    try:
        self._pick_to_target_delay_pending = False
    except Exception:
        pass


def _delay_seconds(self):
    try:
        value = float(self._setting("inventory_drop_pick_to_target_delay", 0.20))
    except Exception:
        value = 0.20
    return max(0.0, min(5.0, value))


def _click_point_with_pick_to_target_delay(self, x, y, clicks):
    result = _ORIGINAL_CLICK_POINT(self, x, y, clicks)
    if not result:
        return result

    # _execute_drop calls _click_point first for the item and then for the
    # target. Delay only after the first successful click in that sequence.
    if getattr(self, "_pick_to_target_delay_pending", False):
        self._pick_to_target_delay_pending = False
        delay = _delay_seconds(self)
        if delay > 0 and hasattr(self, "_sleep_interruptible"):
            return self._sleep_interruptible(delay)
        if delay > 0:
            time.sleep(delay)
        return not self._stop_requested()
    return result


def _execute_drop_mark_first_click(self, action, pid, hwnd, grid):
    # The original method performs item click followed by target click.
    # Mark the next click as the item click, then let the wrapped click method
    # insert the configurable delay before the target click.
    self._pick_to_target_delay_pending = True
    try:
        return _ORIGINAL_EXECUTE_DROP(self, action, pid, hwnd, grid)
    finally:
        self._pick_to_target_delay_pending = False


_ORIGINAL_EXECUTE_DROP = InventoryDropWorkerModule._execute_drop


_install_defaults_and_group()
InventoryDropWorkerModule.__init__ = _drop_init
InventoryDropWorkerModule._click_point = _click_point_with_pick_to_target_delay
InventoryDropWorkerModule._execute_drop = _execute_drop_mark_first_click

print("Drop pick-to-target delay patch active: editable delay between item click and drop-target click")
