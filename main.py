"""Application entry point.

The EXE uses external assets next to Login.exe. Startup errors are written to
logs/startup_error.log and shown in a message box instead of silently closing.
"""

import os
from pathlib import Path
import sys
import traceback


def _application_dir():
    """Return the folder containing the running source/EXE.

    EXE builds must resolve external assets, settings, and accounts next to the
    EXE rather than depending on whatever directory Windows used to launch it.
    """
    try:
        if getattr(sys, "frozen", False):
            return Path(sys.executable).resolve().parent
    except Exception:
        pass
    return Path(__file__).resolve().parent


def _set_application_working_directory():
    app_dir = _application_dir()
    try:
        os.chdir(app_dir)
    except Exception:
        pass
    return app_dir


_APP_DIR = _set_application_working_directory()


def _write_startup_error(error):
    try:
        log_dir = _APP_DIR / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        with (log_dir / "startup_error.log").open("a", encoding="utf-8") as stream:
            stream.write("\n" + "=" * 70 + "\n")
            stream.write("Login startup error\n")
            stream.write(traceback.format_exc())
            stream.write("\n")
    except Exception:
        pass


def _show_startup_error(error):
    try:
        import tkinter.messagebox as messagebox
        messagebox.showerror(
            "Login - Startup Error",
            "Login could not start.\n\n"
            f"{error}\n\n"
            "Check logs\\startup_error.log next to Login.exe.",
        )
    except Exception:
        pass


try:
    import patch_bootstrap  # keeps patch order stable and main.py clean
    from selection_launcher import SelectionAwareLauncher
except Exception as error:
    _write_startup_error(error)
    _show_startup_error(error)
    raise


if __name__ == "__main__":
    try:
        app = SelectionAwareLauncher()
        app.app.title("Login")
        app.run()
    except Exception as error:
        _write_startup_error(error)
        _show_startup_error(error)
        raise
