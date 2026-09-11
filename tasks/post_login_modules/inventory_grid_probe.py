import os
from dataclasses import dataclass
from datetime import datetime

from PIL import ImageDraw, ImageStat

from tasks.post_login_modules.window_capture import capture_pid_window


REFERENCE_WIDTH = 1920.0
REFERENCE_HEIGHT = 1080.0

# Calibrated from the user's InventoryProbe screenshot at 1920x1080.
# This is only a safe visual test stage. The next stage can replace this
# fixed calibration with anchor/template detection if needed.
GRID_LEFT = 1642.0
GRID_TOP = 182.0
CELL_WIDTH = 43.0
CELL_HEIGHT = 43.0
GRID_COLS = 5
GRID_ROWS = 8
SLOT_INSET = 0.22
FILLED_STD_THRESHOLD = 18.0


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

    @property
    def filled_count(self):
        return sum(1 for slot in self.slots if slot.filled)

    @property
    def empty_count(self):
        return sum(1 for slot in self.slots if not slot.filled)


def _scaled(value, scale):
    return int(round(float(value) * float(scale)))


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
    """Return the calibrated 5x8 inventory grid for one captured game window."""
    width, height = image.size
    if width < 600 or height < 400:
        return None

    scale_x = width / REFERENCE_WIDTH
    scale_y = height / REFERENCE_HEIGHT

    left = _scaled(GRID_LEFT, scale_x)
    top = _scaled(GRID_TOP, scale_y)
    cell_w = max(8, _scaled(CELL_WIDTH, scale_x))
    cell_h = max(8, _scaled(CELL_HEIGHT, scale_y))
    grid_w = cell_w * GRID_COLS
    grid_h = cell_h * GRID_ROWS

    right = left + grid_w
    bottom = top + grid_h

    if left < 0 or top < 0 or right > width or bottom > height:
        print(
            "Inventory grid probe failed: calibrated grid outside image - "
            f"image={width}x{height} grid=({left},{top},{right},{bottom})"
        )
        return None

    slots = []
    index = 0
    for row in range(GRID_ROWS):
        for col in range(GRID_COLS):
            x1 = left + col * cell_w
            y1 = top + row * cell_h
            x2 = x1 + cell_w
            y2 = y1 + cell_h
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
        box=(left, top, right, bottom),
        slots=slots,
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

    This stage is still safe: it captures, calculates the 5x8 boxes, and saves
    an annotated image. It does not click, type, move, drop, or use items.
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
            f"name={page_name!r} - grid={result.box} - "
            f"filled={result.filled_count} - empty={result.empty_count}"
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
