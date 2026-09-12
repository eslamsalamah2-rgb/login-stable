"""Clear account slots that do not contain real login credentials.

User rule:
- A row/page without Username + Password is not an account.
- It must not stay selected, must not be queued for Login, and must not block
  Drop/Use/Sash with repeated NO_SESSION messages.
- If the UI row has valid credentials but accounts_data is stale, sync it before
  the normal Login pipeline starts.

This is a small hygiene gate only. It does not change Login typing, Recovery,
Health, Drop, Use, Sash, or image detection.
"""

import time

from gui import DEFAULT_RUNTIME_SETTINGS
from selection_launcher import SelectionAwareLauncher
from tasks.login_priority_gate import LoginPriorityGate
from tasks.post_login_command_runner import PostLoginCommandRunner


DEFAULT_RUNTIME_SETTINGS.update({
    "clear_rows_without_login_on_start": True,
    "sync_accounts_from_ui_before_login_queue": True,
})

_ORIGINAL_SELECTED_INDICES = LoginPriorityGate.selected_indices
_ORIGINAL_PROCESS_ACCOUNTS = SelectionAwareLauncher.process_accounts
_ORIGINAL_TRACK_PROBLEM = PostLoginCommandRunner._track_problem_or_recover


def _setting(launcher, key, default=None):
    try:
        if hasattr(launcher, "get_runtime_setting"):
            return launcher.get_runtime_setting(key, default)
    except Exception:
        pass
    return DEFAULT_RUNTIME_SETTINGS.get(key, default)


def _bool_setting(launcher, key, default=False):
    value = _setting(launcher, key, default)
    if isinstance(value, bool):
        return value
    text = str(value if value is not None else "").strip().lower()
    if text in {"1", "true", "yes", "on", "enabled", "enable"}:
        return True
    if text in {"0", "false", "no", "off", "disabled", "disable"}:
        return False
    return bool(default)


def _text(value):
    return str(value if value is not None else "")


def _row_login_values(launcher, index):
    try:
        row = launcher.account_rows[index]
    except Exception:
        return "", ""

    try:
        username = _text(row["username"].get()).strip()
    except Exception:
        username = ""

    try:
        password = _text(row["password"].get()).strip()
    except Exception:
        password = ""

    return username, password


def _row_has_login(launcher, index):
    username, password = _row_login_values(launcher, index)
    return bool(username and password)


def _account_data_has_login(launcher, index):
    try:
        item = launcher.accounts_data[index]
    except Exception:
        return False
    if not isinstance(item, dict):
        return False
    username = _text(item.get("username", "")).strip()
    password = _text(item.get("password", "")).strip()
    return bool(username and password)


def _sync_accounts_from_ui(launcher, reason="unknown"):
    if not _bool_setting(launcher, "sync_accounts_from_ui_before_login_queue", True):
        return

    try:
        accounts = launcher.collect_accounts_from_ui()
    except Exception:
        return

    if not isinstance(accounts, list):
        return

    try:
        current_count = len(getattr(launcher, "accounts_data", []) or [])
    except Exception:
        current_count = 0

    # collect_accounts_from_ui() already ignores blank Username/Password rows.
    # Updating here fixes stale accounts_data when a valid row was added but the
    # runner tries to open it from post-login before a fresh save happened.
    try:
        launcher.accounts_data = accounts
    except Exception:
        pass

    try:
        launcher.account_manager.save_accounts(accounts)
    except Exception:
        pass

    if len(accounts) != current_count:
        print(
            "Accounts data synced from UI - "
            f"reason={reason} - valid_accounts={len(accounts)}"
        )


def _remove_index_from_list(values, index):
    try:
        return [item for item in list(values or []) if item != index]
    except Exception:
        return []


