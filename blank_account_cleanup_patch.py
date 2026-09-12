"""Remove blank account rows before Start/Save and ignore them in selection.

User rule:
- A row without Username or Password is not a real account.
- On Start, blank rows should be removed from the UI and not saved.
- Character Name alone must not create a selectable/runnable account.

This patch is UI/queue hygiene only. It does not change Login typing,
Recovery, Health, Drop, Use, or Sash internals.
"""

from selection_launcher import SelectionAwareLauncher


_ORIGINAL_SELECTED_INDICES = SelectionAwareLauncher._selected_indices
_ORIGINAL_START_FROM_BEGINNING = SelectionAwareLauncher.start_from_beginning
_ORIGINAL_RESUME_PROCESSING = SelectionAwareLauncher.resume_processing
_ORIGINAL_SAVE_ACCOUNTS_FROM_UI = SelectionAwareLauncher.save_accounts_from_ui

_REVIVE_LABEL_TO_MODE = {
    "No Rev": "none",
    "Rev": "revive",
    "Rev Here": "revive_here",
}


def _text(value):
    return str(value if value is not None else "")


def _row_username(row):
    try:
        return _text(row["username"].get()).strip()
    except Exception:
        return ""


def _row_password(row):
    try:
        return _text(row["password"].get())
    except Exception:
        return ""


def _row_has_login(row):
    return bool(_row_username(row)) and bool(_row_password(row).strip())


def _row_character_name(row):
    try:
        row["name"].configure(state="normal")
        value = _text(row["name"].get()).strip()
        row["name"].configure(state="disabled")
        return value
    except Exception:
        return ""


def _row_revive_mode(row):
    try:
        var = row.get("revive_mode_var")
        if var is not None:
            return _REVIVE_LABEL_TO_MODE.get(_text(var.get()).strip(), "revive")
    except Exception:
        pass
    return "revive"


def _row_sash_enabled(row):
    try:
        var = row.get("sash_enabled_var")
        if var is not None:
            return bool(var.get())
    except Exception:
        pass
    return False


def _collect_valid_accounts_and_mapping(launcher):
    accounts = []
    old_to_new = {}
    removed_indices = []

    for old_index, row in enumerate(getattr(launcher, "account_rows", []) or []):
        if not _row_has_login(row):
            removed_indices.append(old_index)
            continue

        old_to_new[old_index] = len(accounts)
        accounts.append({
            "username": _row_username(row),
            "password": _row_password(row),
            "character_name": _row_character_name(row),
            "revive_mode": _row_revive_mode(row),
            "sash_enabled": _row_sash_enabled(row),
        })

    return accounts, old_to_new, removed_indices


def _remap_active_sessions(launcher, old_to_new):
    old_sessions = dict(getattr(launcher, "active_sessions", {}) or {})
    new_sessions = {}
    for old_index, session in old_sessions.items():
        if old_index in old_to_new:
            new_sessions[old_to_new[old_index]] = session
    launcher.active_sessions = new_sessions
    return new_sessions


def _remap_list(values, old_to_new):
    result = []
    for value in list(values or []):
        if value in old_to_new:
            new_value = old_to_new[value]
            if new_value not in result:
                result.append(new_value)
    return result


def _remap_set(values, old_to_new):
    return {old_to_new[value] for value in set(values or set()) if value in old_to_new}


def _remap_dict_keys(values, old_to_new):
    return {old_to_new[key]: val for key, val in dict(values or {}).items() if key in old_to_new}


def _restore_lamps_for_live_sessions(launcher, sessions):
    for index, session in dict(sessions or {}).items():
        try:
            page_name = ""
            if isinstance(session, dict):
                page_name = session.get("page_name", "") or session.get("character_name", "") or ""
            launcher.set_row_state(index, "success", page_name or None)
        except Exception:
            pass


