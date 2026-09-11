"""Editable Login input timings and click offsets.

This patch keeps the existing Login workflow intact. It only exposes the
input timings/click offsets that control how username and password are typed.

Settings added:
- typing interval between characters
- username/password backspace counts
- delays between field click / clear / typing
- small X/Y offsets for username and password click points

No image thresholds are exposed and no post-login worker is touched.
"""

import time

import pydirectinput
import win32api

from gui import DEFAULT_RUNTIME_SETTINGS, SimpleLauncher
from selection_launcher import SelectionAwareLauncher
from tasks.login_task import LoginTask

try:
    import drop_settings_patch
except Exception:
    drop_settings_patch = None


_ORIGINAL_SELECTION_INIT = SelectionAwareLauncher.__init__
_ORIGINAL_COERCE = SelectionAwareLauncher._coerce_runtime_setting

LOGIN_INPUT_DEFAULTS = {
    # General typing speed. 0.50 is deliberately safe for accounts that include numbers.
    "login_input_pause": 0.08,
    "login_type_interval": 0.50,

    # Backspace clearing.
    "login_username_clear_presses": 35,
    "login_password_clear_presses": 35,
    "login_backspace_delay": 0.03,

    # Timing inside the fixed login sequence.
    "login_after_username_click_delay": 0.20,
    "login_after_username_clear_delay": 0.10,
    "login_after_username_type_delay": 0.20,
    "login_after_password_click_delay": 0.15,
    "login_after_password_type_delay": 0.15,
    "login_click_focus_delay": 0.05,

    # Fine click tuning from the detected Account/Password positions.
    # Negative X moves the click left; positive X moves it right.
    "login_username_click_offset_x": 0,
    "login_username_click_offset_y": 0,
    "login_password_click_offset_x": 0,
    "login_password_click_offset_y": 0,
    "login_password_clear_offset_x": 0,
    "login_password_clear_offset_y": 0,
}

LOGIN_INPUT_GROUP = (
    "Setting Login Input / كتابة الدخول",
    "تحكم في كتابة اليوزر والباسورد فقط. الإحداثيات جاية من صورة Account/Password، والـ Offset يزحزح الكليك يمين/شمال أو فوق/تحت.",
    (
        ("login_type_interval", "وقت بين كتابة كل حرف/رقم في اليوزر والباسورد / ثانية"),
        ("login_input_pause", "تأخير داخلي آمن لحركات كيبورد Login"),
        ("login_username_clear_presses", "عدد ضغطات Backspace لمسح خانة اليوزر"),
        ("login_password_clear_presses", "عدد ضغطات Backspace لمسح خانة الباسورد عند إعادة كتابته"),
        ("login_backspace_delay", "وقت بين كل Backspace والتانية / ثانية"),
        ("login_after_username_click_delay", "انتظار بعد كليك خانة اليوزر قبل المسح"),
        ("login_after_username_clear_delay", "انتظار بعد مسح اليوزر قبل الكتابة"),
        ("login_after_username_type_delay", "انتظار بعد كتابة اليوزر قبل كليك الباسورد"),
        ("login_after_password_click_delay", "انتظار بعد كليك خانة الباسورد قبل الكتابة"),
        ("login_after_password_type_delay", "انتظار بعد كتابة الباسورد قبل الضغط على Log In"),
        ("login_click_focus_delay", "انتظار صغير بعد تحريك الماوس وقبل الكليك"),
        ("login_username_click_offset_x", "تحريك كليك اليوزر يمين/شمال بالبكسل - السالب ناحية الشمال"),
        ("login_username_click_offset_y", "تحريك كليك اليوزر فوق/تحت بالبكسل"),
        ("login_password_click_offset_x", "تحريك كليك الباسورد يمين/شمال بالبكسل - السالب ناحية الشمال"),
        ("login_password_click_offset_y", "تحريك كليك الباسورد فوق/تحت بالبكسل"),
        ("login_password_clear_offset_x", "تحريك كليك مسح الباسورد يمين/شمال بالبكسل"),
        ("login_password_clear_offset_y", "تحريك كليك مسح الباسورد فوق/تحت بالبكسل"),
    ),
)

