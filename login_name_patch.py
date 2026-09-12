"""Restore the product name to Login everywhere in the main window."""

from selection_launcher import SelectionAwareLauncher

_ORIGINAL_INIT = SelectionAwareLauncher.__init__


def _set_login_name(self):
    try:
        self.app.title("Login")
    except Exception:
        pass

    # The original GUI has a visible heading with the old descriptive name.
    # Change only that heading; do not touch account rows or workflow controls.
    try:
        for widget in self.app.winfo_children():
            try:
                text = str(widget.cget("text") or "")
            except Exception:
                continue
            if text in {"CONQUER LOGIN MANAGER", "ZERO LOGIN BOT", "Zero Wood", "Zero Good"}:
                try:
                    widget.configure(text="Login")
                except Exception:
                    pass
    except Exception:
        pass


def _init_login_named(self, *args, **kwargs):
    result = _ORIGINAL_INIT(self, *args, **kwargs)
    _set_login_name(self)
    return result


SelectionAwareLauncher.__init__ = _init_login_named
print("Login name patch active: window and visible heading use Login")
