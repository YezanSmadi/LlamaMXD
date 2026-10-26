# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
"""Where settings.json and presets.json live: beside main.py from source, the user's data folder in a
frozen build (made on demand, a portable copy beside the exe carried over once and never over a file
already there), and a save in that folder round-trips."""
import os
import shutil
import sys

from harness import WORK, report

from core import userdata

SANDBOX = os.path.join(WORK, "userdata")


def run():
    problems = []
    shutil.rmtree(SANDBOX, ignore_errors=True)
    appdata, exe_dir = os.path.join(SANDBOX, "appdata"), os.path.join(SANDBOX, "app")
    os.makedirs(exe_dir)
    os.environ["LOCALAPPDATA"] = appdata
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    if userdata.user_file("settings.json") != os.path.join(repo, "settings.json"):
        problems.append("from source: settings.json is not beside main.py")

    sys.frozen = True
    real_exe, sys.executable = sys.executable, os.path.join(exe_dir, "LlamaMXD.exe")
    try:
        want = os.path.join(appdata, "LlamaMXD", "settings.json")
        if userdata.user_file("settings.json") != want:
            problems.append(f"frozen: settings.json at {userdata.user_file('settings.json')}, not {want}")
        if not os.path.isdir(os.path.dirname(want)):
            problems.append("frozen: the data folder was not made")

        with open(os.path.join(exe_dir, "presets.json"), "w", encoding="utf-8") as fh:
            fh.write('{"Encoding": {"mine": {}}}')
        if userdata.user_file("presets.json") != os.path.join(appdata, "LlamaMXD", "presets.json"):
            problems.append("frozen: presets.json is not in the data folder")
        if os.path.exists(os.path.join(appdata, "LlamaMXD", "presets.json")):
            problems.append("frozen: a presets.json beside the exe was copied into the data folder")

        from core import theme
        theme._SETTINGS_PATH = want
        theme.save_settings({**theme.load_settings(), "theme": "Cupid"})
        if theme.load_settings()["theme"] != "Cupid":
            problems.append("frozen: a saved setting did not read back")
        if os.path.exists(os.path.join(exe_dir, "settings.json")):
            problems.append("frozen: settings.json was written beside the exe")
    finally:
        del sys.frozen
        sys.executable = real_exe
    return report("user data: source vs installed location, nothing beside the exe, save", problems)


if __name__ == "__main__":
    run()
