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

- checks whether the bag is open by matching `assets/inventory_open.png`
- if the image anchor is missing, it presses the configured bag hotkey
- verifies the bag again after pressing
- does not drop or use items

Settings:

```text
enable_inventory_ensure_open = true
inventory_open_hotkey = i
inventory_open_attempts = 2
inventory_open_wait_seconds = 0.80
```

### InventoryGridProbeModule

File:

```text
tasks/post_login_modules/inventory_grid_probe.py
```

Purpose:

- captures the exact current account window by PID
- finds the open bag using the image anchor, then calculates the 5x8 slot grid
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
- compares each visible bag slot against the templates
- logs matching item names, slots, and scores
- saves a debug image with item labels
- does not click, drop, or use items

Settings:

```text
enable_inventory_item_probe = true
inventory_item_templates_dir = assets/drop_items
inventory_item_match_threshold = 0.72
inventory_item_probe_debug_dir = logs/inventory_item_probe
```

### InventoryDropWorkerModule

File:

```text
tasks/post_login_modules/inventory_drop_worker.py
```

Purpose:

- first limited real Drop stage
- uses only item templates from `assets/drop_items`
- drops one matched item per account per cycle by default
- saves a before/after debug image
- runs only after the current account passes `LoginPriorityGate`
- runs while the runner owns `AutomationInputLock`

Settings:

```text
enable_inventory_drop_worker = true
inventory_drop_templates_dir = assets/drop_items
inventory_drop_match_threshold = 0.78
inventory_drop_max_items_per_account = 1
inventory_drop_clicks_per_point = 2
inventory_drop_target_x_fraction = 0.50
inventory_drop_target_y_fraction = 0.45
inventory_drop_debug_dir = logs/inventory_drop_worker
```

Expected debug folder:

```text
logs/inventory_drop_worker
```

Expected log lines:

```text
Inventory drop executing
Inventory drop worker OK
```

## Next intended modules

1. Test the limited Drop stage with one matched item per account.
2. If the click style is correct, increase the drop count gradually.
3. Add popup/confirmation handling if the game shows a confirmation after a drop.
4. Add Use-item worker.
5. Add Sash worker.

Each one should be added and tested separately.
