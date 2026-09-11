import os
import time
from dataclasses import dataclass
from functools import lru_cache

import cv2
import numpy as np
import pydirectinput
import win32api
import win32gui

from tasks.post_login_modules.window_capture import capture_pid_window


REVIVE_MODE_NONE = "none"
REVIVE_MODE_REVIVE = "revive"
REVIVE_MODE_REVIVE_HERE = "revive_here"

REVIVE_TEMPLATE_PATHS = (
    os.path.join("assets", "Revive.png"),
    os.path.join("assets", "revive.png"),
    os.path.join("assets", "revive_button.png"),
)

REVIVE_MATCH_THRESHOLD = 0.80
REVIVE_MATCH_SCALES = (0.94, 0.97, 1.00, 1.03, 1.06)
REVIVE_HERE_OFFSET_X = 55
REVIVE_AFTER_CLICK_DELAY = 0.35


@dataclass
class ReviveMatch:
    score: float
    box: tuple[int, int, int, int]
    center_window: tuple[int, int]
    center_screen: tuple[int, int]
    source: str


def _normal_mode(value):
    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if text in {"rev", "revive"}:
        return REVIVE_MODE_REVIVE
    if text in {"rev_here", "revive_here", "rev_and_here", "revive_and_here", "here"}:
        return REVIVE_MODE_REVIVE_HERE
    return REVIVE_MODE_NONE


@lru_cache(maxsize=16)
def _load_template_file(path):
    if not os.path.isfile(path):
        return None
    image = cv2.imread(path, cv2.IMREAD_COLOR)
    if image is None:
        print(f"Revive template load failed: {path}")
        return None
    return image


def load_revive_templates():
    templates = []
    for path in REVIVE_TEMPLATE_PATHS:
        image = _load_template_file(path)
        if image is not None:
            templates.append((path, image))
    if not templates:
        print("Revive template missing - put image at assets\\Revive.png or assets\\revive.png")
    return templates


def _pil_to_bgr(image):
    rgb = np.array(image.convert("RGB"))
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)


def _best_template_match(image, threshold=REVIVE_MATCH_THRESHOLD):
    source = _pil_to_bgr(image)
    source_gray = cv2.cvtColor(source, cv2.COLOR_BGR2GRAY)
    src_h, src_w = source.shape[:2]
    best = None

    for source_name, template in load_revive_templates():
        temp_h, temp_w = template.shape[:2]
        for scale in REVIVE_MATCH_SCALES:
            width = int(round(temp_w * float(scale)))
            height = int(round(temp_h * float(scale)))
            if width < 8 or height < 8 or width > src_w or height > src_h:
                continue
            try:
                resized = cv2.resize(template, (width, height), interpolation=cv2.INTER_AREA)
                resized_gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
                color_result = cv2.matchTemplate(source, resized, cv2.TM_CCOEFF_NORMED)
                _, color_score, _, color_loc = cv2.minMaxLoc(color_result)
                gray_result = cv2.matchTemplate(source_gray, resized_gray, cv2.TM_CCOEFF_NORMED)
                _, gray_score, _, gray_loc = cv2.minMaxLoc(gray_result)
                loc_distance = abs(int(color_loc[0]) - int(gray_loc[0])) + abs(int(color_loc[1]) - int(gray_loc[1]))
                score = (float(color_score) + float(gray_score)) / 2.0
                if loc_distance > 8:
                    score -= 0.06
                candidate = (score, int(color_loc[0]), int(color_loc[1]), width, height, source_name)
                if best is None or candidate[0] > best[0]:
                    best = candidate
            except Exception:
                continue

    if best is None:
        return None

    score, x, y, width, height, source_name = best
    if score < float(threshold):
        print(f"Revive not found - best={score:.3f} threshold={float(threshold):.3f}")
        return None
    return score, x, y, width, height, source_name


