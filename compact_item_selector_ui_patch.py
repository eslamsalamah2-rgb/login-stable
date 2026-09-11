"""Compact GUI cleanup + visual item selectors.

This patch is UI-only for the post-login item-selection workflow.
It keeps Login isolated and does not change any Login typing/recovery logic.

Changes:
- hide old manual post-login command buttons from the main toolbar
- keep only the three global item selector buttons: Drop / Use / Sash
- remove Select All / Clear All buttons from item selector windows
- show a small thumbnail next to every item filename
- save every checkbox change immediately to item_selections.json
- default all current images to selected on first use
"""

import json
import os

import customtkinter as ctk
from PIL import Image

from selection_launcher import SelectionAwareLauncher

try:
    import item_selection_patch
except Exception:
    item_selection_patch = None


_ORIGINAL_SELECTION_INIT = SelectionAwareLauncher.__init__
_ORIGINAL_CREATE_ACCOUNT_ROW = SelectionAwareLauncher.create_account_row

THUMBNAIL_SIZE = 34
COMPACT_APP_GEOMETRY = "1020x690"
COMPACT_APP_MINSIZE = (930, 620)


def _hide_widget(widget):
    if widget is None:
        return
    for method_name in ("pack_forget", "grid_forget", "place_forget"):
        try:
            getattr(widget, method_name)()
            return
        except Exception:
            pass


def _configure_widget(widget, **kwargs):
    if widget is None:
        return
    try:
        widget.configure(**kwargs)
    except Exception:
        pass


def _compact_account_rows(self):
    for row in getattr(self, "account_rows", []) or []:
        _configure_widget(row.get("number"), width=28)
        _configure_widget(row.get("username"), width=150, height=30)
        _configure_widget(row.get("password"), width=145, height=30)
        _configure_widget(row.get("name"), width=165, height=30)
        _configure_widget(row.get("lamp"), width=38, font=("Segoe UI", 22, "bold"))
        _configure_widget(row.get("delete"), width=32, height=28)
        _configure_widget(row.get("revive_mode_menu"), width=82, height=28)
        _configure_widget(row.get("sash_enabled_box"), width=54)


def _compact_toolbar(self):
    # These two are no longer needed in daily operation: commands start
    # automatically after READY accounts, and Stop/9 stops them.
    _hide_widget(getattr(self, "start_commands_button", None))
    _hide_widget(getattr(self, "stop_commands_button", None))

    # Old debug / maintenance buttons already have internal logic or hotkeys.
    for attr in (
        "inventory_probe_test_button",
        "backup_button",
        "scan_open_pages_button",
    ):
        _hide_widget(getattr(self, attr, None))

    _hide_widget(getattr(self, "open_pages_panel", None))

    sizes = {
        "start_fresh_button": (112, 34),
        "pause_button": (110, 34),
        "resume_button": (110, 34),
        "add_account_button": (105, 34),
        "save_accounts_button": (105, 34),
        "settings_button": (82, 34),
        "drop_item_selector_button": (105, 34),
        "use_item_selector_button": (105, 34),
        "sash_item_selector_button": (105, 34),
    }

    for attr, (width, height) in sizes.items():
        _configure_widget(getattr(self, attr, None), width=width, height=height)

    try:
        self.app.geometry(COMPACT_APP_GEOMETRY)
        self.app.minsize(*COMPACT_APP_MINSIZE)
    except Exception:
        pass

    _compact_account_rows(self)


def _create_account_row_compact(self, account=None):
    result = _ORIGINAL_CREATE_ACCOUNT_ROW(self, account)
    _compact_account_rows(self)
    return result


def _stage_images(stage):
    if item_selection_patch is None:
        return []
    try:
        return item_selection_patch._list_stage_images(stage)
    except Exception:
        return []


def _selection_file_path():
    if item_selection_patch is None:
        return "item_selections.json"
    return getattr(item_selection_patch, "SELECTION_FILE", "item_selections.json")


