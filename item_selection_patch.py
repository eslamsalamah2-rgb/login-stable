"""Global item selectors for Drop / Use / Sash item templates.

The user wants one clean, saved selection for all accounts:
- Drop Items: only selected images inside assets/drop_items are dropped.
- Use Items: only selected images inside assets/use_items are right-clicked.
- Sash Items: only selected images inside assets/sash_items are transferred.

Selections are saved in item_selections.json and are global, not per-account.
This patch does not touch Login typing/recovery. It only filters the image
lists loaded by post-login workers and adds three selector buttons to the GUI.
"""

import importlib
import json
import os
from functools import lru_cache

import customtkinter as ctk

from selection_launcher import SelectionAwareLauncher
from tasks.post_login_modules import inventory_item_probe


SELECTION_FILE = "item_selections.json"
IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".bmp", ".webp")

STAGES = {
    "drop": {
        "button": "Drop Items",
        "title": "Drop Items - العناصر اللي هتترمي",
        "folder": os.path.join("assets", "drop_items"),
        "note": "اختار الصور اللي عايز البرنامج يرميها من كل الحسابات. غير المختار لن يتم رميه حتى لو صورته موجودة في الفولدر.",
    },
    "use": {
        "button": "Use Items",
        "title": "Use Items - العناصر اللي يتعملها Use",
        "folder": os.path.join("assets", "use_items"),
        "note": "اختار الصور اللي عايز البرنامج يعمل عليها كليك يمين بعد الدروب. غير المختار لن يتم استخدامه.",
    },
    "sash": {
        "button": "Sash Items",
        "title": "Sash Items - العناصر اللي تدخل Sash/Stash",
        "folder": os.path.join("assets", "sash_items"),
        "note": "اختار الصور اللي عايز البرنامج ينقلها للـ Sash/Stash لكل الحسابات. غير المختار لن يتم نقله.",
    },
}

_ORIGINAL_SELECTION_INIT = SelectionAwareLauncher.__init__
_ORIGINAL_LOAD_ITEM_TEMPLATES = inventory_item_probe.load_item_templates


def _empty_selection_data():
    return {stage: [] for stage in STAGES}


def _normal_filename(value):
    return os.path.basename(str(value or "").strip())


def _normalize_selection_data(data):
    clean = _empty_selection_data()
    if not isinstance(data, dict):
        return clean

    for stage in STAGES:
        values = data.get(stage, [])
        if not isinstance(values, list):
            values = []

        seen = set()
        result = []
        for value in values:
            name = _normal_filename(value)
            if not name or name in seen:
                continue
            seen.add(name)
            result.append(name)
        clean[stage] = result

    return clean


def load_item_selections():
    if not os.path.exists(SELECTION_FILE):
        return _empty_selection_data()

    try:
        with open(SELECTION_FILE, "r", encoding="utf-8") as file:
            return _normalize_selection_data(json.load(file))
    except Exception as error:
        print(f"Item selection load failed: {error}")
        return _empty_selection_data()


def save_item_selections(data):
    clean = _normalize_selection_data(data)
    try:
        with open(SELECTION_FILE, "w", encoding="utf-8") as file:
            json.dump(clean, file, ensure_ascii=False, indent=4)
        return True
    except Exception as error:
        print(f"Item selection save failed: {error}")
        return False


def _list_stage_images(stage):
    folder = STAGES[stage]["folder"]
    try:
        os.makedirs(folder, exist_ok=True)
    except Exception:
        pass

    if not os.path.isdir(folder):
        return []

    files = []
    for name in os.listdir(folder):
        path = os.path.join(folder, name)
        if not os.path.isfile(path):
            continue
        if os.path.splitext(name)[1].lower() not in IMAGE_EXTENSIONS:
            continue
        files.append(name)

    files.sort(key=lambda name: (0, int(os.path.splitext(name)[0])) if os.path.splitext(name)[0].isdigit() else (1, name.lower()))
    return files


def _stage_from_folder(folder):
    try:
        folder_norm = os.path.normcase(os.path.normpath(str(folder or "")))
    except Exception:
        folder_norm = str(folder or "").lower()

    for stage, meta in STAGES.items():
        target = os.path.normcase(os.path.normpath(meta["folder"]))
        if folder_norm == target or folder_norm.endswith(os.sep + os.path.basename(target)):
            return stage

    lowered = folder_norm.replace("\\", "/")
    if "drop_items" in lowered:
        return "drop"
    if "use_items" in lowered:
        return "use"
    if "sash_items" in lowered or "stash_items" in lowered:
        return "sash"
    return None


