"""Login-side stability patch.

Keeps Login independent from fast Drop changes:
- key 9 stops Login/Drop immediately
- detects Invalid Account ID from assets/invalid_account_id.png
- retypes username+password up to 3 times, then skips that row
- skips duplicate selected usernames
- stops low-score post-login message spam during Login
"""

import os
import time

from gui import SimpleLauncher
from maintenance_launcher import MaintenanceAwareLauncher
from selection_launcher import SelectionAwareLauncher
from tasks.memory_reader import ConquerMemoryReader
from tasks.post_login_message_task import PostLoginMessageTask

INVALID_ACCOUNT_ID = "INVALID_ACCOUNT_ID"
USER_STOPPED = "USER_STOPPED"
INVALID_ID_TEMPLATE_PATHS = (
    os.path.join("assets", "invalid_account_id.png"),
    os.path.join("assets", "failed_invalid_account_id.png"),
    os.path.join("assets", "invalid_id.png"),
)

PostLoginMessageTask.INVALID_ACCOUNT_ID = INVALID_ACCOUNT_ID


def _detect_quiet(self):
    screen = self._load_screen()
    best_type = None
    best_value = 0.0

    for path in INVALID_ID_TEMPLATE_PATHS:
        value, _, _ = self._match_template(screen, path)
        value = float(value or 0.0)
        if value > best_value:
            best_value = value
            best_type = INVALID_ACCOUNT_ID

    for message_type, path in self.templates.items():
        value, _, _ = self._match_template(screen, path)
        value = float(value or 0.0)
        if value > best_value:
            best_value = value
            best_type = message_type

    if best_value < float(getattr(self, "threshold", 0.82)):
        return None

    if best_type == self.INVALID_ACCOUNT_PASSWORD:
        best_type = self.WRONG_PASSWORD

    print(f"Post login message detected - type={best_type} - score={best_value:.3f}")
    return best_type


def _server_crowded_quiet(self):
    screen = self._load_screen()
    value, _, _ = self._match_template(screen, self.templates[self.SERVER_CROWDED])
    value = float(value or 0.0)
    if value >= float(getattr(self, "threshold", 0.82)):
        print(f"Post login SERVER_CROWDED detected - score={value:.3f}")
        return True
    return False


PostLoginMessageTask.detect = _detect_quiet
PostLoginMessageTask.is_server_crowded = _server_crowded_quiet


def _global_stop(self):
    self.pause_requested = True
    try:
        runner = getattr(self, "post_login_runner", None)
        if runner is not None:
            runner.request_stop("global_stop_9")
    except Exception:
        pass

    for name in ("start_game_task", "login_task", "login_button_task", "post_login_task"):
        try:
            task = getattr(self, name, None)
            if task is not None and hasattr(task, "stop"):
                task.stop()
        except Exception:
            pass

    self.set_status("تم طلب الإيقاف الفوري بزر 9")
    print("Global stop requested - key 9")


SimpleLauncher.pause_processing = _global_stop
SelectionAwareLauncher.pause_processing = _global_stop


def _selected_unique(self):
    selected = []
    seen = set()
    for index in range(len(self.account_rows)):
        try:
            if not self._is_account_selected(index):
                continue
            username = self.account_rows[index]["username"].get().strip()
        except Exception:
            username = ""
        key = username.lower()
        if key and key in seen:
            print(f"Duplicate username skipped - row={index + 1} - username={username!r}")
            try:
                self.set_row_state(index, "error")
            except Exception:
                pass
            continue
        if key:
            seen.add(key)
        selected.append(index)
    return selected


SelectionAwareLauncher._selected_indices = _selected_unique


def _sleep_stop(owner, seconds):
    end = time.time() + max(0.0, float(seconds))
    while time.time() < end:
        if getattr(owner, "pause_requested", False):
            return False
        time.sleep(min(0.10, end - time.time()))
    return True


def _stop_requested(owner):
    return bool(getattr(owner, "pause_requested", False))


def _retry_credentials_on_same_page(self, conquer_pid, username, password, account_number, total_accounts):
    """Return final message_type, PAGE_TIMEOUT_RETRY, or USER_STOPPED."""
    invalid_count = 0

    while invalid_count < 3:
        if _stop_requested(self):
            return USER_STOPPED

        suffix = "" if invalid_count == 0 else f" - إعادة {invalid_count + 1}/3"
        self.set_status(f"الحساب {account_number}/{total_accounts}: كتابة اليوزر والباسورد{suffix}")

        if not self.login_task.start(username=username, password=password, target_pid=conquer_pid):
            return "PAGE_TIMEOUT_RETRY"

        if _stop_requested(self):
            return USER_STOPPED

        self.set_status(f"الحساب {account_number}/{total_accounts}: الضغط على Log In")
        if not self.login_button_task.start(target_pid=conquer_pid):
            return "LOGIN_BUTTON_ERROR"

        if _stop_requested(self):
            return USER_STOPPED

        message_type = self.post_login_task.wait_for_message(timeout=6.0)
        if _stop_requested(self):
            return USER_STOPPED

        if message_type != INVALID_ACCOUNT_ID:
            return message_type

        invalid_count += 1
        print(
            "Invalid Account ID detected - "
            f"account={account_number} - attempt={invalid_count}/3 - retyping username/password"
        )

        if invalid_count >= 3:
            print(
                "Invalid Account ID repeated 3 times - skipping this account - "
                f"account={account_number} - username={username!r}"
            )
            try:
                ConquerMemoryReader.terminate_conquer_pid(conquer_pid)
            except Exception:
                pass
            try:
                row_index = account_number - 1
                self.set_row_state(row_index, "error")
                self.app.after(300, lambda idx=row_index: self.set_row_state(idx, "error"))
                if getattr(self, "pending_start_indices", None) and self.pending_start_indices[0] == row_index:
                    self.pending_start_indices.pop(0)
            except Exception:
                pass
            return "PAGE_TIMEOUT_RETRY"

        if not _sleep_stop(self, 0.35):
            return USER_STOPPED

    return "PAGE_TIMEOUT_RETRY"


