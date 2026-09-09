import os
from datetime import datetime

from tasks.post_login_modules.window_capture import capture_pid_window


class InventoryProbeModule:
    """First safe merge piece for inventory work.

    This module does not drop, use, click, type, or move the mouse.
    It only proves that the current account window can be captured safely before
    we connect the real Inventory/Drop logic.
    """

    name = "inventory_probe"
    setting_key = "enable_inventory_probe"

    def __init__(self, launcher):
        self.launcher = launcher

    def _setting(self, key, default=None):
        if hasattr(self.launcher, "get_runtime_setting"):
            try:
                return self.launcher.get_runtime_setting(key, default)
            except Exception:
                return default
        return default

    def _feature_enabled(self, key, default=False):
        if hasattr(self.launcher, "feature_enabled"):
            try:
                return bool(self.launcher.feature_enabled(key, default))
            except Exception:
                return bool(default)

        value = self._setting(key, default)
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"1", "true", "yes", "on", "enabled"}

    def enabled(self):
        return self._feature_enabled(self.setting_key, False)

    def _save_debug_enabled(self):
        return self._feature_enabled("inventory_probe_save_debug_image", True)

    def _debug_dir(self):
        value = self._setting("inventory_probe_debug_dir", "logs/inventory_probe")
        text = str(value or "logs/inventory_probe").strip()
        return text or "logs/inventory_probe"

    def run(self, account_index, session):
        if not self.enabled():
            return "SKIPPED"

        pid = session.get("pid")
        page_name = session.get("page_name", "")

        if not pid:
            return "INVENTORY_PROBE_NO_PID"

        image, hwnd = capture_pid_window(pid)
        if image is None:
            return "INVENTORY_PROBE_CAPTURE_FAILED"

        width, height = image.size
        print(
            "Inventory probe capture OK - "
            f"account={account_index + 1} - pid={pid} - hwnd={hwnd} - "
            f"name={page_name!r} - size={width}x{height}"
        )

        if self._save_debug_enabled():
            try:
                folder = self._debug_dir()
                os.makedirs(folder, exist_ok=True)
                stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                path = os.path.join(
                    folder,
                    f"account_{account_index + 1}_pid_{pid}_{stamp}.png",
                )
                image.save(path)
                print(f"Inventory probe debug image saved: {path}")
            except Exception as error:
                print(
                    "Inventory probe debug save failed - "
                    f"account={account_index + 1} - pid={pid} - {error}"
                )

        return "OK"