class ReviveFirstModule:
    """First post-login account action. Uses external asset images only."""

    name = "revive_first"
    setting_key = "enable_revive_first"

    def __init__(self, launcher):
        self.launcher = launcher

    def _setting(self, key, default=None):
        if hasattr(self.launcher, "get_runtime_setting"):
            try:
                return self.launcher.get_runtime_setting(key, default)
            except Exception:
                return default
        return default

    def enabled(self):
        value = self._setting(self.setting_key, True)
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"1", "true", "yes", "on", "enabled"}

    def _stop_requested(self):
        try:
            event = getattr(self.launcher, "post_login_stop_event", None)
            if event is not None and event.is_set():
                return True
        except Exception:
            pass
        return bool(getattr(self.launcher, "pause_requested", False))

    def _account_mode(self, account_index, session):
        if isinstance(session, dict):
            mode = _normal_mode(session.get("revive_mode"))
            if mode != REVIVE_MODE_NONE:
                return mode
        try:
            accounts = getattr(self.launcher, "accounts_data", [])
            if 0 <= account_index < len(accounts):
                mode = _normal_mode(accounts[account_index].get("revive_mode"))
                if mode != REVIVE_MODE_NONE:
                    return mode
        except Exception:
            pass
        try:
            row = self.launcher.account_rows[account_index]
            var = row.get("revive_mode_var")
            if var is not None:
                return _normal_mode(var.get())
        except Exception:
            pass
        return REVIVE_MODE_NONE

    def _match_revive(self, image, hwnd):
        try:
            threshold = float(self._setting("revive_match_threshold", REVIVE_MATCH_THRESHOLD))
        except Exception:
            threshold = REVIVE_MATCH_THRESHOLD

        raw = _best_template_match(image, threshold=threshold)
        if raw is None:
            return None

        score, x, y, width, height, source_name = raw
        try:
            left, top, _, _ = win32gui.GetWindowRect(hwnd)
        except Exception:
            left, top = 0, 0

        center_window = (int(x + width / 2), int(y + height / 2))
        center_screen = (int(left + center_window[0]), int(top + center_window[1]))
        return ReviveMatch(
            score=float(score),
            box=(int(x), int(y), int(x + width), int(y + height)),
            center_window=center_window,
            center_screen=center_screen,
            source=source_name,
        )

    def _click(self, xy):
        if self._stop_requested():
            return False
        try:
            win32api.SetCursorPos((int(xy[0]), int(xy[1])))
        except Exception:
            pydirectinput.moveTo(int(xy[0]), int(xy[1]), duration=0)
        if self._stop_requested():
            return False
        pydirectinput.click()
        return True

    def run(self, account_index, session):
        if not self.enabled():
            return "SKIPPED"

        mode = self._account_mode(account_index, session or {})
        if mode == REVIVE_MODE_NONE:
            print(f"Revive first skipped - account={account_index + 1} - mode=none")
            return "OK"

        if self._stop_requested():
            return "STOP_REQUESTED"

        pid = (session or {}).get("pid")
        if not pid:
            return "REVIVE_NO_PID"

        image, hwnd = capture_pid_window(pid)
        if image is None or not hwnd:
            return "REVIVE_CAPTURE_FAILED"

        match = self._match_revive(image, hwnd)
        if match is None:
            print(f"Revive first OK - account={account_index + 1} - mode={mode} - revive_not_visible")
            return "OK"

        click_xy = match.center_screen
        if mode == REVIVE_MODE_REVIVE_HERE:
            click_xy = (int(match.center_screen[0] + REVIVE_HERE_OFFSET_X), int(match.center_screen[1]))

        print(
            "Revive first executing - "
            f"account={account_index + 1} - mode={mode} - "
            f"score={match.score:.3f} - revive_xy={match.center_screen} - "
            f"click_xy={click_xy} - source={match.source}"
        )

        if not self._click(click_xy):
            return "STOP_REQUESTED"

        try:
            delay = float(self._setting("revive_after_click_delay", REVIVE_AFTER_CLICK_DELAY))
        except Exception:
            delay = REVIVE_AFTER_CLICK_DELAY

        end = time.time() + max(0.0, delay)
        while time.time() < end:
            if self._stop_requested():
                return "STOP_REQUESTED"
            time.sleep(min(0.05, end - time.time()))

        print(f"Revive first OK - account={account_index + 1} - mode={mode}")
        return "OK"
