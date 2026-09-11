import os
from dataclasses import dataclass
from datetime import datetime

import cv2
import numpy as np
from PIL import Image, ImageDraw

from tasks.post_login_modules.inventory_grid_probe import (
    detect_inventory_grid,
    draw_failure_debug,
)
from tasks.post_login_modules.window_capture import capture_pid_window


SUPPORTED_TEMPLATE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".bmp", ".webp")
MATCH_SCALES = (0.80, 0.90, 1.00, 1.10, 1.20)
DEFAULT_MATCH_THRESHOLD = 0.72


@dataclass
class ItemTemplate:
    name: str
    path: str
    image: Image.Image


@dataclass
class SlotItemMatch:
    slot_index: int
    row: int
    col: int
    box: tuple[int, int, int, int]
    item_name: str
    template_path: str
    score: float


@dataclass
class InventoryItemProbeResult:
    matches: list[SlotItemMatch]
    template_count: int
    scanned_slots: int


def _as_float(value, default):
    try:
        return float(value)
    except Exception:
        return float(default)


def _template_files(folder):
    if not folder or not os.path.isdir(folder):
        return []

    files = []
    for name in sorted(os.listdir(folder)):
        path = os.path.join(folder, name)
        if not os.path.isfile(path):
            continue
        if os.path.splitext(name)[1].lower() not in SUPPORTED_TEMPLATE_EXTENSIONS:
            continue
        files.append(path)
    return files


def load_item_templates(folder):
    templates = []
    for path in _template_files(folder):
        try:
            image = Image.open(path).convert("RGB")
            base = os.path.splitext(os.path.basename(path))[0]
            templates.append(ItemTemplate(name=base, path=path, image=image))
        except Exception as error:
            print(f"Inventory item template load failed: {path} - {error}")
    return templates


def _pil_to_bgr(image):
    rgb = np.array(image.convert("RGB"))
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)


def _safe_match_value(result):
    if result is None or result.size == 0:
        return -1.0
    _, score, _, _ = cv2.minMaxLoc(result)
    score = float(score)
    if not np.isfinite(score):
        return -1.0
    return score


def _match_arrays(slot_bgr, template_bgr):
    if slot_bgr is None or template_bgr is None:
        return -1.0

    slot_h, slot_w = slot_bgr.shape[:2]
    temp_h, temp_w = template_bgr.shape[:2]
    if slot_w < 4 or slot_h < 4 or temp_w < 4 or temp_h < 4:
        return -1.0

    best = -1.0

    for scale in MATCH_SCALES:
        scaled_w = int(round(temp_w * float(scale)))
        scaled_h = int(round(temp_h * float(scale)))
        if scaled_w < 4 or scaled_h < 4:
            continue

        if scaled_w > slot_w or scaled_h > slot_h:
            if temp_w > slot_w * 1.35 or temp_h > slot_h * 1.35:
                continue
            scaled_w = slot_w
            scaled_h = slot_h

        resized = cv2.resize(template_bgr, (scaled_w, scaled_h), interpolation=cv2.INTER_AREA)

        try:
            color_result = cv2.matchTemplate(slot_bgr, resized, cv2.TM_CCOEFF_NORMED)
            color_score = _safe_match_value(color_result)
        except Exception:
            color_score = -1.0

        try:
            slot_gray = cv2.cvtColor(slot_bgr, cv2.COLOR_BGR2GRAY)
            template_gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
            gray_result = cv2.matchTemplate(slot_gray, template_gray, cv2.TM_CCOEFF_NORMED)
            gray_score = _safe_match_value(gray_result)
        except Exception:
            gray_score = -1.0

        score = max(color_score, (color_score + gray_score) / 2.0, gray_score)
        if score > best:
            best = float(score)

    return best


def _best_template_for_slot(slot_image, templates):
    slot_bgr = _pil_to_bgr(slot_image)
    best = None
    for template in templates:
        score = _match_arrays(slot_bgr, _pil_to_bgr(template.image))
        if best is None or score > best[0]:
            best = (score, template)
    return best


def probe_items(image, grid_result, templates, threshold=DEFAULT_MATCH_THRESHOLD):
    matches = []
    scanned = 0

    for slot in grid_result.slots:
        scanned += 1
        crop = image.crop(slot.box).convert("RGB")
        best = _best_template_for_slot(crop, templates)
        if best is None:
            continue
        score, template = best
        if score >= threshold:
            matches.append(
                SlotItemMatch(
                    slot_index=slot.index,
                    row=slot.row,
                    col=slot.col,
                    box=slot.box,
                    item_name=template.name,
                    template_path=template.path,
                    score=float(score),
                )
            )

    return InventoryItemProbeResult(
        matches=matches,
        template_count=len(templates),
        scanned_slots=scanned,
    )