LOGIN_FLOAT_KEYS = {
    "login_input_pause",
    "login_type_interval",
    "login_backspace_delay",
    "login_after_username_click_delay",
    "login_after_username_clear_delay",
    "login_after_username_type_delay",
    "login_after_password_click_delay",
    "login_after_password_type_delay",
    "login_click_focus_delay",
}

LOGIN_INT_KEYS = {
    "login_username_clear_presses",
    "login_password_clear_presses",
    "login_username_click_offset_x",
    "login_username_click_offset_y",
    "login_password_click_offset_x",
    "login_password_click_offset_y",
    "login_password_clear_offset_x",
    "login_password_clear_offset_y",
}


def _install_defaults_and_settings_group():
    DEFAULT_RUNTIME_SETTINGS.update(LOGIN_INPUT_DEFAULTS)

    if drop_settings_patch is None:
        return

    try:
        groups = list(getattr(drop_settings_patch, "SETTINGS_GROUPS", ()))
        if not any(group and group[0] == LOGIN_INPUT_GROUP[0] for group in groups):
            insert_at = 1 if groups else 0
            groups.insert(insert_at, LOGIN_INPUT_GROUP)
            drop_settings_patch.SETTINGS_GROUPS = tuple(groups)
    except Exception as error:
        print(f"Could not install Login Input settings group: {error}")


def _coerce_login_setting(self, key, value):
    if key in LOGIN_FLOAT_KEYS:
        try:
            value = float(value)
        except Exception:
            value = float(LOGIN_INPUT_DEFAULTS.get(key, 0.0))
        if key == "login_type_interval":
            return max(0.01, min(2.0, value))
        if key == "login_input_pause":
            return max(0.0, min(1.0, value))
        return max(0.0, min(5.0, value))

    if key in LOGIN_INT_KEYS:
        try:
            value = int(float(value))
        except Exception:
            value = int(LOGIN_INPUT_DEFAULTS.get(key, 0))
        if key.endswith("_presses"):
            return max(0, min(120, value))
        return max(-500, min(500, value))

    return _ORIGINAL_COERCE(self, key, value)


def _launcher(self):
    return getattr(self, "launcher", None)


def _setting(self, key, default=None):
    launcher = _launcher(self)
    if launcher is not None:
        try:
            return launcher.get_runtime_setting(key, default)
        except Exception:
            pass
    return DEFAULT_RUNTIME_SETTINGS.get(key, default)


def _float_setting(self, key, default, minimum=0.0, maximum=5.0):
    try:
        value = float(_setting(self, key, default))
    except Exception:
        value = float(default)
    value = max(float(minimum), value)
    if maximum is not None:
        value = min(float(maximum), value)
    return value


def _int_setting(self, key, default, minimum=-500, maximum=500):
    try:
        value = int(float(_setting(self, key, default)))
    except Exception:
        value = int(default)
    value = max(int(minimum), value)
    if maximum is not None:
        value = min(int(maximum), value)
    return value


def _safe_restore_pause(old_pause=None):
    safe_pause = float(LOGIN_INPUT_DEFAULTS["login_input_pause"])
    try:
        launcher = getattr(LoginTask, "_last_launcher_for_input_settings", None)
        if launcher is not None:
            safe_pause = float(launcher.get_runtime_setting("login_input_pause", safe_pause))
    except Exception:
        pass

    try:
        if old_pause is None or float(old_pause) <= 0.0:
            pydirectinput.PAUSE = safe_pause
        else:
            pydirectinput.PAUSE = old_pause
    except Exception:
        pydirectinput.PAUSE = safe_pause


def _login_pause_guard(self):
    old_pause = getattr(pydirectinput, "PAUSE", LOGIN_INPUT_DEFAULTS["login_input_pause"])
    pydirectinput.PAUSE = _float_setting(self, "login_input_pause", 0.08, minimum=0.0, maximum=1.0)
    return old_pause


