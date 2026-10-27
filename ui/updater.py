# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
"""Settings > About's "Check for Updates" and "Repair": asks GitHub, then offers a newer LlamaMXD and newer
bundled tools one Yes / No question each; Repair checks the installed files against their list and, if
any are missing or damaged, reinstalls over the copy. Downloads run off the GUI thread; the buttons show progress."""
from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QDesktopServices

from core import llamalog, repair, updates, userdata
from ui.widgets.dialogs import ask_yes_no, show_message
from ui.widgets.panels import VERSION
from ui.workers import emit_progress, run_async

IDLE_TEXT = "Check for Updates"
REPAIR_TEXT = "Repair"
# Every label each button can show, so its width can be sized to the widest.
LABELS = (IDLE_TEXT, "Checking...", "Downloading 100%", "Updating 100%")
REPAIR_LABELS = (REPAIR_TEXT, "Checking 100%", "Downloading 100%")
_SHOWN_PROBLEMS = 6


def _mb(size):
    """A download size as "17 MB"."""
    return f"{max(1, round(size / 1_000_000))} MB"


class UpdateFlow:
    """The Check for Updates and Repair buttons' behaviour (one runs at a time)."""

    def __init__(self, app, btn, repair_btn=None):
        self.app = app
        self.btn = btn
        self.repair_btn = repair_btn
        self._shown = btn   # the button that is showing progress
        self._busy = False
        btn.clicked.connect(self.start)
        if repair_btn:
            repair_btn.clicked.connect(self.repair)

    # ------------------------------------------------------------------ #
    #  Button state
    # ------------------------------------------------------------------ #
    def _buttons(self):
        return [b for b in (self.btn, self.repair_btn) if b]

    def _set(self, text, busy=True):
        self._busy = busy
        self._shown.setText(text)
        for button in self._buttons():
            button.setEnabled(not busy)

    def _idle(self):
        self.btn.setText(IDLE_TEXT)
        if self.repair_btn:
            self.repair_btn.setText(REPAIR_TEXT)
        self._busy = False
        for button in self._buttons():
            button.setEnabled(True)

    def _show_progress(self, value):
        label, pct = value
        self._shown.setText(f"{label} {pct}%")

    def _progress(self, label, before, grand):
        """A download callback reporting `label` and the share done of `grand` bytes (`before` already
        done by earlier files) to the button, only when the whole percent changes."""
        last = [-1]

        def report(done, total):
            whole = grand or total
            pct = min(100, int(100 * (before + done) / whole)) if whole else 0
            if pct != last[0]:
                last[0] = pct
                emit_progress(self._show_progress, (label, pct))
        return report

    def _queue_busy(self, doing="check for updates"):
        """Say so and return True while jobs are unfinished: an update must not pull files out from under them."""
        if self.app.tabs["Queue"].pending_task_count() == 0:
            return False
        show_message(self.app, "Unfinished Jobs",
                     f"Finish or clear the jobs in the Queue first, then {doing} again.")
        return True

    # ------------------------------------------------------------------ #
    #  Checking
    # ------------------------------------------------------------------ #
    def start(self, startup=False):
        """Check now. `startup` is the launch-time check: it says nothing unless there is something to offer."""
        if self._busy:
            return
        self._shown = self.btn
        self._set("Checking...")
        run_async(updates.check, lambda report: self._on_report(report, startup), VERSION)

    def _on_report(self, report, startup=False):
        self._idle()
        if report is None or not report.reached:
            detail = "\n".join(report.errors) if report else "Something went wrong. The log has the details."
            if startup:
                llamalog.get("updates").info("The launch-time update check couldn't finish: %s", detail)
            else:
                show_message(self.app, "Couldn't Check for Updates", detail or "GitHub couldn't be reached.")
            return
        if report.app and self._offer_app(report.app):
            return
        if report.tools:
            self._offer_tools(report.tools)
            return
        if report.app or startup:
            return   # offered and declined, or a launch-time check with nothing to say
        lines = [f"LlamaMXD {VERSION} is up to date."]
        if report.versions:
            names = {spec["name"]: spec["label"] for spec in updates.TOOLS}
            lines.append("So are its tools: " + ", ".join(f"{names[n]} {v}" for n, v in report.versions.items()) + ".")
        if report.errors:
            lines.append("\nCouldn't check: " + "; ".join(report.errors))
        show_message(self.app, "Up to Date", "\n".join(lines))

    # ------------------------------------------------------------------ #
    #  LlamaMXD
    # ------------------------------------------------------------------ #
    def _offer_app(self, update):
        """Ask about the new LlamaMXD; True when the user said yes (the tools wait until it is installed)."""
        installed = userdata.is_frozen()
        if installed:
            message = (f"LlamaMXD {update.version} is available (you have {VERSION}).\n\n"
                       "Download and install it now? LlamaMXD will close, update and open again. "
                       "Your settings and presets are kept, and the bundled tools are checked on your next update check.")
        else:
            message = (f"LlamaMXD {update.version} is available (you have {VERSION}).\n\n"
                       "This copy isn't installed, so it can't update itself. Open the download page instead?")
        if not ask_yes_no(self.app, "Update LlamaMXD", message):
            return False
        if not installed:
            QDesktopServices.openUrl(QUrl(update.page or updates.releases_page()))
            return True
        if self._queue_busy():
            return True
        self._download_and_install(update, self.btn, "Update")
        return True

    def _download_and_install(self, update, button, what):
        """Download and verify `update`'s installer, then hand over to it (it closes this app and reopens it)."""
        def work():
            try:
                return ("ok", updates.download_installer(update, self._progress("Downloading", 0, update.asset.size)))
            except updates.UpdateError as exc:
                return ("error", str(exc))

        self._shown = button
        self._set("Downloading 0%")
        run_async(work, lambda result: self._on_installer(result, what))

    def _on_installer(self, result, what="Update"):
        self._idle()
        if result is None or result[0] != "ok":
            show_message(self.app, f"Couldn't {what} LlamaMXD", result[1] if result else "The download failed.")
            return
        try:
            updates.launch_installer(result[1])
        except OSError as exc:
            llamalog.get("updates").error("Couldn't start the installer: %s", exc)
            show_message(self.app, f"Couldn't {what} LlamaMXD", f"The installer couldn't be started ({exc}).")
            return
        QTimer.singleShot(300, self.app.close)

    # ------------------------------------------------------------------ #
    #  Repair
    # ------------------------------------------------------------------ #
    def repair(self):
        """Check the installed files against the list built with them; offer to reinstall over any damage."""
        if self._busy:
            return
        folder = repair.app_dir()
        if folder is None:
            show_message(self.app, "Repair LlamaMXD",
                         "This copy of LlamaMXD isn't installed (it is running from its source folder), "
                         "so there is nothing to repair.")
            return
        if self._queue_busy("repair"):
            return
        self._shown = self.repair_btn
        self._set("Checking 0%")
        last = [-1]

        def progress(done, total):
            pct = int(100 * done / total) if total else 100
            if pct != last[0]:
                last[0] = pct
                emit_progress(self._show_progress, ("Checking", pct))

        run_async(lambda: repair.verify(folder, progress), self._on_verified)

    def _on_verified(self, result):
        self._idle()
        if result is None:
            show_message(self.app, "Couldn't Check the Files", "Something went wrong. The log has the details.")
            return
        keeps = "Your settings, presets and any newer tools are kept. LlamaMXD will close and reopen."
        if not result.manifest_found:
            question = ("LlamaMXD can't check its files because this install has no file list. Reinstall it anyway?\n\n"
                        f"This downloads the installer for version {VERSION} (a few hundred MB) and installs it over "
                        f"this copy. {keeps}")
        elif not result.problems:
            show_message(self.app, "Nothing to Repair", f"All {result.total} of LlamaMXD's files are intact.")
            return
        else:
            names = [f"{rel} ({why})" for rel, why in result.problems[:_SHOWN_PROBLEMS]]
            more = len(result.problems) - len(names)
            listing = "\n".join("• " + n for n in names) + (f"\n• and {more} more" if more > 0 else "")
            question = (f"{len(result.problems)} of LlamaMXD's {result.total} files are missing or damaged:\n\n{listing}"
                        f"\n\nRepair them? This downloads the installer for version {VERSION} (a few hundred MB) and "
                        f"installs it over this copy. {keeps}")
        if not ask_yes_no(self.app, "Repair LlamaMXD", question) or self._queue_busy("repair"):
            return
        self._shown = self.repair_btn
        self._set("Checking...")

        def lookup():
            try:
                exact = updates.release_for(VERSION)
                return ("ok", exact) if exact else ("other", updates.newest_installer(VERSION))
            except updates.UpdateError as exc:
                return ("error", str(exc))

        run_async(lookup, self._on_release)

    def _on_release(self, result):
        self._idle()
        if result is None or result[0] == "error":
            show_message(self.app, "Couldn't Repair LlamaMXD",
                         result[1] if result else "Something went wrong. The log has the details.")
            return
        kind, update = result
        if kind == "other":
            if update is None:
                show_message(self.app, "Couldn't Repair LlamaMXD",
                             f"No installer for version {VERSION} (or any other) could be found on GitHub.")
                return
            if not ask_yes_no(self.app, "Repair LlamaMXD",
                              f"The installer for version {VERSION} isn't published any more. Reinstall version "
                              f"{update.version} instead? Your settings, presets and any newer tools are kept."):
                return
        self._download_and_install(update, self.repair_btn, "Repair")

    # ------------------------------------------------------------------ #
    #  Bundled tools
    # ------------------------------------------------------------------ #
    def _offer_tools(self, found):
        lines = [f"• {u.label} {u.installed} → {u.latest} ({_mb(u.asset.size)})" for u in found]
        message = ("Newer versions of the tools LlamaMXD uses are available:\n\n" + "\n".join(lines) +
                   "\n\nDownload and install them now? Each is checked before it replaces the old one, "
                   "and the old one is kept if anything goes wrong.")
        if not ask_yes_no(self.app, "Update Tools", message) or self._queue_busy():
            return
        grand = sum(u.asset.size for u in found)

        def work():
            results, before = [], 0
            for update in found:
                try:
                    updates.install_tool(update, self._progress("Updating", before, grand))
                    results.append((update, None))
                except updates.UpdateError as exc:
                    llamalog.get("updates").warning("%s update failed: %s", update.name, exc)
                    results.append((update, str(exc)))
                before += update.asset.size
            return results

        self._shown = self.btn
        self._set("Updating 0%")
        run_async(work, self._on_tools_done)

    def _on_tools_done(self, results):
        self._idle()
        if results is None:
            show_message(self.app, "Couldn't Update Tools", "Something went wrong. The log has the details.")
            return
        done = [u for u, err in results if err is None]
        failed = [(u, err) for u, err in results if err is not None]
        lines = []
        if done:
            lines.append("Updated: " + ", ".join(f"{u.label} {u.latest}" for u in done) + ".")
            if any(u.name == "ffmpeg" for u in done):
                lines.append("Restart LlamaMXD to start using the new ffmpeg.")
        for update, err in failed:
            lines.append(f"{update.label} wasn't updated: {err}")
        show_message(self.app, "Tools Updated" if done and not failed else "Update Tools", "\n".join(lines))
