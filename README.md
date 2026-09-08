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

## Pull latest changes

```bash
git pull origin main
```

## Roll back to the stable point before merge experiments

```bash
git fetch origin
git reset --hard origin/stable-before-merge
```
