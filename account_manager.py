import json
import os


class AccountManager:

    def __init__(self, path="accounts.json"):
        self.path = path

    def _normal_revive_mode(self, value):
        text = str(value or "").strip().lower().replace("-", "_")
        if text in {"rev", "revive"}:
            return "revive"
        if text in {"rev_here", "revive_here", "rev and here", "revive and here", "rev_and_here", "revive_and_here"}:
            return "revive_here"
        return "none"

    def _bool_value(self, value, default=False):
        if isinstance(value, bool):
            return value
        text = str(value if value is not None else "").strip().lower()
        if text in {"1", "true", "yes", "on", "enabled"}:
            return True
        if text in {"0", "false", "no", "off", "disabled"}:
            return False
        return bool(default)

    def load_accounts(self):

        if not os.path.exists(self.path):
            return []

        try:
            with open(
                self.path,
                "r",
                encoding="utf-8"
            ) as file:
                data = json.load(file)

            if not isinstance(data, list):
                return []

            accounts = []

            for item in data:
                if not isinstance(item, dict):
                    continue

                username = str(item.get("username", "")).strip()
                password = str(item.get("password", ""))
                character_name = str(
                    item.get("character_name", item.get("name", ""))
                ).strip()
                revive_mode = self._normal_revive_mode(
                    item.get("revive_mode", item.get("revive", "none"))
                )
                sash_enabled = self._bool_value(
                    item.get("sash_enabled", item.get("sash", False))
                )

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

    def save_accounts(self, accounts):
        try:
            clean_accounts = []

            for item in accounts:
                if not isinstance(item, dict):
                    continue

                username = str(item.get("username", "")).strip()
                password = str(item.get("password", ""))
                character_name = str(
                    item.get("character_name", "")
                ).strip()
                revive_mode = self._normal_revive_mode(
                    item.get("revive_mode", item.get("revive", "none"))
                )
                sash_enabled = self._bool_value(
                    item.get("sash_enabled", item.get("sash", False))
                )

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
                json.dump(
                    clean_accounts,
                    file,
                    ensure_ascii=False,
                    indent=4
                )

            return True

        except Exception as error:
            print(f"Failed to save accounts: {error}")
            return False
