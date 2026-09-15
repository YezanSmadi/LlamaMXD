"""Composite pieces: the sub-tab switch, the drop box, the export rundown, and
the sidebar + active-tab pipe."""
import os
from datetime import datetime

from PySide6.QtCore import QEasingCurve, QRectF, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QFontMetricsF, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QFileDialog, QGridLayout, QLabel, QVBoxLayout, QWidget

from ui import theme as T
from ui.widgets.controls import MarqueeLabel, button, ui_font

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ASSETS = os.path.join(_REPO_ROOT, "assets")
VERSION = "v0.5.0-alpha.6"

MEDIA_FILTER = (
    "Media files (*.mp4 *.mkv *.mov *.webm *.avi *.m4v *.mxf "
    "*.mp3 *.m4a *.aac *.flac *.wav *.opus *.ogg *.wma *.aiff);;All files (*.*)"
)


def local_paths(mime):
    """Local file paths carried by a drag's mime data."""
    if not mime.hasUrls():
        return []
    return [u.toLocalFile() for u in mime.urls() if u.isLocalFile()]


# --------------------------------------------------------------------------- #
#  SubTabBar
# --------------------------------------------------------------------------- #
class SubTabBar(QWidget):
    """Overview / Video / Audio. Active = `primary` at full height, inactive =
    `secondary` at 80%, bottom-aligned like tabs on a shelf. Height and fill
    ease between states; hover shades fade too. `set_marked` cross-fades a
    button to STOP_RED — a stream removed on a panel the user can't see."""

    changed = Signal(str)

    _ACTIVE_H = 30.0
    _INACTIVE_H = 24.0
    _GAP = 3.0
    _RADIUS = 6.0
    _PAD_X = 13.0

    def __init__(self, names, parent=None):
        super().__init__(parent)
        self._names = list(names)
        self._active = self._names[0]
        self._marked = set()
        self._hover = None
        self._bold13 = ui_font(13, bold=True)
        self._bold12 = ui_font(12, bold=True)
        fm = QFontMetricsF(self._bold13)
        self._widths = [max(58.0, fm.horizontalAdvance(n) + 2 * self._PAD_X) for n in self._names]
        total = sum(self._widths) + self._GAP * (len(self._names) - 1)
        self.setFixedSize(int(total + 0.999), int(self._ACTIVE_H))
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)

        self._cur = {n: self._target(n) for n in self._names}
        self._from = dict(self._cur)
        self._anim = QVariantAnimation(self)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setDuration(170)
        self._anim.setEasingCurve(QEasingCurve.InOutSine)
        self._anim.valueChanged.connect(self._step)
        T.theme.changed.connect(self._snap)

    def active(self):
        return self._active

    def set_active(self, name, emit=True):
        if name in self._names and name != self._active:
            self._active = name
            self._animate()
            if emit:
                self.changed.emit(name)

    def set_marked(self, name, marked):
        if (name in self._marked) != bool(marked):
            (self._marked.add if marked else self._marked.discard)(name)
            self._animate()

    def _target(self, name):
        """(fill, height, text colour) this button should settle on."""
        th = T.theme
        if name in self._marked:
            key = "stop"
        elif name == self._active:
            key = "primary"
        else:
            key = "secondary"
        fill = th.color(f"{key}_hover" if name == self._hover else key)
        height = self._ACTIVE_H if name == self._active else self._INACTIVE_H
        return fill, height, th.color(f"{key}_text")

    def _animate(self):
        if not self.isVisible():
            self._snap()
            return
        self._from = dict(self._cur)
        self._anim.stop()
        self._anim.start()

    def _snap(self):
        self._anim.stop()
        self._cur = {n: self._target(n) for n in self._names}
        self.update()

    def _step(self, t):
        for n in self._names:
            (f0, h0, c0), (f1, h1, c1) = self._from[n], self._target(n)
            self._cur[n] = (T.lerp(f0, f1, t), h0 + (h1 - h0) * t, T.lerp(c0, c1, t))
        self.update()

    def _hit(self, x):
        edge = 0.0
        for n, w in zip(self._names, self._widths):
            if edge <= x < edge + w:
                return n
            edge += w + self._GAP
        return None

    def mouseMoveEvent(self, e):
        h = self._hit(e.position().x())
        if h != self._hover:
            self._hover = h
            self._animate()

    def leaveEvent(self, e):
        if self._hover is not None:
            self._hover = None
            self._animate()

    def mousePressEvent(self, e):
        n = self._hit(e.position().x())
        if n:
            self.set_active(n)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        edge = 0.0
        for n, w in zip(self._names, self._widths):
            fill, h, text = self._cur[n]
            rect = QRectF(edge, self._ACTIVE_H - h, w, h)
            path = QPainterPath()
            path.addRoundedRect(rect, self._RADIUS, self._RADIUS)
            p.fillPath(path, fill)
            p.setPen(text)
            p.setFont(self._bold13 if n == self._active else self._bold12)
            p.drawText(rect, Qt.AlignCenter, n)
            edge += w + self._GAP


