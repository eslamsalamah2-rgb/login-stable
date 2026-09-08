import os
import time
import json
import cv2
import numpy as np
import pydirectinput
import win32gui
import win32process
import win32ui
import ctypes

from tasks.base_task import BaseTask
from tasks.window_disconnect_detector import WindowDisconnectDetector
from tasks.target_window_context import TargetWindowContext


class LoginTask(BaseTask):

    def __init__(self):
        super().__init__()

        self.template_path = os.path.join(
            "assets",
            "login_fields.png"
        )

        self.credentials_path = "credentials.json"
        # Keep 0.80 as the normal acceptance threshold. A genuine login panel
        # on this client can repeatedly land just under it (~0.798), so use a
        # second PID-bound confirmation instead of blindly lowering the main
        # threshold for every match.
        self.threshold = 0.80
        self.confirm_threshold = 0.78
        self.match_scales = (0.94, 0.97, 1.00, 1.03, 1.06)
        self.target_pid = None
        self.window_helper = WindowDisconnectDetector()

    def set_target_pid(self, pid):
        self.target_pid = pid
        TargetWindowContext.set_pid(pid)

    def _foreground_pid(self):
        try:
            hwnd = win32gui.GetForegroundWindow()
            if not hwnd:
                return None
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            return pid
        except Exception:
            return None

    def _ensure_target_window(self):
        if not self.target_pid:
            return True

        for _ in range(4):
            self.window_helper.activate_main_window(self.target_pid)
            time.sleep(0.12)

            if self._foreground_pid() == self.target_pid:
                return True

            time.sleep(0.12)

        print(
            f"Login safety: could not focus target PID {self.target_pid}; typing blocked"
        )
        return False

    def load_credentials(self):

        if not os.path.exists(self.credentials_path):
            return None, None

        try:
            with open(
                self.credentials_path,
                "r",
                encoding="utf-8"
            ) as file:
                data = json.load(file)

            username = str(data.get("username", ""))
            password = str(data.get("password", ""))

            if not username or not password:
                return None, None

            return username, password

        except Exception:
            return None, None

    def _target_main_window(self, target_pid=None):
        pid = target_pid if target_pid is not None else self.target_pid
        if not pid:
            return None
        return self.window_helper._main_window_for_pid(pid)

    def _capture_target_window(self, target_pid=None):
        """Capture only the exact target PID window using PrintWindow.

        Returns (image_bgr, screen_left, screen_top). This prevents another
        Conquer page or desktop content from winning the template match.
        """
        pid = target_pid if target_pid is not None else self.target_pid
        hwnd = self._target_main_window(pid)
        if not hwnd:
            return None, None, None

        hwnd_dc = src_dc = mem_dc = bitmap = None
        try:
            left, top, right, bottom = win32gui.GetWindowRect(hwnd)
            width = right - left
            height = bottom - top
            if width <= 0 or height <= 0:
                return None, None, None

            hwnd_dc = win32gui.GetWindowDC(hwnd)
            src_dc = win32ui.CreateDCFromHandle(hwnd_dc)
            mem_dc = src_dc.CreateCompatibleDC()
            bitmap = win32ui.CreateBitmap()
            bitmap.CreateCompatibleBitmap(src_dc, width, height)
            mem_dc.SelectObject(bitmap)

            ok = ctypes.windll.user32.PrintWindow(
                int(hwnd), int(mem_dc.GetSafeHdc()), 2
            )
            if not ok:
                return None, None, None

            info = bitmap.GetInfo()
            bits = bitmap.GetBitmapBits(True)
            image = np.frombuffer(bits, dtype=np.uint8)
            image.shape = (info["bmHeight"], info["bmWidth"], 4)
            image = cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
            return image, left, top

        except Exception as error:
            print(f"Login detector capture failed - PID {pid}: {error}")
            return None, None, None
        finally:
            try:
                if bitmap is not None:
                    win32gui.DeleteObject(bitmap.GetHandle())
            except Exception:
                pass
            try:
                if mem_dc is not None:
                    mem_dc.DeleteDC()
            except Exception:
                pass
            try:
                if src_dc is not None:
                    src_dc.DeleteDC()
            except Exception:
                pass
            try:
                if hwnd_dc is not None and hwnd:
                    win32gui.ReleaseDC(hwnd, hwnd_dc)
            except Exception:
                pass

    def _best_login_match(self, screen, template):
        screen_gray = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY)
        best = None

        for scale in self.match_scales:
            width = max(1, int(round(template.shape[1] * scale)))
            height = max(1, int(round(template.shape[0] * scale)))
            if width > screen.shape[1] or height > screen.shape[0]:
                continue

            interpolation = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_CUBIC
            scaled = cv2.resize(template, (width, height), interpolation=interpolation)
            scaled_gray = cv2.cvtColor(scaled, cv2.COLOR_BGR2GRAY)

            color_result = cv2.matchTemplate(screen, scaled, cv2.TM_CCOEFF_NORMED)
            _, color_score, _, color_location = cv2.minMaxLoc(color_result)

            gray_result = cv2.matchTemplate(
                screen_gray, scaled_gray, cv2.TM_CCOEFF_NORMED
            )
            _, gray_score, _, gray_location = cv2.minMaxLoc(gray_result)

            # A real login panel should agree in both representations and place.
            location_distance = abs(color_location[0] - gray_location[0]) + abs(
                color_location[1] - gray_location[1]
            )
            agreement = location_distance <= 8
            combined = (float(color_score) + float(gray_score)) / 2.0
            if not agreement:
                combined -= 0.08

            candidate = (combined, color_score, gray_score, color_location, width, height, scale)
            if best is None or candidate[0] > best[0]:
                best = candidate

        return best

    def find_login_fields(self, target_pid=None, verbose=True):
        if not os.path.exists(self.template_path):
            print("Login fields image not found")
            return None

        template = cv2.imread(self.template_path, cv2.IMREAD_COLOR)
        if template is None:
            return None

        # PID-bound capture is the primary detector path.
        pid = target_pid if target_pid is not None else self.target_pid
        screen, screen_left, screen_top = self._capture_target_window(pid)
        if screen is None:
            if verbose:
                print(f"Login fields capture unavailable for target PID {pid}")
            return None

        best = self._best_login_match(screen, template)
        if best is None:
            return None

        combined, color_score, gray_score, location, template_w, template_h, scale = best
        if verbose:
            print(
                f"Login fields Match - PID {pid}: "
                f"combined={combined:.3f} color={color_score:.3f} "
                f"gray={gray_score:.3f} scale={scale:.2f}"
            )

        if combined < self.threshold:
            # Near-threshold matches are accepted only after a second capture
            # from the exact same PID window confirms the same panel position.
            # This handles the repeatable ~0.798 real match without making the
            # detector globally permissive.
            if combined < self.confirm_threshold:
                return None

            time.sleep(0.12)
            confirm_screen, confirm_left, confirm_top = self._capture_target_window(pid)
            if confirm_screen is None:
                return None

            confirm = self._best_login_match(confirm_screen, template)
            if confirm is None:
                return None

            (
                confirm_combined,
                confirm_color,
                confirm_gray,
                confirm_location,
                confirm_w,
                confirm_h,
                confirm_scale,
            ) = confirm

            location_delta = (
                abs(confirm_location[0] - location[0])
                + abs(confirm_location[1] - location[1])
            )
            size_delta = abs(confirm_w - template_w) + abs(confirm_h - template_h)

            if (
                confirm_combined < self.confirm_threshold
                or location_delta > 6
                or size_delta > 6
            ):
                if verbose:
                    print(
                        f"Login fields near-match rejected - PID {pid}: "
                        f"first={combined:.3f} confirm={confirm_combined:.3f} "
                        f"location_delta={location_delta} size_delta={size_delta}"
                    )
                return None

            if verbose:
                print(
                    f"Login fields confirmed by repeat - PID {pid}: "
                    f"first={combined:.3f} confirm={confirm_combined:.3f} "
                    f"scale={confirm_scale:.2f}"
                )

            # Use the confirmed capture/location for click coordinates.
            screen_left = confirm_left
            screen_top = confirm_top
            location = confirm_location
            template_w = confirm_w
            template_h = confirm_h

        left = screen_left + location[0]
        top = screen_top + location[1]

        username_x = left + int(template_w * 0.82)
        username_y = top + int(template_h * 0.25)
        password_x = left + int(template_w * 0.43)
        password_y = top + int(template_h * 0.76)
        password_clear_x = left + int(template_w * 0.82)

        return (
            username_x,
            username_y,
            password_x,
            password_y,
            password_clear_x
        )

    def clear_username_field(self):
        for _ in range(10):
            pydirectinput.press("backspace")
            time.sleep(0.02)

    def clear_password_field(self):
        for _ in range(20):
            pydirectinput.press("backspace")
            time.sleep(0.02)

    def _type_exact(self, text, interval=0.04):
        text = str(text)

        caps_was_on = False

        try:
            caps_was_on = bool(ctypes.windll.user32.GetKeyState(0x14) & 1)
        except Exception:
            caps_was_on = False

        if caps_was_on:
            pydirectinput.press("capslock")
            time.sleep(0.05)

        try:
            for character in text:
                if self.target_pid and not self._ensure_target_window():
                    return False

                if character.isalpha() and character.isupper():
                    pydirectinput.keyDown("shift")
                    pydirectinput.press(character.lower())
                    pydirectinput.keyUp("shift")
                else:
                    pydirectinput.press(character.lower() if character.isalpha() else character)

                time.sleep(interval)

            return True
        finally:
            if caps_was_on:
                pydirectinput.press("capslock")

    def _click(self, x, y):
        pydirectinput.click(x, y)
        time.sleep(0.15)

    def start(self, username=None, password=None, target_pid=None):
        if target_pid is not None:
            self.set_target_pid(target_pid)

        if not username or not password:
            username, password = self.load_credentials()

        if not username or not password:
            print("Credentials are missing")
            return False

        for _ in range(12):
            if self.target_pid and not self._ensure_target_window():
                time.sleep(0.25)
                continue

            fields = self.find_login_fields(target_pid=self.target_pid)

            if fields:
                username_x, username_y, password_x, password_y, password_clear_x = fields

                if self.target_pid and not self._ensure_target_window():
                    return False

                self._click(username_x, username_y)
                pydirectinput.hotkey("ctrl", "a")
                time.sleep(0.08)
                self.clear_username_field()

                if not self._type_exact(username):
                    return False

                if self.target_pid and not self._ensure_target_window():
                    return False

                self._click(password_clear_x, password_y)
                pydirectinput.hotkey("ctrl", "a")
                time.sleep(0.08)
                self.clear_password_field()

                if not self._type_exact(password):
                    return False

                print(
                    f"Login credentials entered for {username} on target PID {self.target_pid}"
                )
                return True

            time.sleep(0.25)

        print("Login fields not found")
        return False

    def rewrite_password(self, password, target_pid=None):
        if target_pid is not None:
            self.set_target_pid(target_pid)

        if not password:
            return False

        for _ in range(10):
            if self.target_pid and not self._ensure_target_window():
                time.sleep(0.25)
                continue

            fields = self.find_login_fields(target_pid=self.target_pid)
            if not fields:
                time.sleep(0.25)
                continue

            _, _, password_x, password_y, password_clear_x = fields

            if self.target_pid and not self._ensure_target_window():
                return False

            self._click(password_clear_x, password_y)
            pydirectinput.hotkey("ctrl", "a")
            time.sleep(0.08)
            self.clear_password_field()

            if not self._type_exact(password):
                return False

            print(f"Password rewritten on target PID {self.target_pid}")
            return True

        print("Password field not found")
        return False
