import health_recovery_patch  # keeps timer-gated recovery safe
import startup_focus_patch  # pauses monitor during input and retries focus failures
import password_error_policy_patch  # restarts all pages after repeated wrong-password message
import existing_pages_settings_patch  # adds Scan Open, side panel, and editable Settings
import pre_merge_safety_patch  # logging, backups, input lock, feature flags, rollback prep
import post_login_commands_patch  # starts safe post-login command loop after READY accounts
import post_login_module_merge_patch  # safe modular worker hook for future Drop/Use/Sash merge
import account_options_patch  # per-account saved Rev/Rev Here/Sash options
import drop_settings_patch  # clean Settings window: Setting Drop timings only, no thresholds
import input_speed_patch  # keeps Login typing protected while Drop/Yes mouse stays fast only locally
import login_stability_patch  # global stop, Invalid Account ID retry/skip, duplicate username skip
import invalid_account_id_wait_patch  # wait for Invalid Account ID message to disappear before retyping
import inventory_grid_alignment_patch  # shifts detected inventory grid slightly left after user test
from selection_launcher import SelectionAwareLauncher


if __name__ == "__main__":
    app = SelectionAwareLauncher()
    app.run()
