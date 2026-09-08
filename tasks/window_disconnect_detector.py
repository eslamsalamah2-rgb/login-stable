import ctypes
import time

import win32con
import win32gui
import win32process

from tasks.target_window_context import TargetWindowContext


class WindowDisconnectDetector:
    """Detect Conquer disconnect dialogs through Win32 window handles.

    This does not depend on the page being visible or in the foreground.
    It enumerates windows that belong to the target conquer.exe PID and reads
    their native window/control text directly.
    """

    DISCONNECT_PHRASES = (
        "disconnected with game server",
        "please login the game again",
    )

    def _collect_window_text(self, hwnd):
        parts = []

        try:
            title = win32gui.GetWindowText(hwnd)
            if title:
                parts.append(title)
        except Exception:
            pass

        def enum_child(child_hwnd, _):
            try:
                text = win32gui.GetWindowText(child_hwnd)
                if text:
                    parts.append(text)
            except Exception:
                pass
            return True

        try:
            win32gui.EnumChildWindows(hwnd, enum_child, None)
        except Exception:
            pass

        return "\n".join(parts)

    def _windows_for_pid(self, pid):
        windows = []

        def enum_window(hwnd, _):
            try:
                _, window_pid = win32process.GetWindowThreadProcessId(hwnd)
                if window_pid == pid:
                    windows.append(hwnd)
            except Exception:
                pass
            return True

        try:
            win32gui.EnumWindows(enum_window, None)
        except Exception:
            pass

        return windows

    def find_disconnect_dialog(self, pid):
        for hwnd in self._windows_for_pid(pid):
            text = self._collect_window_text(hwnd)
            lowered = text.lower()

            if all(phrase in lowered for phrase in self.DISCONNECT_PHRASES):
                return {
                    "hwnd": hwnd,
                    "text": text,
                }

        return None

    def has_disconnect_dialog(self, pid):
        return self.find_disconnect_dialog(pid) is not None

    def press_ok(self, pid):
        dialog = self.find_disconnect_dialog(pid)
        if not dialog:
            return False

        hwnd = dialog["hwnd"]
        ok_button = None

        def enum_child(child_hwnd, _):
            nonlocal ok_button

            try:
                text = win32gui.GetWindowText(child_hwnd).strip().lower()
                class_name = win32gui.GetClassName(child_hwnd)
            except Exception:
                return True

            if class_name == "Button" and text in {"ok", "&ok"}:
                ok_button = child_hwnd
                return False

            return True

        try:
            win32gui.EnumChildWindows(hwnd, enum_child, None)
        except Exception:
            pass

        if not ok_button:
            return False

        try:
            win32gui.SendMessage(ok_button, win32con.BM_CLICK, 0, 0)
            time.sleep(0.3)
            return True
        except Exception:
            return False

    def _main_window_for_pid(self, pid):
        candidates = []

        for hwnd in self._windows_for_pid(pid):
            try:
                if not win32gui.IsWindowVisible(hwnd):
                    continue

                class_name = win32gui.GetClassName(hwnd)
                title = win32gui.GetWindowText(hwnd)
                rect = win32gui.GetWindowRect(hwnd)
                width = max(0, rect[2] - rect[0])
                height = max(0, rect[3] - rect[1])

                if class_name == "#32770":
                    continue

                if width < 200 or height < 150:
                    continue

                candidates.append((width * height, hwnd, title))
            except Exception:
                continue

        if not candidates:
            return None

        candidates.sort(reverse=True)
        return candidates[0][1]

    def activate_main_window(self, pid):
        """Force the exact target Conquer page to foreground and lock its PID."""
        if pid:
            TargetWindowContext.set_pid(pid)

        hwnd = self._main_window_for_pid(pid)
        if not hwnd:
            return False

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        current_thread = kernel32.GetCurrentThreadId()
        foreground_hwnd = user32.GetForegroundWindow()

        foreground_thread = 0
        if foreground_hwnd:
            foreground_thread = user32.GetWindowThreadProcessId(
                foreground_hwnd,
                None
            )

        target_thread = user32.GetWindowThreadProcessId(hwnd, None)

        attached_foreground = False
        attached_target = False

        try:
            if win32gui.IsIconic(hwnd):
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            else:
                win32gui.ShowWindow(hwnd, win32con.SW_SHOW)

            time.sleep(0.10)

            if foreground_thread and foreground_thread != current_thread:
                attached_foreground = bool(
                    user32.AttachThreadInput(
                        current_thread,
                        foreground_thread,
                        True
                    )
                )

            if target_thread and target_thread != current_thread:
                attached_target = bool(
                    user32.AttachThreadInput(
                        current_thread,
                        target_thread,
                        True
                    )
                )

            win32gui.SetWindowPos(
                hwnd,
                win32con.HWND_TOP,
                0,
                0,
                0,
                0,
                win32con.SWP_NOMOVE
                | win32con.SWP_NOSIZE
                | win32con.SWP_SHOWWINDOW
            )

            try:
                win32gui.BringWindowToTop(hwnd)
            except Exception:
                pass

            try:
                user32.SetForegroundWindow(hwnd)
            except Exception:
                pass

            try:
                user32.SetFocus(hwnd)
            except Exception:
                pass

            time.sleep(0.30)

            success = user32.GetForegroundWindow() == hwnd

            if success:
                TargetWindowContext.set_pid(pid)
                print(f"Activated Conquer window - PID {pid} - HWND {hwnd}")
            else:
                print(f"Could not fully foreground Conquer window - PID {pid} - HWND {hwnd}")

            return bool(success)

        finally:
            if attached_target:
                try:
                    user32.AttachThreadInput(
                        current_thread,
                        target_thread,
                        False
                    )
                except Exception:
                    pass

            if attached_foreground:
                try:
                    user32.AttachThreadInput(
                        current_thread,
                        foreground_thread,
                        False
                    )
                except Exception:
                    pass