def _filter_templates_for_stage(stage, templates):
    selections = load_item_selections()
    selected_names = set(selections.get(stage, []))
    selected_stems = {os.path.splitext(name)[0] for name in selected_names}

    if not selected_names and not selected_stems:
        print(
            "Item selection: no selected active templates - "
            f"stage={stage} - loaded={len(templates)} - nothing will run for this stage"
        )
        return []

    active = []
    for template in templates:
        basename = os.path.basename(getattr(template, "path", ""))
        stem = getattr(template, "name", os.path.splitext(basename)[0])
        if basename in selected_names or stem in selected_stems:
            active.append(template)

    skipped = len(templates) - len(active)
    print(
        "Item selection filter - "
        f"stage={stage} - selected={len(selected_names)} - loaded={len(templates)} - active={len(active)} - skipped={skipped}"
    )
    return active


def filtered_load_item_templates(folder):
    templates = _ORIGINAL_LOAD_ITEM_TEMPLATES(folder)
    stage = _stage_from_folder(folder)
    if stage is None:
        return templates
    return _filter_templates_for_stage(stage, templates)


def _install_template_filter():
    inventory_item_probe.load_item_templates = filtered_load_item_templates

    module_names = (
        "tasks.post_login_modules.inventory_drop_worker",
        "tasks.post_login_modules.inventory_use_worker",
        "tasks.post_login_modules.inventory_sash_worker",
        "use_items_patch",
        "sash_items_patch",
        "sash_next_page_patch",
    )

    for module_name in module_names:
        try:
            module = importlib.import_module(module_name)
            if hasattr(module, "load_item_templates"):
                setattr(module, "load_item_templates", filtered_load_item_templates)
        except Exception:
            # Some optional patches may not be loaded in older copies.
            pass


def _hide_widget(widget):
    if widget is None:
        return
    try:
        widget.pack_forget()
        return
    except Exception:
        pass
    try:
        widget.grid_forget()
        return
    except Exception:
        pass


def _cleanup_main_ui(self):
    """Hide test/debug controls that are no longer needed in daily use."""
    for attr in (
        "inventory_probe_test_button",  # old Drop Scan test button
        "backup_button",                # backups still run automatically
        "scan_open_pages_button",       # auto scan still runs from the background logic
    ):
        _hide_widget(getattr(self, attr, None))

    # The side textbox was useful while debugging Scan Open, but it consumes
    # screen space.  The scanner itself remains available internally.
    _hide_widget(getattr(self, "open_pages_panel", None))


def _active_count(stage):
    selections = load_item_selections()
    available = set(_list_stage_images(stage))
    return len([name for name in selections.get(stage, []) if name in available])


def _refresh_item_button_labels(self):
    for stage, attr in (
        ("drop", "drop_item_selector_button"),
        ("use", "use_item_selector_button"),
        ("sash", "sash_item_selector_button"),
    ):
        button = getattr(self, attr, None)
        if button is None:
            continue
        try:
            button.configure(text=f"{STAGES[stage]['button']} ({_active_count(stage)})")
        except Exception:
            pass


def _set_all_vars(vars_by_name, value):
    for var in vars_by_name.values():
        try:
            var.set(bool(value))
        except Exception:
            pass