def _empty_data():
    stages = getattr(item_selection_patch, "STAGES", {}) if item_selection_patch else {}
    data = {stage: [] for stage in stages}
    data["_seen"] = {stage: [] for stage in stages}
    return data


def _read_raw_selection_file():
    path = _selection_file_path()
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as file:
            data = json.load(file)
        if isinstance(data, dict):
            return data
    except Exception as error:
        print(f"Item selection load failed: {error}")
    return None


def _normalize_selection_with_default_all(data):
    if item_selection_patch is None:
        return _empty_data()

    stages = item_selection_patch.STAGES
    raw = data if isinstance(data, dict) else {}
    seen_raw = raw.get("_seen", {}) if isinstance(raw.get("_seen", {}), dict) else {}

    clean = {"_seen": {}}

    for stage in stages:
        available = _stage_images(stage)
        available_set = set(available)
        seen = [name for name in seen_raw.get(stage, []) if name in available_set]
        seen_set = set(seen)

        saved_value = raw.get(stage, None)
        if saved_value is None:
            # First time for this stage: everything currently in the folder is active.
            selected = list(available)
        elif not isinstance(saved_value, list):
            selected = list(available)
        else:
            selected = []
            selected_seen = set()
            for value in saved_value:
                try:
                    name = os.path.basename(str(value or "").strip())
                except Exception:
                    name = ""
                if not name or name not in available_set or name in selected_seen:
                    continue
                selected_seen.add(name)
                selected.append(name)

            # Compatibility with the previous selector: if the old file exists
            # but a stage is empty before any _seen data exists, treat this as
            # first use and select all current images.
            if not seen and not selected and available:
                selected = list(available)

            # New images added after the last save start selected by default.
            if seen:
                for name in available:
                    if name not in seen_set and name not in selected:
                        selected.append(name)

        clean[stage] = selected
        clean["_seen"][stage] = list(available)

    return clean


def load_item_selections_default_all():
    return _normalize_selection_with_default_all(_read_raw_selection_file())


def save_item_selections_with_seen(data):
    if item_selection_patch is None:
        return False
    clean = _normalize_selection_with_default_all(data)
    # Preserve current visible files as _seen so unchecked files stay unchecked
    # and only truly new image files become selected automatically later.
    for stage in item_selection_patch.STAGES:
        clean.setdefault("_seen", {})[stage] = _stage_images(stage)

    try:
        with open(_selection_file_path(), "w", encoding="utf-8") as file:
            json.dump(clean, file, ensure_ascii=False, indent=4)
        return True
    except Exception as error:
        print(f"Item selection save failed: {error}")
        return False


def _active_count(stage):
    data = load_item_selections_default_all()
    available = set(_stage_images(stage))
    return len([name for name in data.get(stage, []) if name in available])


def _refresh_item_button_labels(self):
    if item_selection_patch is None:
        return
    mapping = (
        ("drop", "drop_item_selector_button"),
        ("use", "use_item_selector_button"),
        ("sash", "sash_item_selector_button"),
    )
    for stage, attr in mapping:
        button = getattr(self, attr, None)
        if button is None:
            continue
        try:
            button.configure(text=f"{item_selection_patch.STAGES[stage]['button']} ({_active_count(stage)})")
        except Exception:
            pass


def _load_thumb(path):
    try:
        image = Image.open(path).convert("RGBA")
        return ctk.CTkImage(light_image=image, dark_image=image, size=(THUMBNAIL_SIZE, THUMBNAIL_SIZE))
    except Exception:
        return None


