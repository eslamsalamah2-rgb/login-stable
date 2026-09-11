"""Add two-page Sash Next handling without touching Login.

When an account has Sash enabled:
- Sash runs after Use as before.
- If an item stays in the same inventory slot after repeated Alt+Click attempts,
  the current Sash page is treated as full/no-space.
- The worker clicks the external Next arrow image once, then retries on page 2.
- If the item still does not move after Next, Sash is disabled for that account
  for the current program run/session only. The saved account checkbox is not changed.

External images only:
    assets/sash_next.png
    assets/SashNext.png
    assets/sash_next_arrow.png
    assets/next_sash.png
"""

import os
import time
from functools import lru_cache

import cv2
import numpy as np
from PIL import Image

from gui import DEFAULT_RUNTIME_SETTINGS
from selection_launcher import SelectionAwareLauncher
from tasks.post_login_modules.inventory_item_probe import load_item_templates
from tasks.post_login_modules.inventory_grid_probe import (
    detect_inventory_grid,
    draw_failure_debug,
)
from tasks.post_login_modules.window_capture import capture_pid_window
from tasks.post_login_modules.inventory_sash_worker import (
    InventorySashWorkerModule,
    SASH_BUTTON_MATCH_SCALES,
    SashButtonMatch,
)

try:
    import drop_settings_patch
except Exception:
    drop_settings_patch = None

try:
    import existing_pages_settings_patch
except Exception:
    existing_pages_settings_patch = None


_ORIGINAL_SELECTION_INIT = SelectionAwareLauncher.__init__

DEFAULT_SASH_NEXT_PATHS = (
    os.path.join("assets", "sash_next.png"),
    os.path.join("assets", "SashNext.png"),
    os.path.join("assets", "sash_next_arrow.png"),
    os.path.join("assets", "next_sash.png"),
)

SASH_NEXT_SETTING_DEFAULTS = {
    "inventory_sash_next_enabled": True,
    "inventory_sash_next_paths": "",
    "inventory_sash_next_threshold": 0.78,
    "inventory_sash_next_wait_seconds": 0.30,
    "inventory_sash_stuck_repeat_limit": 2,
    "inventory_sash_disable_after_next_no_change": True,
}

SASH_NEXT_SETTING_LABELS = {
    "inventory_sash_next_enabled": "inventory_sash_next_enabled | Sash - استخدام صفحة Next عند امتلاء الصفحة الأولى",
    "inventory_sash_next_paths": "inventory_sash_next_paths | مسارات إضافية لصورة سهم Next في Sash",
    "inventory_sash_next_threshold": "inventory_sash_next_threshold | حساسية صورة سهم Next في Sash",
    "inventory_sash_next_wait_seconds": "inventory_sash_next_wait_seconds | انتظار بعد الضغط على سهم Next / ثانية",
    "inventory_sash_stuck_repeat_limit": "inventory_sash_stuck_repeat_limit | عدد مرات نفس الـItem قبل اعتبار صفحة Sash مليانة",
    "inventory_sash_disable_after_next_no_change": "inventory_sash_disable_after_next_no_change | إيقاف Sash للحساب في التشغيل الحالي لو مفيش تغيير بعد Next",
}


@lru_cache(maxsize=32)
def _load_sash_next_image(path):
    try:
        if not os.path.isfile(path):
            return None
        return Image.open(path).convert("RGB")
    except Exception as error:
        print(f"Sash Next image load failed: {path} - {error}")
        return None


def _sash_next_enabled(self):
    return self._feature_enabled("inventory_sash_next_enabled", True)


def _sash_next_paths_text(self):
    return str(self._setting("inventory_sash_next_paths", "") or "")


def _sash_next_paths(self):
    paths = list(DEFAULT_SASH_NEXT_PATHS)
    extra = self._sash_next_paths_text().replace(";", "\n").splitlines()
    for item in extra:
        text = item.strip()
        if text and text not in paths:
            paths.append(text)
    return paths


def _sash_next_threshold(self):
    return self._float_setting("inventory_sash_next_threshold", 0.78, minimum=0.10, maximum=0.99)


def _sash_next_wait(self):
    return self._float_setting("inventory_sash_next_wait_seconds", 0.30, minimum=0.0, maximum=3.0)


def _sash_stuck_repeat_limit(self):
    return self._int_setting("inventory_sash_stuck_repeat_limit", 2, minimum=1, maximum=5)


def _sash_disable_after_next_no_change(self):
    return self._feature_enabled("inventory_sash_disable_after_next_no_change", True)


def _account_sash_runtime_key(self, account_index, session):
    session = session or {}
    username = str(session.get("username", "") or "").strip().lower()
    if not username:
        try:
            accounts = getattr(self.launcher, "accounts_data", [])
            if 0 <= account_index < len(accounts):
                username = str(accounts[account_index].get("username", "") or "").strip().lower()
        except Exception:
            username = ""
    return username or f"index:{account_index}"


