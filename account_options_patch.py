"""Per-account saved options for post-login modules.

This is a UI/data patch only.  It does not change the stable Login workflow.
Each account row can now save independent module choices:
  - Revive mode: No Rev / Rev / Rev Here
  - Sash flag: saved now for the next stage, but not executed yet

Values are saved into accounts.json so they survive restart.
"""

import json
import os

import customtkinter as ctk

from account_manager import AccountManager
from gui import SimpleLauncher
from selection_launcher import SelectionAwareLauncher


REVIVE_LABEL_TO_MODE = {
    "No Rev": "none",
    "Rev": "revive",
    "Rev Here": "revive_here",
}

REVIVE_MODE_TO_LABEL = {
    "none": "No Rev",
    "rev": "Rev",
    "revive": "Rev",
    "revive_here": "Rev Here",
    "rev_here": "Rev Here",
    "rev and here": "Rev Here",
    "revive and here": "Rev Here",
}

REVIVE_VALUES = ["No Rev", "Rev", "Rev Here"]

_ORIGINAL_CREATE_ACCOUNT_ROW = SelectionAwareLauncher.create_account_row


def _normal_revive_mode(value):
    text = str(value or "").strip().lower().replace("-", "_")
    if text in {"rev", "revive"}:
        return "revive"
    if text in {"rev_here", "revive_here", "rev and here", "revive and here", "rev_and_here", "revive_and_here"}:
        return "revive_here"
    return "none"


def _bool_value(value, default=False):
    if isinstance(value, bool):
        return value
    text = str(value if value is not None else "").strip().lower()
    if text in {"1", "true", "yes", "on", "enabled"}:
        return True
    if text in {"0", "false", "no", "off", "disabled"}:
        return False
    return bool(default)


def _revive_label(value):
    key = str(value or "").strip().lower()
    return REVIVE_MODE_TO_LABEL.get(key, REVIVE_MODE_TO_LABEL.get(_normal_revive_mode(value), "No Rev"))


def _revive_mode_from_row(row):
    try:
        var = row.get("revive_mode_var")
        if var is not None:
            return REVIVE_LABEL_TO_MODE.get(var.get(), _normal_revive_mode(var.get()))
    except Exception:
        pass
    return "none"


def _sash_enabled_from_row(row):
    try:
        var = row.get("sash_enabled_var")
        if var is not None:
            return bool(var.get())
    except Exception:
        pass
    return False


def _load_accounts_with_options(self):
    if not os.path.exists(self.path):
        return []

    try:
        with open(self.path, "r", encoding="utf-8") as file:
            data = json.load(file)

        if not isinstance(data, list):
            return []

        accounts = []
        for item in data:
            if not isinstance(item, dict):
                continue

            username = str(item.get("username", "")).strip()
            password = str(item.get("password", ""))
            character_name = str(item.get("character_name", item.get("name", ""))).strip()
            revive_mode = _normal_revive_mode(item.get("revive_mode", item.get("revive", "none")))
            sash_enabled = _bool_value(item.get("sash_enabled", item.get("sash", False)))

            if username and password:
                accounts.append({
                    "username": username,
                    "password": password,
                    "character_name": character_name,
                    "revive_mode": revive_mode,
                    "sash_enabled": sash_enabled,
                })

        return accounts

    except Exception as error:
        print(f"Failed to load accounts: {error}")
        return []


def _save_accounts_with_options(self, accounts):
    try:
        clean_accounts = []
        for item in accounts:
            if not isinstance(item, dict):
                continue

            username = str(item.get("username", "")).strip()
            password = str(item.get("password", ""))
            character_name = str(item.get("character_name", "")).strip()
            revive_mode = _normal_revive_mode(item.get("revive_mode", item.get("revive", "none")))
            sash_enabled = _bool_value(item.get("sash_enabled", item.get("sash", False)))

            if not username or not password:
                continue

            clean_accounts.append({
                "username": username,
                "password": password,
                "character_name": character_name,
                "revive_mode": revive_mode,
                "sash_enabled": sash_enabled,
            })

        with open(self.path, "w", encoding="utf-8") as file:
            json.dump(clean_accounts, file, ensure_ascii=False, indent=4)

        return True

    except Exception as error:
        print(f"Failed to save accounts: {error}")
        return False


def _create_account_row_with_options(self, account=None):
    account = account or {}
    _ORIGINAL_CREATE_ACCOUNT_ROW(self, account)

    row = self.account_rows[-1]

    revive_var = ctk.StringVar(value=_revive_label(account.get("revive_mode", "none")))
    revive_menu = ctk.CTkOptionMenu(
        row["frame"],
        values=REVIVE_VALUES,
        variable=revive_var,
        width=95,
        height=32,
    )
    revive_menu.grid(row=0, column=7, padx=(4, 4), pady=7)

    sash_var = ctk.BooleanVar(value=_bool_value(account.get("sash_enabled", False)))
    sash_box = ctk.CTkCheckBox(
        row["frame"],
        text="Sash",
        width=62,
        variable=sash_var,
        onvalue=True,
        offvalue=False,
    )
    sash_box.grid(row=0, column=8, padx=(2, 6), pady=7)

    row["revive_mode_var"] = revive_var
    row["revive_mode_menu"] = revive_menu
    row["sash_enabled_var"] = sash_var
    row["sash_enabled_box"] = sash_box


def _collect_accounts_with_options(self, include_empty=False):
    accounts = []

    for row in self.account_rows:
        username = row["username"].get().strip()
        password = row["password"].get()

        row["name"].configure(state="normal")
        character_name = row["name"].get().strip()
        row["name"].configure(state="disabled")

        if include_empty or (username and password):
            accounts.append({
                "username": username,
                "password": password,
                "character_name": character_name,
                "revive_mode": _revive_mode_from_row(row),
                "sash_enabled": _sash_enabled_from_row(row),
            })

    return accounts


AccountManager.load_accounts = _load_accounts_with_options
AccountManager.save_accounts = _save_accounts_with_options
SimpleLauncher.collect_accounts_from_ui = _collect_accounts_with_options
SelectionAwareLauncher.collect_accounts_from_ui = _collect_accounts_with_options
SelectionAwareLauncher.create_account_row = _create_account_row_with_options

print("Account options patch active: per-account Rev/Rev Here + Sash flag saved")