def _open_compact_item_selector(self, stage):
    if item_selection_patch is None or stage not in item_selection_patch.STAGES:
        return

    meta = item_selection_patch.STAGES[stage]
    files = _stage_images(stage)
    data = load_item_selections_default_all()
    selected = set(data.get(stage, []))

    window = ctk.CTkToplevel(self.app)
    window.title(meta["button"])
    window.geometry("460x560")
    window.minsize(420, 500)
    window.transient(self.app)
    window.grab_set()

    ctk.CTkLabel(
        window,
        text=meta["title"],
        font=("Segoe UI", 17, "bold"),
    ).pack(pady=(10, 2))

    ctk.CTkLabel(
        window,
        text="التحديد بيتحفظ تلقائيًا لكل الحسابات.",
        font=("Segoe UI", 12),
        text_color="#d7d7d7",
    ).pack(padx=10, pady=(0, 4))

    summary_var = ctk.StringVar(value="")
    ctk.CTkLabel(window, textvariable=summary_var, font=("Segoe UI", 12, "bold")).pack(pady=(0, 6))

    body = ctk.CTkScrollableFrame(window, height=420)
    body.pack(fill="both", expand=True, padx=10, pady=(0, 8))

    vars_by_name = {}
    thumb_refs = []

    def update_summary():
        count = sum(1 for var in vars_by_name.values() if bool(var.get()))
        summary_var.set(f"مختار: {count} / {len(files)}")

    def save_now():
        current = load_item_selections_default_all()
        current[stage] = [name for name in files if name in vars_by_name and bool(vars_by_name[name].get())]
        current.setdefault("_seen", {})[stage] = list(files)
        if save_item_selections_with_seen(current):
            _refresh_item_button_labels(self)
            update_summary()
            self.set_status(f"تم حفظ {meta['button']} تلقائيًا - المختار {len(current[stage])} من {len(files)}")
        else:
            self.set_status("فشل حفظ اختيار الـ Items")

    if not files:
        ctk.CTkLabel(
            body,
            text="مفيش صور في الفولدر ده. حط صور الـ Items وافتح النافذة تاني.",
            font=("Segoe UI", 13),
            text_color="#ffc107",
            wraplength=380,
        ).pack(padx=10, pady=20)
    else:
        for name in files:
            row = ctk.CTkFrame(body)
            row.pack(fill="x", padx=4, pady=3)

            image_path = os.path.join(meta["folder"], name)
            thumb = _load_thumb(image_path)
            if thumb is not None:
                thumb_refs.append(thumb)
                image_label = ctk.CTkLabel(row, image=thumb, text="", width=42)
            else:
                image_label = ctk.CTkLabel(row, text="NoImg", width=42)
            image_label.pack(side="left", padx=(6, 5), pady=5)

            var = ctk.BooleanVar(value=name in selected)
            vars_by_name[name] = var
            box = ctk.CTkCheckBox(
                row,
                text=name,
                variable=var,
                onvalue=True,
                offvalue=False,
                font=("Segoe UI", 12),
                command=save_now,
            )
            box.pack(side="left", fill="x", expand=True, padx=(2, 6), pady=5)

    # Keep image references alive while the selector is open.
    window._item_selector_thumb_refs = thumb_refs

    buttons = ctk.CTkFrame(window, fg_color="transparent")
    buttons.pack(fill="x", padx=10, pady=(0, 10))
    ctk.CTkButton(buttons, text="إغلاق", width=95, height=32, command=window.destroy).pack(side="right", padx=4)

    # Make sure the default-all selection is persisted on first open.
    save_item_selections_with_seen(data)
    _refresh_item_button_labels(self)
    update_summary()


def _selection_init_compact(self):
    _ORIGINAL_SELECTION_INIT(self)
    _compact_toolbar(self)
    _refresh_item_button_labels(self)


def apply_compact_item_selector_ui_patch():
    if item_selection_patch is not None:
        item_selection_patch.load_item_selections = load_item_selections_default_all
        item_selection_patch.save_item_selections = save_item_selections_with_seen
        item_selection_patch._refresh_item_button_labels = _refresh_item_button_labels
        item_selection_patch._active_count = _active_count

    SelectionAwareLauncher.create_account_row = _create_account_row_compact
    SelectionAwareLauncher.open_item_selector = _open_compact_item_selector
    SelectionAwareLauncher.__init__ = _selection_init_compact

    print("Compact item selector UI patch active: thumbnails + auto-save + cleaner toolbar")


apply_compact_item_selector_ui_patch()
