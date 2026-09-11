import os
from dataclasses import dataclass
from datetime import datetime

import cv2
import numpy as np
from PIL import ImageDraw, ImageStat

from tasks.post_login_modules.inventory_anchor import (
    find_inventory_anchor,
    grid_lines_from_anchor,
)
from tasks.post_login_modules.window_capture import capture_pid_window


GRID_COLS = 5
GRID_ROWS = 8
LINE_BAND = 2
SLOT_INSET = 0.22
FILLED_STD_THRESHOLD = 18.0
MIN_GRID_SCORE = 0.09
TOP_AXIS_CANDIDATES = 80
TOP_PER_CELL_SIZE = 6
CELL_ASPECT_TOLERANCE = 6

# Fallback only. The main path is image-anchor detection from the bag itself.
RIGHT_SEARCH_START_FRACTION = 0.55
FIXED_MIN_CELL = 36
FIXED_MAX_CELL = 52


@dataclass
class SlotProbeResult:
    index: int
    row: int
    col: int
    box: tuple[int, int, int, int]
    filled: bool
    mean: float
    stddev: float


@dataclass
class InventoryGridProbeResult:
    box: tuple[int, int, int, int]
    slots: list[SlotProbeResult]
    cell_width: int
    cell_height: int
    score: float
    method: str = "unknown"
    anchor_box: tuple[int, int, int, int] | None = None

    @property
    def filled_count(self):
        return sum(1 for slot in self.slots if slot.filled)

    @property
    def empty_count(self):
        return sum(1 for slot in self.slots if not slot.filled)


def _edge_binary(image):
    rgb = np.array(image.convert("RGB"))
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    edges = cv2.Canny(gray, 45, 120)
    return (edges > 0).astype(np.uint8)


def _band_projection(edge_binary, axis, band=LINE_BAND):
    if axis == "x":
        projection = edge_binary.sum(axis=0).astype(np.float32)
    else:
        projection = edge_binary.sum(axis=1).astype(np.float32)

    result = np.zeros_like(projection)
    for shift in range(-band, band + 1):
        if shift < 0:
            result[-shift:] = np.maximum(result[-shift:], projection[:shift])
        elif shift > 0:
            result[:-shift] = np.maximum(result[:-shift], projection[shift:])
        else:
            result = np.maximum(result, projection)
    return result


def _sequence_candidates(score, line_count, cell_count, min_cell, max_cell, top_n=TOP_AXIS_CANDIDATES):
    length = len(score)
    candidates = []

    for cell in range(int(min_cell), int(max_cell) + 1):
        max_start = length - int(cell_count) * cell - 1
        if max_start <= 0:
            continue

        values = np.zeros(max_start, dtype=np.float32)
        for line_index in range(int(line_count)):
            start = line_index * cell
            values += score[start:start + max_start]

        take = min(TOP_PER_CELL_SIZE, len(values))
        if take <= 0:
            continue

        indexes = np.argpartition(values, -take)[-take:]
        for start in indexes:
            candidates.append((float(values[start]), int(start), int(cell)))

    candidates.sort(reverse=True)

    filtered = []
    for item in candidates:
        _, start, cell = item
        if any(abs(start - old_start) < 8 and abs(cell - old_cell) <= 2 for _, old_start, old_cell in filtered):
            continue
        filtered.append(item)
        if len(filtered) >= top_n:
            break

    return filtered


def _integral(edge_binary):
    return cv2.integral(edge_binary)


def _rect_sum(integral, x1, y1, x2, y2):
    height = integral.shape[0] - 1
    width = integral.shape[1] - 1

    x1 = max(0, min(width, int(x1)))
    x2 = max(0, min(width, int(x2)))
    y1 = max(0, min(height, int(y1)))
    y2 = max(0, min(height, int(y2)))

    if x2 <= x1 or y2 <= y1:
        return 0

    return int(
        integral[y2, x2]
        - integral[y1, x2]
        - integral[y2, x1]
        + integral[y1, x1]
    )


def _grid_score(integral, x0, cell_w, y0, cell_h):
    x_lines = [int(round(x0 + col * cell_w)) for col in range(GRID_COLS + 1)]
    y_lines = [int(round(y0 + row * cell_h)) for row in range(GRID_ROWS + 1)]

    width = integral.shape[1] - 1
    height = integral.shape[0] - 1

    if x_lines[0] < 0 or y_lines[0] < 0 or x_lines[-1] >= width or y_lines[-1] >= height:
        return -1.0

    x_left, x_right = x_lines[0], x_lines[-1]
    y_top, y_bottom = y_lines[0], y_lines[-1]

    vertical = 0
    for x in x_lines:
        vertical += _rect_sum(integral, x - LINE_BAND, y_top, x + LINE_BAND + 1, y_bottom)

    horizontal = 0
    for y in y_lines:
        horizontal += _rect_sum(integral, x_left, y - LINE_BAND, x_right, y + LINE_BAND + 1)

    normalizer = (
        len(x_lines) * max(1, y_bottom - y_top)
        + len(y_lines) * max(1, x_right - x_left)
    ) * max(1, LINE_BAND * 2 + 1)

    return float(vertical + horizontal) / float(normalizer)


