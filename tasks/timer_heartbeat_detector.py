import ctypes
import os
import time

import cv2
import numpy as np
import win32con
import win32gui
import win32process
import win32ui


class TimerHeartbeatDetector:
    """Verify that a Conquer page is visually alive without fixed screen XY.

    The detector first finds a stable visual anchor (Fps:) inside the target
    Conquer window, then watches the text strip to the right of that anchor.
    Because the clock/date/FPS text changes while the page is alive, movement
    inside that strip acts as a lightweight heartbeat.

    This class is intended as a confirmation test only for pages already
    flagged as suspicious by the cheaper memory/Win32 checks.
    """

    ACTIVE = "ACTIVE"
    STATIC = "STATIC"
    UNKNOWN = "UNKNOWN"
    MISSING = "MISSING"

    def __init__(self, anchor_path=None):
        self.anchor_path = anchor_path or os.path.join("assets", "fps_anchor.png")
        self.anchor_threshold = 0.78
        self.sample_interval = 1.20
        self.samples = 3
        self.pixel_diff_threshold = 12
        self.changed_ratio_threshold = 0.002

    def _main_window_for_pid(self, pid):
        candidates = []

        def enum_window(hwnd, _):
            try:
                _, window_pid = win32process.GetWindowThreadProcessId(hwnd)
                if window_pid != pid:
                    return True

                if not win32gui.IsWindow(hwnd):
                    return True

                if not win32gui.IsWindowVisible(hwnd):
                    return True

                class_name = win32gui.GetClassName(hwnd)
                if class_name == "#32770":
                    return True

                left, top, right, bottom = win32gui.GetWindowRect(hwnd)
                width = max(0, right - left)
                height = max(0, bottom - top)

                if width < 300 or height < 200:
                    return True

                candidates.append((width * height, hwnd))
            except Exception:
                pass

            return True

        try:
            win32gui.EnumWindows(enum_window, None)
        except Exception:
            return None

        if not candidates:
            return None

        candidates.sort(reverse=True)
        return candidates[0][1]

    def _capture_window(self, hwnd):
        """Capture a window through PrintWindow so foreground focus is not required."""
        try:
            left, top, right, bottom = win32gui.GetWindowRect(hwnd)
            width = right - left
            height = bottom - top

            if width <= 0 or height <= 0:
                return None

            hwnd_dc = win32gui.GetWindowDC(hwnd)
            src_dc = win32ui.CreateDCFromHandle(hwnd_dc)
            mem_dc = src_dc.CreateCompatibleDC()
            bitmap = win32ui.CreateBitmap()
            bitmap.CreateCompatibleBitmap(src_dc, width, height)
            mem_dc.SelectObject(bitmap)

            result = ctypes.windll.user32.PrintWindow(
                int(hwnd),
                int(mem_dc.GetSafeHdc()),
                2,
            )

            bmp_info = bitmap.GetInfo()
            bmp_bytes = bitmap.GetBitmapBits(True)

            image = np.frombuffer(bmp_bytes, dtype=np.uint8)
            image.shape = (
                bmp_info["bmHeight"],
                bmp_info["bmWidth"],
                4,
            )
            image = cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)

            win32gui.DeleteObject(bitmap.GetHandle())
            mem_dc.DeleteDC()
            src_dc.DeleteDC()
            win32gui.ReleaseDC(hwnd, hwnd_dc)

            if not result:
                return None

            return image

        except Exception as error:
            print(f"Timer heartbeat capture failed: {error}")
            return None

    def _find_anchor_and_strip(self, image):
        if image is None or not os.path.exists(self.anchor_path):
            return None, 0.0

        anchor = cv2.imread(self.anchor_path, cv2.IMREAD_COLOR)
        if anchor is None:
            return None, 0.0

        image_h, image_w = image.shape[:2]
        anchor_h, anchor_w = anchor.shape[:2]

        if anchor_w > image_w or anchor_h > image_h:
            return None, 0.0

        result = cv2.matchTemplate(image, anchor, cv2.TM_CCOEFF_NORMED)
        _, max_value, _, max_location = cv2.minMaxLoc(result)

        if max_value < self.anchor_threshold:
            return None, max_value

        # No fixed screen coordinates are used. The dynamic strip is derived
        # entirely from the detected Fps: anchor position.
        anchor_right = max_location[0] + anchor_w
        y1 = max(0, max_location[1] - 2)
        y2 = min(image_h, max_location[1] + anchor_h + 3)
        x1 = min(image_w, anchor_right + 1)
        x2 = min(image_w, anchor_right + 330)

        if x2 - x1 < 40 or y2 - y1 < 8:
            return None, max_value

        strip = image[y1:y2, x1:x2]
        strip = cv2.cvtColor(strip, cv2.COLOR_BGR2GRAY)
        return strip, max_value

    def _strip_changed(self, previous, current):
        if previous is None or current is None:
            return False, 0.0

        if previous.shape != current.shape:
            return True, 1.0

        diff = cv2.absdiff(previous, current)
        changed = diff > self.pixel_diff_threshold
        ratio = float(np.count_nonzero(changed)) / float(changed.size)
        return ratio >= self.changed_ratio_threshold, ratio

    def check(self, pid, stop_check=None):
        """Check the timer strictly inside the exact PID window.

        ACTIVE  = timer anchor exists and its strip changes.
        STATIC  = timer anchor exists but the strip stays unchanged.
        MISSING = the target window was captured, but the timer anchor is not
                  present inside that window. Pixels from the desktop or from
                  another Conquer page are never used as a fallback.
        UNKNOWN = the PID/window itself could not be captured reliably.
        """
        hwnd = self._main_window_for_pid(pid)
        if not hwnd:
            print(f"Timer heartbeat - PID {pid} - target window not found")
            return self.UNKNOWN

        try:
            left, top, right, bottom = win32gui.GetWindowRect(hwnd)
            print(
                f"Timer heartbeat - PID {pid} - HWND {hwnd} - "
                f"window={max(0, right-left)}x{max(0, bottom-top)}"
            )
        except Exception:
            pass

        previous = None
        valid_samples = 0

        for sample_index in range(self.samples):
            if stop_check and stop_check():
                return self.UNKNOWN

            image = self._capture_window(hwnd)
            strip, score = self._find_anchor_and_strip(image)

            print(
                f"Timer heartbeat - PID {pid} - sample {sample_index + 1}/{self.samples} - "
                f"anchor={score:.3f}"
            )

            if image is None:
                print(f"Timer heartbeat - PID {pid} - window capture unavailable")
                return self.UNKNOWN

            if strip is None:
                print(
                    f"Timer heartbeat - PID {pid} - timer anchor MISSING "
                    f"inside target window (best={score:.3f})"
                )
                return self.MISSING

            valid_samples += 1

            if previous is not None:
                changed, ratio = self._strip_changed(previous, strip)
                print(
                    f"Timer heartbeat - PID {pid} - changed={changed} - ratio={ratio:.5f}"
                )

                if changed:
                    return self.ACTIVE

            previous = strip

            if sample_index < self.samples - 1:
                end_time = time.time() + self.sample_interval
                while time.time() < end_time:
                    if stop_check and stop_check():
                        return self.UNKNOWN
                    time.sleep(0.05)

        if valid_samples == self.samples:
            return self.STATIC

        return self.UNKNOWN