def _cleanup_blank_account_rows(launcher, reason="start"):
    accounts, old_to_new, removed_indices = _collect_valid_accounts_and_mapping(launcher)
    if not removed_indices:
        return True

    print(
        "Blank account rows removed - "
        f"reason={reason} - rows={[i + 1 for i in removed_indices]}"
    )

    sessions = _remap_active_sessions(launcher, old_to_new)

    try:
        launcher.pending_start_indices = _remap_list(getattr(launcher, "pending_start_indices", []), old_to_new)
    except Exception:
        pass

    try:
        launcher.skipped_start_indices = _remap_set(getattr(launcher, "skipped_start_indices", set()), old_to_new)
    except Exception:
        pass

    try:
        launcher.start_retry_counts = _remap_dict_keys(getattr(launcher, "start_retry_counts", {}), old_to_new)
    except Exception:
        pass

    try:
        with launcher.recovering_accounts_lock:
            launcher.recovering_accounts = _remap_set(getattr(launcher, "recovering_accounts", set()), old_to_new)
    except Exception:
        pass

    if accounts:
        launcher.accounts_data = accounts
        launcher.rebuild_account_rows(accounts)
        try:
            launcher.account_manager.save_accounts(accounts)
        except Exception as error:
            print(f"Blank account cleanup save warning: {error}")
        _restore_lamps_for_live_sessions(launcher, sessions)
        try:
            launcher.set_status(f"تم حذف {len(removed_indices)} خانة فاضية قبل التشغيل")
        except Exception:
            pass
        return True

    # No valid accounts left. Keep one empty row for editing, but save no account.
    launcher.accounts_data = []
    launcher.active_sessions = {}
    try:
        launcher.pending_start_indices = []
    except Exception:
        pass
    try:
        launcher.rebuild_account_rows([{"username": "", "password": "", "character_name": "", "revive_mode": "revive", "sash_enabled": False}])
    except Exception:
        pass
    try:
        launcher.account_manager.save_accounts([])
    except Exception:
        pass
    try:
        launcher.set_status("مفيش حساب صالح للتشغيل: لازم Username و Password")
    except Exception:
        pass
    return False


def _selected_indices_ignore_blank_rows(self):
    selected = []
    try:
        base_selected = list(_ORIGINAL_SELECTED_INDICES(self))
    except Exception:
        base_selected = list(range(len(getattr(self, "account_rows", []) or [])))

    for index in base_selected:
        try:
            row = self.account_rows[index]
        except Exception:
            continue
        if _row_has_login(row):
            selected.append(index)
    return selected


def _start_from_beginning_cleanup_blank(self):
    if getattr(self, "is_running", False):
        return _ORIGINAL_START_FROM_BEGINNING(self)
    if not _cleanup_blank_account_rows(self, "start_from_beginning"):
        return
    return _ORIGINAL_START_FROM_BEGINNING(self)


def _resume_processing_cleanup_blank(self):
    if getattr(self, "is_running", False):
        return _ORIGINAL_RESUME_PROCESSING(self)
    if not _cleanup_blank_account_rows(self, "resume_or_top_start"):
        return
    return _ORIGINAL_RESUME_PROCESSING(self)


def _save_accounts_cleanup_blank(self):
    if getattr(self, "is_running", False):
        return _ORIGINAL_SAVE_ACCOUNTS_FROM_UI(self)
    if not _cleanup_blank_account_rows(self, "save_accounts"):
        return False
    return _ORIGINAL_SAVE_ACCOUNTS_FROM_UI(self)


SelectionAwareLauncher._selected_indices = _selected_indices_ignore_blank_rows
SelectionAwareLauncher.start_from_beginning = _start_from_beginning_cleanup_blank
SelectionAwareLauncher.resume_processing = _resume_processing_cleanup_blank
SelectionAwareLauncher.save_accounts_from_ui = _save_accounts_cleanup_blank

print("Blank account cleanup patch active: rows without Username+Password are removed on Start/Save")
