import os
import time
from dataclasses import dataclass
from functools import lru_cache

import cv2
import numpy as np
import pydirectinput
import win32api
import win32gui
import win32process

from tasks.post_login_modules.window_capture import capture_window


DEFAULT_YES_TEMPLATE_PATHS = (
    os.path.join("assets", "drop_confirm_yes.png"),
    os.path.join("assets", "yes.png"),
    os.path.join("assets", "drop_yes.png"),
    # Fallback only. If this image contains Yes+No together, the click point is
    # forced to the Yes side instead of the template center.
    os.path.join("assets", "yes_no.png"),
)

CONFIRM_MATCH_SCALES = (0.94, 0.97, 1.00, 1.03, 1.06)

# Safe Drop confirmation search area.
# The Drop worker passes the inventory/grid box. We allow a little more space
# around the bag than the previous ultra-tight version, but still never scan the
# full game window. This keeps far Yes/No buttons out of range.
BAG_ROI_PAD_LEFT = 130
BAG_ROI_PAD_TOP = 185
BAG_ROI_PAD_RIGHT = 165
BAG_ROI_PAD_BOTTOM = 185
NO_BAG_FALLBACK_RIGHT_FRACTION = 0.72

# When the matched template is wide or named yes_no, it may contain both Yes and
# No. The previous left-side guard could land on No on this client layout, so the
# fallback click is now deliberately on the right-side button area.
WIDE_TEMPLATE_YES_CLICK_X_FRACTION = 0.72
WIDE_TEMPLATE_MIN_WIDTH = 70


@dataclass
class DropConfirmMatch:
    hwnd: int
    score: float
    template_path: str
    center_screen: tuple[int, int]
    center_window: tuple[int, int]
    region: str


def _template_paths(paths_text=None):
    paths = []
    if paths_text:
        for part in str(paths_text).replace(";", ",").replace("|", ",").split(","):
            text = part.strip().strip('"')
            if text:
                paths.append(text)
    paths.extend(DEFAULT_YES_TEMPLATE_PATHS)

    unique = []
    seen = set()
    for path in paths:
        key = os.path.normcase(os.path.normpath(path))
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return tuple(unique)


def _is_yes_no_template_path(path):
    name = os.path.basename(str(path or "")).lower()
    return "yes_no" in name or "yes-no" in name or "yesno" in name


@lru_cache(maxsize=32)
def _load_template_file(path):
    if not os.path.isfile(path):
        return None
    image = cv2.imread(path, cv2.IMREAD_COLOR)
    if image is None:
        print(f"Drop confirm YES template load failed: {path}")
        return None
    return image


def load_yes_templates(paths_text=None):
    loaded = []
    for path in _template_paths(paths_text):
        image = _load_template_file(path)
        if image is not None:
            loaded.append((path, image))

    if not loaded:
        print("Drop confirm YES template missing - put image at assets\\drop_confirm_yes.png or assets\\yes.png")
        return []

    # Prefer Yes-only crops. yes_no.png is only a fallback because it can contain
    # both buttons and needs a guarded click point.
    yes_only = [(path, image) for path, image in loaded if not _is_yes_no_template_path(path)]
    if yes_only:
        return yes_only
    return loaded


def _visible_windows_for_pid(pid, first_hwnd=None, bag_limited=False):
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

    # If the bag/grid box is known, scanning any other hwnd can only cause false
    # clicks. Keep the search locked to the current game window.
    if bag_limited and first_hwnd and first_hwnd in windows:
        return [first_hwnd]

    def enum_window(hwnd, _):
        add(hwnd)
        return True

    try:
        win32gui.EnumWindows(enum_window, None)
    except Exception:
        pass

    def area(hwnd):
        try:
            left, top, right, bottom = win32gui.GetWindowRect(hwnd)
            return max(0, right - left) * max(0, bottom - top)
        except Exception:
            return 0

    if first_hwnd and first_hwnd in windows:
        rest = [hwnd for hwnd in windows if hwnd != first_hwnd]
        rest.sort(key=area, reverse=True)
        return [first_hwnd] + rest

    windows.sort(key=area, reverse=True)
    return windows


def _candidate_regions(image, around_box=None):
    """Return safe ROIs for the Drop confirmation Yes search.

    Normal Drop flow passes the inventory/grid box as around_box. In that case
    we scan only a padded area around the bag. Missing Yes is safer than clicking
    a wrong Yes/No somewhere else, so there is no full-window fallback.
    """
    width, height = image.size

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
                return [("safe_inventory_bag_yes_area", roi)]
        except Exception:
            pass

        print("Drop confirm YES skipped - inventory bag box missing/invalid; refusing wide search")
        return []

    # If the caller failed to pass the bag box, do not guess. A missed Yes is
    # safe; a wrong Yes/No click can break the page.
    print("Drop confirm YES skipped - no inventory bag box; refusing fallback search")
    return []