def _run_account_with_invalid_retry(self, path, username, password, account_number, total_accounts):
    """Mostly the normal login flow, with a front retry loop for Invalid Account ID."""
    if _stop_requested(self):
        return USER_STOPPED, None

    conquer_pid, launch_result = self._open_conquer_pid_with_retries(
        path=path,
        account_number=account_number,
        total_accounts=total_accounts,
    )
    if _stop_requested(self):
        return USER_STOPPED, None
    if conquer_pid is None:
        return launch_result, None

    page_started_at = time.time()
    try:
        memory_reader = ConquerMemoryReader(conquer_pid)
    except Exception as error:
        print(f"Could not open Conquer PID {conquer_pid}: {error}")
        return "MEMORY_OPEN_ERROR", None

    initial_name = memory_reader.read_name() or ""
    initial_state = memory_reader.read_state()
    print(f"Conquer PID {conquer_pid} initial name: {initial_name!r}")
    print(f"Conquer PID {conquer_pid} initial state: {initial_state} ({ConquerMemoryReader.state_name(initial_state)})")

    message_type = _retry_credentials_on_same_page(
        self, conquer_pid, username, password, account_number, total_accounts
    )

    if message_type == USER_STOPPED:
        memory_reader.close()
        return USER_STOPPED, None
    if message_type == "PAGE_TIMEOUT_RETRY":
        memory_reader.close()
        try:
            ConquerMemoryReader.terminate_conquer_pid(conquer_pid)
        except Exception:
            pass
        return "PAGE_TIMEOUT_RETRY", None
    if message_type == "LOGIN_BUTTON_ERROR":
        memory_reader.close()
        return "LOGIN_BUTTON_ERROR", None

    if message_type == PostLoginMessageTask.SERVER_MAINTENANCE:
        return self._maintenance_result(memory_reader)
    if message_type == PostLoginMessageTask.CLIENT_UPDATE:
        return self._client_update_result(memory_reader)

    if message_type == PostLoginMessageTask.DISCONNECTED:
        self.post_login_task.press_ok()
        if not _sleep_stop(self, 0.7):
            memory_reader.close()
            return USER_STOPPED, None
        if not self.login_button_task.start(target_pid=conquer_pid):
            memory_reader.close()
            return "LOGIN_BUTTON_ERROR", None
        message_type = self.post_login_task.wait_for_message(timeout=6.0)
        if message_type == PostLoginMessageTask.SERVER_MAINTENANCE:
            return self._maintenance_result(memory_reader)
        if message_type == PostLoginMessageTask.CLIENT_UPDATE:
            return self._client_update_result(memory_reader)

    if message_type == PostLoginMessageTask.WRONG_PASSWORD:
        self.post_login_task.press_ok()
        if not _sleep_stop(self, 0.5):
            memory_reader.close()
            return USER_STOPPED, None
        if not self.login_task.rewrite_password(password, target_pid=conquer_pid):
            memory_reader.close()
            return "PASSWORD_RETRY_ERROR", None
        if not self.login_button_task.start(target_pid=conquer_pid):
            memory_reader.close()
            return "LOGIN_BUTTON_ERROR", None
        second_message = self.post_login_task.wait_for_message(timeout=6.0)
        if second_message == PostLoginMessageTask.WRONG_PASSWORD:
            self.post_login_task.press_ok()
            memory_reader.close()
            return self._restart_all_accounts_after_password_error(
                account_number,
                "NORMAL_LOGIN_WRONG_PASSWORD_AFTER_REWRITE",
            )

    self.set_status(f"الحساب {account_number}/{total_accounts}: جاري قراءة اسم الشخصية من Memory...")
    page_name = None
    check = 0

    while time.time() - page_started_at < 90.0:
        if _stop_requested(self):
            memory_reader.close()
            return USER_STOPPED, None
        check += 1
        current_name = memory_reader.read_name() or ""
        print(f"Memory name check #{check} - PID {conquer_pid} - Value: {current_name!r}")
        if current_name and current_name != initial_name:
            page_name = current_name
            break
        if self.post_login_task.is_server_crowded():
            if not _sleep_stop(self, 10.0):
                memory_reader.close()
                return USER_STOPPED, None
            if not self.login_button_task.start(target_pid=conquer_pid):
                memory_reader.close()
                return "LOGIN_BUTTON_ERROR"
            continue
        remaining = max(0, int(90 - (time.time() - page_started_at)))
        print(f"Name not ready yet. Page timeout in {remaining} seconds...")
        if not _sleep_stop(self, 2.0):
            memory_reader.close()
            return USER_STOPPED, None

    if not page_name:
        memory_reader.close()
        ConquerMemoryReader.terminate_conquer_pid(conquer_pid)
        _sleep_stop(self, 1.0)
        return "PAGE_TIMEOUT_RETRY", None

    final_state = memory_reader.read_state()
    print(f"Conquer PID {conquer_pid} state after login: {final_state} ({ConquerMemoryReader.state_name(final_state)})")
    memory_reader.close()
    print(f"Account {account_number} ready - PID {conquer_pid} - Name: {page_name}")

    self.active_sessions[account_number - 1] = {
        "pid": conquer_pid,
        "username": username,
        "password": password,
        "page_name": page_name,
    }
    return "SUCCESS", page_name


MaintenanceAwareLauncher.run_account = _run_account_with_invalid_retry

print("Login stability patch active: global stop + Invalid Account ID retry + duplicate username skip")