# --------------------------------------------------------------------------- #
#  DropBox
# --------------------------------------------------------------------------- #
class DropBox(QWidget):
    """The primary-bordered drop target: drop a file, double-click, or Browse.
    Drag-over lights it up. `collapse()` — once a file's been picked the
    prompt and border go, leaving just Browse, until the preview carousel
    takes over."""

    fileSelected = Signal(str)

    def __init__(self, prompt="Drag & Drop File Here", parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self._dragging = False
        self._collapsed = False

        lay = QVBoxLayout(self)
        lay.setAlignment(Qt.AlignCenter)
        lay.setSpacing(14)
        self.prompt = QLabel(prompt)
        self.prompt.setFont(ui_font(14))
        self.prompt.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.prompt)
        self.or_label = QLabel("— or —")
        self.or_label.setFont(ui_font(14))
        self.or_label.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.or_label)
        self.browse_btn = button("Browse File", width=140)
        self.browse_btn.clicked.connect(self.browse)
        lay.addWidget(self.browse_btn, 0, Qt.AlignCenter)
        T.theme.changed.connect(self.update)

    def collapse(self):
        self._collapsed = True
        self.prompt.hide()
        self.or_label.hide()
        self.update()

    def browse(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select a File", "", MEDIA_FILTER)
        if path:
            self.fileSelected.emit(path)

    def mouseDoubleClickEvent(self, e):
        self.browse()

    def dragEnterEvent(self, e):
        if local_paths(e.mimeData()):
            e.acceptProposedAction()
            self._dragging = True
            self.update()

    def dragLeaveEvent(self, e):
        self._dragging = False
        self.update()

    def dropEvent(self, e):
        self._dragging = False
        self.update()
        paths = local_paths(e.mimeData())
        if paths:
            self.fileSelected.emit(paths[0])

    def paintEvent(self, _event):
        if self._collapsed and not self._dragging:
            return
        th = T.theme
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(rect, 10, 10)
        if self._dragging:
            p.fillPath(path, T.with_alpha(th.color("primary"), 0.11))
        p.setPen(QPen(th.color("primary_hover" if self._dragging else "primary"), 2))
        p.drawPath(path)


class BorderedFrame(QWidget):
    """The DropBox's primary rounded border without its drop behaviour — the
    Downloader tab's preview box."""

    def __init__(self, parent=None):
        super().__init__(parent)
        T.theme.changed.connect(self.update)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 10, 10)
        p.setPen(QPen(T.theme.color("primary"), 2))
        p.drawPath(path)


