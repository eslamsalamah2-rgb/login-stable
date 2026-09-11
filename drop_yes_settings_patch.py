"""Editable Drop-Yes search area settings.

Adds a small Settings section for the Drop confirmation Yes search:
- padding around the inventory/bag grid box
- wide yes_no click position, so the user can tune Yes vs No safely

Execution rule stays safe: Drop Yes is still searched only around the inventory
area. This patch never enables full-window Yes scanning.
"""

from gui import DEFAULT_RUNTIME_SETTINGS
from tasks.post_login_modules import drop_confirmation
from tasks.post_login_modules.inventory_drop_worker import InventoryDropWorkerModule

try:
    import drop_settings_patch
except Exception:
    drop_settings_patch = None

try:
    import settings_language_details_patch
except Exception:
    settings_language_details_patch = None


_ORIGINAL_CONFIRM_YES_IF_NEEDED = InventoryDropWorkerModule._confirm_yes_if_needed

YES_SEARCH_DEFAULTS = {
    # Pixels added around the detected inventory/grid box before searching Yes.
    # Bigger values find more popups; smaller values are safer against wrong Yes/No.
    "inventory_drop_yes_area_pad_left": 160,
    "inventory_drop_yes_area_pad_top": 220,
    "inventory_drop_yes_area_pad_right": 220,
    "inventory_drop_yes_area_pad_bottom": 220,
    # For a wide yes_no.png crop containing both buttons, 0.72 means click near
    # the right side of the matched box. Lower it if Yes is on the left.
    "inventory_drop_yes_click_x_fraction": 0.72,
    "inventory_drop_yes_wide_template_min_width": 70,
}

YES_SEARCH_GROUP_TITLE = "Setting Drop Yes / نطاق زر Yes"
YES_SEARCH_GROUP_NOTE = (
    "تحكم في نطاق البحث عن Yes بعد الدروب حوالين الشنطة فقط. "
    "زود الأرقام لو مش لاقي Yes، وقللها لو قرب يدوس غلط."
)
YES_SEARCH_GROUP_ITEMS = (
    ("inventory_drop_yes_area_pad_left", "Drop Yes - توسيع البحث شمال الشنطة بالبكسل"),
    ("inventory_drop_yes_area_pad_top", "Drop Yes - توسيع البحث فوق الشنطة بالبكسل"),
    ("inventory_drop_yes_area_pad_right", "Drop Yes - توسيع البحث يمين الشنطة بالبكسل"),
    ("inventory_drop_yes_area_pad_bottom", "Drop Yes - توسيع البحث تحت الشنطة بالبكسل"),
    ("inventory_drop_yes_click_x_fraction", "Drop Yes - مكان الضغط داخل صورة Yes/No: 0.72 يمين، 0.28 شمال"),
    ("inventory_drop_yes_wide_template_min_width", "Drop Yes - اعتبر الصورة واسعة Yes/No بداية من عرض كام بكسل"),
)

YES_SEARCH_GROUP = (
    YES_SEARCH_GROUP_TITLE,
    YES_SEARCH_GROUP_NOTE,
    YES_SEARCH_GROUP_ITEMS,
)

YES_SEARCH_EN = {
    "inventory_drop_yes_area_pad_left": "Drop Yes search padding left of inventory / pixels",
    "inventory_drop_yes_area_pad_top": "Drop Yes search padding above inventory / pixels",
    "inventory_drop_yes_area_pad_right": "Drop Yes search padding right of inventory / pixels",
    "inventory_drop_yes_area_pad_bottom": "Drop Yes search padding below inventory / pixels",
    "inventory_drop_yes_click_x_fraction": "Drop Yes click position inside wide Yes/No image - 0.72 right, 0.28 left",
    "inventory_drop_yes_wide_template_min_width": "Treat the Yes image as wide Yes/No from this pixel width",
}


def _install_defaults():
    DEFAULT_RUNTIME_SETTINGS.update(YES_SEARCH_DEFAULTS)


def _install_settings_group():
    if drop_settings_patch is None:
        return

    try:
        groups = [group for group in getattr(drop_settings_patch, "SETTINGS_GROUPS", ()) if group and group[0] != YES_SEARCH_GROUP_TITLE]
        insert_at = len(groups)
        for index, group in enumerate(groups):
            if group and group[0] == "Setting Drop":
                insert_at = index + 1
                break
        groups.insert(insert_at, YES_SEARCH_GROUP)
        drop_settings_patch.SETTINGS_GROUPS = tuple(groups)
    except Exception as error:
        print(f"Drop Yes settings group install failed: {error}")


