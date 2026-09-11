"""Separate stable login typing from fast drop mouse movement.

The drop worker needs zero mouse delay, but login typing must stay conservative so
Conquer reliably receives username/password characters.  This patch keeps the
fast mode local to Drop/Yes clicks and restores a safe typing mode during login.
"""

import pydirectinput


LOGIN_INPUT_PAUSE = 0.03
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

    original_enter = LoginTask._enter_credentials_at_positions
    original_rewrite = LoginTask.rewrite_password

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

print("Input speed patch active: login typing stable, drop mouse fast")
