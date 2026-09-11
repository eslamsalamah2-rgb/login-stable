import os
import time
from dataclasses import dataclass
from datetime import datetime

import pydirectinput
import win32gui
from PIL import ImageDraw

from tasks.post_login_modules.drop_confirmation import click_drop_yes_if_visible
from tasks.post_login_modules.inventory_grid_probe import (
    detect_inventory_grid,
    draw_failure_debug,
)
from tasks.post_login_modules.inventory_item_probe import (
    DEFAULT_MATCH_THRESHOLD,
    draw_item_debug,
    load_item_templates,
    probe_items,
)
from tasks.post_login_modules.window_capture import capture_pid_window


@dataclass
class DropAction:
    slot_index: int
    item_name: str
    score: float
    slot_screen: tuple[int, int]
    target_screen: tuple[int, int]


class InventoryDropWorkerModule:
    """Drop only matched target items from the current account inventory.

    Important behavior:
      - scan the current bag
      - choose one matched item only
      - drop it
      - confirm Yes if needed
      - scan again before choosing the next item

    This avoids using stale slot coordinates after the game reorders the bag.
    LoginPriorityGate and AutomationInputLock are owned by the runner before
    this module runs.
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
        return self._float_setting("inventory_drop_click_delay", 0.04, minimum=0.01, maximum=1.0)

    def _after_drop_delay(self):
        return self._float_setting("inventory_drop_after_drop_delay", 0.05, minimum=0.0, maximum=1.0)

    def _target_mode(self):
        return str(self._setting("inventory_drop_target_mode", "top_right") or "top_right").strip().lower()

    def _target_fraction(self):
        x = self._float_setting("inventory_drop_target_x_fraction", 0.50, minimum=0.05, maximum=0.98)
        y = self._float_setting("inventory_drop_target_y_fraction", 0.45, minimum=0.03, maximum=0.90)
        return x, y

    def _target_margins(self):
        x = self._int_setting("inventory_drop_target_margin_x", 2, minimum=1, maximum=300)
        y = self._int_setting("inventory_drop_target_margin_y", 2, minimum=1, maximum=300)
        return x, y

    def _confirm_enabled(self):
        return self._feature_enabled("inventory_drop_confirm_yes_enabled", True)

    def _confirm_strict(self):
        return self._feature_enabled("inventory_drop_confirm_yes_strict", False)

    def _confirm_threshold(self):
        return self._float_setting("inventory_drop_confirm_yes_threshold", 0.76, minimum=0.10, maximum=0.99)

    def _confirm_timeout(self):
        return self._float_setting("inventory_drop_confirm_yes_timeout", 1.0, minimum=0.2, maximum=10.0)

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

    def _screen_point_from_window_point(self, hwnd, point):
        try:
            left, top, _, _ = win32gui.GetWindowRect(hwnd)
        except Exception:
            left, top = 0, 0
        return int(left + point[0]), int(top + point[1])

    def _drop_target_screen(self, hwnd):
        try:
            left, top, right, bottom = win32gui.GetWindowRect(hwnd)
            width = max(1, right - left)
            height = max(1, bottom - top)
        except Exception:
            left, top, width, height = 0, 0, 1920, 1080
            right = left + width
            bottom = top + height

        mode = self._target_mode()
        if mode in {"top_right", "right_top", "upper_right"}:
            margin_x, margin_y = self._target_margins()
            return int(right - margin_x), int(top + margin_y)

        fx, fy = self._target_fraction()
        return int(left + width * fx), int(top + height * fy)

    def _slot_center_screen(self, hwnd, box):
        x1, y1, x2, y2 = box
        center = (int(round((x1 + x2) / 2)), int(round((y1 + y2) / 2)))
        return self._screen_point_from_window_point(hwnd, center)

    def _click_point(self, x, y, clicks):
        delay = self._click_delay()
        pydirectinput.moveTo(int(x), int(y))
        time.sleep(delay)
        for _ in range(max(1, int(clicks))):
            pydirectinput.click(int(x), int(y))
            time.sleep(delay)

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

    def _confirm_yes_if_needed(self, pid, hwnd, grid):
        if not self._confirm_enabled():
            return True

        around_box = getattr(grid, "box", None)
        confirmed = click_drop_yes_if_visible(
            pid=pid,
            hwnd=hwnd,
            timeout=self._confirm_timeout(),
            threshold=self._confirm_threshold(),
            paths_text=self._confirm_template_paths(),
            around_box=around_box,
        )
        if confirmed:
            print("Inventory drop confirm YES clicked")
            return True

        print("Inventory drop confirm YES was not clicked")
        return not self._confirm_strict()

    def _execute_drop(self, action, pid, hwnd, grid):
        slot_x, slot_y = action.slot_screen
        target_x, target_y = action.target_screen
        clicks = self._clicks_per_point()

        print(
            "Inventory drop executing - "
            f"slot={action.slot_index + 1} - item={action.item_name!r} - "
            f"score={action.score:.3f} - slot_xy={action.slot_screen} - "
            f"target_xy={action.target_screen} - target_mode={self._target_mode()} - clicks={clicks}"
        )

        self._click_point(slot_x, slot_y, clicks)
        time.sleep(self._click_delay())
        self._click_point(target_x, target_y, clicks)
        time.sleep(self._after_drop_delay())
        return self._confirm_yes_if_needed(pid, hwnd, grid)

    def _scan_next_drop(self, pid, hwnd, templates):
        image, current_hwnd = capture_pid_window(pid)
        if image is None or not current_hwnd:
            return None, current_hwnd, None, None

        grid = detect_inventory_grid(image)
        if grid is None:
            return image, current_hwnd, None, None

        item_result = probe_items(image, grid, templates, self._threshold())
        if not item_result.matches:
            return image, current_hwnd, grid, item_result

        # Pick one current matched slot only. Do not prepare a list of future
        # slots because the inventory compacts/reorders after every drop.
        match = sorted(item_result.matches, key=lambda item: (item.slot_index, -item.score))[0]
        action = DropAction(
            slot_index=match.slot_index,
            item_name=match.item_name,
            score=match.score,
            slot_screen=self._slot_center_screen(current_hwnd, match.box),
            target_screen=self._drop_target_screen(current_hwnd),
        )
        return image, current_hwnd, grid, (item_result, action)

    def run(self, account_index, session):
        if not self.enabled():
            return "SKIPPED"

        pid = session.get("pid")
        page_name = session.get("page_name", "")
        if not pid:
            return "INVENTORY_DROP_NO_PID"

        templates_dir = self._templates_dir()
        templates = load_item_templates(templates_dir)
        if not templates:
            print("Inventory drop skipped - no drop templates - " f"folder={templates_dir!r}")
            return "OK"

        max_items = self._max_items()
        threshold = self._threshold()
        print(
            "Inventory rescan-drop pass started - "
            f"account={account_index + 1} - pid={pid} - name={page_name!r} - "
            f"templates={len(templates)} - max_items={max_items} - threshold={threshold:.2f}"
        )

        dropped = 0
        last_matches = 0
        last_hwnd = None

        while dropped < max_items:
            image, hwnd, grid, scan_result = self._scan_next_drop(pid, last_hwnd, templates)
            if image is None or not hwnd:
                return "INVENTORY_DROP_CAPTURE_FAILED"
            last_hwnd = hwnd

            if grid is None:
                print(
                    "Inventory drop skipped - bag/grid not detected during rescan - "
                    f"account={account_index + 1} - pid={pid} - hwnd={hwnd} - name={page_name!r}"
                )
                try:
                    self._save_image(draw_failure_debug(image), "grid_not_found", account_index, pid)
                except Exception as error:
                    print(f"Inventory drop failure image save failed: {error}")
                break

            if scan_result is None:
                print(
                    "Inventory drop complete - no matched target items remain - "
                    f"account={account_index + 1} - dropped={dropped}"
                )
                break

            item_result, action = scan_result
            last_matches = len(item_result.matches)
            print(
                "Inventory drop rescan - "
                f"account={account_index + 1} - remaining_matches={last_matches} - "
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

            if not self._execute_drop(action, pid, hwnd, grid):
                return "INVENTORY_DROP_CONFIRM_YES_FAILED"

            dropped += 1

        try:
            after_image, _ = capture_pid_window(pid)
            if after_image is not None:
                self._save_image(after_image, "after_drop_rescan", account_index, pid)
        except Exception as error:
            print(f"Inventory drop after-drop image save failed: {error}")

        print(
            "Inventory drop worker OK - "
            f"account={account_index + 1} - pid={pid} - name={page_name!r} - "
            f"dropped={dropped} - last_matches={last_matches} - threshold={threshold:.2f}"
        )
        return "OK"
