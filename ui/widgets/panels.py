"""Composite pieces: the sub-tab switch, the drop box, the export rundown, and
the sidebar + active-tab pipe."""
import os
from datetime import datetime

import numpy as np
from PySide6.QtCore import QEasingCurve, QPointF, QRectF, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QFontMetricsF, QImage, QPainter, QPainterPath, QPen, QPixmap, QTransform
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QFileDialog, QGridLayout, QLabel, QVBoxLayout, QWidget

from ui import scale
from ui import theme as T
from ui.scale import px
from ui.widgets.controls import (
    MarqueeGroup, MarqueeLabel, ScaledLabel, button, restyle, set_font_px, ui_font,
)

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ASSETS = os.path.join(_REPO_ROOT, "assets")
VERSION = "v0.5.0-beta.3"

MEDIA_FILTER = (
    "Media files (*.mp4 *.mkv *.mov *.webm *.avi *.m4v *.mxf *.ts *.vob "
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
    `secondary` at 80% (swapped for a theme with `swap_subtabs`), bottom-aligned like tabs on a shelf, standing on a
    thin line in the selected tab's colour that runs the whole length of the bar (the tabs' bottom
    rounding is clipped away so each one sits flat on it). Height and fill
    ease between states; hover shades fade too. `set_marked` cross-fades a
    button to STOP_RED — a stream removed on a panel the user can't see."""

    changed = Signal(str)

    _ACTIVE_H = 30.0
    _LINE_H = 4.0
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
        scale.fixed(self, int(total + 0.999), int(self._ACTIVE_H + self._LINE_H))
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
            key = "subtab_active"      # primary, or secondary for a theme that swaps them
        else:
            key = "subtab_inactive"
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
        h = self._hit(scale.ref_pos(e.position()).x())
        if h != self._hover:
            self._hover = h
            self._animate()

    def leaveEvent(self, e):
        if self._hover is not None:
            self._hover = None
            self._animate()

    def mousePressEvent(self, e):
        n = self._hit(scale.ref_pos(e.position()).x())
        if n:
            self.set_active(n)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        scale.begin(p)
        width, height = scale.ref_size(self)
        # Where the tabs' feet meet the line, snapped to a whole device pixel:
        # at a scale where 30 reference px lands mid-pixel, the clip cutting
        # the tabs and the line's own edge each cover part of that row and the
        # window colour shows through the rest — a thin seam under the tab.
        foot = round(self._ACTIVE_H * scale.factor()) / scale.factor()
        edge = 0.0
        p.save()
        p.setClipRect(QRectF(0, 0, width, foot))
        for n, w in zip(self._names, self._widths):
            fill, h, text = self._cur[n]
            rect = QRectF(edge, foot - h, w, h)
            # Drawn a radius taller than visible: the clip above cuts off the
            # bottom corners' rounding, leaving the tab's foot flat on the line.
            path = QPainterPath()
            path.addRoundedRect(rect.adjusted(0, 0, 0, self._RADIUS), self._RADIUS, self._RADIUS)
            p.fillPath(path, fill)
            p.setPen(text)
            p.setFont(self._bold13 if n == self._active else self._bold12)
            p.drawText(rect, Qt.AlignCenter, n)
            edge += w + self._GAP
        p.restore()
        # Square-ended, not a rounded stroke. The selected tab's own colour, so the
        # tab and the line under it read as one piece (primary, except in a theme
        # that swaps the tabs — Terminal's is its green).
        p.fillRect(QRectF(0, foot, width, height - foot), T.theme.color("subtab_active"))


