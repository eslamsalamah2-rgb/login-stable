"""Always-visible Start / Stop buttons beside the program title.

The compact toolbar can hide or squeeze controls when the window is small.
This patch adds a small top-left control strip beside the title area:
- Start button: calls the normal Start flow
- Stop button: calls the normal Stop / global-stop flow

It is UI-only and does not touch Login, Drop, Use, or Sash logic.
"""

import customtkinter as ctk

from selection_launcher import SelectionAwareLauncher


_ORIGINAL_SELECTION_INIT = SelectionAwareLauncher.__init__


def _safe_config(widget, **kwargs):
    try:
        widget.configure(**kwargs)
    except Exception:
        pass


def _add_top_header_buttons(self):
    try:
        # Floating fixed position at the top-left of the app, beside the title.
        # place() keeps it visible even if the normal toolbar becomes crowded.
        holder = ctk.CTkFrame(self.app, fg_color="transparent")
        holder.place(x=14, y=15)
        self.top_header_controls_frame = holder

        start_key = "8"
        stop_key = "9"
        try:
            start_key = str(self.get_runtime_setting("program_start_hotkey", "8") or "8")
            stop_key = str(self.get_runtime_setting("program_stop_hotkey", "9") or "9")
        except Exception:
            pass

        self.top_start_button = ctk.CTkButton(
            holder,
            text=f"Start {start_key}",
            width=95,
            height=31,
            command=self.start_from_beginning,
        )
        self.top_start_button.pack(side="left", padx=(0, 6))

        self.top_stop_button = ctk.CTkButton(
            holder,
            text=f"Stop {stop_key}",
            width=85,
            height=31,
            fg_color="#8b0000",
            hover_color="#a00000",
            command=self.pause_processing,
        )
        self.top_stop_button.pack(side="left", padx=(0, 0))

        # Keep the old toolbar Start/Stop usable if visible, but the top buttons
        # are now the guaranteed visible controls.
        _safe_config(getattr(self, "start_fresh_button", None), text=f"Start {start_key}")
        _safe_config(getattr(self, "pause_button", None), text=f"Stop {stop_key}")

    except Exception as error:
        print(f"Could not add top header Start/Stop buttons: {error}")


def _refresh_top_header_buttons(self):
    start_key = "8"
    stop_key = "9"
    try:
        start_key = str(self.get_runtime_setting("program_start_hotkey", "8") or "8")
        stop_key = str(self.get_runtime_setting("program_stop_hotkey", "9") or "9")
    except Exception:
        pass

    _safe_config(getattr(self, "top_start_button", None), text=f"Start {start_key}")
    _safe_config(getattr(self, "top_stop_button", None), text=f"Stop {stop_key}")
    _safe_config(getattr(self, "start_fresh_button", None), text=f"Start {start_key}")
    _safe_config(getattr(self, "pause_button", None), text=f"Stop {stop_key}")


def _selection_init_with_top_header_controls(self):
    _ORIGINAL_SELECTION_INIT(self)
    _add_top_header_buttons(self)
    _refresh_top_header_buttons(self)


def apply_top_header_controls_patch():
    SelectionAwareLauncher.__init__ = _selection_init_with_top_header_controls
    SelectionAwareLauncher.refresh_top_header_buttons = _refresh_top_header_buttons
    print("Top header controls patch active: Start/Stop visible beside title")


apply_top_header_controls_patch()
