"""Hide duplicate bottom Start/Stop controls.

The top header Start/Stop buttons are the only visible Start/Stop controls.
This patch only hides the duplicate lower toolbar controls; it does not change
Login, recovery, Drop, Use, Sash, Scan Open, or any execution order.
"""

from selection_launcher import SelectionAwareLauncher


_ORIGINAL_SELECTION_INIT = SelectionAwareLauncher.__init__


def _hide_widget(widget):
    if widget is None:
        return
    for method_name in ("pack_forget", "grid_forget", "place_forget"):
        try:
            getattr(widget, method_name)()
            return
        except Exception:
            pass


def _hide_bottom_start_stop_controls(self):
    # The user wants Start/Stop only beside the title at the top-left.
    # Hide only the duplicated lower toolbar buttons.
    for attr in (
        "start_fresh_button",  # lower Start
        "pause_button",        # lower Stop
        "resume_button",       # lower Resume/Start duplicate
    ):
        _hide_widget(getattr(self, attr, None))


def _selection_init_hide_bottom_controls(self):
    _ORIGINAL_SELECTION_INIT(self)
    _hide_bottom_start_stop_controls(self)


SelectionAwareLauncher.__init__ = _selection_init_hide_bottom_controls
SelectionAwareLauncher.hide_bottom_start_stop_controls = _hide_bottom_start_stop_controls

print("Hide bottom Start/Stop patch active: top Start/Stop only, core workflow unchanged")
