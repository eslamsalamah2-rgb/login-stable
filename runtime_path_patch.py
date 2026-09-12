"""Keep relative assets/settings working when launching the EXE from Explorer.

The application intentionally keeps images and runtime JSON files outside the EXE.
When a frozen EXE is opened by double-click, Windows may use another working
folder. Normalize the working directory to the folder containing the EXE/source
so assets, settings, accounts, and item selections resolve consistently.
"""

import os
import sys


def _application_directory():
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


try:
    os.chdir(_application_directory())
    print(f"Runtime path patch active: working directory={os.getcwd()}")
except Exception as error:
    print(f"Runtime path patch warning: {error}")
