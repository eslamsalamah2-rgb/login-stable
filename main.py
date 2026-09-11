import patch_bootstrap  # keeps patch order stable and main.py clean
from selection_launcher import SelectionAwareLauncher


if __name__ == "__main__":
    app = SelectionAwareLauncher()
    app.run()
