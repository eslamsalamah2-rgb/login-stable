"""Inventory anchor detection.

Detect whether the bag window is open by matching a real image crop from the
bag UI. The preferred anchor is a user-managed file:

    assets/inventory_open.png

For this test stage a fallback embedded copy is kept so the program can still
run if the asset has not been copied yet, but the normal workflow is to replace
that file with a fresh crop from the user's own client.
"""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from functools import lru_cache
from io import BytesIO

import cv2
import numpy as np
from PIL import Image


ANCHOR_IMAGE_PATHS = (
    os.path.join("assets", "inventory_open.png"),
    os.path.join("assets", "inventory_open_anchor.png"),
)

# Fallback copy of the user's three-button anchor: Tidy / Lock / Redeem.
# The external assets/inventory_open.png file is preferred when present.
FALLBACK_ANCHOR_BASE64 = (
    "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"
    "AABJRU5ErkJggg=="
)

ANCHOR_NAME = "inventory_open_buttons"
ANCHOR_MATCH_THRESHOLD = 0.76
ANCHOR_SEARCH_RIGHT_FRACTION = 0.40

# Calibrated for the three-button anchor crop sent by the user.
# Anchor top-left -> slot grid top-left.
GRID_OFFSET_X = -161
GRID_OFFSET_Y = -345
GRID_CELL_WIDTH = 43
GRID_CELL_HEIGHT = 43
GRID_COLS = 5
GRID_ROWS = 8

# UI is fixed-size, but allow tiny differences from capture/DPI.
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
    for path in ANCHOR_IMAGE_PATHS:
        if os.path.exists(path):
            try:
                image = Image.open(path).convert("RGB")
                print(f"Inventory anchor image loaded: {path} size={image.size[0]}x{image.size[1]}")
                return image
            except Exception as error:
                print(f"Inventory anchor image failed to load: {path} - {error}")

    raw = base64.b64decode(FALLBACK_ANCHOR_BASE64)
    image = Image.open(BytesIO(raw)).convert("RGB")
    print("Inventory anchor image loaded: embedded fallback inventory_open buttons")
    return image


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
    """Find the manual bag anchor in the current captured game window."""
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
            best = (
                float(score),
                float(scale),
                int(loc[0]) + right_start,
                int(loc[1]),
                int(tw),
                int(th),
            )

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
