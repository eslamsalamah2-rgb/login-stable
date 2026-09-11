import os
from dataclasses import dataclass
from datetime import datetime

import cv2
import numpy as np
from PIL import ImageDraw, ImageStat

from tasks.post_login_modules.window_capture import capture_pid_window


GRID_COLS = 5
GRID_ROWS = 8
LINE_BAND = 2
SLOT_INSET = 0.22
FILLED_STD_THRESHOLD = 18.0
MIN_GRID_SCORE = 0.16
TOP_AXIS_CANDIDATES = 60
TOP_PER_CELL_SIZE = 5
CELL_ASPECT_TOLERANCE = 9


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

    @property
    def filled_count(self):
        return sum(1 for slot in self.slots if slot.filled)

    @property
    def empty_count(self):
        return sum(1 for slot in self.slots if not slot.filled)


def _cell_size_range(width, height):
    """Return a safe search range for the slot size.

    The detector is not tied to a fixed screen size such as 1920x1080. It tries
    plausible grid cell sizes based on the captured game-window size, then lets
    edge scoring choose the real 5x8 grid.
    """
    min_dim = max(1, min(int(width), int(height)))
    min_cell = max(24, int(round(min_dim * 0.025)))
    max_cell = min(90, max(42, int(round(min_dim * 0.075))))
    if max_cell <= min_cell:
        max_cell = min_cell + 18
    return min_cell, max_cell


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

    # A real line can be 1-2 pixels away from the predicted location because of
    # scaling and anti-aliasing. Use a small max band instead of exact pixels.
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
    """Find likely equally-spaced line sequences on one axis.

    For inventory, X needs 6 lines for 5 columns. Y needs 9 lines for 8 rows.
    We do not use fixed coordinates; this searches the current screenshot.
    """
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


def _find_grid_geometry(edge_binary):
    height, width = edge_binary.shape[:2]
    min_cell, max_cell = _cell_size_range(width, height)

    vertical_score = _band_projection(edge_binary, "x")
    horizontal_score = _band_projection(edge_binary, "y")

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

    for _, x0, cell_w in x_candidates:
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
            "Inventory grid probe failed: dynamic grid score too low - "
            f"score={score:.3f} min={MIN_GRID_SCORE:.3f}"
        )
        return None

    x_lines = [int(round(x0 + col * cell_w)) for col in range(GRID_COLS + 1)]
    y_lines = [int(round(y0 + row * cell_h)) for row in range(GRID_ROWS + 1)]

    return x_lines, y_lines, int(cell_w), int(cell_h), float(score)


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


def detect_inventory_grid(image):
    """Dynamically detect the visible 5x8 inventory grid in the captured image."""
    width, height = image.size
    if width < 320 or height < 320:
        return None

    edge_binary = _edge_binary(image)
    geometry = _find_grid_geometry(edge_binary)
    if geometry is None:
        return None

    x_lines, y_lines, cell_w, cell_h, score = geometry

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
        cell_width=cell_w,
        cell_height=cell_h,
        score=score,
    )


def draw_grid_debug(image, result):
    debug = image.copy()
    draw = ImageDraw.Draw(debug)

    draw.rectangle(result.box, outline=(255, 215, 0), width=3)

    for slot in result.slots:
        outline = (255, 80, 80) if slot.filled else (80, 255, 80)
        draw.rectangle(slot.box, outline=outline, width=2)
        x1, y1, _, _ = slot.box
        draw.text((x1 + 3, y1 + 3), str(slot.index + 1), fill=outline)

    return debug


class InventoryGridProbeModule:
    """Detect and draw the inventory slot grid for the current account only.

    This stage is still safe: it captures, dynamically finds the visible 5x8
    slot grid, and saves an annotated image. It does not click, type, move,
    drop, or use items.
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

        result = detect_inventory_grid(image)
        if result is None:
            return "INVENTORY_GRID_PROBE_GRID_NOT_FOUND"

        print(
            "Inventory grid probe OK - "
            f"account={account_index + 1} - pid={pid} - hwnd={hwnd} - "
            f"name={page_name!r} - image={image.size[0]}x{image.size[1]} - "
            f"grid={result.box} - cell={result.cell_width}x{result.cell_height} - "
            f"score={result.score:.3f} - filled={result.filled_count} - empty={result.empty_count}"
        )

        if self._save_debug_enabled():
            try:
                folder = self._debug_dir()
                os.makedirs(folder, exist_ok=True)
                stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                path = os.path.join(
                    folder,
                    f"grid_account_{account_index + 1}_pid_{pid}_{stamp}.png",
                )
                debug = draw_grid_debug(image, result)
                debug.save(path)
                print(f"Inventory grid probe debug image saved: {path}")
            except Exception as error:
                print(
                    "Inventory grid probe debug save failed - "
                    f"account={account_index + 1} - pid={pid} - {error}"
                )

        return "OK"
