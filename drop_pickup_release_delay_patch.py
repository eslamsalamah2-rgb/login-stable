"""Add a configurable delay between picking an item and releasing/dropping it.

This patch intentionally affects ONLY the Drop worker. It does not modify Sash,
Use, Login, Recovery, or Health.
"""

import time

from gui import DEFAULT_RUNTIME_SETTINGS
from tasks.post_login_modules.inventory_drop_worker import InventoryDropWorkerModule


DEFAULT_RUNTIME_SETTINGS.update({
    "inventory_drop_pickup_to_drop_delay": 0.20,
})

_ORIGINAL_EXECUTE_DROP = InventoryDropWorkerModule._execute_drop


def _execute_drop_with_pickup_release_delay(self, action, pid, hwnd, grid):
    """Run the original drop sequence with one delay between the two clicks."""
    # Preserve the original behavior and all existing stop checks by reproducing
    # the two-click sequence here, while inserting only the requested delay.
    if self._stop_requested():
        return "STOP_REQUESTED"

    slot_x, slot_y = action.slot_screen
    target_x, target_y = action.target_screen
    clicks = self._clicks_per_point()

    print(
        "Inventory drop executing - "
        f"slot={action.slot_index + 1} - item={action.item_name!r} - "
        f"score={action.score:.3f} - slot_xy={action.slot_screen} - "
        f"target_xy={action.target_screen} - target_mode={self._target_mode()} - clicks={clicks}"
    )

    if not self._click_point(slot_x, slot_y, clicks):
        return "STOP_REQUESTED"

    try:
        delay = float(self._setting("inventory_drop_pickup_to_drop_delay", 0.20))
    except Exception:
        delay = 0.20
    delay = max(0.0, min(10.0, delay))
    if delay > 0 and not self._sleep_interruptible(delay):
        return "STOP_REQUESTED"

    if not self._click_point(target_x, target_y, clicks):
        return "STOP_REQUESTED"

    after_drop = self._after_drop_delay()
    if after_drop > 0 and not self._sleep_interruptible(after_drop):
        return "STOP_REQUESTED"

    return self._confirm_yes_if_needed(pid, hwnd, grid)


InventoryDropWorkerModule._execute_drop = _execute_drop_with_pickup_release_delay
print("Drop pickup-release delay patch active: configurable delay before drop click")
