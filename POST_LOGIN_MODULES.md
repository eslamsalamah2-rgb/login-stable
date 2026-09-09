# Post-Login Modules

This is the controlled merge area for code inspired by `google2`.

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

- first safe merge piece
- captures the exact current account window by PID
- optionally saves a debug image
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

## Next intended modules

1. Inventory grid detector for current PID window.
2. Item image matcher for selected Drop items.
3. Safe Drop worker.
4. Use-item worker.
5. Sash worker.

Each one should be added and tested separately.