def _sash_no_space_set(self):
    current = getattr(self.launcher, "_sash_no_space_accounts", None)
    if current is None:
        current = set()
        setattr(self.launcher, "_sash_no_space_accounts", current)
    return current


def _sash_mark_no_space(self, account_index, session, reason):
    key = self._account_sash_runtime_key(account_index, session)
    try:
        self._sash_no_space_set().add(key)
    except Exception:
        pass
    try:
        if isinstance(session, dict):
            session["sash_no_space"] = True
            session["sash_no_space_reason"] = reason
    except Exception:
        pass
    print(
        "Inventory sash disabled for this account in current run - "
        f"account={account_index + 1} - reason={reason}"
    )


def _sash_is_no_space(self, account_index, session):
    try:
        if isinstance(session, dict) and session.get("sash_no_space"):
            return True
    except Exception:
        pass
    key = self._account_sash_runtime_key(account_index, session)
    try:
        return key in self._sash_no_space_set()
    except Exception:
        return False


def _find_sash_next_button(self, image, hwnd):
    source = self._pil_to_bgr(image)
    src_h, src_w = source.shape[:2]
    threshold = self._sash_next_threshold()
    best = None

    for path in self._sash_next_paths():
        template_image = _load_sash_next_image(path)
        if template_image is None:
            continue

        template = self._pil_to_bgr(template_image)
        temp_h, temp_w = template.shape[:2]

        for scale in SASH_BUTTON_MATCH_SCALES:
            if self._stop_requested():
                return None

            width = int(round(temp_w * float(scale)))
            height = int(round(temp_h * float(scale)))

            if width < 4 or height < 4 or width > src_w or height > src_h:
                continue

            try:
                resized = cv2.resize(template, (width, height), interpolation=cv2.INTER_AREA)
                result = cv2.matchTemplate(source, resized, cv2.TM_CCOEFF_NORMED)
                _, score, _, loc = cv2.minMaxLoc(result)
                score = float(score)

                if np.isfinite(score) and (best is None or score > best[0]):
                    best = (score, int(loc[0]), int(loc[1]), width, height, path)
            except Exception:
                continue

    if best is None:
        print("Sash Next not found - no external next image loaded")
        return None

    score, x, y, width, height, path = best
    if score < threshold:
        print(f"Sash Next not found - best={score:.3f} threshold={threshold:.3f} source={path}")
        return None

    center_window = (int(x + width / 2), int(y + height / 2))
    center_screen = self._screen_point_from_window_point(hwnd, center_window)
    return SashButtonMatch(score=float(score), center_screen=center_screen, source=path)


def _click_sash_next_page(self, pid, hwnd, account_index):
    if not self._sash_next_enabled():
        print(f"Sash Next disabled in settings - account={account_index + 1}")
        return False, hwnd

    image, hwnd = self._capture_current_window(pid, hwnd)
    if image is None or not hwnd:
        print(f"Sash Next failed - capture failed - account={account_index + 1}")
        return False, hwnd

    match = self._find_sash_next_button(image, hwnd)
    if match is None:
        print(
            "Sash Next skipped - arrow image not found/matched. "
            "Add assets\\sash_next.png"
        )
        return False, hwnd

    print(
        "Sash Next found - "
        f"account={account_index + 1} - score={match.score:.3f} - "
        f"xy={match.center_screen} - source={match.source}"
    )

    if not self._left_click_point(match.center_screen[0], match.center_screen[1]):
        return False, hwnd

    wait_seconds = self._sash_next_wait()
    if wait_seconds > 0 and not self._sleep_interruptible(wait_seconds):
        return False, hwnd

    print(
        "Sash Next clicked - "
        f"account={account_index + 1} - wait={wait_seconds:.2f}s"
    )
    return True, hwnd


def _install_sash_next_defaults():
    DEFAULT_RUNTIME_SETTINGS.update(SASH_NEXT_SETTING_DEFAULTS)

    if existing_pages_settings_patch is not None:
        try:
            existing_pages_settings_patch.SETTING_LABELS.update(SASH_NEXT_SETTING_LABELS)
        except Exception:
            pass


def _install_sash_next_settings_group():
    if drop_settings_patch is None:
        return

    try:
        groups = list(drop_settings_patch.SETTINGS_GROUPS)
        updated = []

        for group in groups:
            if group[0] != "Setting Sash":
                updated.append(group)
                continue

            title, note, items = group
            items = list(items)

            extra_items = (
                ("inventory_sash_next_wait_seconds", "انتظار بعد الضغط على سهم Next / ثانية"),
                ("inventory_sash_stuck_repeat_limit", "عدد مرات نفس الـItem قبل اعتبار صفحة Sash مليانة"),
            )

            existing_keys = {item[0] for item in items}
            for item in extra_items:
                if item[0] not in existing_keys:
                    items.append(item)

            updated.append((title, note, tuple(items)))

        drop_settings_patch.SETTINGS_GROUPS = tuple(updated)

    except Exception as error:
        print(f"Could not install Sash Next settings group: {error}")


