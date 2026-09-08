import health_recovery_patch  # keeps timer-gated recovery safe
import startup_focus_patch  # pauses monitor during input and retries focus failures
import password_error_policy_patch  # restarts all pages after repeated wrong-password message
import existing_pages_settings_patch  # adds Scan Open, side panel, and editable Settings
import pre_merge_safety_patch  # logging, backups, input lock, feature flags, rollback prep
from selection_launcher import SelectionAwareLauncher


if __name__ == "__main__":
    app = SelectionAwareLauncher()
    app.run()
