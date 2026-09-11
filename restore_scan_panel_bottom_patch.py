"""Restore the startup/open-pages scan panel at the bottom.

Purpose:
- Keep top Start/Stop buttons visible beside the title.
- Keep lower duplicate Start/Stop buttons hidden.
- Show the Scan/Open Pages information panel at the bottom of the main window.
- Run startup scan only to update lamps/open-page text; never start Drop/Use/Sash automatically.

UI-only patch. Core Login and post-login execution order are untouched.
"""

from selection_launcher import SelectionAwareLauncher


_ORIGINAL_SELECTION_INIT = SelectionAwareLauncher.__init__
_ORIGINAL_SCAN_OPEN = getattr(SelectionAwareLauncher, "scan_existing_open_pages", None)


def _safe_pack_forget(widget):
    if widget is None:
        return
    try:
        widget.pack_forget()
    except Exception:
        pass


def _safe_config(widget, **kwargs):
    if widget is None:
        return
    try:
        widget.configure(**kwargs)
    except Exception:
        pass


def _restore_scan_panel_bottom(self):
    """Make the existing Scan/Open Pages panel visible under the accounts list."""
    panel = getattr(self, "open_pages_panel", None)
    if panel is None:
        return False

    text_box = getattr(self, "open_pages_text", None)
    summary = getattr(self, "open_pages_summary_label", None)

    _safe_config(text_box, height=72)
    _safe_config(summary, text="Scan الصفحات المفتوحة")

    # Move it to the bottom of the main layout. This is the panel that shows
    # already-open side characters / linked accounts from startup scan.
    _safe_pack_forget(panel)
    try:
        panel.pack(fill="x", padx=14, pady=(6, 8))
    except Exception as error:
        print(f"Could not restore bottom scan panel: {error}")
        return False

    try:
        if text_box is not None:
            text_box.configure(state="normal")
            current = text_box.get("1.0", "end").strip()
            if not current:
                text_box.insert(
                    "1.0",
                    "Startup Scan: هيعرض الحسابات/الصفحات المفتوحة هنا فقط. اضغط Start لبدء التنفيذ.",
                )
            text_box.configure(state="disabled")
    except Exception:
        pass

    return True


def _startup_scan_display_only(self):
    """Allow startup scan display, but do not start any command worker."""
    if _ORIGINAL_SCAN_OPEN is None:
        print("Bottom startup scan skipped - scan function missing")
        return None

    old_flag = getattr(self, "_allow_manual_scan_open", False)
    try:
        self._allow_manual_scan_open = True
        print("Bottom Startup Scan running - display/lamps only, no commands")
        _restore_scan_panel_bottom(self)
        return _ORIGINAL_SCAN_OPEN(self)
    finally:
        try:
            self._allow_manual_scan_open = old_flag
        except Exception:
            pass


def _selection_init_restore_bottom_scan(self):
    _ORIGINAL_SELECTION_INIT(self)

    try:
        self.runtime_settings["manual_start_required"] = True
        self.runtime_settings["auto_start_post_login_on_startup"] = False
        self.runtime_settings["auto_scan_open_pages"] = True
        self.save_settings()
    except Exception:
        pass

    _restore_scan_panel_bottom(self)

    # Run after all other startup UI patches finish hiding/packing controls.
    try:
        self.app.after(1200, lambda: self.scan_existing_open_pages())
    except Exception as error:
        print(f"Could not schedule bottom startup scan: {error}")


SelectionAwareLauncher.scan_existing_open_pages = _startup_scan_display_only
SelectionAwareLauncher.restore_scan_panel_bottom = _restore_scan_panel_bottom
SelectionAwareLauncher.__init__ = _selection_init_restore_bottom_scan

print("Restore scan panel bottom patch active: open-pages scan visible, commands still manual")
