import os
import time
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache

import cv2
import numpy as np
import pydirectinput
import win32api
import win32con
import win32gui
from PIL import Image, ImageDraw

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


SASH_ITEM_MATCH_SCALES = (1.00,)
SASH_BUTTON_MATCH_SCALES = (0.94, 0.97, 1.00, 1.03, 1.06)
DEFAULT_SASH_BUTTON_PATHS = (
    os.path.join("assets", "sash_button.png"),
    os.path.join("assets", "Sash.png"),
    os.path.join("assets", "sash.png"),
    os.path.join("assets", "sash_open.png"),
)


@dataclass
class SashAction:
    slot_index: int
    item_name: str
    score: float
    slot_screen: tuple[int, int]
    slot_box: tuple[int, int, int, int]


@dataclass
class SashButtonMatch:
    score: float
    center_screen: tuple[int, int]
    source: str


@dataclass
class PreparedSashTemplate:
    name: str
    path: str
    bgr: object


@lru_cache(maxsize=32)
def _load_button_image(path):
    try:
        if not os.path.isfile(path):
            return None
        return Image.open(path).convert("RGB")
    except Exception as error:
        print(f"Sash button image load failed: {path} - {error}")
        return None


class InventorySashWorkerModule:
    """Move selected inventory items into Sash after Use.

    Rule:
      - works only for accounts where the saved Sash checkbox is enabled
      - reads item templates from assets/sash_items
      - opens Sash by external button image
      - transfers one matched item at a time with Alt + left click
      - rescans after every transfer

    This is a post-login module only. It does not touch Login typing or recovery.
    """

    name = "inventory_sash_worker"
    setting_key = "enable_inventory_sash_worker"

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

    def _bool_value(self, value, default=False):
        if isinstance(value, bool):
            return value
        text = str(value if value is not None else "").strip().lower()
        if text in {"1", "true", "yes", "on", "enabled"}:
            return True
        if text in {"0", "false", "no", "off", "disabled"}:
            return False
        return bool(default)

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

    def _account_sash_enabled(self, account_index, session):
        if isinstance(session, dict) and "sash_enabled" in session:
            return self._bool_value(session.get("sash_enabled"), False)

        try:
            accounts = getattr(self.launcher, "accounts_data", [])
            if 0 <= account_index < len(accounts):
                return self._bool_value(accounts[account_index].get("sash_enabled"), False)
        except Exception:
            pass

        try:
            row = self.launcher.account_rows[account_index]
            var = row.get("sash_enabled_var")
            if var is not None:
                return bool(var.get())
        except Exception:
            pass

        return False

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
        value = self._setting("inventory_sash_templates_dir", os.path.join("assets", "sash_items"))
        text = str(value or os.path.join("assets", "sash_items")).strip()
        return text or os.path.join("assets", "sash_items")

    def _threshold(self):
        return self._float_setting(
            "inventory_sash_match_threshold",
            max(0.88, DEFAULT_MATCH_THRESHOLD),
            minimum=0.10,
            maximum=0.99,
        )

    def _button_threshold(self):
        return self._float_setting("inventory_sash_button_threshold", 0.80, minimum=0.10, maximum=0.99)

    def _max_items(self):
        return self._int_setting("inventory_sash_max_items_per_account", 20, minimum=1, maximum=40)

    def _click_delay(self):
        return self._float_setting("inventory_sash_click_delay", 0.10, minimum=0.0, maximum=1.0)

    def _after_transfer_delay(self):
        return self._float_setting("inventory_sash_after_transfer_delay", 0.18, minimum=0.0, maximum=3.0)

    def _open_wait(self):
        return self._float_setting("inventory_sash_open_wait_seconds", 0.25, minimum=0.0, maximum=3.0)

    def _require_button(self):
        return self._feature_enabled("inventory_sash_require_button", False)

    def _button_paths_text(self):
        return str(self._setting("inventory_sash_button_paths", "") or "")

    def _save_debug_enabled(self):
        return self._feature_enabled("inventory_sash_save_debug_image", False)

    def _debug_dir(self):
        value = self._setting("inventory_sash_debug_dir", "logs/inventory_sash_worker")
        text = str(value or "logs/inventory_sash_worker").strip()
        return text or "logs/inventory_sash_worker"

    def _button_paths(self):
        paths = list(DEFAULT_SASH_BUTTON_PATHS)
        extra = self._button_paths_text().replace(";", "\n").splitlines()
        for item in extra:
            text = item.strip()
            if text and text not in paths:
                paths.append(text)
        return paths

    def _save_image(self, image, prefix, account_index, pid):
        if not self._save_debug_enabled() or image is None:
            return None
        folder = self._debug_dir()
        os.makedirs(folder, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(folder, f"{prefix}_account_{account_index + 1}_pid_{pid}_{stamp}.png")
        image.save(path)
        print(f"Inventory sash debug image saved: {path}")
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

    def _slot_center_screen(self, hwnd, box):
        x1, y1, x2, y2 = box
        center = (int(round((x1 + x2) / 2)), int(round((y1 + y2) / 2)))
        return self._screen_point_from_window_point(hwnd, center)

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
                    PreparedSashTemplate(
                        name=template.name,
                        path=template.path,
                        bgr=self._pil_to_bgr(template.image),
                    )
                )
            except Exception as error:
                print(f"Inventory sash template prepare failed: {template.path} - {error}")
        return prepared

    def _score_template_in_roi(self, roi_bgr, prepared_template):
        roi_h, roi_w = roi_bgr.shape[:2]
        template = prepared_template.bgr
        temp_h, temp_w = template.shape[:2]
        best = None

        for scale in SASH_ITEM_MATCH_SCALES:
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
            return InventoryItemProbeResult(matches=[], template_count=len(prepared_templates), scanned_slots=len(grid.slots)), None

        score, prepared, x, y, width, height = best
        center_x = int(x + width / 2)
        center_y = int(y + height / 2)
        slot = self._slot_for_point(grid, center_x, center_y)
        if slot is None:
            return InventoryItemProbeResult(matches=[], template_count=len(prepared_templates), scanned_slots=len(grid.slots)), None

        match = SlotItemMatch(
            slot_index=slot.index,
            row=slot.row,
            col=slot.col,
            box=slot.box,
            item_name=prepared.name,
            template_path=prepared.path,
            score=float(score),
        )
        item_result = InventoryItemProbeResult(matches=[match], template_count=len(prepared_templates), scanned_slots=len(grid.slots))
        return item_result, match

    def _find_sash_button(self, image, hwnd):
        source = self._pil_to_bgr(image)
        src_h, src_w = source.shape[:2]
        threshold = self._button_threshold()
        best = None

        for path in self._button_paths():
            template_image = _load_button_image(path)
            if template_image is None:
                continue

            template = self._pil_to_bgr(template_image)
            temp_h, temp_w = template.shape[:2]
            for scale in SASH_BUTTON_MATCH_SCALES:
                if self._stop_requested():
                    return None
                width = int(round(temp_w * float(scale)))
                height = int(round(temp_h * float(scale)))
                if width < 6 or height < 6 or width > src_w or height > src_h:
                    continue
                try:
                    resized = cv2.resize(template, (width, height), interpolation=cv2.INTER_AREA)
                    result = cv2.matchTemplate(source, resized, cv2.TM_CCOEFF_NORMED)
                    _, score, _, loc = cv2.minMaxLoc(result)
                    score = float(score)
                    if np.isfinite(score) and (best is None or score > best[0]):
                        best = (score, int(loc[0]), int(loc[1]), width, height, path)
                except Exception:
                    continue

        if best is None:
            print("Sash button not found - no external button image loaded")
            return None

        score, x, y, width, height, path = best
        if score < threshold:
            print(f"Sash button not found - best={score:.3f} threshold={threshold:.3f} source={path}")
            return None

        center_window = (int(x + width / 2), int(y + height / 2))
        center_screen = self._screen_point_from_window_point(hwnd, center_window)
        return SashButtonMatch(score=float(score), center_screen=center_screen, source=path)

    def _left_click_point(self, x, y):
        if self._stop_requested():
            return False
        delay = self._click_delay()
        try:
            win32api.SetCursorPos((int(x), int(y)))
        except Exception:
            pydirectinput.moveTo(int(x), int(y), duration=0)
        if delay > 0 and not self._sleep_interruptible(delay):
            return False
        try:
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
            time.sleep(0.025)
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        except Exception:
            pydirectinput.click()
        if delay > 0 and not self._sleep_interruptible(delay):
            return False
        return not self._stop_requested()

    def _alt_left_click_point(self, x, y):
        if self._stop_requested():
            return False
        delay = self._click_delay()
        try:
            win32api.SetCursorPos((int(x), int(y)))
        except Exception:
            pydirectinput.moveTo(int(x), int(y), duration=0)
        if delay > 0 and not self._sleep_interruptible(delay):
            return False

        try:
            pydirectinput.keyDown("alt")
            time.sleep(0.025)
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
            time.sleep(0.025)
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        except Exception:
            try:
                pydirectinput.click()
            except Exception:
                return False
        finally:
            try:
                pydirectinput.keyUp("alt")
            except Exception:
                pass

        if delay > 0 and not self._sleep_interruptible(delay):
            return False
        return not self._stop_requested()

    def _move_mouse_clear(self, hwnd):
        try:
            x = self._int_setting("inventory_sash_mouse_clear_x", 900, minimum=0, maximum=4000)
            y = self._int_setting("inventory_sash_mouse_clear_y", 500, minimum=0, maximum=4000)
            sx, sy = win32gui.ClientToScreen(hwnd, (x, y))
            win32api.SetCursorPos((int(sx), int(sy)))
        except Exception:
            pass

    def _draw_sash_debug(self, image, grid, item_result, action=None):
        debug = draw_item_debug(image, grid, item_result)
        if action is None:
            return debug
        draw = ImageDraw.Draw(debug)
        try:
            draw.rectangle(action.slot_box, outline=(255, 128, 0), width=4)
            x1, y1, _, _ = action.slot_box
            draw.text((x1 + 2, y1 + 18), "NEXT SASH", fill=(255, 128, 0))
        except Exception:
            pass
        return debug

    def _scan_next_sash(self, pid, hwnd, grid, prepared_templates):
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

        action = SashAction(
            slot_index=match.slot_index,
            item_name=match.item_name,
            score=match.score,
            slot_screen=self._slot_center_screen(hwnd, match.box),
            slot_box=match.box,
        )
        return image, hwnd, grid, item_result, action, "OK"

    def _open_sash_before_transfer(self, pid, hwnd):
        image, hwnd = self._capture_current_window(pid, hwnd)
        if image is None or not hwnd:
            return False, hwnd, "CAPTURE_FAILED"

        match = self._find_sash_button(image, hwnd)
        if match is None:
            if self._require_button():
                return False, hwnd, "SASH_BUTTON_NOT_FOUND"
            print("Sash skipped safely - button image not found/matched. Add assets\\sash_button.png")
            return False, hwnd, "SKIP_NO_BUTTON"

        print(
            "Sash button found - "
            f"score={match.score:.3f} - xy={match.center_screen} - source={match.source}"
        )
        if not self._left_click_point(match.center_screen[0], match.center_screen[1]):
            return False, hwnd, "STOP_REQUESTED"
        if self._open_wait() > 0 and not self._sleep_interruptible(self._open_wait()):
            return False, hwnd, "STOP_REQUESTED"
        return True, hwnd, "OK"

    def _execute_sash(self, action, hwnd):
        if self._stop_requested():
            return "STOP_REQUESTED"

        print(
            "Inventory sash executing - "
            f"slot={action.slot_index + 1} - item={action.item_name!r} - "
            f"score={action.score:.3f} - slot_xy={action.slot_screen} - action=ALT_LEFT_CLICK"
        )

        if not self._alt_left_click_point(action.slot_screen[0], action.slot_screen[1]):
            return "STOP_REQUESTED"

        after_transfer = self._after_transfer_delay()
        if after_transfer > 0 and not self._sleep_interruptible(after_transfer):
            return "STOP_REQUESTED"

        self._move_mouse_clear(hwnd)
        return "OK"

    def run(self, account_index, session):
        if not self.enabled():
            return "SKIPPED"

        if not self._account_sash_enabled(account_index, session or {}):
            print(f"Inventory sash skipped - account={account_index + 1} - sash_checkbox=false")
            return "OK"

        if self._stop_requested():
            return "STOP_REQUESTED"

        pid = (session or {}).get("pid")
        page_name = (session or {}).get("page_name", "")
        if not pid:
            return "INVENTORY_SASH_NO_PID"

        templates_dir = self._templates_dir()
        templates = load_item_templates(templates_dir)
        if not templates:
            print("Inventory sash skipped - no sash item templates - " f"folder={templates_dir!r}")
            return "OK"

        prepared_templates = self._prepare_templates(templates)
        if self._stop_requested():
            return "STOP_REQUESTED"
        if not prepared_templates:
            print("Inventory sash skipped - no usable prepared templates")
            return "OK"

        image, hwnd = capture_pid_window(pid)
        if image is None or not hwnd:
            return "INVENTORY_SASH_CAPTURE_FAILED"

        grid = detect_inventory_grid(image)
        if grid is None:
            print(
                "Inventory sash skipped - bag/grid not detected - "
                f"account={account_index + 1} - pid={pid} - hwnd={hwnd} - name={page_name!r}"
            )
            try:
                self._save_image(draw_failure_debug(image), "grid_not_found", account_index, pid)
            except Exception as error:
                print(f"Inventory sash failure image save failed: {error}")
            return "OK"

        # First scan before opening Sash. If there is nothing to transfer, do not click the Sash button.
        image, hwnd, grid, item_result, action, scan_status = self._scan_next_sash(pid, hwnd, grid, prepared_templates)
        if scan_status == "STOP_REQUESTED":
            return "STOP_REQUESTED"
        if scan_status == "CAPTURE_FAILED" or image is None or not hwnd:
            return "INVENTORY_SASH_CAPTURE_FAILED"
        if action is None:
            scanned = getattr(item_result, "scanned_slots", 0) if item_result is not None else 0
            print(
                "Inventory sash complete - no matched sash items - "
                f"account={account_index + 1} - scanned_slots={scanned}"
            )
            return "OK"

        opened, hwnd, open_status = self._open_sash_before_transfer(pid, hwnd)
        if open_status == "STOP_REQUESTED":
            return "STOP_REQUESTED"
        if open_status == "CAPTURE_FAILED":
            return "INVENTORY_SASH_CAPTURE_FAILED"
        if not opened:
            return "OK"

        max_items = self._max_items()
        threshold = self._threshold()
        print(
            "Inventory sash pass started - "
            f"account={account_index + 1} - pid={pid} - name={page_name!r} - "
            f"templates={len(prepared_templates)} - max_items={max_items} - threshold={threshold:.2f}"
        )

        transferred = 0
        last_key = None
        same_key_repeats = 0
        last_scanned_slots = 0

        while transferred < max_items:
            if self._stop_requested():
                print("Inventory sash stopped by user - " f"account={account_index + 1} - transferred={transferred}")
                return "STOP_REQUESTED"

            if transferred > 0:
                image, hwnd, grid, item_result, action, scan_status = self._scan_next_sash(
                    pid=pid,
                    hwnd=hwnd,
                    grid=grid,
                    prepared_templates=prepared_templates,
                )

            if scan_status == "STOP_REQUESTED":
                return "STOP_REQUESTED"
            if scan_status == "CAPTURE_FAILED" or image is None or not hwnd:
                return "INVENTORY_SASH_CAPTURE_FAILED"

            last_scanned_slots = getattr(item_result, "scanned_slots", 0) if item_result is not None else 0
            if action is None:
                print(
                    "Inventory sash complete - no matched sash items remain - "
                    f"account={account_index + 1} - transferred={transferred} - scanned_slots={last_scanned_slots}"
                )
                break

            key = (action.slot_index, action.item_name)
            if key == last_key:
                same_key_repeats += 1
            else:
                last_key = key
                same_key_repeats = 0

            if same_key_repeats >= 2:
                print(
                    "Inventory sash stopped safely - same item did not move; Sash may be full - "
                    f"account={account_index + 1} - slot={action.slot_index + 1} - item={action.item_name!r}"
                )
                break

            print(
                "Inventory sash rescan - "
                f"account={account_index + 1} - scanned_slots={last_scanned_slots} - "
                f"next_slot={action.slot_index + 1} - next_item={action.item_name!r} - score={action.score:.3f}"
            )

            try:
                self._save_image(
                    self._draw_sash_debug(image, grid, item_result, action),
                    f"before_sash_{transferred + 1:02d}",
                    account_index,
                    pid,
                )
            except Exception as error:
                print(f"Inventory sash before-transfer debug save failed: {error}")

            execute_result = self._execute_sash(action, hwnd)
            if execute_result == "STOP_REQUESTED":
                print("Inventory sash stopped by user during transfer - " f"account={account_index + 1}")
                return "STOP_REQUESTED"

            transferred += 1

        try:
            if self._save_debug_enabled():
                after_image, _ = self._capture_current_window(pid, hwnd)
                if after_image is not None:
                    self._save_image(after_image, "after_sash", account_index, pid)
        except Exception as error:
            print(f"Inventory sash after image save failed: {error}")

        print(
            "Inventory sash worker OK - "
            f"account={account_index + 1} - pid={pid} - name={page_name!r} - "
            f"transferred={transferred} - last_scanned_slots={last_scanned_slots} - threshold={threshold:.2f}"
        )
        return "OK"
