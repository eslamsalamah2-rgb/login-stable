"""Separate stable login typing from fast drop mouse movement.

Drop needs instant mouse movement. Login must stay conservative so Conquer does
not miss digits/letters while username and password are being typed.
"""

import time

import pydirectinput


LOGIN_INPUT_PAUSE = 0.05
LOGIN_TYPE_INTERVAL = 0.18
DROP_INPUT_PAUSE = 0.0

# Safe default for the whole program after all drop modules were imported.
pydirectinput.PAUSE = LOGIN_INPUT_PAUSE
pydirectinput.FAILSAFE = False


def _install_login_stable_input_patch():
    try:
        from tasks.login_task import LoginTask
    except Exception as error:
        print(f"Input speed patch: LoginTask unavailable - {error}")
        return

    original_type_exact = LoginTask._type_exact
    original_enter = LoginTask._enter_credentials_at_positions
    original_rewrite = LoginTask.rewrite_password

    def type_exact_slow(self, text, interval=0.04):
        old_pause = getattr(pydirectinput, "PAUSE", LOGIN_INPUT_PAUSE)
        pydirectinput.PAUSE = LOGIN_INPUT_PAUSE
        try:
            safe_interval = max(float(interval or 0.0), LOGIN_TYPE_INTERVAL)
            return original_type_exact(self, text, interval=safe_interval)
        finally:
            pydirectinput.PAUSE = old_pause

    def clear_username_stable(self):
        old_pause = getattr(pydirectinput, "PAUSE", LOGIN_INPUT_PAUSE)
        pydirectinput.PAUSE = LOGIN_INPUT_PAUSE
        try:
            # A missed digit means the whole field must be fully cleared before
            # a retry. Keep this longer than the old quick clear.
            for _ in range(30):
                if not getattr(self, "running", True):
                    return
                pydirectinput.press("backspace")
                time.sleep(0.03)
        finally:
            pydirectinput.PAUSE = old_pause

    def clear_password_stable(self):
        old_pause = getattr(pydirectinput, "PAUSE", LOGIN_INPUT_PAUSE)
        pydirectinput.PAUSE = LOGIN_INPUT_PAUSE
        try:
            for _ in range(30):
                if not getattr(self, "running", True):
                    return
                pydirectinput.press("backspace")
                time.sleep(0.03)
        finally:
            pydirectinput.PAUSE = old_pause

    def enter_credentials_stable(self, username, password, positions):
        old_pause = getattr(pydirectinput, "PAUSE", LOGIN_INPUT_PAUSE)
        pydirectinput.PAUSE = LOGIN_INPUT_PAUSE
        try:
            return original_enter(self, username, password, positions)
        finally:
            pydirectinput.PAUSE = old_pause

    def rewrite_password_stable(self, password, timeout=5.0, target_pid=None):
        old_pause = getattr(pydirectinput, "PAUSE", LOGIN_INPUT_PAUSE)
        pydirectinput.PAUSE = LOGIN_INPUT_PAUSE
        try:
            return original_rewrite(self, password, timeout=timeout, target_pid=target_pid)
        finally:
            pydirectinput.PAUSE = old_pause

    LoginTask._type_exact = type_exact_slow
    LoginTask.clear_username_field = clear_username_stable
    LoginTask.clear_password_field = clear_password_stable
    LoginTask._enter_credentials_at_positions = enter_credentials_stable
    LoginTask.rewrite_password = rewrite_password_stable


def _install_drop_fast_click_patch():
    try:
        import win32api
        from tasks.post_login_modules.inventory_drop_worker import InventoryDropWorkerModule
    except Exception as error:
        print(f"Input speed patch: DropWorker unavailable - {error}")
        return

    def fast_click_point(self, x, y, clicks):
        old_pause = getattr(pydirectinput, "PAUSE", LOGIN_INPUT_PAUSE)
        pydirectinput.PAUSE = DROP_INPUT_PAUSE
        try:
            try:
                win32api.SetCursorPos((int(x), int(y)))
            except Exception:
                pydirectinput.moveTo(int(x), int(y), duration=0)

            for _ in range(max(1, int(clicks))):
                if hasattr(self, "_stop_requested") and self._stop_requested():
                    return False
                pydirectinput.click()
            return True
        finally:
            pydirectinput.PAUSE = old_pause

    InventoryDropWorkerModule._click_point = fast_click_point


def _install_yes_fast_click_patch():
    try:
        import tasks.post_login_modules.drop_confirmation as drop_confirmation
        import tasks.post_login_modules.inventory_drop_worker as drop_worker_module
    except Exception as error:
        print(f"Input speed patch: Drop YES unavailable - {error}")
        return

    original_click_yes = drop_confirmation.click_drop_yes_if_visible

    def click_yes_fast(*args, **kwargs):
        old_pause = getattr(pydirectinput, "PAUSE", LOGIN_INPUT_PAUSE)
        pydirectinput.PAUSE = DROP_INPUT_PAUSE
        try:
            return original_click_yes(*args, **kwargs)
        finally:
            pydirectinput.PAUSE = old_pause

    drop_confirmation.click_drop_yes_if_visible = click_yes_fast
    drop_worker_module.click_drop_yes_if_visible = click_yes_fast


_install_login_stable_input_patch()
_install_drop_fast_click_patch()
_install_yes_fast_click_patch()

print(
    "Input speed patch active: login typing stable/slow, drop mouse fast - "
    f"login_interval={LOGIN_TYPE_INTERVAL}s"
)
