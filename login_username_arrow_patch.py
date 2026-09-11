"""Optional Right Arrow presses after clicking the username field.

This is a Login-input tuning patch only.  It keeps the existing Login flow and
adds one optional step after the username field is clicked:
    click username -> optional Right Arrow presses -> clear username -> type username

The goal is to let the user move the cursor to the end of the Account field
before Backspace clearing, without changing detection or recovery logic.
"""

import time

import pydirectinput

from gui import DEFAULT_RUNTIME_SETTINGS
from selection_launcher import SelectionAwareLauncher
from tasks.login_task import LoginTask

try:
    import drop_settings_patch
except Exception:
    drop_settings_patch = None

try:
    import login_input_settings_patch as login_input
except Exception:
    login_input = None


_ORIGINAL_COERCE = SelectionAwareLauncher._coerce_runtime_setting

USERNAME_ARROW_DEFAULTS = {
    "login_username_right_arrow_enabled": True,
    "login_username_right_arrow_count": 10,
    "login_username_right_arrow_delay": 0.03,
    "login_after_username_right_arrow_delay": 0.05,
}

USERNAME_ARROW_ITEMS = (
    ("login_username_right_arrow_enabled", "بعد كليك اليوزر: اضغط سهم يمين قبل المسح - ON/OFF"),
    ("login_username_right_arrow_count", "عدد ضغطات سهم يمين بعد كليك اليوزر"),
    ("login_username_right_arrow_delay", "وقت بين كل ضغطة سهم يمين والتانية / ثانية"),
    ("login_after_username_right_arrow_delay", "انتظار بعد سهم يمين وقبل Backspace / ثانية"),
)

USERNAME_ARROW_FLOAT_KEYS = {
    "login_username_right_arrow_delay",
    "login_after_username_right_arrow_delay",
}
USERNAME_ARROW_INT_KEYS = {"login_username_right_arrow_count"}
USERNAME_ARROW_BOOL_KEYS = {"login_username_right_arrow_enabled"}


def _bool_value(value, default=False):
    if isinstance(value, bool):
        return value
    text = str(value if value is not None else "").strip().lower()
    if text in {"1", "true", "yes", "on", "enabled", "enable"}:
        return True
    if text in {"0", "false", "no", "off", "disabled", "disable"}:
        return False
    return bool(default)


def _install_defaults_and_settings():
    DEFAULT_RUNTIME_SETTINGS.update(USERNAME_ARROW_DEFAULTS)

    if drop_settings_patch is None:
        return

    try:
        groups = []
        inserted = False
        for group in getattr(drop_settings_patch, "SETTINGS_GROUPS", ()):
            if not group or len(group) < 3:
                groups.append(group)
                continue

            title, note, items = group
            if title == "Setting Login Input / كتابة الدخول":
                new_items = []
                added = False
                existing_keys = {item[0] for item in items if item}
                for item in items:
                    new_items.append(item)
                    if item and item[0] == "login_after_username_click_delay" and not added:
                        for arrow_item in USERNAME_ARROW_ITEMS:
                            if arrow_item[0] not in existing_keys:
                                new_items.append(arrow_item)
                        added = True
                if not added:
                    for arrow_item in USERNAME_ARROW_ITEMS:
                        if arrow_item[0] not in existing_keys:
                            new_items.append(arrow_item)
                groups.append((title, note, tuple(new_items)))
                inserted = True
            else:
                groups.append(group)

        if not inserted:
            groups.append((
                "Setting Login Input / كتابة الدخول",
                "تحكم في كتابة اليوزر والباسورد فقط.",
                USERNAME_ARROW_ITEMS,
            ))

        drop_settings_patch.SETTINGS_GROUPS = tuple(groups)
    except Exception as error:
        print(f"Could not install username right-arrow settings: {error}")


def _coerce_username_arrow_setting(self, key, value):
    if key in USERNAME_ARROW_BOOL_KEYS:
        return _bool_value(value, USERNAME_ARROW_DEFAULTS.get(key, False))

    if key in USERNAME_ARROW_INT_KEYS:
        try:
            value = int(float(value))
        except Exception:
            value = int(USERNAME_ARROW_DEFAULTS.get(key, 0))
        return max(0, min(80, value))

    if key in USERNAME_ARROW_FLOAT_KEYS:
        try:
            value = float(value)
        except Exception:
            value = float(USERNAME_ARROW_DEFAULTS.get(key, 0.0))
        return max(0.0, min(2.0, value))

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


def _bool_setting(self, key, default=False):
    return _bool_value(_setting(self, key, default), default)


def _int_setting(self, key, default, minimum=0, maximum=80):
    try:
        value = int(float(_setting(self, key, default)))
    except Exception:
        value = int(default)
    value = max(int(minimum), value)
    if maximum is not None:
        value = min(int(maximum), value)
    return value


def _float_setting(self, key, default, minimum=0.0, maximum=2.0):
    try:
        value = float(_setting(self, key, default))
    except Exception:
        value = float(default)
    value = max(float(minimum), value)
    if maximum is not None:
        value = min(float(maximum), value)
    return value


