import os
import time
from datetime import datetime

import pydirectinput
from PIL import ImageDraw

from tasks.post_login_modules.inventory_anchor import find_inventory_anchor
from tasks.post_login_modules.inventory_grid_probe import (
    detect_inventory_grid,
    draw_failure_debug,
    draw_grid_debug,
)
from tasks.post_login_modules.window_capture import capture_pid_window


class InventoryEnsureOpenModule:
    """Make sure the current account's inventory is open before later work.

    Important rule:
      - Open/closed detection uses ONLY the manual image anchor from the bag UI
        such as assets/inventory_open.png.
      - It must not use the line-grid fallback as proof that the bag is open,
        because other UI/game objects can accidentally look like a grid.

    If the manual anchor is not found, the module presses the configured
    inventory hotkey and then verifies the same anchor again.
    """

    name = "inventory_ensure_open"
    setting_key = "enable_inventory_ensure_open"

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

    def _int_setting(self, key, default, minimum=1):
        try:
            value = int(float(self._setting(key, default)))
        except Exception:
            value = int(default)
        return max(int(minimum), value)

    def _float_setting(self, key, default, minimum=0.1):
        try:
            value = float(self._setting(key, default))
        except Exception:
            value = float(default)
        return max(float(minimum), value)

    def enabled(self):
        return self._feature_enabled(self.setting_key, True)

    def _save_debug_enabled(self):
        return self._feature_enabled("inventory_open_probe_save_debug_image", True)

    def _debug_dir(self):
        value = self._setting("inventory_open_probe_debug_dir", "logs/inventory_open_probe")
        text = str(value or "logs/inventory_open_probe").strip()
        return text or "logs/inventory_open_probe"

    def _hotkey(self):
        text = str(self._setting("inventory_open_hotkey", "i") or "i").strip().lower()
        return text or "i"

    def _attempts(self):
        return self._int_setting("inventory_open_attempts", 2, minimum=1)

    def _wait_seconds(self):
        return self._float_setting("inventory_open_wait_seconds", 0.80, minimum=0.2)

    def _strict(self):
        # Keep false during visual merge tests so the runner keeps rotating even
        # if the hotkey needs adjustment. Later Drop modules can set this true.
        return self._feature_enabled("inventory_open_strict", False)

    def _save_image(self, image, prefix, account_index, pid):
        if not self._save_debug_enabled() or image is None:
            return None

        folder = self._debug_dir()
        os.makedirs(folder, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(
            folder,
            f"{prefix}_account_{account_index + 1}_pid_{pid}_{stamp}.png",
        )
        image.save(path)
        print(f"Inventory open probe debug image saved: {path}")
        return path

    def _draw_anchor_debug(self, image, anchor, label):
        debug = image.copy()
        draw = ImageDraw.Draw(debug)
        if anchor is not None:
            draw.rectangle(anchor.anchor_box, outline=(255, 215, 0), width=3)
            draw.rectangle(anchor.grid_box, outline=(80, 255, 80), width=3)
            x1, y1, _, _ = anchor.anchor_box
            draw.text((x1 + 3, y1 - 14 if y1 >= 16 else y1 + 32), label, fill=(255, 215, 0))
        return debug

    def _capture_and_check_anchor(self, pid):
        image, hwnd = capture_pid_window(pid)
        if image is None:
            return None, hwnd, None, None

        # This is the only open/closed decision.
        anchor = find_inventory_anchor(image)

        # Grid debug is useful only after the real bag anchor is visible.
        grid_result = None
        if anchor is not None:
            try:
                grid_result = detect_inventory_grid(image)
            except Exception as error:
                print(f"Inventory grid check after anchor failed: {error}")

        return image, hwnd, anchor, grid_result

    def _press_hotkey(self, hotkey):
        parts = [part.strip() for part in str(hotkey).replace("+", " ").split() if part.strip()]
        if not parts:
            parts = ["i"]

        if len(parts) == 1:
            pydirectinput.press(parts[0])
            return

        modifiers = parts[:-1]
        key = parts[-1]
        try:
            for modifier in modifiers:
                pydirectinput.keyDown(modifier)
                time.sleep(0.03)
            pydirectinput.press(key)
        finally:
            for modifier in reversed(modifiers):
                try:
                    pydirectinput.keyUp(modifier)
                except Exception:
                    pass

    def _save_open_debug(self, image, anchor, grid_result, prefix, account_index, pid):
        if grid_result is not None:
            self._save_image(draw_grid_debug(image, grid_result), prefix, account_index, pid)
        elif anchor is not None:
            self._save_image(self._draw_anchor_debug(image, anchor, "ANCHOR FOUND"), prefix, account_index, pid)
        else:
            self._save_image(draw_failure_debug(image), prefix, account_index, pid)

    def run(self, account_index, session):
        if not self.enabled():
            return "SKIPPED"

        pid = session.get("pid")
        page_name = session.get("page_name", "")
        if not pid:
            return "INVENTORY_ENSURE_OPEN_NO_PID"

        image, hwnd, anchor, grid_result = self._capture_and_check_anchor(pid)
        if image is None:
            return "INVENTORY_ENSURE_OPEN_CAPTURE_FAILED"

        if anchor is not None:
            print(
                "Inventory already open by image anchor - "
                f"account={account_index + 1} - pid={pid} - hwnd={hwnd} - "
                f"name={page_name!r} - anchor={anchor.anchor_box} - "
                f"grid={anchor.grid_box} - score={anchor.score:.3f}"
            )
            try:
                self._save_open_debug(image, anchor, grid_result, "already_open", account_index, pid)
            except Exception as error:
                print(f"Inventory open probe already-open debug save failed: {error}")
            return "OK"

        print(
            "Inventory anchor not detected - pressing hotkey - "
            f"account={account_index + 1} - pid={pid} - hwnd={hwnd} - "
            f"name={page_name!r} - hotkey={self._hotkey()!r}"
        )
        try:
            self._save_image(draw_failure_debug(image), "before_open", account_index, pid)
        except Exception as error:
            print(f"Inventory open probe before-open debug save failed: {error}")

        last_image = image
        last_hwnd = hwnd
        last_anchor = None
        last_grid_result = None
        hotkey = self._hotkey()
        wait_seconds = self._wait_seconds()

        for attempt in range(1, self._attempts() + 1):
            try:
                self._press_hotkey(hotkey)
                print(
                    "Inventory hotkey pressed - "
                    f"account={account_index + 1} - attempt={attempt}/{self._attempts()} - hotkey={hotkey!r}"
                )
            except Exception as error:
                print(
                    "Inventory hotkey press failed - "
                    f"account={account_index + 1} - hotkey={hotkey!r} - {error}"
                )
                return "INVENTORY_OPEN_HOTKEY_FAILED" if self._strict() else "OK"

            time.sleep(wait_seconds)

            last_image, last_hwnd, last_anchor, last_grid_result = self._capture_and_check_anchor(pid)
            if last_image is None:
                return "INVENTORY_ENSURE_OPEN_CAPTURE_FAILED"

            if last_anchor is not None:
                print(
                    "Inventory opened by image anchor - "
                    f"account={account_index + 1} - pid={pid} - hwnd={last_hwnd} - "
                    f"attempt={attempt} - anchor={last_anchor.anchor_box} - "
                    f"grid={last_anchor.grid_box} - score={last_anchor.score:.3f}"
                )
                try:
                    self._save_open_debug(last_image, last_anchor, last_grid_result, "opened", account_index, pid)
                except Exception as error:
                    print(f"Inventory open probe opened debug save failed: {error}")
                return "OK"

            print(
                "Inventory anchor still not detected after hotkey - "
                f"account={account_index + 1} - attempt={attempt}/{self._attempts()}"
            )

        try:
            self._save_open_debug(last_image, last_anchor, last_grid_result, "open_failed", account_index, pid)
        except Exception as error:
            print(f"Inventory open probe failed debug save failed: {error}")

        print(
            "Inventory open failed by image anchor - "
            f"account={account_index + 1} - pid={pid} - hwnd={last_hwnd} - "
            f"hotkey={hotkey!r}"
        )
        return "INVENTORY_NOT_OPEN_AFTER_HOTKEY" if self._strict() else "OK"