def _stable_left_click(self, x, y):
    try:
        win32api.SetCursorPos((int(x), int(y)))
    except Exception:
        pydirectinput.moveTo(int(x), int(y), duration=0)

    focus_delay = _float_setting(self, "login_click_focus_delay", 0.05, minimum=0.0, maximum=1.0)
    if focus_delay > 0:
        time.sleep(focus_delay)
    pydirectinput.click()


def _type_exact_configurable(self, text, interval=0.04):
    text = str(text)
    safe_interval = _float_setting(
        self,
        "login_type_interval",
        max(float(interval or 0.0), 0.50),
        minimum=0.01,
        maximum=2.0,
    )

    caps_was_on = False
    try:
        import ctypes
        caps_was_on = bool(ctypes.windll.user32.GetKeyState(0x14) & 0x0001)
    except Exception:
        caps_was_on = False

    old_pause = _login_pause_guard(self)
    try:
        if caps_was_on:
            pydirectinput.press("capslock")
            time.sleep(0.08)

        for char in text:
            if self.target_pid and self._foreground_pid() != self.target_pid:
                raise RuntimeError(
                    f"Target focus lost while typing; expected PID {self.target_pid}"
                )

            if "A" <= char <= "Z":
                key = char.lower()
                pydirectinput.keyDown("shift")
                pydirectinput.press(key)
                pydirectinput.keyUp("shift")
            else:
                pydirectinput.write(char)

            if safe_interval > 0:
                time.sleep(safe_interval)

    finally:
        try:
            pydirectinput.keyUp("shift")
        except Exception:
            pass

        if caps_was_on:
            pydirectinput.press("capslock")
            time.sleep(0.08)

        _safe_restore_pause(old_pause)


def _clear_username_configurable(self):
    presses = _int_setting(self, "login_username_clear_presses", 35, minimum=0, maximum=120)
    delay = _float_setting(self, "login_backspace_delay", 0.03, minimum=0.0, maximum=1.0)
    old_pause = _login_pause_guard(self)
    try:
        for _ in range(presses):
            pydirectinput.press("backspace")
            if delay > 0:
                time.sleep(delay)
    finally:
        _safe_restore_pause(old_pause)


def _clear_password_configurable(self):
    presses = _int_setting(self, "login_password_clear_presses", 35, minimum=0, maximum=120)
    delay = _float_setting(self, "login_backspace_delay", 0.03, minimum=0.0, maximum=1.0)
    old_pause = _login_pause_guard(self)
    try:
        for _ in range(presses):
            pydirectinput.press("backspace")
            if delay > 0:
                time.sleep(delay)
    finally:
        _safe_restore_pause(old_pause)


def _enter_credentials_configurable(self, username, password, positions):
    (
        username_x,
        username_y,
        password_x,
        password_y,
        _password_clear_x,
    ) = positions

    username_x = int(username_x) + _int_setting(self, "login_username_click_offset_x", 0)
    username_y = int(username_y) + _int_setting(self, "login_username_click_offset_y", 0)
    password_x = int(password_x) + _int_setting(self, "login_password_click_offset_x", 0)
    password_y = int(password_y) + _int_setting(self, "login_password_click_offset_y", 0)

    old_pause = _login_pause_guard(self)
    try:
        if not self._ensure_target_window():
            return False

        print(
            "Login input positions - "
            f"username=({username_x},{username_y}) password=({password_x},{password_y})"
        )

        _stable_left_click(self, username_x, username_y)
        time.sleep(_float_setting(self, "login_after_username_click_delay", 0.20, maximum=3.0))

        self.clear_username_field()
        time.sleep(_float_setting(self, "login_after_username_clear_delay", 0.10, maximum=3.0))

        self._type_exact(username)
        time.sleep(_float_setting(self, "login_after_username_type_delay", 0.20, maximum=5.0))

        if not self._ensure_target_window():
            raise RuntimeError(
                f"Target focus lost after username; expected PID {self.target_pid}"
            )

        _stable_left_click(self, password_x, password_y)
        time.sleep(_float_setting(self, "login_after_password_click_delay", 0.15, maximum=3.0))

        self._type_exact(password)
        time.sleep(_float_setting(self, "login_after_password_type_delay", 0.15, maximum=5.0))

        if self.target_pid and self._foreground_pid() != self.target_pid:
            raise RuntimeError(
                f"Target focus lost after password; expected PID {self.target_pid}"
            )

        return True
    finally:
        _safe_restore_pause(old_pause)


