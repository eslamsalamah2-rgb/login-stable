import os
import time
from dataclasses import dataclass
from datetime import datetime

import cv2
import numpy as np
import pydirectinput
import win32api
import win32gui
from PIL import ImageDraw

from tasks.post_login_modules.drop_confirmation import click_drop_yes_if_visible
from tasks.post_login_modules.inventory_grid_probe import (
    detect_inventory_grid,
    draw_failure_debug,
)
from tasks.post_login_modules.inventory_item_probe import (
    DEFAULT_MATCH_THRESHOLD,
    InventoryItemProbeResult,
    SlotItemMatch,
    draw_item_debug,
    load_item_templates,
)
from tasks.post_login_modules.window_capture import capture_pid_window, capture_window


# Speed-critical mouse mode. Same idea as the old google2 mouse helper:
# move instantly with Win32, then send the click through pydirectinput.
pydirectinput.PAUSE = 0
pydirectinput.FAILSAFE = False

# The item crops come from the same client inventory slots, so exact scale is the
# fastest and safest default. Extra scales can be re-added only if a machine needs
# them later.
FAST_MATCH_SCALES = (1.00,)


@dataclass
class DropAction:
    slot_index: int
    item_name: str
    score: float
    slot_screen: tuple[int, int]
    target_screen: tuple[int, int]


@dataclass
class PreparedDropTemplate:
    name: str
    path: str
    bgr: object


