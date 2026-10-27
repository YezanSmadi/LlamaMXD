# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
"""The launch-time update check and the Repair button, offscreen with a faked GitHub: the setting's default and
validation, the Performance dropdown (its values, saving, Reset to Default), that launch only starts a check when
the setting says so, and that a launch-time check stays silent unless it finds something while the About button
never does; Repair through its dialogs (nothing to repair, declined, a missing release, a queue busy with jobs)
down to handing over to the installer and closing the app."""
import os
import tempfile

os.environ["QT_QPA_PLATFORM"] = "offscreen"

import harness  # noqa: E402
from harness import report  # noqa: E402

from check_ui import settle, window  # noqa: E402
from core import theme, update_check, updates  # noqa: E402
import ui.tabs.settings as st  # noqa: E402
import ui.updater as up  # noqa: E402
from core import repair  # noqa: E402


def _asset(name):
    return updates.Asset(name, "http://x/" + name, 1_000_000, "sha256:" + "0" * 64)


def _setting():
    problems = []
    if update_check.DEFAULT_MODE != update_check.STARTUP:
        problems.append("the default should be Check on Start Up")
    if update_check.MODES != ["Check on Start Up", "Never"]:
        problems.append(f"modes: {update_check.MODES}")
    keep = theme._SETTINGS_PATH
    with tempfile.TemporaryDirectory() as folder:
        theme._SETTINGS_PATH = os.path.join(folder, "settings.json")
        try:
            for stored, want in ((update_check.STARTUP, update_check.STARTUP), (update_check.NEVER, update_check.NEVER), ("sometimes", update_check.STARTUP), (None, update_check.STARTUP)):
                theme.save_settings({"update_check": stored})
                got = theme.load_settings()["update_check"]
                if got != want:
                    problems.append(f"stored {stored!r} loaded as {got!r}, expected {want!r}")
            os.remove(theme._SETTINGS_PATH)
            if theme.load_settings()["update_check"] != update_check.STARTUP:
                problems.append("a missing settings file should give Check on Start Up")
        finally:
            theme._SETTINGS_PATH = keep
    return problems


def _dropdown():
    problems = []
    tab = window.tabs["Settings"]
    saved = {}
    keep = (st.save_settings, st.ask_yes_no)
    st.save_settings = lambda settings: saved.update(settings)
    try:
        if tab.update_check_menu.value() != window.update_check:
            problems.append("the menu doesn't show the app's setting")
        tab._on_update_check_change(update_check.NEVER)
        if window.update_check != update_check.NEVER or saved.get("update_check") != update_check.NEVER:
            problems.append(f"picking Never: app={window.update_check!r} saved={saved.get('update_check')!r}")
        st.ask_yes_no = lambda *a, **k: True
        tab._on_reset_defaults()
        if window.update_check != update_check.STARTUP or tab.update_check_menu.value() != update_check.STARTUP:
            problems.append("Reset to Default didn't put the update check back to Check on Start Up")
        if saved.get("update_check") != update_check.STARTUP:
            problems.append("Reset to Default didn't save it")
    finally:
        st.save_settings, st.ask_yes_no = keep
    return problems


