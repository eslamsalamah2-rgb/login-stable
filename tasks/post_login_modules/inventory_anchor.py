"""Inventory anchor detection.

This module implements the first step the user requested:
detect whether the bag window is open by looking for a real image anchor from
the bag UI, not by assuming fixed screen coordinates.

The embedded anchor is a crop of the stable "Tidy" button from the bag window.
It is text/base64 so GitHub can carry it without requiring the user to copy a
PNG manually during this test stage.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from functools import lru_cache
from io import BytesIO

import cv2
import numpy as np
from PIL import Image


TIDY_ANCHOR_BASE64 = (
    "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"
)

ANCHOR_NAME = "inventory_tidy_button"
ANCHOR_MATCH_THRESHOLD = 0.78
ANCHOR_SEARCH_RIGHT_FRACTION = 0.45

# The bag UI size is effectively fixed. These offsets are measured from the
# anchor's top-left corner to the inventory slot grid's top-left corner.
GRID_OFFSET_X = -163
GRID_OFFSET_Y = -348
GRID_CELL_WIDTH = 43
GRID_CELL_HEIGHT = 43
GRID_COLS = 5
GRID_ROWS = 8

# Keep small tolerance for DPI/client-border variations.
ANCHOR_SCALES = (0.96, 0.98, 1.00, 1.02, 1.04)


@dataclass
class InventoryAnchorMatch:
    name: str
    score: float
    scale: float
    anchor_box: tuple[int, int, int, int]
    grid_box: tuple[int, int, int, int]
    cell_width: int
    cell_height: int


@lru_cache(maxsize=1)
def _anchor_template_rgb() -> Image.Image:
    raw = base64.b64decode(TIDY_ANCHOR_BASE64)
    return Image.open(BytesIO(raw)).convert("RGB")


@lru_cache(maxsize=16)
def _anchor_template_gray(scale: float) -> np.ndarray | None:
    template = np.array(_anchor_template_rgb())
    gray = cv2.cvtColor(template, cv2.COLOR_RGB2GRAY)

    if abs(scale - 1.0) < 0.0001:
        return gray

    height, width = gray.shape[:2]
    new_width = max(4, int(round(width * scale)))
    new_height = max(4, int(round(height * scale)))
    if new_width < 4 or new_height < 4:
        return None

    return cv2.resize(gray, (new_width, new_height), interpolation=cv2.INTER_AREA)


def find_inventory_anchor(image: Image.Image) -> InventoryAnchorMatch | None:
    """Find the bag anchor in the current captured game window.

    The search is intentionally limited to the right side because the bag is
    always docked there in this client. This reduces false positives and keeps
    the check fast on any external screen size.
    """
    width, height = image.size
    if width < 320 or height < 320:
        return None

    rgb = np.array(image.convert("RGB"))
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)

    right_start = int(round(width * ANCHOR_SEARCH_RIGHT_FRACTION))
    roi = gray[:, right_start:]

    best = None
    for scale in ANCHOR_SCALES:
        template = _anchor_template_gray(float(scale))
        if template is None:
            continue

        th, tw = template.shape[:2]
        if th >= roi.shape[0] or tw >= roi.shape[1]:
            continue

        result = cv2.matchTemplate(roi, template, cv2.TM_CCOEFF_NORMED)
        _, score, _, loc = cv2.minMaxLoc(result)

        if best is None or float(score) > best[0]:
            best = (float(score), float(scale), int(loc[0]) + right_start, int(loc[1]), int(tw), int(th))

    if best is None:
        return None

    score, scale, anchor_x, anchor_y, anchor_w, anchor_h = best
    if score < ANCHOR_MATCH_THRESHOLD:
        print(
            "Inventory anchor not found - "
            f"best={score:.3f} threshold={ANCHOR_MATCH_THRESHOLD:.3f}"
        )
        return None

    cell_w = max(8, int(round(GRID_CELL_WIDTH * scale)))
    cell_h = max(8, int(round(GRID_CELL_HEIGHT * scale)))
    grid_left = int(round(anchor_x + GRID_OFFSET_X * scale))
    grid_top = int(round(anchor_y + GRID_OFFSET_Y * scale))
    grid_right = grid_left + cell_w * GRID_COLS
    grid_bottom = grid_top + cell_h * GRID_ROWS

    if grid_left < 0 or grid_top < 0 or grid_right > width or grid_bottom > height:
        print(
            "Inventory anchor found but grid is outside image - "
            f"anchor=({anchor_x},{anchor_y}) score={score:.3f} "
            f"grid=({grid_left},{grid_top},{grid_right},{grid_bottom}) image={width}x{height}"
        )
        return None

    return InventoryAnchorMatch(
        name=ANCHOR_NAME,
        score=score,
        scale=scale,
        anchor_box=(anchor_x, anchor_y, anchor_x + anchor_w, anchor_y + anchor_h),
        grid_box=(grid_left, grid_top, grid_right, grid_bottom),
        cell_width=cell_w,
        cell_height=cell_h,
    )


def grid_lines_from_anchor(match: InventoryAnchorMatch):
    left, top, _, _ = match.grid_box
    x_lines = [left + col * match.cell_width for col in range(GRID_COLS + 1)]
    y_lines = [top + row * match.cell_height for row in range(GRID_ROWS + 1)]
    return x_lines, y_lines
