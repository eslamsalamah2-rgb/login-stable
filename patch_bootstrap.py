"""Central bootstrap for runtime patches.

Keep the import order stable here so main.py stays small and future maintenance
happens in one place.  This file does not add behavior by itself; it imports the
same patch modules in the same order, then installs the final safety cleanup.
"""

# Core Login / recovery protection.
import health_recovery_patch
import startup_focus_patch
import password_error_policy_patch
import existing_pages_settings_patch
import security_logger_update_patch
import pre_merge_safety_patch

# Post-login command runner and isolated modules.
import post_login_commands_patch
import post_login_module_merge_patch
import post_login_account_budget_patch
import account_options_patch
import drop_settings_patch
import use_items_patch
import sash_items_patch
import sash_next_page_patch
import post_sash_final_actions_patch

# Item selection and UI.
import item_selection_patch
import compact_item_selector_ui_patch
import ui_controls_settings_patch
import settings_onoff_close_patch
import top_header_controls_patch
import startup_scan_visible_patch
import hide_bottom_start_stop_patch
import restore_scan_panel_bottom_patch
import language_toggle_patch

# Login input tuning.
import input_speed_patch
import login_input_settings_patch
import login_username_arrow_patch

# Language polish.
import settings_language_details_patch
import drop_yes_settings_patch
import remaining_labels_language_patch
import language_buttons_fixed_english_patch

# Login retry/skip protections.
import login_stability_patch
import invalid_account_id_wait_patch
import account_retry_limit_patch

# Geometry alignment and final maintenance guards.
import inventory_grid_alignment_patch
import final_stability_cleanup_patch

# Final gates: manual Start launches real post-login work, Stop interrupts fast,
# unavailable accounts do not block the cycle, blank UI rows are ignored, and
# selected/pending slots with no real account data are cleared from queues.
import post_login_start_gate_fix_patch
import immediate_stop_hotkey_patch
import post_login_skip_unavailable_patch
import blank_account_cleanup_patch
import post_login_no_account_clear_patch

print("Patch bootstrap loaded: stable import order active")
