import health_recovery_patch  # applies recovery safety patch on import
import startup_focus_patch  # pauses monitor during input and retries focus failures
from selection_launcher import SelectionAwareLauncher


if __name__ == "__main__":
    app = SelectionAwareLauncher()
    app.run()
