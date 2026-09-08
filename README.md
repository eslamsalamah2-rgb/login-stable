# login-stable

Stable test baseline for the Conquer login manager.

## Current health logic

- Timer/FPS heartbeat is captured only from the exact target PID window, never from the full desktop.
- Memory state values are learned dynamically; no numeric state is hard-coded as special.
- If the same memory state is seen with the expected character name while the login page is visible in that same PID window, that state becomes timer-gated.
- Any timer-gated state must pass the in-window timer heartbeat before it can be treated as healthy.
- If timer data is missing/static/unknown while memory still equals a learned state, that state is also learned as timer-gated.

## Pre-merge safety

- Branch `stable-before-merge` was created before the pre-merge changes so the project can be restored quickly.
- Runtime logs are written to `logs/app.log`.
- Local JSON files are backed up to `backups/` on startup and from the `Backup` button.
- A shared input lock protects mouse/keyboard actions from future merged features.
- New feature flags are stored in `settings.json` and are off by default: Monster Scan, Auto Drop, Movement.
- Local credentials/account files remain excluded by `.gitignore`.

## Post-login Commands - Stage 1

- Starts only after all selected accounts become READY.
- Loops over the selected accounts in order: account 1, account 2, account 3, then back to account 1.
- Login, Health, Recovery, Disconnected, Maintenance, and Update always have priority over command work.
- If a selected account becomes unhealthy, command work waits while Login/Health fixes it.
- If the account stays problematic longer than the configured timeout, the runner closes that page and asks the login system to reopen it.
- Stage 1 is safe test mode only: it proves the loop and safety behavior without doing Drop/Use clicks yet.

## Post-login Commands settings

- `enable_post_login_commands`: turns the command runner on/off.
- `post_login_debug_only`: keeps Stage 1 in safe test mode.
- `post_login_recovery_max_seconds`: max wait before closing/reopening a stuck account.
- `post_login_account_delay_seconds`: delay between accounts in the command loop.
- `post_login_round_delay_seconds`: delay between full command rounds.

## Pull latest changes

```bash
git pull origin main
```

## Roll back to the stable point before merge experiments

```bash
git fetch origin
git reset --hard origin/stable-before-merge
```
