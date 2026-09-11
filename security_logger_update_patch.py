"""Handle the 99 Security Logger update dialog before Start Game.

The dialog can appear after opening the game file and before the Start Game
button is available:

    The game client is still running. Exit the client and try to update again?

This patch is intentionally pre-login only.  It does not touch the stable Login
input flow or any post-login Drop/Use/Sash workers.
"""

import time

import win32con
import win32gui

from maintenance_launcher import MaintenanceAwareLauncher
from tasks.memory_reader import ConquerMemoryReader


_ORIGINAL_OPEN_CONQUER_PID_WITH_RETRIES = MaintenanceAwareLauncher._open_conquer_pid_with_retries

SECURITY_LOGGER_TITLE = "99 Security Logger"
SECURITY_LOGGER_TEXT_PARTS = (
    "game client is still running",
    "try to update again",
)
BM_CLICK = 0x00F5


def _safe_window_text(hwnd):
    try:
        return win32gui.GetWindowText(hwnd) or ""
    except Exception:
        return ""


def _collect_child_windows(hwnd):
    children = []

    def _enum_child(child, _param):
        children.append(child)
        return True

    try:
        win32gui.EnumChildWindows(hwnd, _enum_child, None)
    except Exception:
        pass

    return children


def _collect_child_text(hwnd):
    texts = []
    for child in _collect_child_windows(hwnd):
        text = _safe_window_text(child).strip()
        if text:
            texts.append(text)
    return texts


def _looks_like_security_logger_update_dialog(hwnd):
    title = _safe_window_text(hwnd).strip()
    child_texts = _collect_child_text(hwnd)
    combined = " ".join([title] + child_texts).lower()

    title_ok = SECURITY_LOGGER_TITLE.lower() in title.lower()
    message_ok = all(part in combined for part in SECURITY_LOGGER_TEXT_PARTS)

    return title_ok and message_ok


def _find_ok_button(hwnd):
    for child in _collect_child_windows(hwnd):
        text = _safe_window_text(child).strip().lower()
        if text == "ok":
            return child
    return None


def _click_ok_on_dialog(hwnd):
    try:
        if not win32gui.IsWindow(hwnd):
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

    ok_hwnd = _find_ok_button(hwnd)
    if ok_hwnd:
        try:
            win32gui.SendMessage(ok_hwnd, BM_CLICK, 0, 0)
            return True
        except Exception:
            pass

    try:
        win32gui.SendMessage(hwnd, win32con.WM_COMMAND, 1, 0)
        return True
    except Exception:
        pass

    try:
        win32gui.PostMessage(hwnd, win32con.WM_KEYDOWN, win32con.VK_RETURN, 0)
        win32gui.PostMessage(hwnd, win32con.WM_KEYUP, win32con.VK_RETURN, 0)
        return True
    except Exception:
        return False


def find_security_logger_update_dialog():
    matches = []

    def _enum_window(hwnd, _param):
        try:
            if _looks_like_security_logger_update_dialog(hwnd):
                matches.append(hwnd)
        except Exception:
            pass
        return True

    try:
        win32gui.EnumWindows(_enum_window, None)
    except Exception:
        pass

    return matches[0] if matches else None


def handle_security_logger_update_dialog(reason="scan", timeout=0.80):
    """Return True if the update dialog was found and OK was pressed."""
    end = time.time() + max(0.0, float(timeout))
    first = True

    while first or time.time() < end:
        first = False
        hwnd = find_security_logger_update_dialog()
        if hwnd:
            print(
                "99 Security Logger update dialog detected - "
                f"reason={reason} - hwnd={hwnd} - pressing OK"
            )
            clicked = _click_ok_on_dialog(hwnd)
            time.sleep(0.30)
            print(
                "99 Security Logger update dialog handled - "
                f"clicked_ok={clicked} - reason={reason}"
            )
            return True
        time.sleep(0.10)

    return False


