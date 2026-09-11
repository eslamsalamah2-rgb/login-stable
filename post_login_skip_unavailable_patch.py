"""Skip unavailable post-login accounts instead of blocking the whole cycle.

Rules:
- Login/Health still has priority while it is actively running.
- READY accounts keep receiving Drop/Use/Sash work.
- If the current account has no session, missing PID, bad health, disconnect,
  foreground failure, or any account-local module error, skip it for this pass
  and continue with the next selected account.
- The skipped account is tried again when its turn comes around in the next pass.
"""

import time

from gui import DEFAULT_RUNTIME_SETTINGS
from tasks.login_priority_gate import LoginGateResult, LoginPriorityGate
from tasks.post_login_command_runner import PostLoginCommandRunner


DEFAULT_RUNTIME_SETTINGS.update({
    "post_login_skip_unavailable_accounts": True,
    "post_login_skip_unknown_account_errors": True,
    "post_login_skip_log_interval_seconds": 2.0,
})

_ORIGINAL_ALL_SELECTED_READY = LoginPriorityGate.all_selected_ready
_ORIGINAL_TRACK_PROBLEM = PostLoginCommandRunner._track_problem_or_recover
_ORIGINAL_RUNNER_INIT = PostLoginCommandRunner.__init__

_BLOCK_REASONS = {
    "NO_SELECTED_ACCOUNTS",
    "USER_PAUSE_REQUESTED",
    "LOGIN_MONITOR_PAUSED",
    "LOGIN_SEQUENCE_RUNNING",
    "RECOVERING",
    "STOP_REQUESTED",
}

_WAIT_PREFIXES = (
    "BASELINE_PENDING",
    "TIMER_REQUIRED_FOR_STATE",
)

_SKIP_EXACT_REASONS = {
    "NO_SESSION",
    "NO_PID",
    "PID_MISSING",
    "DISCONNECTED_DIALOG",
    "MEMORY_READ_FAILED",
    "FOREGROUND_FAILED",
    "FOREGROUND_ERROR",
    "NO_WINDOW_ACTIVATOR",
    "CAPTURE_FAILED",
    "REVIVE_CAPTURE_FAILED",
    "INVENTORY_CAPTURE_FAILED",
    "INVENTORY_GRID_FAILED",
    "INVENTORY_OPEN_FAILED",
    "CONFIRM_FAILED",
    "COMMAND_ERROR",
    "POST_LOGIN_MERGE_MODULE_ERROR",
}

_SKIP_PREFIXES = (
    "NAME_MISMATCH",
    "STATE_MISMATCH",
)


def _setting(owner, key, default=None):
    launcher = getattr(owner, "launcher", owner)
    try:
        if launcher is not None and hasattr(launcher, "get_runtime_setting"):
            return launcher.get_runtime_setting(key, default)
    except Exception:
        pass
    return DEFAULT_RUNTIME_SETTINGS.get(key, default)


def _bool_setting(owner, key, default=False):
    value = _setting(owner, key, default)
    if isinstance(value, bool):
        return value
    text = str(value if value is not None else "").strip().lower()
    if text in {"1", "true", "yes", "on", "enabled", "enable"}:
        return True
    if text in {"0", "false", "no", "off", "disabled", "disable"}:
        return False
    return bool(default)


def _float_setting(owner, key, default, minimum=0.0):
    try:
        value = float(_setting(owner, key, default))
    except Exception:
        value = float(default)
    return max(float(minimum), value)


def _reason_text(reason):
    return str(reason or "UNKNOWN")


def _is_wait_reason(reason):
    text = _reason_text(reason)
    return text in _BLOCK_REASONS or any(text.startswith(prefix) for prefix in _WAIT_PREFIXES)


def _is_skippable_reason(owner, reason):
    if not _bool_setting(owner, "post_login_skip_unavailable_accounts", True):
        return False

    text = _reason_text(reason)
    if _is_wait_reason(text):
        return False
    if text in _SKIP_EXACT_REASONS:
        return True
    if any(text.startswith(prefix) for prefix in _SKIP_PREFIXES):
        return True
    return _bool_setting(owner, "post_login_skip_unknown_account_errors", True)