def _find_grid_geometry_fallback(image):
    width, height = image.size
    edge_binary = _edge_binary(image)
    right_start = int(round(width * RIGHT_SEARCH_START_FRACTION))
    right_edges = edge_binary[:, right_start:]

    min_cell, max_cell = FIXED_MIN_CELL, FIXED_MAX_CELL

    vertical_score = _band_projection(right_edges, "x")
    horizontal_score = _band_projection(right_edges, "y")

    x_candidates = _sequence_candidates(
        vertical_score,
        line_count=GRID_COLS + 1,
        cell_count=GRID_COLS,
        min_cell=min_cell,
        max_cell=max_cell,
    )
    y_candidates = _sequence_candidates(
        horizontal_score,
        line_count=GRID_ROWS + 1,
        cell_count=GRID_ROWS,
        min_cell=min_cell,
        max_cell=max_cell,
    )

    if not x_candidates or not y_candidates:
        return None

    integral = _integral(edge_binary)
    best = None

    for _, x0_roi, cell_w in x_candidates:
        x0 = x0_roi + right_start
        for _, y0, cell_h in y_candidates:
            if abs(cell_w - cell_h) > CELL_ASPECT_TOLERANCE:
                continue

            score = _grid_score(integral, x0, cell_w, y0, cell_h)
            if best is None or score > best[0]:
                best = (score, x0, cell_w, y0, cell_h)

    if best is None:
        return None

    score, x0, cell_w, y0, cell_h = best
    if score < MIN_GRID_SCORE:
        print(
            "Inventory grid fallback failed: dynamic grid score too low - "
            f"score={score:.3f} min={MIN_GRID_SCORE:.3f}"
        )
        return None

    x_lines = [int(round(x0 + col * cell_w)) for col in range(GRID_COLS + 1)]
    y_lines = [int(round(y0 + row * cell_h)) for row in range(GRID_ROWS + 1)]

    return x_lines, y_lines, int(cell_w), int(cell_h), float(score), "dynamic_fallback", None


def _slot_stats(image, box):
    x1, y1, x2, y2 = box
    width = max(1, x2 - x1)
    height = max(1, y2 - y1)
    inset_x = max(2, int(round(width * SLOT_INSET)))
    inset_y = max(2, int(round(height * SLOT_INSET)))

    crop_box = (
        x1 + inset_x,
        y1 + inset_y,
        max(x1 + inset_x + 1, x2 - inset_x),
        max(y1 + inset_y + 1, y2 - inset_y),
    )
    crop = image.crop(crop_box).convert("L")
    stat = ImageStat.Stat(crop)
    mean = float(stat.mean[0]) if stat.mean else 0.0
    stddev = float(stat.stddev[0]) if stat.stddev else 0.0
    return mean, stddev


def _build_result_from_lines(image, x_lines, y_lines, cell_w, cell_h, score, method, anchor_box=None):
    slots = []
    index = 0
    for row in range(GRID_ROWS):
        for col in range(GRID_COLS):
            x1 = x_lines[col]
            y1 = y_lines[row]
            x2 = x_lines[col + 1]
            y2 = y_lines[row + 1]
            mean, stddev = _slot_stats(image, (x1, y1, x2, y2))
            filled = stddev >= FILLED_STD_THRESHOLD
            slots.append(
                SlotProbeResult(
                    index=index,
                    row=row,
                    col=col,
                    box=(x1, y1, x2, y2),
                    filled=filled,
                    mean=mean,
                    stddev=stddev,
                )
            )
            index += 1

    return InventoryGridProbeResult(
        box=(x_lines[0], y_lines[0], x_lines[-1], y_lines[-1]),
        slots=slots,
        cell_width=int(cell_w),
        cell_height=int(cell_h),
        score=float(score),
        method=str(method),
        anchor_box=anchor_box,
    )


def detect_inventory_grid(image):
    """Detect the open bag by image anchor, then return the 5x8 slot grid.

    Primary path:
      - find the real embedded "Tidy" button image on the right side
      - compute the fixed-size grid relative to that anchor

    Fallback:
      - if the anchor is not found, try the older line-grid detector.
    """
    width, height = image.size
    if width < 320 or height < 320:
        return None

    anchor = find_inventory_anchor(image)
    if anchor is not None:
        x_lines, y_lines = grid_lines_from_anchor(anchor)
        return _build_result_from_lines(
            image=image,
            x_lines=x_lines,
            y_lines=y_lines,
            cell_w=anchor.cell_width,
            cell_h=anchor.cell_height,
            score=anchor.score,
            method=f"anchor:{anchor.name}",
            anchor_box=anchor.anchor_box,
        )

    geometry = _find_grid_geometry_fallback(image)
    if geometry is None:
        return None

    x_lines, y_lines, cell_w, cell_h, score, method, anchor_box = geometry
    return _build_result_from_lines(
        image=image,
        x_lines=x_lines,
        y_lines=y_lines,
        cell_w=cell_w,
        cell_h=cell_h,
        score=score,
        method=method,
        anchor_box=anchor_box,
    )