# --------------------------------------------------------------------------- #
#  SummaryPanel
# --------------------------------------------------------------------------- #
class SummaryPanel(QWidget):
    """The Overview rundown: `label  value` rows, values marquee when long.
    The one place every cross-panel consequence is visible at once (a removed
    stream shows `— removed —` in STOP_RED)."""

    def __init__(self, labels, parent=None):
        super().__init__(parent)
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(0)
        grid.setVerticalSpacing(12)
        self._values = []
        for row, text in enumerate(labels):
            lab = QLabel(text)
            lab.setProperty("role", "muted")
            lab.setStyleSheet("font-weight: bold;")
            lab.setFixedWidth(72)
            grid.addWidget(lab, row, 0)
            val = MarqueeLabel("—", pixel_size=11)
            grid.addWidget(val, row, 1)
            self._values.append(val)
        grid.setColumnStretch(1, 1)

    def set_values(self, rows):
        """`rows` = [(text, color_key_or_None), ...] in label order."""
        for label, (text, color) in zip(self._values, rows):
            label.setText(text)
            label.set_color_key(color or "text")


# --------------------------------------------------------------------------- #
#  Sidebar + active-tab pipe
# --------------------------------------------------------------------------- #
class Sidebar(QWidget):
    """Title, logo, the four nav buttons, then Settings + footer pinned to the
    bottom via a layout stretch."""

    navigate = Signal(str)
    WIDTH = 200

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(self.WIDTH)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 24, 0, 10)
        lay.setSpacing(0)

        title = QLabel("LlamaMXD")
        title.setProperty("role", "sidebarTitle")
        title.setAlignment(Qt.AlignCenter)
        lay.addWidget(title)
        lay.addSpacing(20)

        self.logo = QLabel()
        self.logo.setFixedSize(140, 140)
        self._load_logo()
        lay.addWidget(self.logo, 0, Qt.AlignHCenter)
        lay.addSpacing(10)

        self.buttons = {}
        for name in ("Muxing", "Encoding", "Downloader", "Queue"):
            lay.addSpacing(10)
            self._add_nav(lay, name)
            lay.addSpacing(10)
        lay.addStretch(1)
        self._add_nav(lay, "Settings")
        lay.addSpacing(8)

        footer = QLabel(f"{datetime.now().year} Yezan Smadi     {VERSION}")
        footer.setProperty("role", "sidebarFooter")
        footer.setAlignment(Qt.AlignCenter)
        lay.addWidget(footer)
        T.theme.changed.connect(self.update)

    def _add_nav(self, lay, name):
        btn = button(name)
        btn.setFixedSize(140, 28)
        btn.clicked.connect(lambda _=False, n=name: self.navigate.emit(n))
        lay.addWidget(btn, 0, Qt.AlignHCenter)
        self.buttons[name] = btn

    def _load_logo(self):
        pix = QPixmap(os.path.join(ASSETS, "llama.png"))
        if pix.isNull():
            return
        dpr = self.devicePixelRatioF() or 1.0
        pix = pix.scaled(int(140 * dpr), int(140 * dpr), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        pix.setDevicePixelRatio(dpr)
        self.logo.setPixmap(pix)

    def paintEvent(self, _event):
        QPainter(self).fillRect(self.rect(), T.theme.color("primary"))


class TabIndicator(QWidget):
    """The flat `primary` pipe from the active nav button to the tab frame,
    with the 12px `secondary` band through its middle. It *glides* to the new
    button instead of jumping. Square corners, so it meets the button's
    rounded edge flush at mid-height."""

    _LINE_H = 12

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(220)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(lambda y: self.move(self.x(), round(y)))
        T.theme.changed.connect(self.update)

    def align_to(self, target, frame_left, animate=True):
        top_left = target.mapTo(self.parentWidget(), target.rect().topLeft())
        x = top_left.x() + target.width()
        self.resize(max(1, frame_left - x), target.height())
        if animate and self.isVisible():
            self._anim.stop()
            self._anim.setStartValue(float(self.y()))
            self._anim.setEndValue(float(top_left.y()))
            self.move(x, self.y())
            self._anim.start()
        else:
            self._anim.stop()
            self.move(x, top_left.y())
        self.show()
        self.raise_()

    def paintEvent(self, _event):
        p = QPainter(self)
        th = T.theme
        p.fillRect(self.rect(), th.color("primary"))
        y = self.height() // 2 - self._LINE_H // 2
        p.fillRect(0, y, self.width(), self._LINE_H, th.color("secondary"))
