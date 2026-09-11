"""Retryable post-login credential-message guard.

Images are loaded from external assets only. No embedded images.

Handled retry messages:
- Invalid Account ID
- Password length error: "Your password must be 10-14 characters..."

For either message:
- count as one credential retry attempt
- press OK when needed
- wait briefly for the message to clear
- retype username + password
- after 3 total retry-message hits, skip the account in this run
"""

import os
import time
from functools import lru_cache

import cv2

import login_stability_patch
from tasks.memory_reader import ConquerMemoryReader
from tasks.post_login_message_task import PostLoginMessageTask


INVALID_ACCOUNT_ID = login_stability_patch.INVALID_ACCOUNT_ID
PASSWORD_LENGTH_ERROR = "PASSWORD_LENGTH_ERROR"
USER_STOPPED = login_stability_patch.USER_STOPPED

PostLoginMessageTask.PASSWORD_LENGTH_ERROR = PASSWORD_LENGTH_ERROR

RETRY_MESSAGE_THRESHOLD = 0.78
RETRY_MESSAGE_GONE_SECONDS = 0.45
RETRY_MESSAGE_WAIT_TIMEOUT = 6.0

INVALID_ID_TEMPLATE_PATHS = (
    os.path.join("assets", "invalid_account_id.png"),
    os.path.join("assets", "failed_invalid_account_id.png"),
    os.path.join("assets", "invalid_id.png"),
)

PASSWORD_LENGTH_TEMPLATE_PATHS = (
    os.path.join("assets", "password_length_error.png"),
    os.path.join("assets", "password_10_14.png"),
    os.path.join("assets", "password_must_10_14.png"),
    os.path.join("assets", "password_10_to_14.png"),
)

RETRY_MATCH_SCALES = (0.94, 0.97, 1.00, 1.03, 1.06)
RETRY_CREDENTIAL_MESSAGES = {INVALID_ACCOUNT_ID, PASSWORD_LENGTH_ERROR}


@lru_cache(maxsize=32)
def _load_template(path):
    if not os.path.isfile(path):
        return None
    image = cv2.imread(path, cv2.IMREAD_COLOR)
    if image is None:
        print(f"Retry message template load failed: {path}")
        return None
    return image


def _load_templates_bgr(paths, label):
    templates = []
    for path in paths:
        image = _load_template(path)
        if image is not None:
            templates.append((path, image))
    if not templates:
        print(f"Retry message template missing - {label} - put image in assets")
    return templates


def _load_invalid_templates_bgr():
    return _load_templates_bgr(INVALID_ID_TEMPLATE_PATHS, "Invalid Account ID")


def _load_password_length_templates_bgr():
    return _load_templates_bgr(PASSWORD_LENGTH_TEMPLATE_PATHS, "Password length 10-14")


def _best_score(screen, template):
    screen_h, screen_w = screen.shape[:2]
    temp_h, temp_w = template.shape[:2]
    best = 0.0

    for scale in RETRY_MATCH_SCALES:
        width = int(round(temp_w * scale))
        height = int(round(temp_h * scale))
        if width <= 2 or height <= 2 or width > screen_w or height > screen_h:
            continue
        try:
            resized = cv2.resize(template, (width, height), interpolation=cv2.INTER_AREA)
            result = cv2.matchTemplate(screen, resized, cv2.TM_CCOEFF_NORMED)
            _, score, _, _ = cv2.minMaxLoc(result)
            best = max(best, float(score))
        except Exception:
            continue
    return best


def _message_score(post_login_task, message_type):
    screen = post_login_task._load_screen()
    best = 0.0

    if message_type == INVALID_ACCOUNT_ID:
        templates = _load_invalid_templates_bgr()
    elif message_type == PASSWORD_LENGTH_ERROR:
        templates = _load_password_length_templates_bgr()
    else:
        templates = []

    for _, template in templates:
        best = max(best, _best_score(screen, template))
    return best


def _retry_message_visible(post_login_task, message_type):
    if message_type == INVALID_ACCOUNT_ID:
        templates = _load_invalid_templates_bgr()
    elif message_type == PASSWORD_LENGTH_ERROR:
        templates = _load_password_length_templates_bgr()
    else:
        return False

    if not templates:
        return False
    return _message_score(post_login_task, message_type) >= RETRY_MESSAGE_THRESHOLD


def _detect_quiet_with_retry_messages(self):
    screen = self._load_screen()
    best_type = None
    best_value = 0.0

    for _, template in _load_invalid_templates_bgr():
        value = _best_score(screen, template)
        if value > best_value:
            best_value = value
            best_type = INVALID_ACCOUNT_ID

    for _, template in _load_password_length_templates_bgr():
        value = _best_score(screen, template)
        if value > best_value:
            best_value = value
            best_type = PASSWORD_LENGTH_ERROR

    for message_type, path in self.templates.items():
        value, _, _ = self._match_template(screen, path)
        value = float(value or 0.0)
        if value > best_value:
            best_value = value
            best_type = message_type

    if best_type in RETRY_CREDENTIAL_MESSAGES:
        if best_value < RETRY_MESSAGE_THRESHOLD:
            return None
    elif best_value < float(getattr(self, "threshold", 0.82)):
        return None

    if best_type == self.INVALID_ACCOUNT_PASSWORD:
        best_type = self.WRONG_PASSWORD

    print(f"Post login message detected - type={best_type} - score={best_value:.3f}")
    return best_type