def _selection_init_with_sash_next_defaults(self):
    _ORIGINAL_SELECTION_INIT(self)

    changed = False
    try:
        for key, value in SASH_NEXT_SETTING_DEFAULTS.items():
            if key not in self.runtime_settings:
                self.runtime_settings[key] = value
                changed = True
        if changed:
            self.apply_runtime_settings()
            self.save_settings()
    except Exception as error:
        print(f"Could not apply Sash Next defaults: {error}")


def _run_sash_with_next_page(self, account_index, session):
    if not self.enabled():
        return "SKIPPED"

    if not self._account_sash_enabled(account_index, session or {}):
        print(f"Inventory sash skipped - account={account_index + 1} - sash_checkbox=false")
        return "OK"

    if self._sash_is_no_space(account_index, session or {}):
        print(
            "Inventory sash skipped - no more Sash space for this account in current run - "
            f"account={account_index + 1}"
        )
        return "OK"

    if self._stop_requested():
        return "STOP_REQUESTED"

    session = session or {}
    pid = session.get("pid")
    page_name = session.get("page_name", "")
    if not pid:
        return "INVENTORY_SASH_NO_PID"

    templates_dir = self._templates_dir()
    templates = load_item_templates(templates_dir)
    if not templates:
        print("Inventory sash skipped - no sash item templates - " f"folder={templates_dir!r}")
        return "OK"

    prepared_templates = self._prepare_templates(templates)
    if self._stop_requested():
        return "STOP_REQUESTED"
    if not prepared_templates:
        print("Inventory sash skipped - no usable prepared templates")
        return "OK"

    image, hwnd = capture_pid_window(pid)
    if image is None or not hwnd:
        return "INVENTORY_SASH_CAPTURE_FAILED"

    grid = detect_inventory_grid(image)
    if grid is None:
        print(
            "Inventory sash skipped - bag/grid not detected - "
            f"account={account_index + 1} - pid={pid} - hwnd={hwnd} - name={page_name!r}"
        )
        try:
            self._save_image(draw_failure_debug(image), "grid_not_found", account_index, pid)
        except Exception as error:
            print(f"Inventory sash failure image save failed: {error}")
        return "OK"

    image, hwnd, grid, item_result, action, scan_status = self._scan_next_sash(pid, hwnd, grid, prepared_templates)
    if scan_status == "STOP_REQUESTED":
        return "STOP_REQUESTED"
    if scan_status == "CAPTURE_FAILED" or image is None or not hwnd:
        return "INVENTORY_SASH_CAPTURE_FAILED"
    if action is None:
        scanned = getattr(item_result, "scanned_slots", 0) if item_result is not None else 0
        print(
            "Inventory sash complete - no matched sash items - "
            f"account={account_index + 1} - scanned_slots={scanned}"
        )
        return "OK"

    opened, hwnd, open_status = self._open_sash_before_transfer(pid, hwnd)
    if open_status == "STOP_REQUESTED":
        return "STOP_REQUESTED"
    if open_status == "CAPTURE_FAILED":
        return "INVENTORY_SASH_CAPTURE_FAILED"
    if not opened:
        return "OK"

    max_items = self._max_items()
    threshold = self._threshold()
    print(
        "Inventory sash pass started - "
        f"account={account_index + 1} - pid={pid} - name={page_name!r} - "
        f"templates={len(prepared_templates)} - max_items={max_items} - threshold={threshold:.2f} - next_enabled={self._sash_next_enabled()}"
    )

    transferred = 0
    last_key = None
    same_key_repeats = 0
    last_scanned_slots = 0
    next_used = False
    sash_page = 1
    scan_status = "OK"
    stuck_limit = self._sash_stuck_repeat_limit()

    while transferred < max_items:
        if self._stop_requested():
            print("Inventory sash stopped by user - " f"account={account_index + 1} - transferred={transferred}")
            return "STOP_REQUESTED"

        if transferred > 0 or next_used:
            image, hwnd, grid, item_result, action, scan_status = self._scan_next_sash(
                pid=pid,
                hwnd=hwnd,
                grid=grid,
                prepared_templates=prepared_templates,
            )

        if scan_status == "STOP_REQUESTED":
            return "STOP_REQUESTED"
        if scan_status == "CAPTURE_FAILED" or image is None or not hwnd:
            return "INVENTORY_SASH_CAPTURE_FAILED"

        last_scanned_slots = getattr(item_result, "scanned_slots", 0) if item_result is not None else 0
        if action is None:
            print(
                "Inventory sash complete - no matched sash items remain - "
                f"account={account_index + 1} - transferred={transferred} - scanned_slots={last_scanned_slots} - sash_page={sash_page}"
            )
            break

        key = (action.slot_index, action.item_name)
        if key == last_key:
            same_key_repeats += 1
        else:
            last_key = key
            same_key_repeats = 0

        if same_key_repeats >= stuck_limit:
            print(
                "Inventory sash no-change detected - "
                f"account={account_index + 1} - sash_page={sash_page} - "
                f"slot={action.slot_index + 1} - item={action.item_name!r} - repeats={same_key_repeats}"
            )

            if not next_used:
                clicked_next, hwnd = self._click_sash_next_page(pid, hwnd, account_index)
                if self._stop_requested():
                    return "STOP_REQUESTED"

                if clicked_next:
                    next_used = True
                    sash_page = 2
                    last_key = None
                    same_key_repeats = 0
                    print(
                        "Inventory sash switched to next page - "
                        f"account={account_index + 1}; retrying transfer on page 2"
                    )
                    continue

                print(
                    "Inventory sash stopped safely - first page seems full and Next not available - "
                    f"account={account_index + 1}"
                )
                if self._sash_disable_after_next_no_change():
                    self._sash_mark_no_space(account_index, session, "NEXT_NOT_AVAILABLE")
                break

            print(
                "Inventory sash stopped safely - no change after Next; no more useful Sash space - "
                f"account={account_index + 1} - slot={action.slot_index + 1} - item={action.item_name!r}"
            )
            if self._sash_disable_after_next_no_change():
                self._sash_mark_no_space(account_index, session, "NO_CHANGE_AFTER_NEXT")
            break

        print(
            "Inventory sash rescan - "
            f"account={account_index + 1} - sash_page={sash_page} - scanned_slots={last_scanned_slots} - "
            f"next_slot={action.slot_index + 1} - next_item={action.item_name!r} - score={action.score:.3f}"
        )

        try:
            self._save_image(
                self._draw_sash_debug(image, grid, item_result, action),
                f"before_sash_p{sash_page}_{transferred + 1:02d}",
                account_index,
                pid,
            )
        except Exception as error:
            print(f"Inventory sash before-transfer debug save failed: {error}")

        execute_result = self._execute_sash(action, hwnd)
        if execute_result == "STOP_REQUESTED":
            print("Inventory sash stopped by user during transfer - " f"account={account_index + 1}")
            return "STOP_REQUESTED"

        transferred += 1

    try:
        if self._save_debug_enabled():
            after_image, _ = self._capture_current_window(pid, hwnd)
            if after_image is not None:
                self._save_image(after_image, "after_sash", account_index, pid)
    except Exception as error:
        print(f"Inventory sash after image save failed: {error}")

    print(
        "Inventory sash worker OK - "
        f"account={account_index + 1} - pid={pid} - name={page_name!r} - "
        f"transferred={transferred} - last_scanned_slots={last_scanned_slots} - "
        f"threshold={threshold:.2f} - next_used={next_used}"
    )
    return "OK"