def _safe_restore_pause(old_pause=None):
    if login_input is not None and hasattr(login_input, "_safe_restore_pause"):
        return login_input._safe_restore_pause(old_pause)
    try:
        if old_pause is not None:
            pydirectinput.PAUSE = old_pause
    except Exception:
        pass


def _login_pause_guard(self):
    if login_input is not None and hasattr(login_input, "_login_pause_guard"):
        return login_input._login_pause_guard(self)
    old_pause = getattr(pydirectinput, "PAUSE", 0.08)
    pydirectinput.PAUSE = float(DEFAULT_RUNTIME_SETTINGS.get("login_input_pause", 0.08))
    return old_pause


def _stable_left_click(self, x, y):
    if login_input is not None and hasattr(login_input, "_stable_left_click"):
        return login_input._stable_left_click(self, x, y)
    pydirectinput.click(int(x), int(y))


def _press_username_right_arrows(self):
    if not _bool_setting(self, "login_username_right_arrow_enabled", True):
        return True

    count = _int_setting(self, "login_username_right_arrow_count", 10, minimum=0, maximum=80)
    delay = _float_setting(self, "login_username_right_arrow_delay", 0.03, minimum=0.0, maximum=2.0)
    after_delay = _float_setting(self, "login_after_username_right_arrow_delay", 0.05, minimum=0.0, maximum=2.0)

    if count <= 0:
        return True

    print(f"Login username right-arrow before clear - count={count}")
    for _ in range(count):
        if not getattr(self, "running", True):
            return False
        if self.target_pid and self._foreground_pid() != self.target_pid:
            raise RuntimeError(
                f"Target focus lost during username right-arrow; expected PID {self.target_pid}"
            )
        pydirectinput.press("right")
        if delay > 0:
            time.sleep(delay)

    if after_delay > 0:
        time.sleep(after_delay)
    return True


def _enter_credentials_with_username_arrows(self, username, password, positions):
    if login_input is None:
        print("Username arrow patch: login_input_settings_patch missing; using original Login input")
        return LoginTask._enter_credentials_at_positions(self, username, password, positions)

    (
        username_x,
        username_y,
        password_x,
        password_y,
        _password_clear_x,
    ) = positions

    username_x = int(username_x) + login_input._int_setting(self, "login_username_click_offset_x", 0)
    username_y = int(username_y) + login_input._int_setting(self, "login_username_click_offset_y", 0)
    password_x = int(password_x) + login_input._int_setting(self, "login_password_click_offset_x", 0)
    password_y = int(password_y) + login_input._int_setting(self, "login_password_click_offset_y", 0)

    old_pause = _login_pause_guard(self)
    try:
        if not self._ensure_target_window():
            return False

        print(
            "Login input positions - "
            f"username=({username_x},{username_y}) password=({password_x},{password_y})"
        )

        _stable_left_click(self, username_x, username_y)
        time.sleep(login_input._float_setting(self, "login_after_username_click_delay", 0.20, maximum=3.0))

        if not _press_username_right_arrows(self):
            return False

        self.clear_username_field()
        time.sleep(login_input._float_setting(self, "login_after_username_clear_delay", 0.10, maximum=3.0))

        self._type_exact(username)
        time.sleep(login_input._float_setting(self, "login_after_username_type_delay", 0.20, maximum=5.0))

        if not self._ensure_target_window():
            raise RuntimeError(
                f"Target focus lost after username; expected PID {self.target_pid}"
            )

        _stable_left_click(self, password_x, password_y)
        time.sleep(login_input._float_setting(self, "login_after_password_click_delay", 0.15, maximum=3.0))

        self._type_exact(password)
        time.sleep(login_input._float_setting(self, "login_after_password_type_delay", 0.15, maximum=5.0))

        if self.target_pid and self._foreground_pid() != self.target_pid:
            raise RuntimeError(
                f"Target focus lost after password; expected PID {self.target_pid}"
            )

        return True
    finally:
        _safe_restore_pause(old_pause)


def _install_runtime_defaults_on_init():
    original_init = SelectionAwareLauncher.__init__

    def init_with_username_arrow_defaults(self):
        original_init(self)
        changed = False
        try:
            for key, value in USERNAME_ARROW_DEFAULTS.items():
                if key not in self.runtime_settings:
                    self.runtime_settings[key] = value
                    changed = True
            if changed:
                self.apply_runtime_settings()
                self.save_settings()
        except Exception as error:
            print(f"Could not apply username arrow defaults: {error}")

    SelectionAwareLauncher.__init__ = init_with_username_arrow_defaults


_install_defaults_and_settings()
SelectionAwareLauncher._coerce_runtime_setting = _coerce_username_arrow_setting
LoginTask._enter_credentials_at_positions = _enter_credentials_with_username_arrows
_install_runtime_defaults_on_init()

print("Login username arrow patch active: optional Right Arrow presses before username clear")
