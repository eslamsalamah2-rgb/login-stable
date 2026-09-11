# Post-Login Modules

This is the controlled merge area for ideas inspired by `google2`.

We do not paste the old app into the Login Manager. Each feature must be added
as a small module under:

```text
tasks/post_login_modules/
```

## Rules

1. Login/Health remains the controller.
2. A module runs only after `LoginPriorityGate` allows the current account.
3. The runner handles the account order.
4. A module must not select or skip accounts by itself.
5. A module must not start while Login/Recovery is active.
6. Any mouse/keyboard work must happen inside `AutomationInputLock`.
7. A module that needs to act on the game must work on the current account PID only.
8. Real execution must bring only the current account window to foreground immediately before the command.
9. Test/background checks must not foreground pages or move/click/type.
10. Each module must return a clear result string: `OK`, `SKIPPED`, or a specific failure reason.

## Current modules

### InventoryProbeModule

File:

```text
tasks/post_login_modules/inventory_probe.py
```

Purpose:

- captures the exact current account window by PID
- optionally saves a full debug image
- does not click
- does not type
- does not drop/use items
- does not capture the whole desktop

Settings:

```text
enable_inventory_probe = false
inventory_probe_save_debug_image = true
inventory_probe_debug_dir = logs/inventory_probe
```

### InventoryEnsureOpenModule

File:

```text
tasks/post_login_modules/inventory_ensure_open.py
```

Purpose:

- detects whether the bag is open using the manual image anchor
- preferred anchor file: `assets/inventory_open.png`
- if the bag image is not found, presses the configured inventory hotkey
- verifies again after pressing the hotkey
- does not click items, drop, or use anything

Settings:

```text
enable_inventory_ensure_open = true
inventory_open_hotkey = i
inventory_open_attempts = 2
inventory_open_wait_seconds = 0.80
inventory_open_strict = false
```

### InventoryGridProbeModule

File:

```text
tasks/post_login_modules/inventory_grid_probe.py
```

Purpose:

- captures the exact current account window by PID
- detects the open bag by image anchor first
- computes the 5 columns x 8 rows slot grid from the detected bag position
- fallback: dynamic line-grid detector if the image anchor is not found
- saves an annotated debug image with boxes around the 40 slots
- gives a rough filled/empty count for logging
- does not click
- does not type
- does not drop/use items

Settings:

```text
enable_inventory_grid_probe = true
inventory_grid_probe_save_debug_image = true
inventory_grid_probe_debug_dir = logs/inventory_grid_probe
```

### InventoryItemProbeModule

File:

```text
tasks/post_login_modules/inventory_item_probe.py
```

Purpose:

- reads PNG/JPG item templates from `assets/drop_items`
- compares every detected bag slot against those item templates
- logs matched item names, slot numbers, rows, columns, and scores
- saves an annotated debug image showing matched slots
- probe-only: no clicking, no dropping, no using items

Settings:

```text
enable_inventory_item_probe = true
inventory_item_templates_dir = assets/drop_items
inventory_item_match_threshold = 0.72
inventory_item_probe_save_debug_image = true
inventory_item_probe_debug_dir = logs/inventory_item_probe
```

Expected item template folder:

```text
assets/drop_items
```

Expected item probe log lines:

```text
Inventory item probe OK
Inventory item match
Inventory item probe debug image saved
```

## Next intended modules

1. Confirm Item Probe recognizes the intended item templates correctly.
2. Add a decision layer: Drop / Use / Ignore.
3. Safe Drop worker for one item, one account, one cycle.
4. Expand Drop worker to all selected accounts.
5. Sash worker.

Each one should be added and tested separately.
