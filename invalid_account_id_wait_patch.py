"""Invalid Account ID retry guard.

This file keeps the stable Login flow separated from post-login Drop changes.
It only adds one Login-side recovery rule:
- detect "Failed to login: Invalid Account ID" from the user's crop
- wait until that temporary message disappears
- retype username + password from scratch
- after 3 failures, skip that row instead of looping the same account forever
"""

import base64
import os
import time
from functools import lru_cache
from io import BytesIO

import cv2
import numpy as np
from PIL import Image

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

INVALID_ID_BASE64 = (
    "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"
)


@lru_cache(maxsize=1)
def _embedded_invalid_template_bgr():
    raw = base64.b64decode(INVALID_ID_BASE64)
    image = Image.open(BytesIO(raw)).convert("RGB")
    rgb = np.array(image)
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)


def _load_invalid_templates_bgr():
    templates = []
    for path in INVALID_ID_TEMPLATE_PATHS:
        if not os.path.isfile(path):
            continue
        image = cv2.imread(path, cv2.IMREAD_COLOR)
        if image is not None:
            templates.append((path, image))
    templates.append(("embedded:invalid_account_id", _embedded_invalid_template_bgr()))
    return templates


def _best_score(screen, template):
    screen_h, screen_w = screen.shape[:2]
    temp_h, temp_w = template.shape[:2]
    best = 0.0

    for scale in (0.94, 0.97, 1.00, 1.03, 1.06):
        width = int(round(temp_w * scale))
        height = int(round(temp_h * scale))
        if width <= 2 or height <= 2 or width > screen_w or height > screen_h:
            continue
        resized = cv2.resize(template, (width, height), interpolation=cv2.INTER_AREA)
        try:
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
    return _invalid_id_score(post_login_task) >= INVALID_ID_THRESHOLD


def _detect_quiet_with_embedded_invalid(self):
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

    if best_value < float(getattr(self, "threshold", 0.82)) and best_type != INVALID_ACCOUNT_ID:
        return None
    if best_type == INVALID_ACCOUNT_ID and best_value < INVALID_ID_THRESHOLD:
        return None

    if best_type == self.INVALID_ACCOUNT_PASSWORD:
        best_type = self.WRONG_PASSWORD

    print(f"Post login message detected - type={best_type} - score={best_value:.3f}")
    return best_type


def _wait_invalid_id_disappear(owner):
    print("Invalid Account ID visible - waiting for message to disappear before retyping")
    start = time.time()
    last_seen = time.time()

    while time.time() - start < INVALID_ID_WAIT_TIMEOUT:
        if login_stability_patch._stop_requested(owner):
            return False

        if _invalid_id_visible(owner.post_login_task):
            last_seen = time.time()
        elif time.time() - last_seen >= INVALID_ID_GONE_SECONDS:
            print("Invalid Account ID disappeared - retrying username/password")
            return True

        time.sleep(0.10)

    print("Invalid Account ID wait timeout - retrying anyway")
    return True


def _retry_credentials_waiting_for_invalid_to_hide(self, conquer_pid, username, password, account_number, total_accounts):
    invalid_count = 0

    while invalid_count < 3:
        if login_stability_patch._stop_requested(self):
            return USER_STOPPED

        suffix = "" if invalid_count == 0 else f" - إعادة {invalid_count + 1}/3"
        self.set_status(f"الحساب {account_number}/{total_accounts}: كتابة اليوزر والباسورد{suffix}")

        if not self.login_task.start(username=username, password=password, target_pid=conquer_pid):
            return "PAGE_TIMEOUT_RETRY"

        if login_stability_patch._stop_requested(self):
            return USER_STOPPED

        self.set_status(f"الحساب {account_number}/{total_accounts}: الضغط على Log In")
        if not self.login_button_task.start(target_pid=conquer_pid):
            return "LOGIN_BUTTON_ERROR"

        if login_stability_patch._stop_requested(self):
            return USER_STOPPED

        message_type = self.post_login_task.wait_for_message(timeout=6.0)
        if login_stability_patch._stop_requested(self):
            return USER_STOPPED

        if message_type != INVALID_ACCOUNT_ID:
            return message_type

        invalid_count += 1
        print(
            "Invalid Account ID detected - "
            f"account={account_number} - attempt={invalid_count}/3 - will retype username/password"
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
                if getattr(self, "pending_start_indices", None) and self.pending_start_indices[0] == row_index:
                    self.pending_start_indices.pop(0)
            except Exception:
                pass
            return "PAGE_TIMEOUT_RETRY"

        if not _wait_invalid_id_disappear(self):
            return USER_STOPPED

    return "PAGE_TIMEOUT_RETRY"


PostLoginMessageTask.detect = _detect_quiet_with_embedded_invalid
login_stability_patch._retry_credentials_on_same_page = _retry_credentials_waiting_for_invalid_to_hide

print("Invalid Account ID wait patch active: wait message hide before retyping")