def _clear_no_account_slot(launcher, index, reason="NO_ACCOUNT_DATA"):
    if not _bool_setting(launcher, "clear_rows_without_login_on_start", True):
        return False

    try:
        if index in getattr(launcher, "active_sessions", {}):
            launcher.active_sessions.pop(index, None)
    except Exception:
        pass

    try:
        launcher.pending_start_indices = _remove_index_from_list(
            getattr(launcher, "pending_start_indices", []),
            index,
        )
    except Exception:
        pass

    try:
        skipped = getattr(launcher, "skipped_start_indices", None)
        if skipped is None:
            skipped = set()
            launcher.skipped_start_indices = skipped
        skipped.add(index)
    except Exception:
        pass

    try:
        row = launcher.account_rows[index]
        selected_var = row.get("selected_var")
        if selected_var is not None:
            selected_var.set(False)
    except Exception:
        pass

    try:
        launcher.set_row_state(index, "idle", "")
    except Exception:
        pass

    now = time.time()
    key = f"_no_account_clear_log_at_{index}"
    last = float(getattr(launcher, key, 0.0) or 0.0)
    if now - last >= 1.5:
        try:
            setattr(launcher, key, now)
        except Exception:
            pass
        print(
            "No-account slot cleared - "
            f"account={index + 1} - reason={reason} - selected=False - session_cleared=True"
        )
        try:
            launcher.set_status(
                f"الحساب {index + 1}: مفيش Username/Password صالح - اتعمله Clear"
            )
        except Exception:
            pass

    return True


def _valid_or_clear_for_login(launcher, index, reason="check"):
    # First sync, because a newly added valid row may exist in the UI while
    # accounts_data is still stale/short.
    _sync_accounts_from_ui(launcher, reason=reason)

    if _row_has_login(launcher, index):
        return True

    if _account_data_has_login(launcher, index):
        return True

    return not _clear_no_account_slot(launcher, index, reason=reason)


def _selected_indices_clear_invalid(self):
    launcher = getattr(self, "launcher", None)
    try:
        selected = list(_ORIGINAL_SELECTED_INDICES(self))
    except Exception:
        selected = []

    if launcher is None:
        return selected

    result = []
    for index in selected:
        if _row_has_login(launcher, index) or _account_data_has_login(launcher, index):
            result.append(index)
            continue
        _clear_no_account_slot(launcher, index, reason="selected_indices_no_login")
    return result


def _process_accounts_sync_first(self):
    _sync_accounts_from_ui(self, reason="process_accounts_start")

    # Remove pending indices that have no real account behind them. This prevents
    # the Login thread from finishing instantly while the post-login runner keeps
    # asking for the same missing account again.
    pending = []
    removed = []
    for index in list(getattr(self, "pending_start_indices", []) or []):
        if _row_has_login(self, index) or _account_data_has_login(self, index):
            pending.append(index)
        else:
            removed.append(index)
            _clear_no_account_slot(self, index, reason="pending_login_no_account")

    if removed:
        try:
            self.pending_start_indices = pending
        except Exception:
            pass

    return _ORIGINAL_PROCESS_ACCOUNTS(self)


def _track_problem_clear_no_account(self, problem_index, problem_reason):
    if problem_index is not None:
        launcher = getattr(self, "launcher", None)
        if launcher is not None:
            index = int(problem_index)
            if not (_row_has_login(launcher, index) or _account_data_has_login(launcher, index)):
                if _clear_no_account_slot(launcher, index, reason=f"post_login_{problem_reason}"):
                    try:
                        selected = list(self.gate.selected_indices())
                        if selected:
                            if index in selected:
                                self.next_position = (selected.index(index) + 1) % len(selected)
                            elif self.next_position >= len(selected):
                                self.next_position = 0
                    except Exception:
                        pass
                    self.problem_key = None
                    self.problem_started_at = None
                    return

    return _ORIGINAL_TRACK_PROBLEM(self, problem_index, problem_reason)


LoginPriorityGate.selected_indices = _selected_indices_clear_invalid
SelectionAwareLauncher.process_accounts = _process_accounts_sync_first
PostLoginCommandRunner._track_problem_or_recover = _track_problem_clear_no_account

print("No-account clear patch active: selected/pending rows without Username+Password are cleared")
