# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
"""Settings > About's "Check for Updates": asks GitHub, then offers a newer LlamaMXD and newer bundled
tools one Yes / No question each. Downloads run off the GUI thread; the button shows their progress."""
from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QDesktopServices

from core import llamalog, updates, userdata
from ui.widgets.dialogs import ask_yes_no, show_message
from ui.widgets.panels import VERSION
from ui.workers import emit_progress, run_async

IDLE_TEXT = "Check for Updates"
# Every label the button can show, so its width can be sized to the widest.
LABELS = (IDLE_TEXT, "Checking...", "Downloading 100%", "Updating 100%")


def _mb(size):
    """A download size as "17 MB"."""
    return f"{max(1, round(size / 1_000_000))} MB"


class UpdateFlow:
    """The Check for Updates button's behaviour."""

    def __init__(self, app, btn):
        self.app = app
        self.btn = btn
        self._busy = False
        btn.clicked.connect(self.start)

    # ------------------------------------------------------------------ #
    #  Button state
    # ------------------------------------------------------------------ #
    def _set(self, text, busy=True):
        self._busy = busy
        self.btn.setText(text)
        self.btn.setEnabled(not busy)

    def _idle(self):
        self._set(IDLE_TEXT, busy=False)

    def _show_progress(self, value):
        label, pct = value
        self.btn.setText(f"{label} {pct}%")

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

    def _queue_busy(self):
        """Say so and return True while jobs are unfinished: an update must not pull files out from under them."""
        if self.app.tabs["Queue"].pending_task_count() == 0:
            return False
        show_message(self.app, "Unfinished Jobs",
                     "Finish or clear the jobs in the Queue first, then check for updates again.")
        return True

    # ------------------------------------------------------------------ #
    #  Checking
    # ------------------------------------------------------------------ #
    def start(self, startup=False):
        """Check now. `startup` is the launch-time check: it says nothing unless there is something to offer."""
        if self._busy:
            return
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

        def work():
            try:
                return ("ok", updates.download_installer(update, self._progress("Downloading", 0, update.asset.size)))
            except updates.UpdateError as exc:
                return ("error", str(exc))

        self._set("Downloading 0%")
        run_async(work, self._on_installer)
        return True

    def _on_installer(self, result):
        self._idle()
        if result is None or result[0] != "ok":
            show_message(self.app, "Couldn't Update LlamaMXD", result[1] if result else "The download failed.")
            return
        try:
            updates.launch_installer(result[1])
        except OSError as exc:
            llamalog.get("updates").error("Couldn't start the installer: %s", exc)
            show_message(self.app, "Couldn't Update LlamaMXD", f"The installer couldn't be started ({exc}).")
            return
        QTimer.singleShot(300, self.app.close)

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
