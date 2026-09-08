import ctypes
import os
import time

import cv2
import numpy as np
import pydirectinput
import win32con
import win32gui
import win32process
import win32ui

from PIL import ImageGrab
from tasks.base_task import BaseTask


class StartGameTask(BaseTask):

    def __init__(self):
        super().__init__()

        self.template_path = os.path.join(
            "assets",
            "start_game.png"
        )

        # Windows is case-insensitive, but keep an explicit fallback for ZIP/Git use.
        self.template_fallback_path = os.path.join(
            "assets",
            "start_game.PNG"
        )

        self.threshold = 0.82

    def _template_path(self):
        if os.path.exists(self.template_path):
            return self.template_path
        return self.template_fallback_path

    def _windows_for_pid(self, pid):
        windows = []

        def enum_window(hwnd, _):
            try:
                _, window_pid = win32process.GetWindowThreadProcessId(hwnd)
                if int(window_pid) == int(pid):
                    windows.append(hwnd)
            except Exception:
                pass
            return True

        try:
            win32gui.EnumWindows(enum_window, None)
        except Exception:
            pass

        return windows

    def _main_window_for_pid(self, pid):
        candidates = []

        for hwnd in self._windows_for_pid(pid):
            try:
                if not win32gui.IsWindowVisible(hwnd):
                    continue

                rect = win32gui.GetWindowRect(hwnd)
                width = max(0, rect[2] - rect[0])
                height = max(0, rect[3] - rect[1])
                if width < 200 or height < 120:
                    continue

                class_name = win32gui.GetClassName(hwnd)
                if class_name == "#32770":
                    # Dialog windows are not the launcher surface that contains
                    # Start Game.
                    continue

                candidates.append((width * height, hwnd))
            except Exception:
                continue

        if not candidates:
            return None

        candidates.sort(reverse=True)
        return candidates[0][1]

    def _activate_window(self, hwnd):
        try:
            if win32gui.IsIconic(hwnd):
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            else:
                win32gui.ShowWindow(hwnd, win32con.SW_SHOW)

            time.sleep(0.10)
            win32gui.SetWindowPos(
                hwnd,
                win32con.HWND_TOP,
                0,
                0,
                0,
                0,
                win32con.SWP_NOMOVE
                | win32con.SWP_NOSIZE
                | win32con.SWP_SHOWWINDOW,
            )
            try:
                win32gui.BringWindowToTop(hwnd)
            except Exception:
                pass
            try:
                ctypes.windll.user32.SetForegroundWindow(hwnd)
            except Exception:
                pass
            time.sleep(0.15)
            return True
        except Exception:
            return False

    def _capture_window(self, hwnd):
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
            print(f"Start Game window capture failed: {error}")
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

    def _load_template(self):
        path = self._template_path()
        if not os.path.exists(path):
            print("Start Game image not found")
            return None

        return cv2.imread(path, cv2.IMREAD_COLOR)

    def _match_template(self, screen, template):
        result = cv2.matchTemplate(
            screen,
            template,
            cv2.TM_CCOEFF_NORMED
        )

        _, max_value, _, max_location = cv2.minMaxLoc(result)
        return float(max_value), max_location

    def find_start_button(self, target_pid=None):
        template = self._load_template()
        if template is None:
            return None

        template_height, template_width = template.shape[:2]

        # Prefer the exact launcher PID window when we have it. This prevents a
        # Start Game button from another visible/background launcher winning the
        # scan.
        if target_pid:
            hwnd = self._main_window_for_pid(target_pid)
            if hwnd:
                self._activate_window(hwnd)
                screen, screen_left, screen_top = self._capture_window(hwnd)
                if screen is not None:
                    max_value, max_location = self._match_template(screen, template)
                    print(f"Start Game Match - launcher PID {target_pid}: {max_value:.3f}")
                    if max_value >= self.threshold:
                        x = screen_left + max_location[0] + template_width // 2
                        y = screen_top + max_location[1] + template_height // 2
                        return x, y
                    return None
                print(f"Start Game capture unavailable for launcher PID {target_pid}")
            else:
                print(f"Start Game launcher window not found for PID {target_pid}")

        screenshot = ImageGrab.grab()
        screen = np.array(screenshot)
        screen = cv2.cvtColor(
            screen,
            cv2.COLOR_RGB2BGR
        )

        max_value, max_location = self._match_template(screen, template)

        print(f"Start Game Match: {max_value:.3f}")

        if max_value < self.threshold:
            return None

        x = max_location[0] + template_width // 2
        y = max_location[1] + template_height // 2

        return x, y

    def start(self, target_pid=None, timeout=30.0):
        self.running = True

        if target_pid:
            print(f"Searching for Start Game on launcher PID {target_pid}...")
        else:
            print("Searching for Start Game...")

        start_time = time.time()

        while self.running:
            if time.time() - start_time > timeout:
                print("Start Game button not found")
                self.running = False
                return False

            position = self.find_start_button(target_pid=target_pid)

            if position:
                x, y = position
                print(f"Start Game found: {x}, {y}")

                pydirectinput.moveTo(x, y, duration=0.15)
                time.sleep(0.2)
                pydirectinput.click()
                print("Start Game clicked")

                self.running = False
                return True

            time.sleep(0.5)

        return False

    def stop(self):
        self.running = False