class InventoryDropWorkerModule:
    """Drop only user-marked target items from the current account inventory.

    Real drop rule:
      - use only templates from assets/drop_items
      - find one current matched item
      - drop it and confirm Yes
      - capture/scan again before the next item

    Stop rule:
      - key 9 sets the runner stop event
      - this worker checks it before/after scans and between mouse clicks
      - no Login/Health recovery should be triggered just because the user stops
    """

    name = "inventory_drop_worker"
    setting_key = "enable_inventory_drop_worker"

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

    def _float_setting(self, key, default, minimum=0.0, maximum=None):
        try:
            value = float(self._setting(key, default))
        except Exception:
            value = float(default)
        value = max(float(minimum), value)
        if maximum is not None:
            value = min(float(maximum), value)
        return value

    def _int_setting(self, key, default, minimum=1, maximum=None):
        try:
            value = int(float(self._setting(key, default)))
        except Exception:
            value = int(default)
        value = max(int(minimum), value)
        if maximum is not None:
            value = min(int(maximum), value)
        return value

    def enabled(self):
        return self._feature_enabled(self.setting_key, True)

    def _stop_requested(self):
        runner = getattr(self.launcher, "post_login_runner", None)
        try:
            if runner is not None and runner.stop_event.is_set():
                return True
        except Exception:
            pass

        stop_event = getattr(self.launcher, "post_login_stop_event", None)
        try:
            if stop_event is not None and stop_event.is_set():
                return True
        except Exception:
            pass

        try:
            if bool(getattr(self.launcher, "pause_requested", False)):
                return True
        except Exception:
            pass

        return False

    def _sleep_interruptible(self, seconds):
        end = time.perf_counter() + max(0.0, float(seconds))
        while time.perf_counter() < end:
            if self._stop_requested():
                return False
            time.sleep(min(0.01, max(0.0, end - time.perf_counter())))
        return not self._stop_requested()

    def _templates_dir(self):
        value = self._setting("inventory_drop_templates_dir", os.path.join("assets", "drop_items"))
        text = str(value or os.path.join("assets", "drop_items")).strip()
        return text or os.path.join("assets", "drop_items")

    def _threshold(self):
        return self._float_setting(
            "inventory_drop_match_threshold",
            max(0.88, DEFAULT_MATCH_THRESHOLD),
            minimum=0.10,
            maximum=0.99,
        )

    def _max_items(self):
        return self._int_setting("inventory_drop_max_items_per_account", 40, minimum=1, maximum=40)

    def _clicks_per_point(self):
        return self._int_setting("inventory_drop_clicks_per_point", 2, minimum=1, maximum=3)

    def _click_delay(self):
        return self._float_setting("inventory_drop_click_delay", 0.01, minimum=0.0, maximum=1.0)

    def _after_drop_delay(self):
        return self._float_setting("inventory_drop_after_drop_delay", 0.0, minimum=0.0, maximum=1.0)

    def _target_mode(self):
        return str(self._setting("inventory_drop_target_mode", "top_right") or "top_right").strip().lower()

    def _target_fraction(self):
        x = self._float_setting("inventory_drop_target_x_fraction", 0.50, minimum=0.05, maximum=0.98)
        y = self._float_setting("inventory_drop_target_y_fraction", 0.45, minimum=0.03, maximum=0.90)
        return x, y

    def _target_margins(self):
        x = self._int_setting("inventory_drop_target_margin_x", 1, minimum=1, maximum=300)
        y = self._int_setting("inventory_drop_target_margin_y", 1, minimum=1, maximum=300)
        return x, y

    def _confirm_enabled(self):
        return self._feature_enabled("inventory_drop_confirm_yes_enabled", True)

    def _confirm_strict(self):
        return self._feature_enabled("inventory_drop_confirm_yes_strict", False)

    def _confirm_threshold(self):
        return self._float_setting("inventory_drop_confirm_yes_threshold", 0.76, minimum=0.10, maximum=0.99)

    def _confirm_timeout(self):
        return self._float_setting("inventory_drop_confirm_yes_timeout", 0.45, minimum=0.1, maximum=10.0)

    def _confirm_template_paths(self):
        value = self._setting("inventory_drop_confirm_yes_paths", "")
        return str(value or "")

    def _save_debug_enabled(self):
        return self._feature_enabled("inventory_drop_save_debug_image", False)

    def _debug_dir(self):
        value = self._setting("inventory_drop_debug_dir", "logs/inventory_drop_worker")
        text = str(value or "logs/inventory_drop_worker").strip()
        return text or "logs/inventory_drop_worker"

    def _save_image(self, image, prefix, account_index, pid):
        if not self._save_debug_enabled() or image is None:
            return None
        folder = self._debug_dir()
        os.makedirs(folder, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(folder, f"{prefix}_account_{account_index + 1}_pid_{pid}_{stamp}.png")
        image.save(path)
        print(f"Inventory drop debug image saved: {path}")
        return path

    def _capture_current_window(self, pid, hwnd=None):
        if hwnd and win32gui.IsWindow(hwnd):
            image = capture_window(hwnd)
            if image is not None:
                return image, hwnd
        return capture_pid_window(pid)

    def _screen_point_from_window_point(self, hwnd, point):
        try:
            left, top, _, _ = win32gui.GetWindowRect(hwnd)
        except Exception:
            left, top = 0, 0
        return int(left + point[0]), int(top + point[1])

    def _drop_target_screen(self, hwnd):
        mode = self._target_mode()

        if mode in {"top_right", "right_top", "upper_right"}:
            margin_x, margin_y = self._target_margins()

            try:
                client_left, client_top, client_right, client_bottom = win32gui.GetClientRect(hwnd)
                point = (
                    max(client_left + 1, client_right - margin_x),
                    min(client_bottom - 1, client_top + margin_y),
                )
                x, y = win32gui.ClientToScreen(hwnd, point)
                return int(x), int(y)
            except Exception:
                pass

            try:
                left, top, right, bottom = win32gui.GetWindowRect(hwnd)
            except Exception:
                left, top, right, bottom = 0, 0, 1920, 1080
            return int(right - margin_x), int(top + margin_y)

        try:
            left, top, right, bottom = win32gui.GetWindowRect(hwnd)
            width = max(1, right - left)
            height = max(1, bottom - top)
        except Exception:
            left, top, width, height = 0, 0, 1920, 1080

        fx, fy = self._target_fraction()
        return int(left + width * fx), int(top + height * fy)

    def _slot_center_screen(self, hwnd, box):
        x1, y1, x2, y2 = box
        center = (int(round((x1 + x2) / 2)), int(round((y1 + y2) / 2)))
        return self._screen_point_from_window_point(hwnd, center)

    def _click_point(self, x, y, clicks):
        if self._stop_requested():
            return False

        delay = self._click_delay()
        try:
            win32api.SetCursorPos((int(x), int(y)))
        except Exception:
            pydirectinput.moveTo(int(x), int(y), duration=0)

        if delay > 0 and not self._sleep_interruptible(delay):
            return False

        for _ in range(max(1, int(clicks))):
            if self._stop_requested():
                return False
            try:
                pydirectinput.mouseDown()
                pydirectinput.mouseUp()
            except Exception:
                pydirectinput.click()
            if delay > 0 and not self._sleep_interruptible(delay):
                return False

        return not self._stop_requested()

    def _draw_drop_debug(self, image, grid, item_result, action=None):
        debug = draw_item_debug(image, grid, item_result)
        if action is None:
            return debug

        draw = ImageDraw.Draw(debug)
        try:
            draw.rectangle(grid.slots[action.slot_index].box, outline=(255, 255, 0), width=4)
            x1, y1, _, _ = grid.slots[action.slot_index].box
            draw.text((x1 + 2, y1 + 18), "NEXT DROP", fill=(255, 255, 0))
        except Exception:
            pass
        return debug

    def _pil_to_bgr(self, image):
        rgb = np.array(image.convert("RGB"))
        return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)

    def _prepare_templates(self, templates):
        prepared = []
        for template in templates:
            if self._stop_requested():
                break
            try:
                prepared.append(
                    PreparedDropTemplate(
                        name=template.name,
                        path=template.path,
                        bgr=self._pil_to_bgr(template.image),
                    )
                )
            except Exception as error:
                print(f"Inventory drop template prepare failed: {template.path} - {error}")
        return prepared

    def _score_template_in_roi(self, roi_bgr, prepared_template):
        roi_h, roi_w = roi_bgr.shape[:2]
        template = prepared_template.bgr
        temp_h, temp_w = template.shape[:2]
        best = None

        for scale in FAST_MATCH_SCALES:
            if self._stop_requested():
                return None

            width = int(round(temp_w * float(scale)))
            height = int(round(temp_h * float(scale)))

            if width < 4 or height < 4 or width > roi_w or height > roi_h:
                continue

            try:
                resized = cv2.resize(template, (width, height), interpolation=cv2.INTER_AREA)
                result = cv2.matchTemplate(roi_bgr, resized, cv2.TM_CCOEFF_NORMED)
                _, score, _, loc = cv2.minMaxLoc(result)
                score = float(score)
                if np.isfinite(score) and (best is None or score > best[0]):
                    best = (score, int(loc[0]), int(loc[1]), width, height)
            except Exception:
                continue

        return best

    def _slot_for_point(self, grid, x, y):
        for slot in grid.slots:
            x1, y1, x2, y2 = slot.box
            if x1 <= x <= x2 and y1 <= y <= y2:
                return slot
        return None

    def _first_matching_slot(self, image, grid, prepared_templates, threshold):
        if self._stop_requested():
            return None, None

        try:
            gx1, gy1, gx2, gy2 = [int(v) for v in grid.box]
        except Exception:
            gx1 = min(slot.box[0] for slot in grid.slots)
            gy1 = min(slot.box[1] for slot in grid.slots)
            gx2 = max(slot.box[2] for slot in grid.slots)
            gy2 = max(slot.box[3] for slot in grid.slots)

        source_bgr = self._pil_to_bgr(image)
        roi_bgr = source_bgr[max(0, gy1):max(0, gy2), max(0, gx1):max(0, gx2)]
        if roi_bgr.size == 0:
            return InventoryItemProbeResult(matches=[], template_count=len(prepared_templates), scanned_slots=0), None

        best = None
        for prepared in prepared_templates:
            if self._stop_requested():
                return None, None

            scored = self._score_template_in_roi(roi_bgr, prepared)
            if scored is None:
                continue

            score, rx, ry, width, height = scored
            if best is None or score > best[0]:
                best = (score, prepared, int(gx1 + rx), int(gy1 + ry), width, height)

        if best is None or best[0] < float(threshold):
            return InventoryItemProbeResult(
                matches=[],
                template_count=len(prepared_templates),
                scanned_slots=len(grid.slots),
            ), None

        score, prepared, x, y, width, height = best
        center_x = int(x + width / 2)
        center_y = int(y + height / 2)
        slot = self._slot_for_point(grid, center_x, center_y)
        if slot is None:
            return InventoryItemProbeResult(
                matches=[],
                template_count=len(prepared_templates),
                scanned_slots=len(grid.slots),
            ), None

        match = SlotItemMatch(
            slot_index=slot.index,
            row=slot.row,
            col=slot.col,
            box=slot.box,
            item_name=prepared.name,
            template_path=prepared.path,
            score=float(score),
        )
        item_result = InventoryItemProbeResult(
            matches=[match],
            template_count=len(prepared_templates),
            scanned_slots=len(grid.slots),
        )
        return item_result, match

    def _confirm_yes_if_needed(self, pid, hwnd, grid):
        if self._stop_requested():
            return "STOP_REQUESTED"

        if not self._confirm_enabled():
            return "OK"

        around_box = getattr(grid, "box", None)
        confirmed = click_drop_yes_if_visible(
            pid=pid,
            hwnd=hwnd,
            timeout=self._confirm_timeout(),
            threshold=self._confirm_threshold(),
            paths_text=self._confirm_template_paths(),
            around_box=around_box,
            stop_check=self._stop_requested,
        )

        if self._stop_requested():
            return "STOP_REQUESTED"

        if confirmed:
            print("Inventory drop confirm YES clicked")
            return "OK"

        print("Inventory drop confirm YES was not clicked")
        return "OK" if not self._confirm_strict() else "CONFIRM_FAILED"

    def _execute_drop(self, action, pid, hwnd, grid):
        if self._stop_requested():
            return "STOP_REQUESTED"

        slot_x, slot_y = action.slot_screen
        target_x, target_y = action.target_screen
        clicks = self._clicks_per_point()

        print(
            "Inventory drop executing - "
            f"slot={action.slot_index + 1} - item={action.item_name!r} - "
            f"score={action.score:.3f} - slot_xy={action.slot_screen} - "
            f"target_xy={action.target_screen} - target_mode={self._target_mode()} - clicks={clicks}"
        )

        if not self._click_point(slot_x, slot_y, clicks):
            return "STOP_REQUESTED"

        if not self._click_point(target_x, target_y, clicks):
            return "STOP_REQUESTED"

        after_drop = self._after_drop_delay()
        if after_drop > 0 and not self._sleep_interruptible(after_drop):
            return "STOP_REQUESTED"

        return self._confirm_yes_if_needed(pid, hwnd, grid)

    def _scan_next_drop(self, pid, hwnd, grid, prepared_templates):
        if self._stop_requested():
            return None, hwnd, grid, None, None, "STOP_REQUESTED"

        image, hwnd = self._capture_current_window(pid, hwnd)
        if image is None or not hwnd:
            return None, hwnd, grid, None, None, "CAPTURE_FAILED"

        item_result, match = self._first_matching_slot(
            image=image,
            grid=grid,
            prepared_templates=prepared_templates,
            threshold=self._threshold(),
        )

        if self._stop_requested():
            return image, hwnd, grid, item_result, None, "STOP_REQUESTED"

        if item_result is None:
            return image, hwnd, grid, None, None, "STOP_REQUESTED"

        if match is None:
            return image, hwnd, grid, item_result, None, "NO_MATCH"

        action = DropAction(
            slot_index=match.slot_index,
            item_name=match.item_name,
            score=match.score,
            slot_screen=self._slot_center_screen(hwnd, match.box),
            target_screen=self._drop_target_screen(hwnd),
        )
        return image, hwnd, grid, item_result, action, "OK"

    def run(self, account_index, session):
        if not self.enabled():
            return "SKIPPED"

        if self._stop_requested():
            return "STOP_REQUESTED"

        pid = session.get("pid")
        page_name = session.get("page_name", "")
        if not pid:
            return "INVENTORY_DROP_NO_PID"

        templates_dir = self._templates_dir()
        templates = load_item_templates(templates_dir)
        if not templates:
            print("Inventory drop skipped - no drop templates - " f"folder={templates_dir!r}")
            return "OK"

        prepared_templates = self._prepare_templates(templates)
        if self._stop_requested():
            return "STOP_REQUESTED"
        if not prepared_templates:
            print("Inventory drop skipped - no usable prepared templates")
            return "OK"

        image, hwnd = capture_pid_window(pid)
        if image is None or not hwnd:
            return "INVENTORY_DROP_CAPTURE_FAILED"

        grid = detect_inventory_grid(image)
        if grid is None:
            print(
                "Inventory drop skipped - bag/grid not detected before rescan - "
                f"account={account_index + 1} - pid={pid} - hwnd={hwnd} - name={page_name!r}"
            )
            try:
                self._save_image(draw_failure_debug(image), "grid_not_found", account_index, pid)
            except Exception as error:
                print(f"Inventory drop failure image save failed: {error}")
            return "OK"

        max_items = self._max_items()
        threshold = self._threshold()
        print(
            "Inventory fast rescan-drop pass started - "
            f"account={account_index + 1} - pid={pid} - name={page_name!r} - "
            f"templates={len(prepared_templates)} - max_items={max_items} - threshold={threshold:.2f}"
        )

        dropped = 0
        last_scanned_slots = 0

        while dropped < max_items:
            if self._stop_requested():
                print(
                    "Inventory drop stopped by user - "
                    f"account={account_index + 1} - dropped={dropped}"
                )
                return "STOP_REQUESTED"

            image, hwnd, grid, item_result, action, scan_status = self._scan_next_drop(
                pid=pid,
                hwnd=hwnd,
                grid=grid,
                prepared_templates=prepared_templates,
            )

            if scan_status == "STOP_REQUESTED":
                print(
                    "Inventory drop stopped by user during scan - "
                    f"account={account_index + 1} - dropped={dropped}"
                )
                return "STOP_REQUESTED"

            if scan_status == "CAPTURE_FAILED" or image is None or not hwnd:
                return "INVENTORY_DROP_CAPTURE_FAILED"

            last_scanned_slots = getattr(item_result, "scanned_slots", 0) if item_result is not None else 0

            if action is None:
                print(
                    "Inventory drop complete - no matched target items remain - "
                    f"account={account_index + 1} - dropped={dropped} - scanned_slots={last_scanned_slots}"
                )
                break

            print(
                "Inventory drop rescan - "
                f"account={account_index + 1} - scanned_slots={last_scanned_slots} - "
                f"next_slot={action.slot_index + 1} - next_item={action.item_name!r} - score={action.score:.3f}"
            )

            try:
                self._save_image(
                    self._draw_drop_debug(image, grid, item_result, action),
                    f"before_drop_{dropped + 1:02d}",
                    account_index,
                    pid,
                )
            except Exception as error:
                print(f"Inventory drop before-drop debug save failed: {error}")

            execute_result = self._execute_drop(action, pid, hwnd, grid)
            if execute_result == "STOP_REQUESTED":
                print(
                    "Inventory drop stopped by user during click/confirm - "
                    f"account={account_index + 1} - dropped={dropped}"
                )
                return "STOP_REQUESTED"
            if execute_result == "CONFIRM_FAILED":
                return "INVENTORY_DROP_CONFIRM_YES_FAILED"

            dropped += 1

        try:
            if self._save_debug_enabled():
                after_image, _ = self._capture_current_window(pid, hwnd)
                if after_image is not None:
                    self._save_image(after_image, "after_drop_rescan", account_index, pid)
        except Exception as error:
            print(f"Inventory drop after-drop image save failed: {error}")

        print(
            "Inventory drop worker OK - "
            f"account={account_index + 1} - pid={pid} - name={page_name!r} - "
            f"dropped={dropped} - last_scanned_slots={last_scanned_slots} - threshold={threshold:.2f}"
        )
        return "OK"