def _open_item_selector(self, stage):
    if stage not in STAGES:
        return

    meta = STAGES[stage]
    files = _list_stage_images(stage)
    selections = load_item_selections()
    selected = set(selections.get(stage, []))

    window = ctk.CTkToplevel(self.app)
    window.title(meta["button"])
    window.geometry("620x650")
    window.transient(self.app)
    window.grab_set()

    ctk.CTkLabel(
        window,
        text=meta["title"],
        font=("Segoe UI", 21, "bold"),
    ).pack(pady=(14, 4))

    ctk.CTkLabel(
        window,
        text=meta["note"],
        font=("Segoe UI", 12),
        text_color="#d7d7d7",
        wraplength=560,
        justify="right",
    ).pack(padx=16, pady=(0, 8))

    ctk.CTkLabel(
        window,
        text=f"Folder: {meta['folder']}",
        font=("Consolas", 11),
        text_color="#bdbdbd",
    ).pack(padx=16, pady=(0, 8))

    summary_var = ctk.StringVar(value="")

    def update_summary():
        count = sum(1 for var in vars_by_name.values() if bool(var.get()))
        summary_var.set(f"Selected: {count} / {len(files)}")

    summary_label = ctk.CTkLabel(window, textvariable=summary_var, font=("Segoe UI", 13, "bold"))
    summary_label.pack(pady=(0, 8))

    body = ctk.CTkScrollableFrame(window, height=435)
    body.pack(fill="both", expand=True, padx=16, pady=(0, 12))

    vars_by_name = {}

    if not files:
        ctk.CTkLabel(
            body,
            text="مفيش صور في الفولدر ده. حط صور الـ Items الأول وافتح النافذة تاني.",
            font=("Segoe UI", 14),
            text_color="#ffc107",
            wraplength=520,
        ).pack(padx=12, pady=22)
    else:
        for name in files:
            row = ctk.CTkFrame(body)
            row.pack(fill="x", padx=6, pady=4)
            var = ctk.BooleanVar(value=name in selected)
            vars_by_name[name] = var
            box = ctk.CTkCheckBox(
                row,
                text=name,
                variable=var,
                onvalue=True,
                offvalue=False,
                font=("Segoe UI", 13),
                command=update_summary,
            )
            box.pack(side="left", padx=10, pady=8)

    def save_stage_selection():
        new_selection = [name for name in files if vars_by_name.get(name) is not None and bool(vars_by_name[name].get())]
        data = load_item_selections()
        data[stage] = new_selection
        if save_item_selections(data):
            print(f"Item selection saved - stage={stage} - selected={new_selection}")
            self.set_status(f"تم حفظ {meta['button']} - المختار {len(new_selection)} من {len(files)}")
            _refresh_item_button_labels(self)
            window.destroy()
        else:
            self.set_status("فشل حفظ اختيار الـ Items")

    buttons = ctk.CTkFrame(window, fg_color="transparent")
    buttons.pack(fill="x", padx=16, pady=(0, 14))

    ctk.CTkButton(
        buttons,
        text="اختيار الكل",
        width=110,
        height=36,
        command=lambda: (_set_all_vars(vars_by_name, True), update_summary()),
    ).pack(side="left", padx=5)

    ctk.CTkButton(
        buttons,
        text="مسح الكل",
        width=110,
        height=36,
        command=lambda: (_set_all_vars(vars_by_name, False), update_summary()),
    ).pack(side="left", padx=5)

    ctk.CTkButton(buttons, text="حفظ", width=100, height=36, command=save_stage_selection).pack(side="right", padx=5)
    ctk.CTkButton(buttons, text="إلغاء", width=100, height=36, command=window.destroy).pack(side="right", padx=5)

    update_summary()


def _add_item_selector_buttons(self):
    try:
        controls = self.resume_button.master

        self.drop_item_selector_button = ctk.CTkButton(
            controls,
            text="Drop Items",
            width=125,
            height=40,
            command=lambda: self.open_item_selector("drop"),
        )
        self.drop_item_selector_button.pack(side="left", padx=6, pady=10)

        self.use_item_selector_button = ctk.CTkButton(
            controls,
            text="Use Items",
            width=125,
            height=40,
            command=lambda: self.open_item_selector("use"),
        )
        self.use_item_selector_button.pack(side="left", padx=6, pady=10)

        self.sash_item_selector_button = ctk.CTkButton(
            controls,
            text="Sash Items",
            width=125,
            height=40,
            command=lambda: self.open_item_selector("sash"),
        )
        self.sash_item_selector_button.pack(side="left", padx=6, pady=10)

        _refresh_item_button_labels(self)
    except Exception as error:
        print(f"Could not add item selector buttons: {error}")


def _selection_init_with_item_selection(self):
    _ORIGINAL_SELECTION_INIT(self)
    _cleanup_main_ui(self)
    _add_item_selector_buttons(self)


_install_template_filter()
SelectionAwareLauncher.open_item_selector = _open_item_selector
SelectionAwareLauncher.__init__ = _selection_init_with_item_selection

print("Item selection patch active: global Drop/Use/Sash item selectors saved in item_selections.json")