def draw_item_debug(image, grid_result, item_result):
    debug = image.copy()
    draw = ImageDraw.Draw(debug)

    if getattr(grid_result, "anchor_box", None) is not None:
        draw.rectangle(grid_result.anchor_box, outline=(255, 215, 0), width=3)

    draw.rectangle(grid_result.box, outline=(255, 215, 0), width=3)

    match_by_slot = {match.slot_index: match for match in item_result.matches}
    for slot in grid_result.slots:
        match = match_by_slot.get(slot.index)
        if match is None:
            draw.rectangle(slot.box, outline=(90, 220, 90), width=1)
            continue

        draw.rectangle(slot.box, outline=(255, 80, 80), width=3)
        x1, y1, _, _ = slot.box
        label = f"{match.item_name}:{match.score:.2f}"
        draw.text((x1 + 2, y1 + 2), label, fill=(255, 80, 80))

    return debug


class InventoryItemProbeModule:
    """Identify user-provided item templates inside the current account bag.

    This is still a safe probe stage. It does not click, drop, or use anything.
    It only captures the current PID window, finds the already-open bag grid,
    compares each slot against PNG/JPG templates from assets/drop_items, logs
    matches, and saves a debug image.
    """

    name = "inventory_item_probe"
    setting_key = "enable_inventory_item_probe"

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
        return self._feature_enabled(self.setting_key, True)

    def _templates_dir(self):
        value = self._setting("inventory_item_templates_dir", os.path.join("assets", "drop_items"))
        text = str(value or os.path.join("assets", "drop_items")).strip()
        return text or os.path.join("assets", "drop_items")

    def _threshold(self):
        value = _as_float(self._setting("inventory_item_match_threshold", DEFAULT_MATCH_THRESHOLD), DEFAULT_MATCH_THRESHOLD)
        return max(0.10, min(0.99, value))

    def _save_debug_enabled(self):
        return self._feature_enabled("inventory_item_probe_save_debug_image", True)

    def _debug_dir(self):
        value = self._setting("inventory_item_probe_debug_dir", "logs/inventory_item_probe")
        text = str(value or "logs/inventory_item_probe").strip()
        return text or "logs/inventory_item_probe"

    def _save_image(self, image, prefix, account_index, pid):
        if not self._save_debug_enabled() or image is None:
            return None
        folder = self._debug_dir()
        os.makedirs(folder, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(folder, f"{prefix}_account_{account_index + 1}_pid_{pid}_{stamp}.png")
        image.save(path)
        print(f"Inventory item probe debug image saved: {path}")
        return path

    def run(self, account_index, session):
        if not self.enabled():
            return "SKIPPED"

        pid = session.get("pid")
        page_name = session.get("page_name", "")
        if not pid:
            return "INVENTORY_ITEM_PROBE_NO_PID"

        image, hwnd = capture_pid_window(pid)
        if image is None:
            return "INVENTORY_ITEM_PROBE_CAPTURE_FAILED"

        grid = detect_inventory_grid(image)
        if grid is None:
            print(
                "Inventory item probe skipped - bag/grid not detected - "
                f"account={account_index + 1} - pid={pid} - hwnd={hwnd} - name={page_name!r}"
            )
            try:
                self._save_image(draw_failure_debug(image), "grid_not_found", account_index, pid)
            except Exception as error:
                print(f"Inventory item probe failure image save failed: {error}")
            return "OK"

        templates_dir = self._templates_dir()
        templates = load_item_templates(templates_dir)
        if not templates:
            print(
                "Inventory item probe has no templates - "
                f"folder={templates_dir!r} - put item PNG files there"
            )
            try:
                self._save_image(draw_item_debug(image, grid, InventoryItemProbeResult([], 0, len(grid.slots))), "no_templates", account_index, pid)
            except Exception as error:
                print(f"Inventory item probe no-template debug save failed: {error}")
            return "OK"

        result = probe_items(image, grid, templates, self._threshold())
        print(
            "Inventory item probe OK - "
            f"account={account_index + 1} - pid={pid} - hwnd={hwnd} - name={page_name!r} - "
            f"templates={result.template_count} - scanned_slots={result.scanned_slots} - "
            f"matches={len(result.matches)} - threshold={self._threshold():.2f}"
        )

        for match in result.matches:
            print(
                "Inventory item match - "
                f"account={account_index + 1} - slot={match.slot_index + 1} - "
                f"row={match.row + 1} - col={match.col + 1} - "
                f"item={match.item_name!r} - score={match.score:.3f}"
            )

        try:
            self._save_image(draw_item_debug(image, grid, result), "items", account_index, pid)
        except Exception as error:
            print(f"Inventory item probe debug save failed: {error}")

        return "OK"