def apply_sash_next_page_patch():
    _install_sash_next_defaults()
    _install_sash_next_settings_group()

    InventorySashWorkerModule._sash_next_enabled = _sash_next_enabled
    InventorySashWorkerModule._sash_next_paths_text = _sash_next_paths_text
    InventorySashWorkerModule._sash_next_paths = _sash_next_paths
    InventorySashWorkerModule._sash_next_threshold = _sash_next_threshold
    InventorySashWorkerModule._sash_next_wait = _sash_next_wait
    InventorySashWorkerModule._sash_stuck_repeat_limit = _sash_stuck_repeat_limit
    InventorySashWorkerModule._sash_disable_after_next_no_change = _sash_disable_after_next_no_change
    InventorySashWorkerModule._account_sash_runtime_key = _account_sash_runtime_key
    InventorySashWorkerModule._sash_no_space_set = _sash_no_space_set
    InventorySashWorkerModule._sash_mark_no_space = _sash_mark_no_space
    InventorySashWorkerModule._sash_is_no_space = _sash_is_no_space
    InventorySashWorkerModule._find_sash_next_button = _find_sash_next_button
    InventorySashWorkerModule._click_sash_next_page = _click_sash_next_page
    InventorySashWorkerModule.run = _run_sash_with_next_page

    SelectionAwareLauncher.__init__ = _selection_init_with_sash_next_defaults

    print("Sash Next page patch active: page 1 full -> click Next -> page 2; no-change disables Sash for current account run")


apply_sash_next_page_patch()
