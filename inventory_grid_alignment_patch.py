"""Temporary inventory grid alignment tuning.

The user-confirmed grid detector is working, but the boxes sit a little to the
right of the real slot cells. This patch only shifts the fixed grid computed
from the inventory_open.png anchor. It does not affect Login/Health, foreground
selection, item matching logic, or any click/drop behavior.
"""

try:
    from tasks.post_login_modules import inventory_anchor

    # More negative means: move the calculated 5x8 slot grid to the LEFT.
    # Previous effective value was -161. User test showed the grid needs a
    # small left shift to sit on the first slot edges.
    inventory_anchor.GRID_OFFSET_X = -169

    print("Inventory grid alignment patch active: GRID_OFFSET_X=-169")
except Exception as error:
    print(f"Inventory grid alignment patch failed: {error}")