def draw_grid_debug(image, result):
    debug = image.copy()
    draw = ImageDraw.Draw(debug)

    if result.anchor_box is not None:
        draw.rectangle(result.anchor_box, outline=(255, 215, 0), width=3)
        x1, y1, _, _ = result.anchor_box
        draw.text((x1 + 3, y1 - 14 if y1 >= 16 else y1 + 32), "ANCHOR", fill=(255, 215, 0))

    draw.rectangle(result.box, outline=(255, 215, 0), width=3)

    for slot in result.slots:
        outline = (255, 80, 80) if slot.filled else (80, 255, 80)
        draw.rectangle(slot.box, outline=outline, width=2)
        x1, y1, _, _ = slot.box
        draw.text((x1 + 3, y1 + 3), str(slot.index + 1), fill=outline)

    return debug


def draw_failure_debug(image):
    debug = image.copy()
    draw = ImageDraw.Draw(debug)
    width, height = image.size
    right_start = int(round(width * RIGHT_SEARCH_START_FRACTION))
    draw.rectangle((right_start, 0, width - 1, height - 1), outline=(255, 215, 0), width=3)
    draw.text((right_start + 10, 10), "BAG ANCHOR / GRID NOT FOUND - right-side search area", fill=(255, 215, 0))
    return debug


class InventoryGridProbeModule:
    """Detect and draw the inventory slot grid for the current account only.

    Safe test stage: it captures the current account PID, saves debug evidence,
    and locates the 5x8 bag grid using a real image anchor when possible. It
    never clicks, types, moves, drops, or uses items.
    """

    name = "inventory_grid_probe"
    setting_key = "enable_inventory_grid_probe"

    def __init__(self, launcher):
        self.launcher = launcher

    def _setting(self, key, default=None):
        if hasattr(self.launcher, "get_runtime_setting"):
            try:
                return self.launcher.get_runtime_setting(key, default)
            except Exception:
                return default
        return default

    def _feature_enabled(self, key, default=False):
        if hasattr(self.launcher, "feature_enabled"):
            try:
                return bool(self.launcher.feature_enabled(key, default))
            except Exception:
                return bool(default)

        value = self._setting(key, default)
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"1", "true", "yes", "on", "enabled"}

    def enabled(self):
        return self._feature_enabled(self.setting_key, False)

    def _save_debug_enabled(self):
        return self._feature_enabled("inventory_grid_probe_save_debug_image", True)

    def _debug_dir(self):
        value = self._setting("inventory_grid_probe_debug_dir", "logs/inventory_grid_probe")
        text = str(value or "logs/inventory_grid_probe").strip()
        return text or "logs/inventory_grid_probe"

    def _save_image(self, image, prefix, account_index, pid):
        folder = self._debug_dir()
        os.makedirs(folder, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(
            folder,
            f"{prefix}_account_{account_index + 1}_pid_{pid}_{stamp}.png",
        )
        image.save(path)
        print(f"Inventory grid probe debug image saved: {path}")
        return path

    def run(self, account_index, session):
        if not self.enabled():
            return "SKIPPED"

        pid = session.get("pid")
        page_name = session.get("page_name", "")
        if not pid:
            return "INVENTORY_GRID_PROBE_NO_PID"

        image, hwnd = capture_pid_window(pid)
        if image is None:
            return "INVENTORY_GRID_PROBE_CAPTURE_FAILED"

        if self._save_debug_enabled():
            try:
                self._save_image(image, "raw", account_index, pid)
            except Exception as error:
                print(
                    "Inventory grid probe raw save failed - "
                    f"account={account_index + 1} - pid={pid} - {error}"
                )

        result = detect_inventory_grid(image)
        if result is None:
            print(
                "Inventory grid probe did not find inventory - "
                f"account={account_index + 1} - pid={pid} - hwnd={hwnd} - "
                f"name={page_name!r} - image={image.size[0]}x{image.size[1]}"
            )
            if self._save_debug_enabled():
                try:
                    self._save_image(draw_failure_debug(image), "inventory_not_found", account_index, pid)
                except Exception as error:
                    print(
                        "Inventory grid probe failure debug save failed - "
                        f"account={account_index + 1} - pid={pid} - {error}"
                    )

            return "OK"

        print(
            "Inventory grid probe OK - "
            f"account={account_index + 1} - pid={pid} - hwnd={hwnd} - "
            f"name={page_name!r} - image={image.size[0]}x{image.size[1]} - "
            f"method={result.method} - grid={result.box} - "
            f"cell={result.cell_width}x{result.cell_height} - "
            f"score={result.score:.3f} - filled={result.filled_count} - empty={result.empty_count}"
        )

        if self._save_debug_enabled():
            try:
                debug = draw_grid_debug(image, result)
                self._save_image(debug, "grid", account_index, pid)
            except Exception as error:
                print(
                    "Inventory grid probe debug save failed - "
                    f"account={account_index + 1} - pid={pid} - {error}"
                )

        return "OK"
