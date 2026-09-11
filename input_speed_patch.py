"""Separate stable Login typing from fast Drop mouse movement.

Project rule:
- Login/Start/Recovery are protected and conservative.
- Drop/Yes may use instant mouse movement only inside their own click functions.
- Drop changes must never leave pydirectinput in a fast/global state that affects Login.
"""

import time

import pydirectinput


LOGIN_INPUT_PAUSE = 0.08
LOGIN_TYPE_INTERVAL = 0.50
DROP_INPUT_PAUSE = 0.0

# Login-safe default after post-login modules are imported.
pydirectinput.PAUSE = LOGIN_INPUT_PAUSE
pydirectinput.FAILSAFE = False


def _safe_restore_pause(old_pause=None):
    # Never restore Drop's zero-delay mode as the global program state.
    if old_pause is None or float(old_pause) <= 0.0:
        pydirectinput.PAUSE = LOGIN_INPUT_PAUSE
    else:
        pydirectinput.PAUSE = old_pause


def _install_login_stable_input_patch():
    """Login-only input guard.

    This does not change the login workflow/order. It only forces safe typing
    speed while the existing LoginTask writes username/password.
    """
    try:
        from tasks.login_task import LoginTask
    except Exception as error:
        print(f"Input boundary patch: LoginTask unavailable - {error}")
        return

    original_type_exact = LoginTask._type_exact
    original_enter = LoginTask._enter_credentials_at_positions
    original_rewrite = LoginTask.rewrite_password
    original_start = LoginTask.start

    def type_exact_slow(self, text, interval=0.04):
        old_pause = getattr(pydirectinput, "PAUSE", LOGIN_INPUT_PAUSE)
        pydirectinput.PAUSE = LOGIN_INPUT_PAUSE
        try:
            safe_interval = max(float(interval or 0.0), LOGIN_TYPE_INTERVAL)
            return original_type_exact(self, text, interval=safe_interval)
        finally:
            _safe_restore_pause(old_pause)

    def clear_username_stable(self):
        old_pause = getattr(pydirectinput, "PAUSE", LOGIN_INPUT_PAUSE)
        pydirectinput.PAUSE = LOGIN_INPUT_PAUSE
        try:
            for _ in range(35):
                if not getattr(self, "running", True):
                    return
                pydirectinput.press("backspace")
                time.sleep(0.03)
        finally:
            _safe_restore_pause(old_pause)

    def clear_password_stable(self):
        old_pause = getattr(pydirectinput, "PAUSE", LOGIN_INPUT_PAUSE)
        pydirectinput.PAUSE = LOGIN_INPUT_PAUSE
        try:
            for _ in range(35):
                if not getattr(self, "running", True):
                    return
                pydirectinput.press("backspace")
                time.sleep(0.03)
        finally:
            _safe_restore_pause(old_pause)

    def start_with_login_pause(self, *args, **kwargs):
        old_pause = getattr(pydirectinput, "PAUSE", LOGIN_INPUT_PAUSE)
        pydirectinput.PAUSE = LOGIN_INPUT_PAUSE
        try:
            return original_start(self, *args, **kwargs)
        finally:
            _safe_restore_pause(old_pause)

    def enter_credentials_stable(self, username, password, positions):
        old_pause = getattr(pydirectinput, "PAUSE", LOGIN_INPUT_PAUSE)
        pydirectinput.PAUSE = LOGIN_INPUT_PAUSE
        try:
            return original_enter(self, username, password, positions)
        finally:
            _safe_restore_pause(old_pause)

    def rewrite_password_stable(self, password, timeout=5.0, target_pid=None):
        old_pause = getattr(pydirectinput, "PAUSE", LOGIN_INPUT_PAUSE)
        pydirectinput.PAUSE = LOGIN_INPUT_PAUSE
        try:
            return original_rewrite(self, password, timeout=timeout, target_pid=target_pid)
        finally:
            _safe_restore_pause(old_pause)

    LoginTask._type_exact = type_exact_slow
    LoginTask.clear_username_field = clear_username_stable
    LoginTask.clear_password_field = clear_password_stable
    LoginTask.start = start_with_login_pause
    LoginTask._enter_credentials_at_positions = enter_credentials_stable
    LoginTask.rewrite_password = rewrite_password_stable


def _install_drop_fast_click_patch():
    try:
        import win32api
        from tasks.post_login_modules.inventory_drop_worker import InventoryDropWorkerModule
    except Exception as error:
        print(f"Input boundary patch: DropWorker unavailable - {error}")
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
            _safe_restore_pause(old_pause)

    InventoryDropWorkerModule._click_point = fast_click_point


def _install_yes_fast_click_patch():
    try:
        import tasks.post_login_modules.drop_confirmation as drop_confirmation
        import tasks.post_login_modules.inventory_drop_worker as drop_worker_module
    except Exception as error:
        print(f"Input boundary patch: Drop YES unavailable - {error}")
        return

    original_click_yes = drop_confirmation.click_drop_yes_if_visible

    def click_yes_fast(*args, **kwargs):
        old_pause = getattr(pydirectinput, "PAUSE", LOGIN_INPUT_PAUSE)
        pydirectinput.PAUSE = DROP_INPUT_PAUSE
        try:
            return original_click_yes(*args, **kwargs)
        finally:
            _safe_restore_pause(old_pause)

    drop_confirmation.click_drop_yes_if_visible = click_yes_fast
    drop_worker_module.click_drop_yes_if_visible = click_yes_fast


_install_login_stable_input_patch()
_install_drop_fast_click_patch()
_install_yes_fast_click_patch()
_safe_restore_pause(None)

print(
    "Input boundary patch active: Login typing protected, Drop/Yes fast isolated - "
    f"login_interval={LOGIN_TYPE_INTERVAL}s"
)
