import os
import time
from dataclasses import dataclass

import cv2
import numpy as np
import pydirectinput
import win32gui
import win32process
from PIL import Image

from tasks.post_login_modules.window_capture import capture_window


DEFAULT_YES_TEMPLATE_PATHS = (
    os.path.join("assets", "drop_confirm_yes.png"),
    os.path.join("assets", "yes.png"),
    os.path.join("assets", "drop_yes.png"),
)

CONFIRM_MATCH_SCALES = (0.90, 0.95, 1.00, 1.05, 1.10)


@dataclass
class DropConfirmMatch:
    hwnd: int
    score: float
    template_path: str
    center_screen: tuple[int, int]
    center_window: tuple[int, int]


def _template_paths(paths_text=None):
    if paths_text:
        paths = []
        for part in str(paths_text).replace(";", ",").split(","):
            text = part.strip().strip('"')
            if text:
                paths.append(text)
        if paths:
            return tuple(paths)
    return DEFAULT_YES_TEMPLATE_PATHS


def existing_yes_templates(paths_text=None):
    return [path for path in _template_paths(paths_text) if os.path.isfile(path)]


def _visible_windows_for_pid(pid, first_hwnd=None):
    windows = []
    seen = set()

    def add(hwnd):
        if not hwnd or hwnd in seen:
            return
        try:
            if not win32gui.IsWindow(hwnd) or not win32gui.IsWindowVisible(hwnd):
                return
            _, window_pid = win32process.GetWindowThreadProcessId(hwnd)
            if int(window_pid) != int(pid):
                return
            left, top, right, bottom = win32gui.GetWindowRect(hwnd)
            if right - left < 20 or bottom - top < 20:
                return
            seen.add(hwnd)
            windows.append(hwnd)
        except Exception:
            pass

    add(first_hwnd)

    def enum_window(hwnd, _):
        add(hwnd)
        return True

    try:
        win32gui.EnumWindows(enum_window, None)
    except Exception:
        pass

    if first_hwnd and first_hwnd in windows:
        rest = [hwnd for hwnd in windows if hwnd != first_hwnd]
    else:
        rest = list(windows)

    def area(hwnd):
        try:
            left, top, right, bottom = win32gui.GetWindowRect(hwnd)
            return max(0, right - left) * max(0, bottom - top)
        except Exception:
            return 0

    rest.sort(key=area, reverse=True)
    return ([first_hwnd] if first_hwnd and first_hwnd in windows else []) + rest


def _pil_to_bgr(image):
    rgb = np.array(image.convert("RGB"))
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)


def _best_match_in_image(image, template_image):
    source = _pil_to_bgr(image)
    template = _pil_to_bgr(template_image)
    src_h, src_w = source.shape[:2]
    tmp_h, tmp_w = template.shape[:2]

    best = None
    for scale in CONFIRM_MATCH_SCALES:
        width = int(round(tmp_w * float(scale)))
        height = int(round(tmp_h * float(scale)))
        if width < 4 or height < 4 or width > src_w or height > src_h:
            continue

        resized = cv2.resize(template, (width, height), interpolation=cv2.INTER_AREA)

        try:
            color_result = cv2.matchTemplate(source, resized, cv2.TM_CCOEFF_NORMED)
            _, color_score, _, color_loc = cv2.minMaxLoc(color_result)
        except Exception:
            color_score, color_loc = -1.0, (0, 0)

        try:
            src_gray = cv2.cvtColor(source, cv2.COLOR_BGR2GRAY)
            tmp_gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
            gray_result = cv2.matchTemplate(src_gray, tmp_gray, cv2.TM_CCOEFF_NORMED)
            _, gray_score, _, gray_loc = cv2.minMaxLoc(gray_result)
        except Exception:
            gray_score, gray_loc = -1.0, (0, 0)

        if gray_score > color_score:
            score = float(gray_score)
            loc = gray_loc
        else:
            score = float(color_score)
            loc = color_loc

        if best is None or score > best[0]:
            best = (score, int(loc[0]), int(loc[1]), width, height)

    return best


def find_drop_yes_button(pid, hwnd=None, threshold=0.78, paths_text=None):
    templates = []
    for path in existing_yes_templates(paths_text):
        try:
            templates.append((path, Image.open(path).convert("RGB")))
        except Exception as error:
            print(f"Drop confirm YES template load failed: {path} - {error}")

    if not templates:
        print("Drop confirm YES template missing - put image at assets\\drop_confirm_yes.png")
        return None

    best = None
    for candidate_hwnd in _visible_windows_for_pid(pid, hwnd):
        image = capture_window(candidate_hwnd)
        if image is None:
            continue

        for path, template in templates:
            match = _best_match_in_image(image, template)
            if match is None:
                continue
            score, x, y, width, height = match
            if best is None or score > best[0]:
                best = (score, candidate_hwnd, path, x, y, width, height)

    if best is None:
        print("Drop confirm YES not found - no match candidates")
        return None

    score, match_hwnd, path, x, y, width, height = best
    if score < float(threshold):
        print(
            "Drop confirm YES not found - "
            f"best={score:.3f} threshold={float(threshold):.3f} template={path}"
        )
        return None

    try:
        left, top, _, _ = win32gui.GetWindowRect(match_hwnd)
    except Exception:
        left, top = 0, 0

    center_window = (int(x + width / 2), int(y + height / 2))
    center_screen = (int(left + center_window[0]), int(top + center_window[1]))
    return DropConfirmMatch(
        hwnd=match_hwnd,
        score=float(score),
        template_path=path,
        center_screen=center_screen,
        center_window=center_window,
    )


def click_drop_yes_if_visible(pid, hwnd=None, timeout=3.0, threshold=0.78, paths_text=None):
    start = time.time()
    while time.time() - start < float(timeout):
        match = find_drop_yes_button(
            pid=pid,
            hwnd=hwnd,
            threshold=threshold,
            paths_text=paths_text,
        )
        if match is not None:
            print(
                "Drop confirm YES found - "
                f"hwnd={match.hwnd} - score={match.score:.3f} - "
                f"xy={match.center_screen} - template={match.template_path}"
            )
            pydirectinput.moveTo(match.center_screen[0], match.center_screen[1])
            time.sleep(0.05)
            pydirectinput.click(match.center_screen[0], match.center_screen[1])
            time.sleep(0.35)
            return True
        time.sleep(0.15)

    print("Drop confirm YES timeout")
    return False
