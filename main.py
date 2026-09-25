# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yezan Smadi
"""LlamaMXD entry point.

    python main.py
"""
import os
import sys

from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication

_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _ROOT)

from core import llamalog  # noqa: E402
from core.theme import load_settings  # noqa: E402
from ui import qt_log, scale  # noqa: E402
from ui import theme as T  # noqa: E402
from ui.single_instance import ALREADY_RUNNING, InstanceLock  # noqa: E402
from ui.widgets.panels import VERSION  # noqa: E402
from ui.workers import init_workers  # noqa: E402


def _load_fonts():
    """Register the bundled Roboto (assets/fonts) — the app's typeface."""
    folder = os.path.join(_ROOT, "assets", "fonts")
    if os.path.isdir(folder):
        for name in os.listdir(folder):
            if name.lower().endswith((".ttf", ".otf")):
                QFontDatabase.addApplicationFont(os.path.join(folder, name))


def _make_app(log_qt):
    """The QApplication with the app's style, fonts and UI scale (`log_qt`: also route Qt's own
    messages into the log, which only exists for a copy that is really starting)."""
    app = QApplication(sys.argv)
    if log_qt:
        qt_log.install()
    app.setApplicationName("LlamaMXD")
    app.setStyle("Fusion")
    _load_fonts()
    # The window is a fixed share of the screen and the whole UI scales with
    # it (`ui.scale`) — adopt that scale before the stylesheet is generated.
    screen = app.primaryScreen().geometry()
    scale.set_factor(scale.fit(*scale.window_size(screen.width(), screen.height())))
    font = QFont()
    font.setFamilies(["Roboto", "Segoe UI"])
    font.setPixelSize(scale.font_px(13))
    font.setHintingPreference(QFont.PreferNoHinting)   # inherited by every widget font; see ui_font
    app.setFont(font)
    return app


def _apply_theme(app):
    """The live theme and the application-level stylesheet (widgets built later measure against it)."""
    T.init_theme()
    app.setStyleSheet(T.stylesheet())


def main():
    # Before logging: a second copy must not write a session header, or set aside the running
    # copy's crash.log (`llamalog.setup` does that at start).
    instance = InstanceLock()
    if not instance.held:
        from ui.widgets.dialogs import show_message
        app = _make_app(log_qt=False)
        _apply_theme(app)
        show_message(None, "LlamaMXD", ALREADY_RUNNING)
        sys.exit(0)

    # Logging first, so a failure anywhere below (or in a thread, or natively) is on record. It
    # starts at Normal; the saved log detail is applied as soon as the settings are read.
    llamalog.setup(version=VERSION)
    llamalog.set_detail(load_settings()["log_detail"])
    llamalog.describe_environment_async()
    app = _make_app(log_qt=True)

    init_workers()
    _apply_theme(app)

    from ui.app import MainWindow
    window = MainWindow()
    window.present()
    code = app.exec()
    llamalog.get("app").info("LlamaMXD exiting (code %s)", code)
    instance.release()
    sys.exit(code)


if __name__ == "__main__":
    main()
