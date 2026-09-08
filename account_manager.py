import json
import os


class AccountManager:

    def __init__(self, path="accounts.json"):
        self.path = path

    def load_accounts(self):
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
                character_name = str(
                    item.get("character_name", item.get("name", ""))
                ).strip()

                if username and password:
                    accounts.append({
                        "username": username,
                        "password": password,
                        "character_name": character_name
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

                if not username or not password:
                    continue

                clean_accounts.append({
                    "username": username,
                    "password": password,
                    "character_name": character_name
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