def _runner_init_with_skip_state(self, *args, **kwargs):
    _ORIGINAL_RUNNER_INIT(self, *args, **kwargs)
    self._post_login_skip_counts = {}
    self._post_login_skip_log_at = {}


def _all_selected_ready_skip_unavailable(self):
    if not _bool_setting(self, "post_login_skip_unavailable_accounts", True):
        return _ORIGINAL_ALL_SELECTED_READY(self)

    priority_active, priority_reason = self.login_priority_active()
    if priority_active:
        return LoginGateResult(False, priority_reason, None)

    selected = self.selected_indices()
    if not selected:
        return LoginGateResult(False, "NO_SELECTED_ACCOUNTS", None)

    ready = []
    skipped = []
    for index in selected:
        result = self.account_ready(index)
        if result.ok:
            ready.append(index)
            continue

        if _is_skippable_reason(self, result.reason):
            skipped.append((index, result.reason))
            continue

        result.ready_indices = ready
        return result

    if ready:
        if skipped:
            skipped_text = ", ".join(f"{idx + 1}:{reason}" for idx, reason in skipped)
            print(
                "Post-login startup gate: continuing with READY accounts, "
                f"skipping unavailable this pass - skipped={skipped_text}"
            )
        return LoginGateResult(True, "READY_WITH_SKIPPED_UNAVAILABLE", None, ready)

    if skipped:
        first_index, first_reason = skipped[0]
        return LoginGateResult(False, f"NO_READY_ACCOUNTS_FIRST_SKIPPED({first_reason})", first_index, ready)

    return _ORIGINAL_ALL_SELECTED_READY(self)


def _advance_from_skipped_account(self, index, reason):
    selected = []
    try:
        selected = list(self.gate.selected_indices())
    except Exception:
        selected = []

    if not selected or index not in selected:
        return False

    current_pos = selected.index(index)
    next_pos = (current_pos + 1) % len(selected)
    self.next_position = next_pos
    self.current_index = index
    self.problem_key = None
    self.problem_started_at = None

    try:
        self._post_login_skip_counts[index] = int(self._post_login_skip_counts.get(index, 0)) + 1
    except Exception:
        self._post_login_skip_counts = {index: 1}

    now = time.time()
    try:
        last = float(self._post_login_skip_log_at.get(index, 0.0))
    except Exception:
        self._post_login_skip_log_at = {}
        last = 0.0

    interval = _float_setting(self, "post_login_skip_log_interval_seconds", 2.0, minimum=0.2)
    if now - last >= interval:
        try:
            self._post_login_skip_log_at[index] = now
        except Exception:
            pass
        next_account = selected[next_pos] + 1 if selected else "?"
        count = 0
        try:
            count = int(self._post_login_skip_counts.get(index, 0))
        except Exception:
            count = 0
        print(
            "Post-login account skipped this pass - "
            f"account={index + 1} - reason={reason} - "
            f"next_account={next_account} - skip_count={count}"
        )
        try:
            self._set_status(
                f"الحساب {index + 1}: Skip مؤقت بسبب {reason} - نكمل الحساب {next_account}"
            )
        except Exception:
            pass

    return True


def _track_problem_or_skip_unavailable(self, problem_index, problem_reason):
    if problem_index is not None and _is_skippable_reason(self, problem_reason):
        if _advance_from_skipped_account(self, int(problem_index), _reason_text(problem_reason)):
            return

    return _ORIGINAL_TRACK_PROBLEM(self, problem_index, problem_reason)


LoginPriorityGate.all_selected_ready = _all_selected_ready_skip_unavailable
PostLoginCommandRunner.__init__ = _runner_init_with_skip_state
PostLoginCommandRunner._track_problem_or_recover = _track_problem_or_skip_unavailable

print("Post-login skip unavailable patch active: bad/missing accounts skip this pass and cycle continues")
