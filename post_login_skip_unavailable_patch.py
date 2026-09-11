"""Skip unavailable post-login accounts, but reopen missing ones on their turn.

Rules:
- Login/Health still has priority while it is actively running.
- READY accounts keep receiving Drop/Use/Sash work.
- Startup may begin with the accounts that are already READY.
- When the cycle reaches a selected account with NO_SESSION/NO_PID/PID_MISSING,
  it immediately asks the normal Login pipeline to open that account, then tries
  that same account after Login finishes.
- If an account has a local problem that is not safe to open immediately, skip it
  for this pass and continue with the next selected account.
"""

import time

from gui import DEFAULT_RUNTIME_SETTINGS
from tasks.login_priority_gate import LoginGateResult, LoginPriorityGate
from tasks.post_login_command_runner import PostLoginCommandRunner


DEFAULT_RUNTIME_SETTINGS.update({
    "post_login_skip_unavailable_accounts": True,
    "post_login_skip_unknown_account_errors": True,
    "post_login_skip_log_interval_seconds": 2.0,
    "post_login_open_missing_on_turn": True,
    "post_login_open_missing_cooldown_seconds": 8.0,
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
    "NO_READY_ACCOUNTS",
)

# These reasons mean the account/page is missing or stale. Do not just keep
# skipping them forever; ask the normal Login queue to open them when their turn
# arrives in the post-login cycle.
_OPEN_ON_TURN_REASONS = {
    "NO_SESSION",
    "NO_PID",
    "PID_MISSING",
}

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


def _is_open_on_turn_reason(owner, reason):
    if not _bool_setting(owner, "post_login_open_missing_on_turn", True):
        return False
    return _reason_text(reason) in _OPEN_ON_TURN_REASONS


def _runner_init_with_skip_state(self, *args, **kwargs):
    _ORIGINAL_RUNNER_INIT(self, *args, **kwargs)
    self._post_login_skip_counts = {}
    self._post_login_skip_log_at = {}
    self._post_login_open_attempt_log_at = {}
    self._post_login_open_requested_at = {}


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
                f"will open/skip unavailable on their turn - skipped={skipped_text}"
            )
        return LoginGateResult(True, "READY_WITH_SKIPPED_UNAVAILABLE", None, ready)

    if skipped:
        first_index, first_reason = skipped[0]
        return LoginGateResult(False, f"NO_READY_ACCOUNTS_FIRST_SKIPPED({first_reason})", first_index, ready)

    return _ORIGINAL_ALL_SELECTED_READY(self)


def _selected_contains(launcher, index):
    try:
        if hasattr(launcher, "_is_account_selected"):
            return bool(launcher._is_account_selected(index))
    except Exception:
        pass
    return True


def _already_skipped_by_login(launcher, index):
    try:
        skipped = getattr(launcher, "skipped_start_indices", set()) or set()
        return index in skipped
    except Exception:
        return False


def _safe_pending_list(launcher):
    pending = getattr(launcher, "pending_start_indices", None)
    if not isinstance(pending, list):
        pending = []
        launcher.pending_start_indices = pending
    return pending


def _request_open_account_on_turn(self, index, reason):
    """Queue a missing account in the normal Start/Login pipeline.

    Returns True when an open/login request is already active or has just been
    scheduled. The command loop should then stay on this account; Login priority
    will pause post-login work until the account is either READY or skipped by
    the normal login retry limiter.
    """
    launcher = getattr(self, "launcher", None)
    if launcher is None:
        return False

    if _already_skipped_by_login(launcher, index):
        return False

    if not _selected_contains(launcher, index):
        return False

    try:
        if hasattr(self.gate, "account_is_recovering") and self.gate.account_is_recovering(index):
            return True
    except Exception:
        pass

    pending = _safe_pending_list(launcher)
    if index not in pending:
        pending.insert(0, index)

    # Remove stale session data so the incremental starter does not think this
    # account is still alive and skip opening it.
    try:
        session = dict(launcher.active_sessions.get(index) or {})
        pid = session.get("pid")
        if _reason_text(reason) in {"NO_PID", "PID_MISSING"}:
            launcher.active_sessions.pop(index, None)
        elif _reason_text(reason) == "NO_SESSION":
            launcher.active_sessions.pop(index, None)
    except Exception:
        pid = None

    # Keep the post-login runner on the same account. After Login succeeds, this
    # same turn will run Drop/Use/Sash on it instead of jumping past it.
    try:
        selected = list(self.gate.selected_indices())
        if index in selected:
            self.next_position = selected.index(index)
            self.current_index = index
    except Exception:
        pass

    now = time.time()
    cooldown = _float_setting(self, "post_login_open_missing_cooldown_seconds", 8.0, minimum=1.0)
    last_request = 0.0
    try:
        last_request = float(self._post_login_open_requested_at.get(index, 0.0))
    except Exception:
        self._post_login_open_requested_at = {}

    if getattr(launcher, "is_running", False):
        return True

    if now - last_request < cooldown:
        return True

    try:
        self._post_login_open_requested_at[index] = now
    except Exception:
        pass

    try:
        setattr(launcher, "_post_login_manual_start_requested", True)
    except Exception:
        pass

    try:
        launcher.set_row_state(index, "working")
    except Exception:
        pass

    next_text = "?"
    try:
        next_text = str(index + 1)
    except Exception:
        pass

    print(
        "Post-login missing account open requested - "
        f"account={index + 1} - reason={reason} - queued_for_login=True"
    )
    try:
        launcher.set_status(f"الحساب {index + 1}: مفقود - جاري فتحه قبل أوامر الدخول")
    except Exception:
        pass

    try:
        launcher.is_running = True
        launcher.pause_requested = False
        monitor_pause_event = getattr(launcher, "monitor_pause_event", None)
        if monitor_pause_event is not None:
            try:
                monitor_pause_event.clear()
            except Exception:
                pass
        launcher.run_in_thread(launcher.process_accounts)
        return True
    except Exception as error:
        print(
            "Post-login missing account open request failed - "
            f"account={index + 1} - reason={reason} - {error}"
        )
        try:
            launcher.is_running = False
        except Exception:
            pass
        return False


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
    if problem_index is not None and _is_open_on_turn_reason(self, problem_reason):
        if _request_open_account_on_turn(self, int(problem_index), _reason_text(problem_reason)):
            self.problem_key = None
            self.problem_started_at = None
            return

    if problem_index is not None and _is_skippable_reason(self, problem_reason):
        if _advance_from_skipped_account(self, int(problem_index), _reason_text(problem_reason)):
            return

    return _ORIGINAL_TRACK_PROBLEM(self, problem_index, problem_reason)


LoginPriorityGate.all_selected_ready = _all_selected_ready_skip_unavailable
PostLoginCommandRunner.__init__ = _runner_init_with_skip_state
PostLoginCommandRunner._track_problem_or_recover = _track_problem_or_skip_unavailable

print("Post-login skip/open patch active: missing accounts open on turn; bad accounts skip this pass")
