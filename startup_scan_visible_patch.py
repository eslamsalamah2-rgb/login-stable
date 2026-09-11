"""Show startup Scan Open results without starting post-login commands.

User workflow:
- Program opens.
- It automatically scans already-open Conquer pages and updates lamps/panel.
- It does NOT start Drop/Use/Sash/Final actions until the user presses Start/hotkey.

This patch is UI/startup-scan only. It does not touch Login typing or post-login
worker execution order.
"""

import customtkinter as ctk

from selection_launcher import SelectionAwareLauncher


_ORIGINAL_SELECTION_INIT = SelectionAwareLauncher.__init__
_ORIGINAL_SCAN_OPEN = getattr(SelectionAwareLauncher, "scan_existing_open_pages", None)


def _show_startup_scan_panel(self):
    """Re-show the Scan Open panel that earlier compact UI patches hid."""
    panel = getattr(self, "open_pages_panel", None)
    if panel is None:
        return

    try:
        # Keep it visible but compact so the accounts table still fits.
        text_box = getattr(self, "open_pages_text", None)
        if text_box is not None:
            try:
                text_box.configure(height=52)
            except Exception:
                pass
    except Exception:
        pass

    try:
        panel.pack_forget()
    except Exception:
        pass

    try:
        before_widget = getattr(self, "accounts_frame", None)
        if before_widget is not None:
            panel.pack(fill="x", padx=18, pady=(0, 6), before=before_widget)
        else:
            panel.pack(fill="x", padx=18, pady=(0, 6))
    except Exception:
        try:
            panel.pack(fill="x", padx=18, pady=(0, 6))
        except Exception as error:
            print(f"Could not show startup scan panel: {error}")

    try:
        summary = getattr(self, "open_pages_summary_label", None)
        if summary is not None:
            summary.configure(text="Startup Scan جاهز")
    except Exception:
        pass

    try:
        text_box = getattr(self, "open_pages_text", None)
        if text_box is not None:
            text_box.configure(state="normal")
            text_box.delete("1.0", "end")
            text_box.insert(
                "1.0",
                "Startup Scan: هيتم فحص الصفحات المفتوحة وتحديث اللمبات فقط. الأوامر لن تبدأ إلا بعد Start.",
            )
            text_box.configure(state="disabled")
    except Exception:
        pass


def _scan_open_without_starting_commands(self):
    """Run Scan Open even when manual_start_required=True.

    ui_controls_settings_patch blocks automatic scans when manual_start_required is
    enabled. For this workflow we want scan only, not command execution, so we
    temporarily allow the scan and call the existing implementation.
    """
    if _ORIGINAL_SCAN_OPEN is None:
        print("Startup Scan Open skipped - scan function missing")
        return None

    old_flag = getattr(self, "_allow_manual_scan_open", False)
    try:
        self._allow_manual_scan_open = True
        return _ORIGINAL_SCAN_OPEN(self)
    finally:
        try:
            self._allow_manual_scan_open = old_flag
        except Exception:
            pass


def _startup_scan_now(self):
    try:
        if getattr(self, "is_running", False):
            return
        print("Startup Scan Open running - lamps/panel only, no commands")
        _show_startup_scan_panel(self)
        return self.scan_existing_open_pages()
    except Exception as error:
        print(f"Startup Scan Open failed: {error}")
        try:
            self.set_status("Startup Scan فشل - اضغط Start للتشغيل اليدوي")
        except Exception:
            pass
        return None


def _selection_init_with_visible_startup_scan(self):
    _ORIGINAL_SELECTION_INIT(self)

    # Scan is allowed on startup, but post-login commands are still manual.
    try:
        self.runtime_settings["manual_start_required"] = True
        self.runtime_settings["auto_start_post_login_on_startup"] = False
        self.runtime_settings["auto_scan_open_pages"] = True
        self.save_settings()
    except Exception:
        pass

    _show_startup_scan_panel(self)

    try:
        self.app.after(900, lambda: self.startup_scan_open_pages())
    except Exception as error:
        print(f"Could not schedule visible startup scan: {error}")


SelectionAwareLauncher.scan_existing_open_pages = _scan_open_without_starting_commands
SelectionAwareLauncher.startup_scan_open_pages = _startup_scan_now
SelectionAwareLauncher.__init__ = _selection_init_with_visible_startup_scan

print("Startup scan visible patch active: auto Scan Open visible, commands wait for Start")