def _install_language_labels():
    if settings_language_details_patch is None:
        return

    try:
        settings_language_details_patch.TITLE_EN[YES_SEARCH_GROUP_TITLE] = "Drop Yes Search Area"
        settings_language_details_patch.NOTE_EN[YES_SEARCH_GROUP_NOTE] = (
            "Controls the Drop confirmation Yes search area around the inventory only. "
            "Increase values if Yes is not found; decrease them if it gets close to a wrong click."
        )
        settings_language_details_patch.KEY_EN_LABELS.update(YES_SEARCH_EN)

        if drop_settings_patch is not None:
            settings_language_details_patch._AR_SETTINGS_GROUPS = tuple(drop_settings_patch.SETTINGS_GROUPS)

        if hasattr(settings_language_details_patch, "_install_language_dictionary"):
            settings_language_details_patch._install_language_dictionary()
    except Exception as error:
        print(f"Drop Yes English settings labels install failed: {error}")


def _int_setting(owner, key, default, minimum=0, maximum=600):
    try:
        value = owner._setting(key, default)
    except Exception:
        value = default
    try:
        value = int(float(value))
    except Exception:
        value = int(default)
    value = max(int(minimum), value)
    value = min(int(maximum), value)
    return value


def _float_setting(owner, key, default, minimum=0.05, maximum=0.95):
    try:
        value = owner._setting(key, default)
    except Exception:
        value = default
    try:
        value = float(value)
    except Exception:
        value = float(default)
    value = max(float(minimum), value)
    value = min(float(maximum), value)
    return value


def _apply_drop_yes_search_settings(owner):
    left = _int_setting(owner, "inventory_drop_yes_area_pad_left", YES_SEARCH_DEFAULTS["inventory_drop_yes_area_pad_left"])
    top = _int_setting(owner, "inventory_drop_yes_area_pad_top", YES_SEARCH_DEFAULTS["inventory_drop_yes_area_pad_top"])
    right = _int_setting(owner, "inventory_drop_yes_area_pad_right", YES_SEARCH_DEFAULTS["inventory_drop_yes_area_pad_right"])
    bottom = _int_setting(owner, "inventory_drop_yes_area_pad_bottom", YES_SEARCH_DEFAULTS["inventory_drop_yes_area_pad_bottom"])
    click_fraction = _float_setting(owner, "inventory_drop_yes_click_x_fraction", YES_SEARCH_DEFAULTS["inventory_drop_yes_click_x_fraction"])
    wide_min = _int_setting(owner, "inventory_drop_yes_wide_template_min_width", YES_SEARCH_DEFAULTS["inventory_drop_yes_wide_template_min_width"], minimum=20, maximum=300)

    changed = (
        getattr(drop_confirmation, "BAG_ROI_PAD_LEFT", None) != left or
        getattr(drop_confirmation, "BAG_ROI_PAD_TOP", None) != top or
        getattr(drop_confirmation, "BAG_ROI_PAD_RIGHT", None) != right or
        getattr(drop_confirmation, "BAG_ROI_PAD_BOTTOM", None) != bottom or
        abs(float(getattr(drop_confirmation, "WIDE_TEMPLATE_YES_CLICK_X_FRACTION", click_fraction)) - click_fraction) > 0.0001 or
        getattr(drop_confirmation, "WIDE_TEMPLATE_MIN_WIDTH", None) != wide_min
    )

    drop_confirmation.BAG_ROI_PAD_LEFT = left
    drop_confirmation.BAG_ROI_PAD_TOP = top
    drop_confirmation.BAG_ROI_PAD_RIGHT = right
    drop_confirmation.BAG_ROI_PAD_BOTTOM = bottom
    drop_confirmation.WIDE_TEMPLATE_YES_CLICK_X_FRACTION = click_fraction
    drop_confirmation.WIDE_TEMPLATE_MIN_WIDTH = wide_min

    if changed:
        print(
            "Drop Yes search settings applied - "
            f"pad_left={left} pad_top={top} pad_right={right} pad_bottom={bottom} "
            f"click_x_fraction={click_fraction:.2f} wide_min={wide_min}"
        )


def _confirm_yes_if_needed_with_settings(self, pid, hwnd, grid):
    _apply_drop_yes_search_settings(self)
    return _ORIGINAL_CONFIRM_YES_IF_NEEDED(self, pid, hwnd, grid)


_install_defaults()
_install_settings_group()
_install_language_labels()
InventoryDropWorkerModule._confirm_yes_if_needed = _confirm_yes_if_needed_with_settings

print("Drop Yes settings patch active: Yes search area is editable in Settings")
