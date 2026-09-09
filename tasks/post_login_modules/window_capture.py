import ctypes

import win32con
import win32gui
import win32process
import win32ui
from PIL import Image


def main_window_for_pid(pid):
    """Return the best visible non-dialog game window for one conquer.exe PID."""
    candidates = []

    def enum_window(hwnd, _):
        try:
            _, window_pid = win32process.GetWindowThreadProcessId(hwnd)
            if int(window_pid) != int(pid):
                return True

            if not win32gui.IsWindowVisible(hwnd):
                return True

            class_name = win32gui.GetClassName(hwnd)
            if class_name == "#32770":
                return True

            left, top, right, bottom = win32gui.GetWindowRect(hwnd)
            width = max(0, right - left)
            height = max(0, bottom - top)

            if width < 200 or height < 150:
                return True

            title = win32gui.GetWindowText(hwnd)
            candidates.append((width * height, hwnd, title))
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


def capture_window(hwnd):
    """Capture one exact window using PrintWindow and return a PIL image.

    This is adapted from the old google2 capture idea, but isolated for the
    Login Manager pipeline. It never captures the whole desktop and never moves
    the mouse.
    """
    hwnd_dc = None
    mfc_dc = None
    save_dc = None
    bitmap = None

    try:
        if not hwnd or not win32gui.IsWindow(hwnd):
            print("Post-login capture failed: invalid hwnd")
            return None

        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        width = max(0, right - left)
        height = max(0, bottom - top)

        if width <= 0 or height <= 0:
            print(f"Post-login capture failed: invalid size {width}x{height}")
            return None

        hwnd_dc = win32gui.GetWindowDC(hwnd)
        mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
        save_dc = mfc_dc.CreateCompatibleDC()

        bitmap = win32ui.CreateBitmap()
        bitmap.CreateCompatibleBitmap(mfc_dc, width, height)
        save_dc.SelectObject(bitmap)

        user32 = ctypes.windll.user32
        result = 0

        # 3 = render full content + client area. Fallbacks handle older windows.
        for flag in (3, 2, 0):
            try:
                result = user32.PrintWindow(int(hwnd), int(save_dc.GetSafeHdc()), int(flag))
            except Exception:
                result = 0
            if result == 1:
                break

        if result != 1:
            print(f"Post-login capture failed: PrintWindow result={result}")
            return None

        bmpinfo = bitmap.GetInfo()
        bmpstr = bitmap.GetBitmapBits(True)

        image = Image.frombuffer(
            "RGB",
            (bmpinfo["bmWidth"], bmpinfo["bmHeight"]),
            bmpstr,
            "raw",
            "BGRX",
            0,
            1,
        )

        return image.copy()

    except Exception as error:
        print(f"Post-login capture error: {error}")
        return None

    finally:
        if bitmap is not None:
            try:
                win32gui.DeleteObject(bitmap.GetHandle())
            except Exception:
                pass
        if save_dc is not None:
            try:
                save_dc.DeleteDC()
            except Exception:
                pass
        if mfc_dc is not None:
            try:
                mfc_dc.DeleteDC()
            except Exception:
                pass
        if hwnd_dc is not None:
            try:
                win32gui.ReleaseDC(hwnd, hwnd_dc)
            except Exception:
                pass


def capture_pid_window(pid):
    """Capture the main window for one exact PID."""
    hwnd = main_window_for_pid(pid)
    if not hwnd:
        print(f"Post-login capture failed: no main window for PID {pid}")
        return None, None

    return capture_window(hwnd), hwnd