def _launch_and_prompts():
    problems = []
    flow = window.tabs["Settings"].update_flow
    shown, asked = [], []
    keep = (up.updates.check, up.show_message, up.ask_yes_no)
    up.show_message = lambda parent, title, message: shown.append(title)
    up.ask_yes_no = lambda parent, title, message: (asked.append(title) or False)
    try:
        # 1. Launch starts a check only when the setting says so.
        starts = []
        keep_start, window.tabs["Settings"].update_flow.start = flow.start, lambda startup=False: starts.append(startup)
        import ui.app as ui_app
        keep_delay, ui_app._STARTUP_UPDATE_CHECK_MS = ui_app._STARTUP_UPDATE_CHECK_MS, 0
        try:
            window.update_check = update_check.NEVER
            window.run_startup_update_check()
            settle(0.2)
            if starts:
                problems.append(f"Never still started a check at launch: {starts}")
            window.update_check = update_check.STARTUP
            window.run_startup_update_check()
            settle(0.2)
            if starts != [True]:
                problems.append(f"Check on Start Up should start exactly one launch-time check, got {starts}")
        finally:
            window.tabs["Settings"].update_flow.start = keep_start
            ui_app._STARTUP_UPDATE_CHECK_MS = keep_delay
            window.update_check = update_check.NEVER

        # 2. What a check does with each answer, launch-time (silent) versus the About button.
        cur = up.VERSION
        cases = {
            "offline": updates.Report(current=cur, errors=["GitHub couldn't be reached."], reached=False),
            "up to date": updates.Report(current=cur, reached=True, versions={"yt-dlp": "2026.10.26"}),
            "app update": updates.Report(current=cur, reached=True,
                                         app=updates.AppUpdate("9.9.9", "http://x/r", _asset("LlamaMXD-Setup-9.9.9.exe"))),
            "tool update": updates.Report(current=cur, reached=True, tools=[updates.ToolUpdate(
                "yt-dlp", "yt-dlp", "2026.08.19", "2026.10.26", _asset("yt-dlp.exe"), ("yt-dlp.exe",), False, ".")]),
        }
        expect = {  # (launch-time: dialogs shown / questions asked, button: dialogs shown / questions asked)
            "offline": ((0, 0), (1, 0)),
            "up to date": ((0, 0), (1, 0)),
            "app update": ((0, 1), (0, 1)),
            "tool update": ((0, 1), (0, 1)),
        }
        for name, rep in cases.items():
            up.updates.check = lambda current, rep=rep: rep
            for which, startup in (("launch", True), ("button", False)):
                del shown[:], asked[:]
                flow.start(startup=startup)
                settle(0.4)
                want = expect[name][0 if startup else 1]
                if (len(shown), len(asked)) != want:
                    problems.append(f"{name} / {which}: dialogs {len(shown)}, questions {len(asked)}, expected {want} ({shown} {asked})")
                if flow.btn.text() != up.IDLE_TEXT or not flow.btn.isEnabled():
                    problems.append(f"{name} / {which}: the button didn't return to idle ({flow.btn.text()!r})")
    finally:
        up.updates.check, up.show_message, up.ask_yes_no = keep
    return problems