# --------------------------------------------------------------------------- #
#  DropBox
# --------------------------------------------------------------------------- #
class DropBox(QWidget):
    """The primary-bordered drop target: drop a file, double-click, or Browse.
    Drag-over lights it up. `collapse()` — once a file's been picked the
    prompt and border go, leaving just Browse, until the preview carousel
    takes over."""

    fileSelected = Signal(str)

    def __init__(self, prompt="Drag & Drop File Here", parent=None, start_dir=None):
        """`start_dir` is an optional callable returning the folder Browse
        should open in (else the OS's own default — which for an unset start
        directory was this app's working folder)."""
        super().__init__(parent)
        self._start_dir = start_dir
        self._prompt_text = prompt
        self.setAcceptDrops(True)
        self._dragging = False
        self._collapsed = False

        lay = QVBoxLayout(self)
        lay.setAlignment(Qt.AlignCenter)
        scale.spacing(lay, 14)
        self.prompt = ScaledLabel(prompt)
        set_font_px(self.prompt, 14)
        self.prompt.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.prompt)
        self.or_label = ScaledLabel("— or —")
        set_font_px(self.or_label, 14)
        self.or_label.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.or_label)
        self.browse_btn = button("Browse File", width=140)
        self.browse_btn.clicked.connect(self.browse)
        lay.addWidget(self.browse_btn, 0, Qt.AlignCenter)
        T.theme.changed.connect(self.update)

    def _set_prompt(self, text, role=""):
        """The prompt's wording and stylesheet role (`error` is STOP_RED), restyled."""
        self.prompt.setText(text)
        self.prompt.setProperty("role", role)
        restyle(self.prompt)

    def collapse(self):
        self._collapsed = True
        self._set_prompt(self._prompt_text)
        self.prompt.hide()
        self.or_label.hide()
        self.update()

    def show_no_preview(self):
        """A file was picked and is in use, but no preview frames could be made
        for it: the box stays up with its border, saying so in red where the
        drag/drop prompt was ("— or —" goes), and Browse stays."""
        self._collapsed = False
        self._set_prompt("No Preview Available", "error")
        self.prompt.show()
        self.or_label.hide()
        self.update()

    def reset(self):
        """Undo `collapse()` — back to the full drag/drop + Browse prompt,
        exactly as before any file was ever picked (a rejected/unreadable
        import never leaves the box looking like one was)."""
        self._collapsed = False
        self._set_prompt(self._prompt_text)
        self.prompt.show()
        self.or_label.show()
        self.update()

    def browse(self):
        start = self._start_dir() if self._start_dir else ""
        path, _ = QFileDialog.getOpenFileName(self, "Select a File", start, MEDIA_FILTER)
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
        scale.begin(p)
        rect = scale.ref_rect(self).adjusted(1, 1, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(rect, 10, 10)
        if self._dragging:
            p.fillPath(path, T.with_alpha(th.color("primary"), 0.11))
        p.setPen(QPen(th.color("primary_hover" if self._dragging else "primary"), 2))
        p.drawPath(path)


class BorderedFrame(QWidget):
    """The DropBox's rounded border without its drop behaviour — the
    Downloader tab's preview box (primary), and Muxing's track box, which
    passes `color_key="secondary"` for a visually distinct (blue on Lemon)
    border rather than DropBox's own primary one."""

    def __init__(self, parent=None, color_key="primary"):
        super().__init__(parent)
        self._color_key = color_key
        T.theme.changed.connect(self.update)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        scale.begin(p)
        path = QPainterPath()
        path.addRoundedRect(scale.ref_rect(self).adjusted(1, 1, -1, -1), 10, 10)
        p.setPen(QPen(T.theme.color(self._color_key), 2))
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
        scale.grid_spacing(grid, 0, 12)
        self._values = []
        # One shared clock for all rows: whichever value is shortest finishes
        # its scroll first and holds at rest until the slowest one catches
        # up, so all rows sweep and restart in step instead of drifting.
        marquee_group = MarqueeGroup()
        for row, text in enumerate(labels):
            lab = ScaledLabel(text)
            lab.setProperty("role", "muted")
            lab.setStyleSheet("font-weight: bold;")
            scale.fixed(lab, w=72)
            grid.addWidget(lab, row, 0)
            val = MarqueeLabel("—", pixel_size=11, group=marquee_group)
            grid.addWidget(val, row, 1)
            self._values.append(val)
        grid.setColumnStretch(1, 1)

    def set_values(self, rows):
        """`rows` = [(text, color_key_or_None), ...] in label order."""
        for label, (text, color) in zip(self._values, rows):
            label.setText(text)
            label.set_color_key(color or "text")


class _AccentBar(QWidget):
    """A thin accent-coloured bar — the sidebar title's underline, in the
    theme's secondary colour (e.g. Lemon's blue) rather than a text-level
    underline."""

    def __init__(self, width, height=4, parent=None):
        super().__init__(parent)
        scale.fixed(self, width, height)
        T.theme.changed.connect(self.update)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        scale.begin(p)
        p.setPen(Qt.NoPen)
        p.setBrush(T.theme.color("secondary"))
        rect = scale.ref_rect(self)
        r = rect.height() / 2
        p.drawRoundedRect(rect, r, r)


# --------------------------------------------------------------------------- #
#  Sidebar + active-tab pipe
# --------------------------------------------------------------------------- #
class Sidebar(QWidget):
    """Title, logo, the four nav buttons, then Settings + footer pinned to the
    bottom via a layout stretch."""

    navigate = Signal(str)
    WIDTH = 200
    LOGO_SIZE = 170

    def __init__(self, parent=None):
        super().__init__(parent)
        scale.fixed(self, w=self.WIDTH)
        lay = QVBoxLayout(self)
        scale.margins(lay, 0, 24, 0, 10)
        lay.setSpacing(0)

        title = ScaledLabel("LlamaMXD")
        title.setProperty("role", "sidebarTitle")
        title.setAlignment(Qt.AlignCenter)
        lay.addWidget(title)

        title_width = QFontMetricsF(ui_font(36, bold=True, family="Oswald")).horizontalAdvance("LlamaMXD")
        underline = _AccentBar(round(title_width))
        lay.addWidget(underline, 0, Qt.AlignHCenter)
        scale.spacer(lay, 20)

        self.logo = QLabel()
        scale.fixed(self.logo, self.LOGO_SIZE, self.LOGO_SIZE)
        self._load_logo()
        lay.addWidget(self.logo, 0, Qt.AlignHCenter)
        scale.spacer(lay, 10)

        self.buttons = {}
        for name in ("Muxing", "Encoding", "Downloader", "Queue"):
            scale.spacer(lay, 10)
            self._add_nav(lay, name)
            scale.spacer(lay, 10)
        lay.addStretch(1)
        self._add_nav(lay, "Settings")
        scale.spacer(lay, 8)

        footer = ScaledLabel(f"© {datetime.now().year} Yezan Smadi     {VERSION}")
        footer.setProperty("role", "sidebarFooter")
        footer.setAlignment(Qt.AlignCenter)
        lay.addWidget(footer)
        T.theme.changed.connect(self._load_logo)
        scale.changed.connect(self._load_logo)
        T.theme.changed.connect(self.update)

    NAV_BUTTON_WIDTH = 110  # narrower than the sidebar itself, so the pipe's
    # own gap runs wider on both sides — enough to see the RCA cable's black
    # lead trailing out from behind the button before it plugs in.

    def _add_nav(self, lay, name):
        btn = button(name)
        scale.fixed(btn, self.NAV_BUTTON_WIDTH, 28)
        btn.clicked.connect(lambda _=False, n=name: self.navigate.emit(n))
        lay.addWidget(btn, 0, Qt.AlignHCenter)
        self.buttons[name] = btn

    _LOGO_OVERSAMPLE = 4  # rendered above any real screen DPR, then scaled down — never up

    def _load_logo(self):
        renderer = QSvgRenderer(os.path.join(ASSETS, "LlamaMXD-Logo.svg"))
        if not renderer.isValid():
            return
        box = px(self.LOGO_SIZE) * self._LOGO_OVERSAMPLE
        native = renderer.defaultSize()
        k = box / max(native.width(), native.height())
        w, h = native.width() * k, native.height() * k
        x, y = (box - w) / 2, (box - h) / 2
        img = QImage(box, box, QImage.Format_ARGB32_Premultiplied)
        img.fill(Qt.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        renderer.render(p, QRectF(x, y, w, h))
        p.end()

        # Tint the rendered ink to the sidebar's text colour — the same one the
        # title text uses (`sidebar_text`: readable-on-primary, unless the theme
        # names its own) — so the logo goes white on a dark primary (Noir,
        # Vaporwave) or on Funk exactly like the title does, and stays black
        # elsewhere. SourceIn keeps the source's alpha (the art's own
        # anti-aliased shape) and replaces only its RGB.
        tint = QPainter(img)
        tint.setCompositionMode(QPainter.CompositionMode_SourceIn)
        tint.fillRect(img.rect(), T.theme.color("sidebar_text"))
        tint.end()

        pix = QPixmap.fromImage(img)
        pix.setDevicePixelRatio(self._LOGO_OVERSAMPLE)
        self.logo.setPixmap(pix)

    def paintEvent(self, _event):
        QPainter(self).fillRect(self.rect(), T.theme.color("primary"))


_CABLE_SVG = os.path.join(ASSETS, "RCA Cable Yellow.svg")
_CABLE_OVERSAMPLE = 4  # rendered above any real screen DPR, then scaled down — never up
_cable_base_cache = {}
_cable_pixmap_cache = {}


def _cable_base_image():
    """The RCA cable art rendered once at high resolution and cropped to
    its own drawn content — the SVG's declared viewBox (509 wide) is
    nearly 3x wider than the plug it actually draws (~172 units, the rest
    blank margin), which would otherwise squash the rotated art into one
    end of its frame instead of filling it edge to edge."""
    cached = _cable_base_cache.get("img")
    if cached is not None:
        return cached
    renderer = QSvgRenderer(_CABLE_SVG)
    if not renderer.isValid():
        return None
    native = renderer.defaultSize()
    k = 3
    w, h = round(native.width() * k), round(native.height() * k)
    img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    renderer.render(p, QRectF(0, 0, w, h))
    p.end()

    stride = img.bytesPerLine()
    raw = np.frombuffer(img.constBits(), dtype=np.uint8, count=h * stride).reshape(h, stride)[:, : w * 4]
    raw = raw.reshape(h, w, 4)
    alpha = raw[:, :, 3]
    cols = np.where(alpha.any(axis=0))[0]
    rows = np.where(alpha.any(axis=1))[0]
    if len(cols) and len(rows):
        img = img.copy(int(cols[0]), int(rows[0]), int(cols[-1] - cols[0] + 1), int(rows[-1] - rows[0] + 1))
    _cable_base_cache["img"] = img
    return img


def _cable_pixmap(height):
    """The cropped cable art (above), rotated 90° clockwise so the grey
    plug collar — the top of the source art, at low y — lands on the
    *right* (toward the tab frame it plugs into) and the trailing cable —
    the bottom, at high y — lands on the *left* (toward the sidebar button
    it slides out of). Rasterized `height` px tall (oversampled the same
    way the sidebar logo is) and cached by that height, since every nav
    button's pipe wants the same size."""
    cached = _cable_pixmap_cache.get(height)
    if cached is not None:
        return cached
    base = _cable_base_image()
    if base is None or base.isNull():
        return None
    w0 = height * _CABLE_OVERSAMPLE
    h0 = w0 * base.height() / base.width()
    scaled = base.scaled(round(w0), round(h0), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    pix = QPixmap.fromImage(scaled).transformed(QTransform().rotate(90), Qt.SmoothTransformation)
    pix.setDevicePixelRatio(_CABLE_OVERSAMPLE)
    _cable_pixmap_cache[height] = pix
    return pix


class _TabPipe(QWidget):
    """One nav button's own pipe: the RCA cable art sliding out of the
    button and toward the tab frame. *extension* (0 = hidden, flush with
    the button's own edge; 1 = plugged in) slides the cable horizontally —
    at 1 it's pushed in just far enough that the long thin grey pin (the
    plug's actual contact, see `_cable_pixmap`) lands entirely past the
    frame's edge, hidden behind it the way a real plug's pin disappears
    into a jack — but *not* the wider grey base collar right behind it,
    which stays visible sitting proud of the frame along with the yellow
    shell and the cable trailing back off toward the button. Independent
    per button so an outgoing and an incoming pipe can animate at once
    instead of one bar jumping between button positions.

    Replaces an earlier abstract pill-plus-pin shape meant to *suggest* a
    jack plug in the round-rectangle language the rest of the UI uses —
    dropped once a real cable graphic (`assets/RCA Cable Yellow.svg`) made
    that abstraction unnecessary."""

    # The art's own long thin pin (`assets/RCA Cable Yellow.svg`'s first
    # grey path) runs tip-to-142.23 out of the full 825.37 length; its
    # wider base collar (the second grey path, 146.9-171.22) is deliberately
    # excluded here so insertion stops with the base still showing.
    _PIN_FRAC = 142.23 / 825.37
    _MARGIN = 6  # vertical breathing room within the button's own row height

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._extension = 0.0
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(220)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(self._set_extension)
        T.theme.changed.connect(self.update)

    def _set_extension(self, value):
        self._extension = value
        self.update()

    def set_active(self, active, animate=True):
        target = 1.0 if active else 0.0
        self._anim.stop()
        if animate:
            self._anim.setStartValue(self._extension)
            self._anim.setEndValue(target)
            self._anim.start()
        else:
            self._set_extension(target)

    def paintEvent(self, _event):
        if self._extension <= 0:
            return
        pix = _cable_pixmap(max(1, self.height() - px(self._MARGIN)))
        if pix is None:
            return
        dpr = pix.devicePixelRatio()
        img_w, img_h = pix.width() / dpr, pix.height() / dpr

        # Hidden: the tip sits flush with local x=0 (the button's own
        # edge), so nothing is visible. Shown: the tip has crossed past
        # this widget's own right edge (the frame's edge) by exactly the
        # long pin's own width — the base collar right behind it stops
        # short of the edge and stays visible.
        hidden_x = -img_w
        shown_x = self.width() - img_w * (1 - self._PIN_FRAC)
        x = hidden_x + (shown_x - hidden_x) * self._extension
        y = (self.height() - img_h) / 2

        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.drawPixmap(QPointF(x, y), pix)


class TabIndicator(QWidget):
    """Owns one independently-animated `_TabPipe` per nav button. Selecting
    a tab grows that button's own pipe out of it and into the tab frame
    while, at the same time, the previously-selected button's pipe shrinks
    back into its own button — two motions at once, rather than one shared
    bar jumping between button positions like the pipe used to. No longer
    paints anything of its own — an earlier version also drew a static
    `primary` notch per button, always visible regardless of selection, but
    that's being replaced with a different idea."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._buttons = {}
        self._pipes = {}
        self._active = None
        self._frame_left = 0
        T.theme.changed.connect(self.update)

    def set_active(self, name, buttons, frame_left, animate=True):
        """(Re)lays out every button's pipe geometry — cheap, and needed
        since a button's position is only final once the window's actually
        shown — then animates the outgoing pipe shut and the incoming one
        open together."""
        self._buttons = buttons
        self._frame_left = frame_left
        parent = self.parentWidget()
        self.setGeometry(0, 0, parent.width(), parent.height())
        for btn_name, btn in buttons.items():
            top_left = btn.mapTo(parent, btn.rect().topLeft())
            x = top_left.x() + btn.width()
            pipe = self._pipes.get(btn_name)
            if pipe is None:
                pipe = _TabPipe(self)
                # A widget created after its parent is already shown doesn't
                # inherit that visibility automatically — without this it
                # silently never paints at all, notch or full pipe alike.
                pipe.show()
                self._pipes[btn_name] = pipe
            pipe.setGeometry(x, top_left.y(), max(1, frame_left - x), btn.height())
        self._active = name
        for btn_name, pipe in self._pipes.items():
            pipe.set_active(btn_name == name, animate=animate)
        self.show()
        self.raise_()
        for pipe in self._pipes.values():
            pipe.raise_()
        self.update()