def _open_conquer_pid_with_security_logger_guard(self, path, account_number, total_accounts):
    max_attempts = 3

    for attempt in range(1, max_attempts + 1):
        if handle_security_logger_update_dialog(
            reason=f"before_launcher_attempt_{attempt}",
            timeout=0.20,
        ):
            self.set_status("تم اكتشاف 99 Security Logger Update - جاري إغلاق صفحات Conquer وإعادة المحاولة")
            closed_count = ConquerMemoryReader.terminate_all_conquer()
            self._stop_launcher_only()
            print(
                "99 Security Logger update before launcher - "
                f"closed {closed_count} conquer.exe process(es)"
            )
            return None, "CLIENT_UPDATE"

        previous_conquer_pids = ConquerMemoryReader.list_conquer_pids()

        self.set_status(
            f"الحساب {account_number}/{total_accounts}: فتح اللانشر "
            f"محاولة {attempt}/{max_attempts}..."
        )

        success, message = self.launcher.open(path)
        if not success:
            return None, "OPEN_ERROR"

        # The update dialog normally appears right after opening the game file,
        # before Start Game can be found.  We look for it globally because it can
        # be behind other windows or only visible from the taskbar.
        if handle_security_logger_update_dialog(
            reason=f"after_launcher_open_attempt_{attempt}",
            timeout=1.20,
        ):
            self.set_status("تم اكتشاف 99 Security Logger Update قبل Start Game - جاري إعادة المحاولة")
            closed_count = ConquerMemoryReader.terminate_all_conquer()
            self._stop_launcher_only()
            print(
                "99 Security Logger update after launcher open - "
                f"attempt={attempt}/{max_attempts} - "
                f"closed {closed_count} conquer.exe process(es)"
            )
            return None, "CLIENT_UPDATE"

        time.sleep(0.50)

        launcher_pid = self._current_launcher_pid()

        self.set_status(
            f"الحساب {account_number}/{total_accounts}: البحث عن Start Game "
            f"محاولة {attempt}/{max_attempts}..."
        )

        found = self.start_game_task.start(
            target_pid=launcher_pid,
            timeout=20.0,
        )

        if handle_security_logger_update_dialog(
            reason=f"after_start_game_search_attempt_{attempt}",
            timeout=0.20,
        ):
            self.set_status("تم اكتشاف 99 Security Logger Update أثناء Start Game - جاري إعادة المحاولة")
            closed_count = ConquerMemoryReader.terminate_all_conquer()
            self._stop_launcher_only()
            print(
                "99 Security Logger update during Start Game search - "
                f"attempt={attempt}/{max_attempts} - "
                f"closed {closed_count} conquer.exe process(es)"
            )
            return None, "CLIENT_UPDATE"

        if not found:
            print(
                f"Start Game attempt {attempt}/{max_attempts} failed - "
                "button not found"
            )
            self._stop_launcher_only()
            time.sleep(1.0)
            continue

        self.set_status(
            f"الحساب {account_number}/{total_accounts}: انتظار صفحة Conquer "
            f"الجديدة محاولة {attempt}/{max_attempts}..."
        )

        conquer_pid = ConquerMemoryReader.wait_for_new_conquer_pid(
            previous_conquer_pids,
            timeout=20.0,
            launcher_pid=launcher_pid,
        )

        if conquer_pid is not None:
            return conquer_pid, "SUCCESS"

        print(
            f"Start Game attempt {attempt}/{max_attempts} clicked but no "
            "new Conquer PID appeared - retrying with a fresh launcher"
        )
        self._stop_launcher_only()
        time.sleep(1.0)

    return None, "CONQUER_PID_ERROR"


def apply_security_logger_update_patch():
    MaintenanceAwareLauncher._open_conquer_pid_with_retries = _open_conquer_pid_with_security_logger_guard
    print("99 Security Logger update patch active: global dialog OK before Start Game")


apply_security_logger_update_patch()