def _best_match_in_region(image, template, roi, stop_check=None):
    if stop_check and stop_check():
        return None

    left, top, right, bottom = roi
    crop_rgb = np.array(image.crop((left, top, right, bottom)).convert("RGB"))
    source = cv2.cvtColor(crop_rgb, cv2.COLOR_RGB2BGR)
    source_gray = cv2.cvtColor(source, cv2.COLOR_BGR2GRAY)
    tmp_h, tmp_w = template.shape[:2]
    best = None

    for scale in CONFIRM_MATCH_SCALES:
        if stop_check and stop_check():
            return None
        width = int(round(tmp_w * float(scale)))
        height = int(round(tmp_h * float(scale)))
        if width < 4 or height < 4 or width > source.shape[1] or height > source.shape[0]:
            continue
        try:
            resized = cv2.resize(template, (width, height), interpolation=cv2.INTER_AREA)
            color_result = cv2.matchTemplate(source, resized, cv2.TM_CCOEFF_NORMED)
            _, color_score, _, color_loc = cv2.minMaxLoc(color_result)
            tmp_gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
            gray_result = cv2.matchTemplate(source_gray, tmp_gray, cv2.TM_CCOEFF_NORMED)
            _, gray_score, _, gray_loc = cv2.minMaxLoc(gray_result)
            if gray_score > color_score:
                score, loc = float(gray_score), gray_loc
            else:
                score, loc = float(color_score), color_loc
            if best is None or score > best[0]:
                best = (score, int(loc[0]) + left, int(loc[1]) + top, width, height)
        except Exception:
            continue

    return best


def _click_point_for_yes_match(path, x, y, width, height):
    """Return the click point for a matched Drop confirmation template.

    Yes-only crops click center. Wide/yes_no crops click right-side to avoid No.
    """
    use_right_guard = _is_yes_no_template_path(path) or int(width) >= WIDE_TEMPLATE_MIN_WIDTH
    if use_right_guard:
        click_x = int(x + width * WIDE_TEMPLATE_YES_CLICK_X_FRACTION)
        rule = "yes_right_guard"
    else:
        click_x = int(x + width / 2)
        rule = "yes_center"
    click_y = int(y + height / 2)
    return click_x, click_y, rule


def find_drop_yes_button(pid, hwnd=None, threshold=0.72, paths_text=None, around_box=None, stop_check=None):
    if stop_check and stop_check():
        return None

    templates = load_yes_templates(paths_text)
    if not templates:
        return None

    bag_limited = around_box is not None and hwnd is not None
    best = None
    for candidate_hwnd in _visible_windows_for_pid(pid, hwnd, bag_limited=bag_limited):
        if stop_check and stop_check():
            return None
        image = capture_window(candidate_hwnd)
        if image is None:
            continue
        local_around = around_box if candidate_hwnd == hwnd else None
        for region_name, roi in _candidate_regions(image, local_around):
            for path, template in templates:
                match = _best_match_in_region(image, template, roi, stop_check=stop_check)
                if match is None:
                    continue
                score, x, y, width, height = match
                if best is None or score > best[0]:
                    best = (score, candidate_hwnd, path, x, y, width, height, region_name)

    if best is None:
        print("Drop confirm YES not found - no match candidates in safe inventory/bag area")
        return None

    score, match_hwnd, path, x, y, width, height, region_name = best
    if score < float(threshold):
        print(
            "Drop confirm YES not found - "
            f"best={score:.3f} threshold={float(threshold):.3f} template={path} region={region_name}"
        )
        return None

    try:
        left, top, _, _ = win32gui.GetWindowRect(match_hwnd)
    except Exception:
        left, top = 0, 0

    click_x, click_y, click_rule = _click_point_for_yes_match(path, x, y, width, height)
    center_window = (int(click_x), int(click_y))
    center_screen = (int(left + center_window[0]), int(top + center_window[1]))
    print(
        "Drop confirm YES found - "
        f"score={score:.3f} template={path} region={region_name} hwnd={match_hwnd} "
        f"click_rule={click_rule} xy={center_screen}"
    )
    return DropConfirmMatch(int(match_hwnd), float(score), path, center_screen, center_window, region_name)


def click_drop_yes_if_visible(pid, hwnd=None, timeout=1.20, threshold=0.72, paths_text=None, around_box=None, stop_check=None):
    start = time.perf_counter()
    timeout = max(0.05, float(timeout))

    while time.perf_counter() - start < timeout:
        if stop_check and stop_check():
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
            try:
                win32api.SetCursorPos((int(match.center_screen[0]), int(match.center_screen[1])))
            except Exception:
                pydirectinput.moveTo(int(match.center_screen[0]), int(match.center_screen[1]), duration=0)
            if stop_check and stop_check():
                return False
            pydirectinput.click()
            return True

        time.sleep(0.03)

    print("Drop confirm YES timeout")
    return False
