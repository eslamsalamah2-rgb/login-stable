"""Invalid Account ID retry guard.

Images are loaded from external assets only:
- assets/invalid_account_id.png
- assets/failed_invalid_account_id.png
- assets/invalid_id.png
"""

import os
import time
from functools import lru_cache

import cv2

import login_stability_patch
from tasks.memory_reader import ConquerMemoryReader
from tasks.post_login_message_task import PostLoginMessageTask


INVALID_ACCOUNT_ID = login_stability_patch.INVALID_ACCOUNT_ID
USER_STOPPED = login_stability_patch.USER_STOPPED
INVALID_ID_THRESHOLD = 0.78
INVALID_ID_GONE_SECONDS = 0.45
INVALID_ID_WAIT_TIMEOUT = 6.0

INVALID_ID_TEMPLATE_PATHS = (
    os.path.join("assets", "invalid_account_id.png"),
    os.path.join("assets", "failed_invalid_account_id.png"),
    os.path.join("assets", "invalid_id.png"),
)

INVALID_MATCH_SCALES = (0.94, 0.97, 1.00, 1.03, 1.06)


@lru_cache(maxsize=16)
def _load_template(path):
    if not os.path.isfile(path):
        return None
    image = cv2.imread(path, cv2.IMREAD_COLOR)
    if image is None:
        print(f"Invalid Account ID template load failed: {path}")
        return None
    return image


def _load_invalid_templates_bgr():
    templates = []
    for path in INVALID_ID_TEMPLATE_PATHS:
        image = _load_template(path)
        if image is not None:
            templates.append((path, image))
    if not templates:
        print("Invalid Account ID template missing - put image at assets\\invalid_account_id.png")
    return templates


def _best_score(screen, template):
    screen_h, screen_w = screen.shape[:2]
    temp_h, temp_w = template.shape[:2]
    best = 0.0

    for scale in INVALID_MATCH_SCALES:
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


def _invalid_id_score(post_login_task):
    screen = post_login_task._load_screen()
    best = 0.0
    for _, template in _load_invalid_templates_bgr():
        best = max(best, _best_score(screen, template))
    return best


def _invalid_id_visible(post_login_task):
    templates = _load_invalid_templates_bgr()
    if not templates:
        return False
    return _invalid_id_score(post_login_task) >= INVALID_ID_THRESHOLD


def _detect_quiet_with_external_invalid(self):
    screen = self._load_screen()
    best_type = None
    best_value = 0.0

    for _, template in _load_invalid_templates_bgr():
        value = _best_score(screen, template)
        if value > best_value:
            best_value = value
            best_type = INVALID_ACCOUNT_ID

    for message_type, path in self.templates.items():
        value, _, _ = self._match_template(screen, path)
        value = float(value or 0.0)
        if value > best_value:
            best_value = value
            best_type = message_type

    if best_type == INVALID_ACCOUNT_ID:
        if best_value < INVALID_ID_THRESHOLD:
            return None
    elif best_value < float(getattr(self, "threshold", 0.82)):
        return None

    if best_type == self.INVALID_ACCOUNT_PASSWORD:
        best_type = self.WRONG_PASSWORD

    print(f"Post login message detected - type={best_type} - score={best_value:.3f}")
    return best_type


def _wait_invalid_id_disappear(owner):
    print("Invalid Account ID visible - waiting for message to disappear before retyping")
    start = time.time()
    gone_since = None

    while time.time() - start < INVALID_ID_WAIT_TIMEOUT:
        if getattr(owner, "pause_requested", False):
            return False

        visible = _invalid_id_visible(owner.post_login_task)
        if not visible:
            if gone_since is None:
                gone_since = time.time()
            if time.time() - gone_since >= INVALID_ID_GONE_SECONDS:
                print("Invalid Account ID disappeared - retyping username/password")
                return True
        else:
            gone_since = None

        time.sleep(0.10)

    print("Invalid Account ID did not disappear in time - retyping anyway")
    return True


def _sleep_stop(owner, seconds):
    end = time.time() + max(0.0, float(seconds))
    while time.time() < end:
        if getattr(owner, "pause_requested", False):
            return False
        time.sleep(min(0.10, end - time.time()))
    return True


def _retry_credentials_waiting_invalid(owner, conquer_pid, username, password, account_number, total_accounts):
    invalid_count = 0

    while invalid_count < 3:
        if getattr(owner, "pause_requested", False):
            return USER_STOPPED

        suffix = "" if invalid_count == 0 else f" - إعادة {invalid_count + 1}/3"
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

        if message_type != INVALID_ACCOUNT_ID:
            return message_type

        invalid_count += 1
        print(
            "Invalid Account ID detected - "
            f"account={account_number} - attempt={invalid_count}/3 - waiting then retyping username/password"
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
                owner.set_row_state(row_index, "error")
                if getattr(owner, "pending_start_indices", None) and owner.pending_start_indices[0] == row_index:
                    owner.pending_start_indices.pop(0)
            except Exception:
                pass
            return "PAGE_TIMEOUT_RETRY"

        if not _wait_invalid_id_disappear(owner):
            return USER_STOPPED
        if not _sleep_stop(owner, 0.20):
            return USER_STOPPED

    return "PAGE_TIMEOUT_RETRY"


PostLoginMessageTask.detect = _detect_quiet_with_external_invalid
login_stability_patch._retry_credentials_on_same_page = _retry_credentials_waiting_invalid

print("Invalid Account ID wait patch active: external image only, wait message hide before retyping")
