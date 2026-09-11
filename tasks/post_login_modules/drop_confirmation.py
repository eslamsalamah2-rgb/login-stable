import base64
import os
import time
from dataclasses import dataclass
from functools import lru_cache
from io import BytesIO

import cv2
import numpy as np
import pydirectinput
import win32api
import win32gui
import win32process
from PIL import Image

from tasks.post_login_modules.window_capture import capture_window


pydirectinput.PAUSE = 0
pydirectinput.FAILSAFE = False

DEFAULT_YES_TEMPLATE_PATHS = (
    os.path.join("assets", "drop_confirm_yes.png"),
    os.path.join("assets", "yes_no.png"),
    os.path.join("assets", "yes.png"),
    os.path.join("assets", "drop_yes.png"),
)

# Embedded fallback from the Yes crop sent during the drop test.
# External files above are still preferred, but the drop confirmation no longer
# fails just because the user has not copied assets/drop_confirm_yes.png yet.
FALLBACK_YES_BASE64 = (
    "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"
)

CONFIRM_MATCH_SCALES = (1.00,)
BAG_ROI_PAD_LEFT = 80
BAG_ROI_PAD_TOP = 140
BAG_ROI_PAD_RIGHT = 220
BAG_ROI_PAD_BOTTOM = 120


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


@lru_cache(maxsize=16)
def _load_template_file(path):
    try:
        return Image.open(path).convert("RGB")
    except Exception as error:
        print(f"Drop confirm YES template load failed: {path} - {error}")
        return None


@lru_cache(maxsize=1)
def _fallback_yes_template():
    raw = base64.b64decode(FALLBACK_YES_BASE64)
    return Image.open(BytesIO(raw)).convert("RGB")


def load_yes_templates(paths_text=None):
    templates = []

    for path in _template_paths(paths_text):
        if not os.path.isfile(path):
            continue

        image = _load_template_file(path)
        if image is None:
            continue
        templates.append((path, image))

    if templates:
        return templates

    try:
        image = _fallback_yes_template()
        print("Drop confirm YES using embedded fallback template")
        return [("embedded:drop_confirm_yes", image)]
    except Exception as error:
        print(f"Drop confirm YES fallback template failed: {error}")
        return []


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


def _candidate_regions(image, around_box=None):
    width, height = image.size
    regions = []

    if around_box is not None:
        try:
            x1, y1, x2, y2 = [int(v) for v in around_box]
            roi = (
                max(0, x1 - BAG_ROI_PAD_LEFT),
                max(0, y1 - BAG_ROI_PAD_TOP),
                min(width, x2 + BAG_ROI_PAD_RIGHT),
                min(height, y2 + BAG_ROI_PAD_BOTTOM),
            )
            if roi[2] - roi[0] >= 30 and roi[3] - roi[1] >= 20:
                regions.append(("around_bag", roi))
        except Exception:
            pass

    # Small right-side fallback. Full-window scan is intentionally avoided for
    # speed during repeated drop confirmation.
    right_roi = (int(width * 0.45), 0, width, height)
    if right_roi[2] - right_roi[0] >= 30:
        regions.append(("right_side", right_roi))

    if not regions:
        regions.append(("full_window", (0, 0, width, height)))

    unique = []
    seen = set()
    for name, roi in regions:
        if roi in seen:
            continue
        seen.add(roi)
        unique.append((name, roi))
    return unique


def _best_match_in_region(image, template_image, roi, stop_check=None):
    if stop_check and stop_check():
        return None

    left, top, right, bottom = roi
    crop = image.crop((left, top, right, bottom)).convert("RGB")
    source = _pil_to_bgr(crop)
    template = _pil_to_bgr(template_image)
    src_h, src_w = source.shape[:2]
    tmp_h, tmp_w = template.shape[:2]

    best = None
    for scale in CONFIRM_MATCH_SCALES:
        if stop_check and stop_check():
            return None

        width = int(round(tmp_w * float(scale)))
        height = int(round(tmp_h * float(scale)))
        if width < 4 or height < 4 or width > src_w or height > src_h:
            continue

        try:
            resized = cv2.resize(template, (width, height), interpolation=cv2.INTER_AREA)
            color_result = cv2.matchTemplate(source, resized, cv2.TM_CCOEFF_NORMED)
            _, score, _, loc = cv2.minMaxLoc(color_result)
            score = float(score)
        except Exception:
            continue

        if best is None or score > best[0]:
            best = (score, int(loc[0]) + left, int(loc[1]) + top, width, height)

    return best


def find_drop_yes_button(pid, hwnd=None, threshold=0.78, paths_text=None, around_box=None, stop_check=None):
    if stop_check and stop_check():
        return None

    templates = load_yes_templates(paths_text)
    if not templates:
        print("Drop confirm YES has no usable templates")
        return None

    best = None
    for candidate_hwnd in _visible_windows_for_pid(pid, hwnd):
        if stop_check and stop_check():
            return None

        image = capture_window(candidate_hwnd)
        if image is None:
            continue

        local_around_box = around_box if candidate_hwnd == hwnd else None
        for region_name, roi in _candidate_regions(image, local_around_box):
            if stop_check and stop_check():
                return None
            for path, template in templates:
                match = _best_match_in_region(image, template, roi, stop_check=stop_check)
                if match is None:
                    continue
                score, x, y, width, height = match
                if best is None or score > best[0]:
                    best = (score, candidate_hwnd, path, x, y, width, height, region_name)

    if best is None:
        print("Drop confirm YES not found - no match candidates")
        return None

    score, match_hwnd, path, x, y, width, height, region_name = best
    if score < float(threshold):
        print(
            "Drop confirm YES not found - "
            f"best={score:.3f} threshold={float(threshold):.3f} "
            f"template={path} region={region_name}"
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
        template_path=f"{path}@{region_name}",
        center_screen=center_screen,
        center_window=center_window,
    )


def click_drop_yes_if_visible(
    pid,
    hwnd=None,
    timeout=0.45,
    threshold=0.78,
    paths_text=None,
    around_box=None,
    stop_check=None,
):
    start = time.perf_counter()
    while time.perf_counter() - start < float(timeout):
        if stop_check and stop_check():
            print("Drop confirm YES stopped by user")
            return False

        match = find_drop_yes_button(
            pid=pid,
            hwnd=hwnd,
            threshold=threshold,
            paths_text=paths_text,
            around_box=around_box,
            stop_check=stop_check,
        )
        if match is not None:
            print(
                "Drop confirm YES found - "
                f"hwnd={match.hwnd} - score={match.score:.3f} - "
                f"xy={match.center_screen} - template={match.template_path}"
            )
            if stop_check and stop_check():
                return False
            try:
                win32api.SetCursorPos((match.center_screen[0], match.center_screen[1]))
            except Exception:
                pydirectinput.moveTo(match.center_screen[0], match.center_screen[1], duration=0)
            pydirectinput.click()
            return True

        time.sleep(0.03)

    print("Drop confirm YES timeout")
    return False
