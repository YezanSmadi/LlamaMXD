"""LlamaMXD entry point.

    python main.py
"""
import os
import sys

from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication

_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _ROOT)

from ui import scale  # noqa: E402
from ui import theme as T  # noqa: E402
from ui.workers import init_workers  # noqa: E402


def _load_fonts():
    """Register the bundled Roboto (assets/fonts) — the app's typeface."""
    folder = os.path.join(_ROOT, "assets", "fonts")
    if os.path.isdir(folder):
        for name in os.listdir(folder):
            if name.lower().endswith((".ttf", ".otf")):
                QFontDatabase.addApplicationFont(os.path.join(folder, name))


def main():
    app = QApplication(sys.argv)
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

    init_workers()
    T.init_theme()
    app.setStyleSheet(T.stylesheet())

    from ui.app import MainWindow
    window = MainWindow()
    window.present()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