def _wait_retry_message_disappear(owner, message_type):
    print(f"{message_type} visible - waiting for message to disappear before retyping")
    start = time.time()
    gone_since = None

    while time.time() - start < RETRY_MESSAGE_WAIT_TIMEOUT:
        if getattr(owner, "pause_requested", False):
            return False

        visible = _retry_message_visible(owner.post_login_task, message_type)
        if not visible:
            if gone_since is None:
                gone_since = time.time()
            if time.time() - gone_since >= RETRY_MESSAGE_GONE_SECONDS:
                print(f"{message_type} disappeared - retyping username/password")
                return True
        else:
            gone_since = None

        time.sleep(0.10)

    print(f"{message_type} did not disappear in time - retyping anyway")
    return True


def _sleep_stop(owner, seconds):
    end = time.time() + max(0.0, float(seconds))
    while time.time() < end:
        if getattr(owner, "pause_requested", False):
            return False
        time.sleep(min(0.10, end - time.time()))
    return True


def _skip_bad_credential_account(owner, conquer_pid, username, account_number, reason):
    print(
        "Retryable credential message repeated 3 times - skipping this account - "
        f"account={account_number} - reason={reason} - username={username!r}"
    )
    try:
        ConquerMemoryReader.terminate_conquer_pid(conquer_pid)
    except Exception:
        pass
    try:
        row_index = account_number - 1
        owner.set_row_state(row_index, "error")
        if getattr(owner, "pending_start_indices", None) and owner.pending_start_indices[0] == row_index:
            owner.pending_start_indices.pop(0)
    except Exception:
        pass


def _handle_retry_message_before_retype(owner, message_type):
    if message_type == PASSWORD_LENGTH_ERROR:
        print("Password length error detected - pressing OK before retyping username/password")
        try:
            owner.post_login_task.press_ok(timeout=3.0)
        except Exception as error:
            print(f"Password length OK press failed: {error}")
        if not _sleep_stop(owner, 0.25):
            return False
        return _wait_retry_message_disappear(owner, message_type)

    if message_type == INVALID_ACCOUNT_ID:
        return _wait_retry_message_disappear(owner, message_type)

    return True


def _retry_credentials_waiting_retry_messages(owner, conquer_pid, username, password, account_number, total_accounts):
    retry_count = 0
    last_retry_type = None

    while retry_count < 3:
        if getattr(owner, "pause_requested", False):
            return USER_STOPPED

        suffix = "" if retry_count == 0 else f" - إعادة {retry_count + 1}/3"
        owner.set_status(f"الحساب {account_number}/{total_accounts}: كتابة اليوزر والباسورد{suffix}")

        if not owner.login_task.start(username=username, password=password, target_pid=conquer_pid):
            return "PAGE_TIMEOUT_RETRY"

        if getattr(owner, "pause_requested", False):
            return USER_STOPPED

        owner.set_status(f"الحساب {account_number}/{total_accounts}: الضغط على Log In")
        if not owner.login_button_task.start(target_pid=conquer_pid):
            return "LOGIN_BUTTON_ERROR"

        if getattr(owner, "pause_requested", False):
            return USER_STOPPED

        message_type = owner.post_login_task.wait_for_message(timeout=6.0)
        if getattr(owner, "pause_requested", False):
            return USER_STOPPED

        if message_type not in RETRY_CREDENTIAL_MESSAGES:
            return message_type

        retry_count += 1
        last_retry_type = message_type
        print(
            "Retryable credential message detected - "
            f"type={message_type} - account={account_number} - attempt={retry_count}/3 - retyping username/password"
        )

        if retry_count >= 3:
            _skip_bad_credential_account(owner, conquer_pid, username, account_number, message_type)
            return "PAGE_TIMEOUT_RETRY"

        if not _handle_retry_message_before_retype(owner, message_type):
            return USER_STOPPED
        if not _sleep_stop(owner, 0.20):
            return USER_STOPPED

    _skip_bad_credential_account(owner, conquer_pid, username, account_number, last_retry_type or "UNKNOWN")
    return "PAGE_TIMEOUT_RETRY"


PostLoginMessageTask.detect = _detect_quiet_with_retry_messages
login_stability_patch._retry_credentials_on_same_page = _retry_credentials_waiting_retry_messages

print("Retry credential messages patch active: Invalid Account ID + password length 10-14 handled with 3-attempt skip")
