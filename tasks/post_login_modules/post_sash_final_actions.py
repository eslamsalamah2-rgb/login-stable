"""Final per-account actions after Sash.

Order in the post-login pipeline:
Drop -> Use -> Sash -> PostSashFinalActions

Current actions:
1) press I twice (configurable)
2) right-click once at a configurable client coordinate

This module is post-login only. It does not touch Login typing, Login recovery,
or global input timing.
"""

import time

import pydirectinput
import win32api
import win32con
import win32gui

from tasks.post_login_modules.window_capture import capture_pid_window


class PostSashFinalActionsModule:
    name = "post_sash_final_actions"
    setting_key = "enable_post_sash_final_actions"

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

    def _int_setting(self, key, default, minimum=0, maximum=None):
        try:
            value = int(float(self._setting(key, default)))
        except Exception:
            value = int(default)
        value = max(int(minimum), value)
        if maximum is not None:
            value = min(int(maximum), value)
        return value

    def _float_setting(self, key, default, minimum=0.0, maximum=None):
        try:
            value = float(self._setting(key, default))
        except Exception:
            value = float(default)
        value = max(float(minimum), value)
        if maximum is not None:
            value = min(float(maximum), value)
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
            time.sleep(min(0.02, max(0.0, end - time.perf_counter())))
        return not self._stop_requested()

    def _activate_hwnd(self, hwnd):
        try:
            if not hwnd or not win32gui.IsWindow(hwnd):
                return False
        except Exception:
            return False

        try:
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        except Exception:
            pass

        try:
            win32gui.SetForegroundWindow(hwnd)
        except Exception:
            pass

        return self._sleep_interruptible(0.10)

    def _press_i_twice(self):
        count = self._int_setting("post_sash_i_press_count", 2, minimum=0, maximum=5)
        delay = self._float_setting("post_sash_i_press_delay", 0.20, minimum=0.0, maximum=2.0)
        after_delay = self._float_setting("post_sash_after_i_delay", 0.30, minimum=0.0, maximum=3.0)

        for index in range(count):
            if self._stop_requested():
                return False
            print(f"Post-sash final action: press I {index + 1}/{count}")
            try:
                pydirectinput.press("i")
            except Exception as error:
                print(f"Post-sash final action I press failed: {error}")
                return False
            if delay > 0 and not self._sleep_interruptible(delay):
                return False

        if after_delay > 0 and not self._sleep_interruptible(after_delay):
            return False
        return not self._stop_requested()

    def _right_click_anywhere(self, hwnd):
        if not self._feature_enabled("post_sash_right_click_enabled", True):
            print("Post-sash final action: right-click skipped by setting")
            return True

        x = self._int_setting("post_sash_right_click_x", 900, minimum=0, maximum=4000)
        y = self._int_setting("post_sash_right_click_y", 500, minimum=0, maximum=4000)
        click_delay = self._float_setting("post_sash_right_click_delay", 0.10, minimum=0.0, maximum=2.0)
        after_delay = self._float_setting("post_sash_after_right_click_delay", 0.20, minimum=0.0, maximum=3.0)

        if self._stop_requested():
            return False

        try:
            sx, sy = win32gui.ClientToScreen(hwnd, (int(x), int(y)))
        except Exception:
            sx, sy = int(x), int(y)

        print(f"Post-sash final action: right-click at client=({x},{y}) screen=({sx},{sy})")

        try:
            win32api.SetCursorPos((int(sx), int(sy)))
        except Exception:
            pydirectinput.moveTo(int(sx), int(sy), duration=0)

        if click_delay > 0 and not self._sleep_interruptible(click_delay):
            return False

        try:
            win32api.mouse_event(win32con.MOUSEEVENTF_RIGHTDOWN, 0, 0, 0, 0)
            time.sleep(0.025)
            win32api.mouse_event(win32con.MOUSEEVENTF_RIGHTUP, 0, 0, 0, 0)
        except Exception:
            try:
                pydirectinput.rightClick()
            except Exception:
                pydirectinput.click(button="right")

        if after_delay > 0 and not self._sleep_interruptible(after_delay):
            return False
        return not self._stop_requested()

    def run(self, account_index, session):
        if not self.enabled():
            return "SKIPPED"

        if self._stop_requested():
            return "STOP_REQUESTED"

        session = session or {}
        pid = session.get("pid")
        page_name = session.get("page_name", "")
        if not pid:
            return "POST_SASH_FINAL_NO_PID"

        _image, hwnd = capture_pid_window(pid)
        if not hwnd:
            return "POST_SASH_FINAL_CAPTURE_FAILED"

        if not self._activate_hwnd(hwnd):
            return "STOP_REQUESTED"

        print(
            "Post-sash final actions started - "
            f"account={account_index + 1} - pid={pid} - name={page_name!r}"
        )

        if not self._press_i_twice():
            print(f"Post-sash final actions stopped during I presses - account={account_index + 1}")
            return "STOP_REQUESTED"

        if not self._right_click_anywhere(hwnd):
            print(f"Post-sash final actions stopped during right-click - account={account_index + 1}")
            return "STOP_REQUESTED"

        print(
            "Post-sash final actions OK - "
            f"account={account_index + 1} - pid={pid} - name={page_name!r}"
        )
        return "OK"
