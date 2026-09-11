from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

import cv2
import numpy as np
from PIL import Image


ANCHOR_IMAGE_PATHS = (
    os.path.join("assets", "inventory_open.png"),
    os.path.join("assets", "inventory_open_anchor.png"),
)

ANCHOR_NAME = "inventory_open_buttons"
ANCHOR_MATCH_THRESHOLD = 0.76
ANCHOR_SEARCH_RIGHT_FRACTION = 0.40

GRID_OFFSET_X = -169
GRID_OFFSET_Y = -345
GRID_CELL_WIDTH = 43
GRID_CELL_HEIGHT = 43
GRID_COLS = 5
GRID_ROWS = 8
ANCHOR_SCALES = (0.96, 0.98, 1.00, 1.02, 1.04)


@dataclass
class InventoryAnchorMatch:
    name: str
    score: float
    anchor_box: tuple[int, int, int, int]
    grid_box: tuple[int, int, int, int]
    cell_width: int
    cell_height: int
    rows: int
    cols: int
    source_path: str


@lru_cache(maxsize=16)
def _load_anchor_file(path):
    if not os.path.isfile(path):
        return None
    try:
        return Image.open(path).convert("RGB")
    except Exception as error:
        print(f"Inventory anchor image load failed: {path} - {error}")
        return None


@lru_cache(maxsize=1)
def _anchor_templates_rgb():
    templates = []
    for path in ANCHOR_IMAGE_PATHS:
        image = _load_anchor_file(path)
        if image is not None:
            print(f"Inventory anchor image loaded: {path} size={image.size[0]}x{image.size[1]}")
            templates.append((path, np.array(image)))
    if not templates:
        print("Inventory anchor image missing - put image at assets\\inventory_open.png")
    return tuple(templates)


def _best_anchor_match(source_gray, source_color, template_rgb, x_offset):
    template_color = cv2.cvtColor(template_rgb, cv2.COLOR_RGB2BGR)
    template_gray = cv2.cvtColor(template_color, cv2.COLOR_BGR2GRAY)
    src_h, src_w = source_gray.shape[:2]
    temp_h, temp_w = template_gray.shape[:2]
    best = None

    for scale in ANCHOR_SCALES:
        width = int(round(temp_w * float(scale)))
        height = int(round(temp_h * float(scale)))
        if width < 8 or height < 8 or width > src_w or height > src_h:
            continue
        try:
            interpolation = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_CUBIC
            gray = cv2.resize(template_gray, (width, height), interpolation=interpolation)
            color = cv2.resize(template_color, (width, height), interpolation=interpolation)
            gray_result = cv2.matchTemplate(source_gray, gray, cv2.TM_CCOEFF_NORMED)
            _, gray_score, _, gray_loc = cv2.minMaxLoc(gray_result)
            color_result = cv2.matchTemplate(source_color, color, cv2.TM_CCOEFF_NORMED)
            _, color_score, _, color_loc = cv2.minMaxLoc(color_result)
            loc_distance = abs(int(color_loc[0]) - int(gray_loc[0])) + abs(int(color_loc[1]) - int(gray_loc[1]))
            score = (float(gray_score) + float(color_score)) / 2.0
            if loc_distance > 8:
                score -= 0.06
            candidate = (score, int(color_loc[0]) + int(x_offset), int(color_loc[1]), width, height, scale)
            if best is None or candidate[0] > best[0]:
                best = candidate
        except Exception:
            continue

    return best


def find_inventory_anchor(image):
    if image is None:
        return None

    templates = _anchor_templates_rgb()
    if not templates:
        return None

    source_rgb = np.array(image.convert("RGB"))
    source_bgr = cv2.cvtColor(source_rgb, cv2.COLOR_RGB2BGR)
    source_gray = cv2.cvtColor(source_bgr, cv2.COLOR_BGR2GRAY)
    height, width = source_gray.shape[:2]
    search_x0 = max(0, min(int(width * ANCHOR_SEARCH_RIGHT_FRACTION), width - 1))
    search_gray = source_gray[:, search_x0:]
    search_bgr = source_bgr[:, search_x0:]

    best = None
    best_path = None
    for path, template_rgb in templates:
        candidate = _best_anchor_match(search_gray, search_bgr, template_rgb, search_x0)
        if candidate is None:
            continue
        if best is None or candidate[0] > best[0]:
            best = candidate
            best_path = path

    if best is None:
        return None

    score, ax, ay, aw, ah, scale = best
    if score < ANCHOR_MATCH_THRESHOLD:
        print(f"Inventory anchor not found - best={score:.3f} threshold={ANCHOR_MATCH_THRESHOLD:.3f}")
        return None

    grid_x = int(round(ax + GRID_OFFSET_X * float(scale)))
    grid_y = int(round(ay + GRID_OFFSET_Y * float(scale)))
    cell_w = int(round(GRID_CELL_WIDTH * float(scale)))
    cell_h = int(round(GRID_CELL_HEIGHT * float(scale)))
    grid_w = cell_w * GRID_COLS
    grid_h = cell_h * GRID_ROWS

    return InventoryAnchorMatch(
        name=ANCHOR_NAME,
        score=float(score),
        anchor_box=(int(ax), int(ay), int(ax + aw), int(ay + ah)),
        grid_box=(int(grid_x), int(grid_y), int(grid_x + grid_w), int(grid_y + grid_h)),
        cell_width=int(cell_w),
        cell_height=int(cell_h),
        rows=GRID_ROWS,
        cols=GRID_COLS,
        source_path=str(best_path or ""),
    )


def grid_lines_from_anchor(match):
    x1, y1, _, _ = match.grid_box
    x_lines = [int(x1 + col * match.cell_width) for col in range(match.cols + 1)]
    y_lines = [int(y1 + row * match.cell_height) for row in range(match.rows + 1)]
    return x_lines, y_lines