def _repair_flow():
    problems = []
    flow = window.tabs["Settings"].update_flow
    btn, rbtn = flow.btn, flow.repair_btn
    shown, asked, launched, closed = [], [], [], []
    answers = []        # what each ask_yes_no returns, in order
    keep = (up.show_message, up.ask_yes_no, up.repair.app_dir, up.updates.release_for, up.updates.newest_installer,
            up.updates.download_installer, up.updates.launch_installer, window.close,
            window.tabs["Queue"].pending_task_count)
    up.show_message = lambda parent, title, message: shown.append((title, message))
    up.ask_yes_no = lambda parent, title, message: (asked.append((title, message)) or (answers.pop(0) if answers else False))
    up.updates.download_installer = lambda update, progress=None: "C:/fake/" + update.asset.name
    up.updates.launch_installer = lambda path: launched.append(path)
    window.close = lambda: closed.append(True)

    def make_tree(damage):
        import shutil
        import tempfile
        folder = tempfile.mkdtemp(prefix="llama-repair-ui-")
        for rel, data in {"LlamaMXD.exe": b"exe", "_internal/a.dll": b"dll", "manual/m.html": b"m"}.items():
            path = os.path.join(folder, *rel.split("/"))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            open(path, "wb").write(data)
        repair.write_manifest(folder, "1.0.0", {})
        if damage == "missing":
            os.remove(os.path.join(folder, "manual", "m.html"))
        elif damage == "nolist":
            os.remove(os.path.join(folder, repair.MANIFEST))
        return folder, lambda: shutil.rmtree(folder, ignore_errors=True)

    def run(label, damage, ask=(), release=None, newest=None, jobs=0, want=None):
        folder, cleanup = make_tree(damage)
        try:
            up.repair.app_dir = lambda: folder
            up.updates.release_for = lambda version: release
            up.updates.newest_installer = lambda version: newest
            window.tabs["Queue"].pending_task_count = lambda: jobs
            for box in (shown, asked, launched, closed):
                del box[:]
            answers[:] = list(ask)
            rbtn.click()
            settle(0.8)
            got = {"shown": [t for t, _ in shown], "asked": [t for t, _ in asked], "launched": list(launched),
                   "closed": bool(closed)}
            for key, value in want.items():
                if got[key] != value:
                    problems.append(f"{label}: {key} = {got[key]!r}, expected {value!r}")
            if btn.text() != up.IDLE_TEXT or rbtn.text() != up.REPAIR_TEXT or not (btn.isEnabled() and rbtn.isEnabled()):
                problems.append(f"{label}: the buttons didn't return to idle ({btn.text()!r}, {rbtn.text()!r})")
            return got
        finally:
            cleanup()

    try:
        update = updates.AppUpdate("1.0.0", "http://x", _asset("LlamaMXD-Setup-1.0.0.exe"))
        newer = updates.AppUpdate("1.1.0", "http://x", _asset("LlamaMXD-Setup-1.1.0.exe"))

        # not installed: nothing to repair, no questions
        up.repair.app_dir = lambda: None
        for box in (shown, asked):
            del box[:]
        rbtn.click()
        settle(0.3)
        if [t for t, _ in shown] != ["Repair LlamaMXD"] or asked:
            problems.append(f"a copy run from source: {shown} {asked}")

        run("intact", "none", want={"shown": ["Nothing to Repair"], "asked": [], "launched": [], "closed": False})
        run("damaged, declined", "missing", ask=[False], release=update,
            want={"shown": [], "asked": ["Repair LlamaMXD"], "launched": [], "closed": False})
        got = run("damaged, accepted", "missing", ask=[True], release=update,
                  want={"shown": [], "asked": ["Repair LlamaMXD"], "closed": True})
        if got["launched"] != ["C:/fake/LlamaMXD-Setup-1.0.0.exe"]:
            problems.append(f"damaged, accepted: launched {got['launched']}")
        if "manual/m.html" not in " ".join(m for t, m in asked):
            problems.append("the question didn't name the damaged file")
        run("no list, accepted", "nolist", ask=[True], release=update,
            want={"asked": ["Repair LlamaMXD"], "closed": True})
        if "no file list" not in asked[0][1]:
            problems.append("an install with no list should say it can't check its files")
        run("this version unpublished, newer offered and accepted", "missing", ask=[True, True], release=None, newest=newer,
            want={"asked": ["Repair LlamaMXD", "Repair LlamaMXD"], "launched": ["C:/fake/LlamaMXD-Setup-1.1.0.exe"], "closed": True})
        run("this version unpublished, newer declined", "missing", ask=[True, False], release=None, newest=newer,
            want={"asked": ["Repair LlamaMXD", "Repair LlamaMXD"], "launched": [], "closed": False})
        run("nothing published at all", "missing", ask=[True], release=None, newest=None,
            want={"shown": ["Couldn't Repair LlamaMXD"], "launched": [], "closed": False})
        run("jobs in the queue", "missing", ask=[True], release=update, jobs=2,
            want={"shown": ["Unfinished Jobs"], "asked": [], "launched": [], "closed": False})
    finally:
        (up.show_message, up.ask_yes_no, up.repair.app_dir, up.updates.release_for, up.updates.newest_installer,
         up.updates.download_installer, up.updates.launch_installer, window.close,
         window.tabs["Queue"].pending_task_count) = keep
    return problems


def run():
    ok = report("update check setting: default and validation", _setting())
    ok &= report("update check dropdown: value, saving, Reset to Default", _dropdown())
    ok &= report("launch-time check: only when asked, silent unless there is something", _launch_and_prompts())
    ok &= report("Repair: its dialogs, down to the installer launch and closing the app", _repair_flow())
    return ok


if __name__ == "__main__":
    run()
    harness.finish()
