# Post-Login Priority Summary

## Core rule

Login/Health is the controller.
Post-login commands are workers.

The final goal is to run post-login work such as Drop, Use, Sash, Movement, or Attack. However, no post-login worker may start or continue unless Login/Health says the target account is READY.

## Stage order

1. Open only the selected accounts.
2. Login each selected account.
3. Wait until all selected accounts become READY.
4. Start stage two: post-login commands.
5. Stage two processes one current account at a time.
6. Before moving to the next account, the current account must pass the LoginPriorityGate.

## LoginPriorityGate

`tasks/login_priority_gate.py` is the single authority used by post-login commands before execution.

It checks:

- no login sequence is currently running
- no global pause/monitor pause is active
- the account is not already in recovery
- the account has a registered session
- the session has a PID
- the PID still exists
- no disconnect dialog is present
- memory name can be read
- memory state can be read
- current memory name matches the expected character name
- healthy baseline state exists
- timer-gated states are not trusted without the existing timer logic
- current memory state matches the learned healthy state

## Startup rule for stage two

Before post-login commands start, all selected accounts must be READY.
If any selected account is not READY, stage two does not start yet.

## Current-account rule after stage two starts

After stage two starts, the runner checks only the account whose turn is next.

If account 1 is next, only account 1 is checked.
If account 1 is READY, it runs account 1's post-login step, then moves to account 2.
If account 1 is not READY, the runner stays on account 1 and does not skip to account 2.

## Recovery rule

If the current account is not READY:

1. Post-login commands pause at the same account.
2. Login/Health keeps priority and attempts recovery.
3. When the account becomes READY again, stage two continues from that same account.
4. If the problem lasts longer than `post_login_recovery_max_seconds`, that account page is closed and reopened.

## Global close rule

Global login problems remain controlled by Login/Health:

- Server Maintenance
- Client Update
- repeated Wrong Password after password rewrite

These conditions close all Conquer pages and restart the selected-account login flow from the beginning.

Post-login command modules must not override this rule.

## Test Mode rule

Test Mode is background-only.

It does not:

- bring any game page to the foreground
- click
- type
- move the mouse
- use the input lock
- perform Drop/Use/Sash

It only checks the current account whose turn would be executed next, then advances to the next account if READY.

## Real command rule

Real post-login execution must follow this order for every account:

1. Check LoginPriorityGate for the current account.
2. Acquire AutomationInputLock.
3. Bring only that current account's window to the foreground.
4. Re-check LoginPriorityGate after foreground activation.
5. Execute the real command.
6. Release AutomationInputLock.
7. Move to the next selected account only if the command step completed safely.

## Priority order

1. Manual Stop / Pause
2. Global login conditions: Maintenance, Update, repeated password failure
3. Account recovery: Logout, Disconnect, missing PID, bad state, timer-gated state
4. Real post-login commands: Drop, Use, Sash, Movement, Attack
5. Background Test Mode
