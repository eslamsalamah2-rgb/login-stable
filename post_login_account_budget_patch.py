"""Per-account time budget for post-login command work.

This affects only stage-two commands after Login/Health says the account is
READY.  Login itself remains the controller and is not timed by this patch.

Default rule:
- each account gets post_login_account_budget_seconds seconds (180 = 3 minutes)
- when the budget ends, the current worker stops cleanly and the runner moves to
  the next selected READY account
- key 9 still means real user stop and stops everything
"""

import time

from gui import DEFAULT_RUNTIME_SETTINGS
from tasks.post_login_command_runner import PostLoginCommandRunner
from tasks.post_login_modules.inventory_drop_worker import InventoryDropWorkerModule


DEFAULT_RUNTIME_SETTINGS.setdefault("post_login_account_budget_seconds", 180.0)

_ORIGINAL_RUN_ACCOUNT_COMMANDS = PostLoginCommandRunner._run_account_commands
_ORIGINAL_DROP_STOP_REQUESTED = InventoryDropWorkerModule._stop_requested


def _budget_seconds(runner):
    try:
        value = runner.launcher.get_runtime_setting("post_login_account_budget_seconds", 180.0)
    except Exception:
        value = 180.0
    try:
        value = float(value)
    except Exception:
        value = 180.0
    return max(10.0, min(3600.0, value))


def _run_account_commands_with_budget(self, index, session):
    budget = _budget_seconds(self)
    deadline = time.perf_counter() + budget

    try:
        self.post_login_account_deadline = deadline
        self.post_login_account_budget_seconds = budget
        self.post_login_account_index = index
        self.launcher.post_login_account_deadline = deadline
        self.launcher.post_login_account_budget_seconds = budget
        self.launcher.post_login_account_budget_account_index = index
        self.launcher.post_login_account_budget_expired = False
    except Exception:
        pass

    print(
        "Post-login account time budget started - "
        f"account={index + 1} - budget={budget:.1f}s"
    )

    result = _ORIGINAL_RUN_ACCOUNT_COMMANDS(self, index, session)

    try:
        expired = bool(getattr(self.launcher, "post_login_account_budget_expired", False))
        if time.perf_counter() >= deadline:
            expired = True
        user_stop = bool(self.stop_event.is_set() or getattr(self.launcher, "pause_requested", False))
    except Exception:
        expired = False
        user_stop = False

    try:
        for attr in (
            "post_login_account_deadline",
            "post_login_account_budget_seconds",
            "post_login_account_index",
        ):
            if hasattr(self, attr):
                delattr(self, attr)
        for attr in (
            "post_login_account_deadline",
            "post_login_account_budget_seconds",
            "post_login_account_budget_account_index",
            "post_login_account_budget_expired",
        ):
            if hasattr(self.launcher, attr):
                delattr(self.launcher, attr)
    except Exception:
        pass

    if expired and not user_stop:
        print(
            "Post-login account time budget finished - moving next account - "
            f"account={index + 1} - result={result}"
        )
        self._set_status(f"الحساب {index + 1}: انتهت مدة أوامر الدخول - الانتقال للتالي")
        return "OK"

    return result


def _drop_stop_or_budget(self):
    if _ORIGINAL_DROP_STOP_REQUESTED(self):
        return True

    deadline = getattr(self.launcher, "post_login_account_deadline", None)
    if deadline is None:
        return False

    try:
        if time.perf_counter() < float(deadline):
            return False
    except Exception:
        return False

    try:
        if not bool(getattr(self.launcher, "post_login_account_budget_expired", False)):
            index = getattr(self.launcher, "post_login_account_budget_account_index", None)
            account_text = "?" if index is None else str(int(index) + 1)
            budget = getattr(self.launcher, "post_login_account_budget_seconds", 180.0)
            print(
                "Post-login account time budget reached inside Drop - "
                f"account={account_text} - budget={float(budget):.1f}s"
            )
        self.launcher.post_login_account_budget_expired = True
    except Exception:
        pass

    return True


PostLoginCommandRunner._run_account_commands = _run_account_commands_with_budget
InventoryDropWorkerModule._stop_requested = _drop_stop_or_budget

print("Post-login account budget patch active: each account gets 180 seconds by default")