def _rewrite_password_configurable(self, password, timeout=5.0, target_pid=None):
    if not password:
        return False

    if target_pid is not None:
        self.set_target_pid(target_pid)
    else:
        try:
            from tasks.target_window_context import TargetWindowContext
            shared_pid = TargetWindowContext.get_pid()
            if shared_pid:
                self.target_pid = shared_pid
        except Exception:
            pass

    start_time = time.time()
    positions = None

    while time.time() - start_time < timeout:
        if not self._ensure_target_window():
            time.sleep(0.20)
            continue

        positions = self.find_login_fields()
        if positions:
            break
        time.sleep(0.20)

    if not positions:
        print("Password retry: login fields not found after OK")
        return False

    if not self._ensure_target_window():
        return False

    (
        _username_x,
        _username_y,
        password_x,
        password_y,
        password_clear_x,
    ) = positions

    password_x = int(password_x) + _int_setting(self, "login_password_click_offset_x", 0)
    password_y = int(password_y) + _int_setting(self, "login_password_click_offset_y", 0)
    password_clear_x = int(password_clear_x) + _int_setting(self, "login_password_clear_offset_x", 0)
    password_clear_y = int(password_y) + _int_setting(self, "login_password_clear_offset_y", 0)

    old_pause = _login_pause_guard(self)
    try:
        _stable_left_click(self, password_clear_x, password_clear_y)
        time.sleep(_float_setting(self, "login_after_username_click_delay", 0.20, maximum=3.0))

        self.clear_password_field()
        time.sleep(_float_setting(self, "login_after_username_clear_delay", 0.10, maximum=3.0))

        if not self._ensure_target_window():
            return False

        _stable_left_click(self, password_x, password_y)
        time.sleep(_float_setting(self, "login_after_password_click_delay", 0.15, maximum=3.0))

        self._type_exact(password)
        time.sleep(_float_setting(self, "login_after_password_type_delay", 0.15, maximum=5.0))

    except RuntimeError as error:
        print(f"Password retry safety: {error}")
        return False
    finally:
        _safe_restore_pause(old_pause)

    print(f"Password rewritten on target PID {self.target_pid} with configurable Login timing")
    return True


def _selection_init_with_login_input_settings(self):
    _ORIGINAL_SELECTION_INIT(self)
    try:
        self.login_task.launcher = self
        LoginTask._last_launcher_for_input_settings = self
    except Exception as error:
        print(f"Could not attach launcher to LoginTask for input settings: {error}")

    changed = False
    try:
        for key, value in LOGIN_INPUT_DEFAULTS.items():
            if key not in self.runtime_settings:
                self.runtime_settings[key] = value
                changed = True
        if changed:
            self.apply_runtime_settings()
            self.save_settings()
    except Exception as error:
        print(f"Could not apply Login Input defaults: {error}")


def apply_login_input_settings_patch():
    _install_defaults_and_settings_group()

    # Allow sub-0.10 timing values for these Login-only controls; the old generic
    # coerce clamps floats to 0.10 because it was written for large timeouts.
    SimpleLauncher._coerce_runtime_setting = _coerce_login_setting
    SelectionAwareLauncher._coerce_runtime_setting = _coerce_login_setting

    LoginTask._type_exact = _type_exact_configurable
    LoginTask.clear_username_field = _clear_username_configurable
    LoginTask.clear_password_field = _clear_password_configurable
    LoginTask._enter_credentials_at_positions = _enter_credentials_configurable
    LoginTask.rewrite_password = _rewrite_password_configurable

    SelectionAwareLauncher.__init__ = _selection_init_with_login_input_settings

    print("Login input settings patch active: typing delays, clear counts, and click offsets are editable")


apply_login_input_settings_patch()
