"""Icônes vectorielles dans le style « monoline » d'Office.

Toutes les icônes sont dessinées sur une grille de 32 unités puis rendues à la
taille exacte demandée (16, 20, 24, 32 px…) avec accrochage des traits aux
pixels : traits d'un pixel nets, comme les icônes du ruban de Visio. Aucune
image de Microsoft n'est utilisée ; une variante monochrome (blanche) sert à la
barre de titre.
"""

from __future__ import annotations

import math

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (QBrush, QColor, QFont, QIcon, QLinearGradient, QPainter, QPainterPath,
                         QPen, QPixmap, QPolygonF, QTransform)

from .units import THEMES

INK = QColor("#444444")
INK2 = QColor("#8a8886")
PAPER = QColor("#ffffff")
BLUE = QColor("#2771d3")
BLUE_L = QColor("#c9ddf5")
VBLUE = QColor("#3955a3")
ORANGE = QColor("#e1702a")
ORANGE_L = QColor("#fbd9c2")
YELLOW = QColor("#f0b414")
YELLOW_L = QColor("#fdecb6")
GREEN = QColor("#2b8a3e")
GREEN_L = QColor("#cdebd2")
RED = QColor("#d13438")
PURPLE = QColor("#7c5cc4")
TAN = QColor("#e8d2b0")
_LIGHT_FILLS = {"#ffffff", "#c9ddf5", "#fbd9c2", "#fdecb6", "#cdebd2", "#e8d2b0", "#3b3a39", "#284a7a"}

_cache: dict[tuple, QIcon] = {}
_dark = False


def set_dark(dark: bool) -> None:
    global _dark, INK, INK2, PAPER, BLUE_L
    if dark == _dark:
        return
    _dark = dark
    INK = QColor("#d6d6d6" if dark else "#444444")
    INK2 = QColor("#a19f9d" if dark else "#8a8886")
    PAPER = QColor("#3b3a39" if dark else "#ffffff")
    BLUE_L = QColor("#284a7a" if dark else "#c9ddf5")
    _cache.clear()


class _C:
    """Pinceau sur grille 32×32 avec accrochage aux pixels."""

    def __init__(self, p: QPainter, device: int, dpr: float, mono: QColor | None):
        self.p = p
        self.k = device / 32.0
        self.lw = float(max(1, round(dpr)))
        self.mono = mono

    # --------------------------------------------------------------- couleurs
    def col(self, c):
        if c is None:
            return None
        if self.mono is not None:
            if c.name() in _LIGHT_FILLS and c.alpha() == 255:
                return None
            out = QColor(self.mono)
            out.setAlpha(c.alpha())
            return out
        return c

    def _pen(self, color, w=1.0, style=Qt.PenStyle.SolidLine):
        c = self.col(color)
        if c is None:
            self.p.setPen(Qt.PenStyle.NoPen)
            return False
        pen = QPen(c, self.lw * w, style)
        pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
        pen.setCapStyle(Qt.PenCapStyle.FlatCap)
        self.p.setPen(pen)
        return True

    def _brush(self, color):
        c = self.col(color)
        self.p.setBrush(QBrush(c) if c is not None else Qt.BrushStyle.NoBrush)

    # --------------------------------------------------------------- accrochage
    def s(self, v: float, w: float = 1.0) -> float:
        px = self.lw * w
        d = v * self.k
        if round(px) % 2 == 1:
            return math.floor(d) + 0.5
        return float(round(d))

    def r(self, v: float) -> float:
        return float(round(v * self.k))

    # --------------------------------------------------------------- primitives
    def rect(self, x, y, w, h, fill=None, stroke=None, radius=0.0, sw=1.0):
        left, top, right, bottom = self.r(x), self.r(y), self.r(x + w), self.r(y + h)
        if fill is not None and self.col(fill) is not None:
            self.p.setPen(Qt.PenStyle.NoPen)
            self._brush(fill)
            if radius:
                self.p.drawRoundedRect(QRectF(left, top, right - left, bottom - top),
                                       radius * self.k, radius * self.k)
            else:
                self.p.drawRect(QRectF(left, top, right - left, bottom - top))
        if stroke is not None and self._pen(stroke, sw):
            half = self.lw * sw / 2
            self.p.setBrush(Qt.BrushStyle.NoBrush)
            rr = QRectF(left + half, top + half, right - left - 2 * half, bottom - top - 2 * half)
            if radius:
                self.p.drawRoundedRect(rr, radius * self.k, radius * self.k)
            else:
                self.p.drawRect(rr)
        return self

    def line(self, x1, y1, x2, y2, color=None, w=1.0, style=Qt.PenStyle.SolidLine):
        if not self._pen(INK if color is None else color, w, style):
            return self
        if abs(x1 - x2) < 1e-6:
            x = self.s(x1, w)
            self.p.drawLine(QPointF(x, self.r(y1)), QPointF(x, self.r(y2)))
        elif abs(y1 - y2) < 1e-6:
            y = self.s(y1, w)
            self.p.drawLine(QPointF(self.r(x1), y), QPointF(self.r(x2), y))
        else:
            self.p.drawLine(QPointF(x1 * self.k, y1 * self.k), QPointF(x2 * self.k, y2 * self.k))
        return self

    def poly(self, pts, fill=None, stroke=None, sw=1.0, closed=True):
        q = QPolygonF([QPointF(x * self.k, y * self.k) for x, y in pts])
        self._brush(fill)
        if stroke is None or not self._pen(stroke, sw):
            self.p.setPen(Qt.PenStyle.NoPen)
        if closed:
            self.p.drawPolygon(q)
        else:
            self.p.setBrush(Qt.BrushStyle.NoBrush)
            self.p.drawPolyline(q)
        return self

    def ellipse(self, cx, cy, rx, ry=None, fill=None, stroke=None, sw=1.0):
        ry = rx if ry is None else ry
        self._brush(fill)
        if stroke is None or not self._pen(stroke, sw):
            self.p.setPen(Qt.PenStyle.NoPen)
        self.p.drawEllipse(QPointF(cx * self.k, cy * self.k), rx * self.k, ry * self.k)
        return self

    def path(self, path: QPainterPath, fill=None, stroke=None, sw=1.0):
        t = QTransform.fromScale(self.k, self.k)
        self._brush(fill)
        if stroke is None or not self._pen(stroke, sw):
            self.p.setPen(Qt.PenStyle.NoPen)
        self.p.drawPath(t.map(path))
        return self

    def text(self, x, y, w, h, s, size, bold=False, italic=False, underline=False, strike=False,
             color=None, align=Qt.AlignmentFlag.AlignCenter, serif=False):
        f = QFont("DejaVu Serif" if serif else "Inter")
        f.setPixelSize(max(1, round(size * self.k)))
        f.setBold(bold)
        f.setItalic(italic)
        f.setUnderline(underline)
        f.setStrikeOut(strike)
        self.p.setFont(f)
        c = self.col(INK if color is None else color)
        if c is None:
            return self
        self.p.setPen(c)
        self.p.drawText(QRectF(x * self.k, y * self.k, w * self.k, h * self.k), align, s)
        return self

    def head(self, tip, direction, size=4.0, color=None):
        dx, dy = direction
        n = math.hypot(dx, dy) or 1.0
        dx, dy = dx / n, dy / n
        bx, by = tip[0] - dx * size, tip[1] - dy * size
        return self.poly([tip, (bx - dy * size * 0.75, by + dx * size * 0.75),
                          (bx + dy * size * 0.75, by - dx * size * 0.75)],
                         fill=INK if color is None else color, stroke=None)


# =========================================================================== motifs communs

def _page(c: _C, x=7, y=3, w=18, h=26, fold=6, fill=None):
    fill = PAPER if fill is None else fill
    path = QPainterPath()
    path.moveTo(x + 0.5, y + 0.5)
    path.lineTo(x + w - fold - 0.5, y + 0.5)
    path.lineTo(x + w - 0.5, y + fold + 0.5)
    path.lineTo(x + w - 0.5, y + h - 0.5)
    path.lineTo(x + 0.5, y + h - 0.5)
    path.closeSubpath()
    c.path(path, fill=fill, stroke=INK)
    c.poly([(x + w - fold - 0.5, y + 0.5), (x + w - fold - 0.5, y + fold + 0.5), (x + w - 0.5, y + fold + 0.5)],
           fill=None, stroke=INK, closed=False)


def _plus_badge(c: _C, cx=24, cy=24, color=None):
    c.ellipse(cx, cy, 6, fill=GREEN if color is None else color, stroke=None)
    if c.mono is None:
        c.line(cx - 3, cy, cx + 3, cy, QColor("#ffffff"), 2)
        c.line(cx, cy - 3, cx, cy + 3, QColor("#ffffff"), 2)


def _x_badge(c: _C, cx=24, cy=24):
    c.ellipse(cx, cy, 6, fill=RED, stroke=None)
    if c.mono is None:
        c.line(cx - 2.6, cy - 2.6, cx + 2.6, cy + 2.6, QColor("#ffffff"), 2)
        c.line(cx + 2.6, cy - 2.6, cx - 2.6, cy + 2.6, QColor("#ffffff"), 2)


def _magnifier(c: _C, cx=13, cy=13, r=8):
    c.ellipse(cx, cy, r, fill=PAPER, stroke=INK, sw=1.5)
    c.line(cx + r * 0.72, cy + r * 0.72, 28, 28, INK, 3)


def _lines(c: _C, align: str, justify=False):
    widths = (22, 14, 22, 18, 12)
    for i, w in enumerate(widths):
        if justify and i < 4:
            w = 22
        y = 7 + i * 4.5
        x = {"left": 5, "center": 16 - w / 2, "right": 27 - w}[align]
        c.line(x, y, x + w, y, INK, 1)


def _shape_pair(c: _C):
    c.rect(4, 5, 12, 10, fill=BLUE_L, stroke=BLUE)
    c.ellipse(22, 22, 6, fill=ORANGE_L, stroke=ORANGE)


DRAW: dict = {}


def _reg(*names):
    def deco(fn):
        for n in names:
            DRAW[n] = fn
        return fn
    return deco


# =========================================================================== Presse-papiers
@_reg("paste")
def _paste(c):
    c.rect(4, 5, 18, 24, fill=TAN, stroke=INK)
    c.rect(9, 3, 8, 5, fill=INK2, stroke=INK)
    _page(c, 13, 11, 16, 19, 5)
    for y in (19, 22, 25):
        c.line(16, y, 26, y, BLUE)


@_reg("cut")
def _cut(c):
    c.poly([(11, 3), (13.5, 3), (19, 19), (17, 20)], fill=INK2, stroke=INK)
    c.poly([(21, 3), (18.5, 3), (13, 19), (15, 20)], fill=INK2, stroke=INK)
    c.ellipse(11, 24, 4.5, fill=None, stroke=BLUE, sw=2)
    c.ellipse(21, 24, 4.5, fill=None, stroke=BLUE, sw=2)


@_reg("copy")
def _copy(c):
    _page(c, 4, 3, 16, 20, 5)
    _page(c, 12, 9, 16, 20, 5)
    for y in (17, 20, 23):
        c.line(15, y, 25, y, BLUE)


@_reg("format_painter")
def _format_painter(c):
    c.rect(5, 4, 20, 9, fill=YELLOW, stroke=INK, radius=1.5)
    c.line(25, 8, 28, 8, INK).line(28, 8, 28, 16, INK).line(16, 16, 28, 16, INK)
    c.line(16, 16, 16, 19, INK)
    c.rect(13, 19, 6, 10, fill=INK2, stroke=INK, radius=1)


# =========================================================================== Police
@_reg("font_grow")
def _font_grow(c):
    c.text(1, 6, 22, 24, "A", 22, True)
    c.poly([(21, 11), (29, 11), (25, 5)], fill=BLUE, stroke=None)


@_reg("font_shrink")
def _font_shrink(c):
    c.text(2, 10, 20, 20, "A", 16, True)
    c.poly([(21, 5), (29, 5), (25, 11)], fill=BLUE, stroke=None)


@_reg("clear_format")
def _clear_format(c):
    c.text(1, 3, 22, 24, "A", 22, True)
    c.poly([(16, 24), (23, 17), (29, 23), (22, 30)], fill=QColor("#f4a6b8"), stroke=INK)
    c.line(19.5, 20.5, 25.5, 26.5, INK)


@_reg("bold")
def _bold(c):
    c.text(4, 3, 24, 26, "G", 22, True)


@_reg("italic")
def _italic(c):
    c.text(4, 3, 24, 26, "I", 22, False, italic=True, serif=True)


@_reg("underline")
def _underline(c):
    c.text(4, 1, 24, 24, "S", 21, False)
    c.line(8, 27, 24, 27, INK, 1.5)


@_reg("strike")
def _strike(c):
    c.text(1, 4, 30, 24, "abc", 15, False)
    c.line(3, 17, 29, 17, RED, 1.5)


@_reg("case")
def _case(c):
    c.text(1, 4, 30, 24, "Aa", 18, False)


@_reg("font_color", "text_color", "text")
def _font_color(c):
    c.text(4, 1, 24, 24, "A", 21, True)


@_reg("align_text_left")
def _atl(c):
    _lines(c, "left")


@_reg("align_text_center")
def _atc(c):
    _lines(c, "center")


@_reg("align_text_right")
def _atr(c):
    _lines(c, "right")


@_reg("justify")
def _atj(c):
    _lines(c, "left", justify=True)


def _valign(c, pos):
    c.rect(4, 4, 24, 24, fill=PAPER, stroke=INK2)
    y = {"top": 9, "middle": 15, "bottom": 21}[pos]
    c.line(9, y, 23, y, BLUE, 1.5).line(11, y + 3.5, 21, y + 3.5, BLUE, 1.5)


for _p in ("top", "middle", "bottom"):
    DRAW[f"valign_{_p}"] = (lambda p: lambda c: _valign(c, p))(_p)


@_reg("bullets")
def _bullets(c):
    for y in (8, 16, 24):
        c.ellipse(7, y, 2, fill=BLUE, stroke=None)
        c.line(12, y, 27, y, INK)


# =========================================================================== Outils
@_reg("pointer", "tool_select")
def _pointer(c):
    c.poly([(10, 3.5), (10, 25), (15, 20.5), (19, 28.5), (22.5, 27), (18.5, 19), (25, 19)],
           fill=PAPER, stroke=INK, sw=1.2)


@_reg("connector", "tool_connector")
def _connector(c):
    c.rect(2, 3, 12, 9, fill=BLUE_L, stroke=BLUE)
    c.rect(18, 20, 12, 9, fill=BLUE_L, stroke=BLUE)
    c.line(14, 7.5, 9, 7.5, INK)
    c.line(9, 7.5, 9, 24.5, INK)
    c.line(9, 24.5, 14, 24.5, INK)
    c.head((18, 24.5), (1, 0), 4, INK)


@_reg("tool_text", "text_tool")
def _text_tool(c):
    c.text(1, 3, 22, 26, "A", 24, False)
    c.line(25, 6, 25, 26, INK).line(22, 6, 28, 6, INK).line(22, 26, 28, 26, INK)


@_reg("line", "tool_line")
def _line(c):
    c.line(6, 26, 26, 6, INK, 1.5)
    c.rect(3, 23, 6, 6, fill=PAPER, stroke=INK)
    c.rect(23, 3, 6, 6, fill=PAPER, stroke=INK)


@_reg("rect_tool", "tool_rectangle")
def _rect_tool(c):
    c.rect(3, 7, 26, 18, fill=PAPER, stroke=INK)


@_reg("ellipse_tool", "tool_ellipse")
def _ellipse_tool(c):
    c.ellipse(16, 16, 13, 9.5, fill=PAPER, stroke=INK)


@_reg("pen_tool", "tool_pen")
def _pen_tool(c):
    c.line(7, 24, 23, 8, INK, 3)
    c.poly([(5, 27), (7, 21), (11, 25)], fill=YELLOW, stroke=INK)
    c.line(20, 7, 24, 11, BLUE, 2)


@_reg("drawing_tools")
def _drawing_tools(c):
    c.rect(3, 4, 15, 12, fill=PAPER, stroke=INK)
    c.ellipse(21, 21, 8, 7, fill=BLUE_L, stroke=BLUE)
    c.line(4, 28, 13, 19, INK)


# =========================================================================== Styles de forme
@_reg("fill")
def _fill(c):
    c.poly([(5, 15), (14, 6), (25, 17), (16, 26)], fill=PAPER, stroke=INK)
    c.poly([(6.5, 15.5), (24, 15.5), (16, 24.5)], fill=BLUE, stroke=None)
    c.line(14, 6, 10, 2, INK)
    c.ellipse(27.5, 23, 2.2, 3.2, fill=BLUE, stroke=None)


@_reg("line_color")
def _line_color(c):
    c.poly([(20, 4), (27, 11), (12, 26), (5, 27), (6, 20)], fill=YELLOW, stroke=INK)
    c.line(17, 7, 24, 14, INK)
    c.poly([(6, 20), (12, 26), (5, 27)], fill=INK2, stroke=None)


@_reg("effects")
def _effects(c):
    c.rect(9, 9, 18, 18, fill=QColor(0, 0, 0, 70), stroke=None, radius=2)
    c.rect(5, 5, 18, 18, fill=BLUE, stroke=None, radius=2)
    c.ellipse(26, 6, 1.5, fill=YELLOW, stroke=None)
    c.line(26, 1, 26, 3.5, YELLOW).line(26, 8.5, 26, 11, YELLOW).line(21, 6, 23.5, 6, YELLOW)


@_reg("styles", "quick_styles")
def _styles(c):
    c.rect(3, 3, 12, 12, fill=BLUE, stroke=None)
    c.rect(17, 3, 12, 12, fill=ORANGE, stroke=None)
    c.rect(3, 17, 12, 12, fill=GREEN, stroke=None)
    c.rect(17, 17, 12, 12, fill=PAPER, stroke=BLUE)


@_reg("line_weight")
def _line_weight(c):
    for i, w in enumerate((1, 2, 3, 4)):
        c.line(4, 6 + i * 6.5, 28, 6 + i * 6.5, INK, w)


@_reg("line_dash")
def _line_dash(c):
    c.line(4, 8, 28, 8, INK, 2)
    c.line(4, 16, 28, 16, INK, 2, Qt.PenStyle.DashLine)
    c.line(4, 24, 28, 24, INK, 2, Qt.PenStyle.DotLine)


@_reg("arrows")
def _arrows(c):
    c.line(4, 10, 24, 10, INK)
    c.head((29, 10), (1, 0), 5, INK)
    c.line(8, 22, 28, 22, INK)
    c.head((3, 22), (-1, 0), 5, INK)


@_reg("shadow")
def _shadow(c):
    c.rect(9, 9, 19, 19, fill=QColor(0, 0, 0, 90), stroke=None)
    c.rect(4, 4, 19, 19, fill=BLUE_L, stroke=BLUE)


@_reg("glow")
def _glow(c):
    for i, a in enumerate((40, 70, 110)):
        r = 13 - i * 2
        c.rect(16 - r, 16 - r, 2 * r, 2 * r, fill=QColor(240, 180, 20, a), stroke=None, radius=4)
    c.rect(9, 9, 14, 14, fill=BLUE, stroke=None, radius=1)


@_reg("soft_edges")
def _soft_edges(c):
    for i, a in enumerate((30, 70, 140, 255)):
        r = 12 - i * 1.6
        col = QColor(BLUE)
        col.setAlpha(a)
        c.rect(16 - r, 16 - r, 2 * r, 2 * r, fill=col, stroke=None, radius=2)


# =========================================================================== Organiser
def _align_obj(c, mode):
    if mode in ("left", "center", "right"):
        x = {"left": 4, "center": 16, "right": 28}[mode]
        for y, w in ((5, 20), (17, 12)):
            left = {"left": 4, "center": 16 - w / 2, "right": 28 - w}[mode]
            c.rect(left, y, w, 9, fill=BLUE_L, stroke=BLUE)
        c.line(x, 2, x, 30, INK)
    else:
        y = {"top": 4, "middle": 16, "bottom": 28}[mode]
        for x, h in ((5, 20), (17, 12)):
            top = {"top": 4, "middle": 16 - h / 2, "bottom": 28 - h}[mode]
            c.rect(x, top, 9, h, fill=BLUE_L, stroke=BLUE)
        c.line(2, y, 30, y, INK)


for _m in ("left", "center", "right", "top", "middle", "bottom"):
    DRAW[f"align_{_m}"] = (lambda m: lambda c: _align_obj(c, m))(_m)
DRAW["align"] = DRAW["align_center"]


@_reg("position", "distribute_h")
def _distribute_h(c):
    for x in (3, 13, 23):
        c.rect(x, 7, 7, 14, fill=BLUE_L, stroke=BLUE)
    c.line(3, 26, 29, 26, INK)
    c.line(3, 24, 3, 28, INK).line(29, 24, 29, 28, INK)


@_reg("distribute_v")
def _distribute_v(c):
    for y in (3, 13, 23):
        c.rect(9, y, 14, 7, fill=BLUE_L, stroke=BLUE)
    c.line(28, 3, 28, 29, INK)


@_reg("front")
def _front(c):
    c.rect(3, 3, 14, 14, fill=PAPER, stroke=INK)
    c.rect(15, 15, 14, 14, fill=PAPER, stroke=INK)
    c.rect(9, 9, 14, 14, fill=BLUE, stroke=BLUE)


@_reg("back")
def _back(c):
    c.rect(9, 9, 14, 14, fill=BLUE, stroke=BLUE)
    c.rect(3, 3, 14, 14, fill=PAPER, stroke=INK)
    c.rect(15, 15, 14, 14, fill=PAPER, stroke=INK)


@_reg("forward")
def _forward(c):
    c.rect(12, 4, 16, 14, fill=PAPER, stroke=INK)
    c.rect(4, 14, 16, 14, fill=BLUE, stroke=BLUE)


@_reg("backward")
def _backward(c):
    c.rect(4, 14, 16, 14, fill=BLUE, stroke=BLUE)
    c.rect(12, 4, 16, 14, fill=PAPER, stroke=INK)


@_reg("group")
def _group(c):
    c.rect(2, 2, 28, 28, fill=None, stroke=INK2)
    for x, y in ((2, 2), (28, 2), (2, 28), (28, 28)):
        c.rect(x - 1.5, y - 1.5, 3, 3, fill=PAPER, stroke=INK)
    _shape_pair(c)


@_reg("ungroup")
def _ungroup(c):
    _shape_pair(c)
    c.rect(2, 2, 28, 28, fill=None, stroke=INK2)
    c.line(2, 16, 30, 16, PAPER, 3)


@_reg("rotate_right", "rotate")
def _rotate_right(c):
    c.rect(4, 12, 14, 16, fill=BLUE_L, stroke=BLUE)
    path = QPainterPath()
    path.moveTo(12, 8)
    path.cubicTo(18, 2, 27, 5, 27, 13)
    c.path(path, None, INK, 1.5)
    c.head((27, 18), (0, 1), 4.5, INK)


@_reg("rotate_left")
def _rotate_left(c):
    c.rect(14, 12, 14, 16, fill=BLUE_L, stroke=BLUE)
    path = QPainterPath()
    path.moveTo(20, 8)
    path.cubicTo(14, 2, 5, 5, 5, 13)
    c.path(path, None, INK, 1.5)
    c.head((5, 18), (0, 1), 4.5, INK)


@_reg("flip_h")
def _flip_h(c):
    c.line(16, 2, 16, 30, INK, 1, Qt.PenStyle.DashLine)
    c.poly([(13, 6), (13, 26), (3, 26)], fill=BLUE, stroke=BLUE)
    c.poly([(19, 6), (19, 26), (29, 26)], fill=PAPER, stroke=INK)


@_reg("flip_v")
def _flip_v(c):
    c.line(2, 16, 30, 16, INK, 1, Qt.PenStyle.DashLine)
    c.poly([(6, 13), (26, 13), (26, 3)], fill=BLUE, stroke=BLUE)
    c.poly([(6, 19), (26, 19), (26, 29)], fill=PAPER, stroke=INK)


# =========================================================================== Modification
@_reg("find", "search")
def _find(c):
    _magnifier(c)


@_reg("replace")
def _replace(c):
    c.text(1, 1, 16, 16, "ab", 11)
    c.text(14, 15, 18, 16, "ac", 11, color=BLUE)
    c.line(9, 16, 9, 22, INK).line(9, 22, 13, 22, INK)
    c.head((16, 22), (1, 0), 3.5, INK)


@_reg("select")
def _select(c):
    c.rect(2, 2, 24, 20, fill=None, stroke=INK2)
    c.poly([(16, 12), (16, 29), (20, 25), (23, 30.5), (25.5, 29.5), (22.5, 24), (28, 24)],
           fill=PAPER, stroke=INK)


@_reg("select_all")
def _select_all(c):
    for a, b, cc, d in ((2, 2, 30, 2), (2, 30, 30, 30), (2, 2, 2, 30), (30, 2, 30, 30)):
        c.line(a, b, cc, d, INK2, 1, Qt.PenStyle.DashLine)
    _shape_pair(c)


@_reg("change_shape")
def _change_shape(c):
    c.rect(3, 4, 12, 10, fill=BLUE_L, stroke=BLUE)
    c.ellipse(22, 22, 7, fill=ORANGE_L, stroke=ORANGE)
    path = QPainterPath()
    path.moveTo(19, 7)
    path.cubicTo(24, 7, 27, 9, 27, 13)
    c.path(path, None, INK, 1.2)
    c.head((27, 16), (0, 1), 3.5, INK)
    path = QPainterPath()
    path.moveTo(13, 26)
    path.cubicTo(8, 26, 5, 23, 5, 20)
    c.path(path, None, INK, 1.2)
    c.head((5, 17), (0, -1), 3.5, INK)


@_reg("layers")
def _layers(c):
    for i, (col, fill) in enumerate(((INK2, PAPER), (BLUE, BLUE_L), (BLUE, BLUE))):
        y = 20 - i * 6
        c.poly([(16, y - 6), (29, y), (16, y + 6), (3, y)], fill=fill, stroke=col)


@_reg("delete")
def _delete(c):
    c.line(7, 7, 25, 25, RED, 2.5).line(25, 7, 7, 25, RED, 2.5)


# =========================================================================== Insertion
@_reg("page_add", "new")
def _page_add(c):
    _page(c, 5, 3, 18, 25)
    _plus_badge(c, 23, 23)


@_reg("page_dup", "duplicate")
def _page_dup(c):
    _page(c, 3, 2, 16, 21, 5)
    _page(c, 12, 9, 16, 21, 5)


@_reg("page_del")
def _page_del(c):
    _page(c, 5, 3, 18, 25)
    _x_badge(c, 23, 23)


@_reg("page_background")
def _page_background(c):
    _page(c, 9, 2, 18, 22, 5, fill=BLUE_L)
    _page(c, 4, 8, 18, 22, 5)


def _op_pair():
    a = QPainterPath()
    a.addRect(QRectF(4.5, 6.5, 15, 15))
    b = QPainterPath()
    b.addEllipse(QPointF(20, 18), 8, 8)
    return a, b


@_reg("shape_union", "shape_ops")
def _shape_union(c):
    a, b = _op_pair()
    c.path(a.united(b), fill=BLUE_L, stroke=BLUE)


@_reg("shape_combine")
def _shape_combine(c):
    a, b = _op_pair()
    p = QPainterPath(a)
    p.addPath(b)
    p.setFillRule(Qt.FillRule.OddEvenFill)
    c.path(p, fill=BLUE_L, stroke=BLUE)


@_reg("shape_fragment")
def _shape_fragment(c):
    a, b = _op_pair()
    c.path(a.subtracted(b), fill=BLUE_L, stroke=BLUE)
    c.path(a.intersected(b), fill=ORANGE_L, stroke=ORANGE)
    c.path(b.subtracted(a), fill=YELLOW_L, stroke=YELLOW)


@_reg("shape_intersect")
def _shape_intersect(c):
    a, b = _op_pair()
    c.path(a, stroke=INK2)
    c.path(b, stroke=INK2)
    c.path(a.intersected(b), fill=BLUE_L, stroke=BLUE)


@_reg("shape_subtract")
def _shape_subtract(c):
    a, b = _op_pair()
    c.path(b.subtracted(a), stroke=INK2)
    c.path(a.subtracted(b), fill=BLUE_L, stroke=BLUE)


@_reg("field")
def _field(c):
    c.rect(3, 8, 26, 16, fill=PAPER, stroke=INK)
    c.text(3, 8, 26, 16, "{ }", 11, bold=True, color=BLUE)


@_reg("auto_space")
def _auto_space(c):
    for x in (3, 13, 23):
        c.rect(x, 9, 6, 6, fill=BLUE_L, stroke=BLUE)
    c.line(9, 12, 13, 12, INK).line(19, 12, 23, 12, INK)
    c.line(3, 24, 29, 24, INK2)
    c.head((29, 24), (1, 0), 3, INK2)


@_reg("export_html")
def _export_html(c):
    c.rect(3, 5, 26, 22, fill=PAPER, stroke=INK)
    c.rect(3, 5, 26, 5, fill=BLUE_L, stroke=INK)
    c.ellipse(16, 19, 5, fill=None, stroke=BLUE)
    c.line(11, 19, 21, 19, BLUE).line(16, 14, 16, 24, BLUE)


@_reg("page_rename", "edit_text")
def _page_rename(c):
    _page(c, 4, 3, 18, 25)
    c.poly([(26, 8), (30, 12), (19, 23), (14, 24), (15, 19)], fill=YELLOW, stroke=INK)


@_reg("background_page")
def _background_page(c):
    _page(c, 9, 2, 18, 24, fill=BLUE_L)
    _page(c, 4, 6, 18, 24)


@_reg("image")
def _image(c):
    c.rect(2, 5, 28, 22, fill=PAPER, stroke=INK)
    c.ellipse(10, 12, 3, fill=YELLOW, stroke=None)
    c.poly([(3, 26), (12, 16), (18, 22), (22, 18), (29, 26)], fill=GREEN, stroke=None)


@_reg("container")
def _container(c):
    c.rect(2, 4, 28, 24, fill=PAPER, stroke=BLUE)
    c.rect(2, 4, 28, 7, fill=BLUE, stroke=BLUE)
    c.rect(7, 15, 8, 8, fill=BLUE_L, stroke=BLUE)
    c.rect(18, 15, 8, 8, fill=BLUE_L, stroke=BLUE)


@_reg("callout")
def _callout(c):
    path = QPainterPath()
    path.addRoundedRect(QRectF(2.5, 3.5, 27, 18), 3, 3)
    tail = QPainterPath()
    tail.addPolygon(QPolygonF([QPointF(8, 20), QPointF(6, 29), QPointF(15, 20)]))
    c.path(path.united(tail).simplified(), fill=PAPER, stroke=INK)
    c.line(8, 10, 24, 10, BLUE).line(8, 15, 20, 15, BLUE)


@_reg("link")
def _link(c):
    c.p.save()
    c.p.translate(16 * c.k, 16 * c.k)
    c.p.rotate(-45)
    c.p.translate(-16 * c.k, -16 * c.k)
    c.rect(2, 12, 15, 8, fill=None, stroke=BLUE, radius=4, sw=2)
    c.rect(15, 12, 15, 8, fill=None, stroke=INK, radius=4, sw=2)
    c.p.restore()


@_reg("screentip")
def _screentip(c):
    c.rect(3, 4, 26, 17, fill=YELLOW_L, stroke=INK, radius=2)
    c.text(3, 4, 26, 17, "i", 13, True, color=BLUE)
    c.poly([(9, 21), (9, 28), (16, 21)], fill=YELLOW_L, stroke=INK)


@_reg("textbox")
def _textbox(c):
    c.rect(3, 4, 26, 24, fill=PAPER, stroke=INK)
    c.text(3, 4, 14, 14, "A", 13, True, color=BLUE)
    c.line(16, 11, 25, 11, INK).line(7, 18, 25, 18, INK).line(7, 23, 21, 23, INK)


@_reg("symbol")
def _symbol(c):
    c.text(0, 1, 32, 30, "Ω", 25, False)


@_reg("field")
def _field(c):
    c.rect(3, 8, 26, 16, fill=PAPER, stroke=INK)
    c.text(3, 8, 26, 16, "#", 13, True, color=BLUE)


# =========================================================================== Création
@_reg("orientation", "portrait", "landscape")
def _orientation(c):
    _page(c, 3, 2, 15, 21, 4)
    c.rect(11, 15, 19, 14, fill=BLUE_L, stroke=INK)
    path = QPainterPath()
    path.moveTo(21, 4)
    path.cubicTo(26, 4, 28, 7, 28, 11)
    c.path(path, None, BLUE, 1.2)
    c.head((28, 13), (0, 1), 3, BLUE)


@_reg("page_size")
def _page_size(c):
    _page(c, 4, 3, 18, 25)
    c.line(27, 3, 27, 28, BLUE)
    c.head((27, 3), (0, -1), 3.5, BLUE)
    c.head((27, 28), (0, 1), 3.5, BLUE)


@_reg("page_setup")
def _page_setup(c):
    _page(c, 5, 3, 22, 26)
    c.line(9, 12, 22, 12, BLUE).line(9, 16, 22, 16, BLUE).line(9, 20, 18, 20, BLUE)


@_reg("auto_size", "fit_drawing")
def _auto_size(c):
    c.rect(3, 3, 26, 26, fill=PAPER, stroke=INK2)
    c.rect(9, 9, 14, 14, fill=BLUE_L, stroke=BLUE)
    for (x, y), (dx, dy) in (((4, 4), (1, 1)), ((28, 4), (-1, 1)), ((4, 28), (1, -1)), ((28, 28), (-1, -1))):
        c.head((x, y), (-dx, -dy), 3.5, BLUE)


@_reg("background")
def _background(c):
    path = QPainterPath()
    path.addRect(QRectF(4.5, 3.5, 23, 25))
    if c.mono is None:
        g = QLinearGradient(0, 4 * c.k, 0, 28 * c.k)
        g.setColorAt(0, QColor("#ffffff"))
        g.setColorAt(1, QColor("#7aa7e3"))
        c.p.setBrush(QBrush(g))
        c.p.setPen(Qt.PenStyle.NoPen)
        c.p.drawPath(QTransform.fromScale(c.k, c.k).map(path))
    c.path(path, None, INK)


@_reg("borders_titles")
def _borders_titles(c):
    c.rect(3, 3, 26, 26, fill=PAPER, stroke=INK)
    c.rect(3, 3, 26, 7, fill=VBLUE, stroke=VBLUE)
    c.line(7, 6.5, 20, 6.5, PAPER, 2)
    c.rect(6, 13, 20, 13, fill=None, stroke=INK2)


@_reg("theme", "themes")
def _theme(c):
    c.rect(3, 3, 26, 26, fill=PAPER, stroke=INK2)
    c.text(4, 3, 16, 14, "Aa", 10, False)
    for i, col in enumerate((BLUE, ORANGE, GREEN, YELLOW)):
        c.rect(5 + i * 6, 20, 5, 6, fill=col, stroke=None)


@_reg("variants")
def _variants(c):
    for i, col in enumerate((BLUE, ORANGE, GREEN)):
        c.rect(3 + i * 4, 3 + i * 8, 20, 9, fill=col, stroke=PAPER)


@_reg("relayout", "layout", "relayout_tb", "relayout_lr")
def _relayout(c):
    c.rect(11, 2, 10, 8, fill=BLUE_L, stroke=BLUE)
    c.rect(2, 22, 10, 8, fill=BLUE_L, stroke=BLUE)
    c.rect(20, 22, 10, 8, fill=BLUE_L, stroke=BLUE)
    c.line(16, 10, 16, 16, INK).line(7, 16, 25, 16, INK)
    c.line(7, 16, 7, 22, INK).line(25, 16, 25, 22, INK)


@_reg("route", "connectors")
def _route(c):
    c.rect(2, 3, 10, 8, fill=BLUE_L, stroke=BLUE)
    c.rect(20, 21, 10, 8, fill=BLUE_L, stroke=BLUE)
    c.line(12, 7, 16, 7, INK).line(16, 7, 16, 25, INK).line(16, 25, 18, 25, INK)
    c.head((20, 25), (1, 0), 3.5, INK)


@_reg("line_jumps")
def _line_jumps(c):
    c.line(16, 3, 16, 29, INK)
    path = QPainterPath()
    path.moveTo(2, 16)
    path.lineTo(12, 16)
    path.arcTo(QRectF(12, 12, 8, 8), 180, -180)
    path.lineTo(30, 16)
    c.path(path, None, BLUE, 1.5)


# =========================================================================== Données / Processus
@_reg("data", "shape_data")
def _data(c):
    c.rect(3, 5, 26, 22, fill=PAPER, stroke=INK)
    c.rect(3, 5, 26, 6, fill=BLUE, stroke=INK)
    c.line(3, 16.5, 29, 16.5, INK2).line(3, 21.5, 29, 21.5, INK2).line(13, 11, 13, 27, INK2)


@_reg("data_import", "data_visualizer")
def _data_import(c):
    c.rect(2, 3, 13, 14, fill=PAPER, stroke=INK)
    c.line(2, 8, 15, 8, INK2).line(2, 12.5, 15, 12.5, INK2).line(8, 3, 8, 17, INK2)
    c.rect(18, 15, 11, 7, fill=BLUE_L, stroke=BLUE)
    c.rect(5, 23, 11, 7, fill=BLUE_L, stroke=BLUE)
    c.line(15, 10, 23, 10, INK).line(23, 10, 23, 15, INK)
    c.line(18, 18.5, 10.5, 18.5, INK).line(10.5, 18.5, 10.5, 23, INK)


@_reg("shape_report", "report")
def _shape_report(c):
    _page(c, 5, 3, 22, 26)
    for i, h in enumerate((6, 10, 14)):
        c.rect(9 + i * 5, 25 - h, 4, h, fill=(BLUE, ORANGE, GREEN)[i], stroke=None)
    c.line(8, 25.5, 25, 25.5, INK)


@_reg("check_diagram")
def _check_diagram(c):
    c.rect(3, 3, 12, 8, fill=BLUE_L, stroke=BLUE)
    c.poly([(9, 15), (15, 20), (9, 25), (3, 20)], fill=BLUE_L, stroke=BLUE)
    c.line(9, 11, 9, 15, INK)
    c.ellipse(23, 22, 7, fill=GREEN, stroke=None)
    if c.mono is None:
        c.poly([(19.5, 22), (22.5, 25), (27, 19)], fill=None, stroke=QColor("#ffffff"), sw=2, closed=False)


@_reg("swimlane")
def _swimlane(c):
    c.rect(2, 4, 28, 24, fill=PAPER, stroke=INK)
    c.rect(2, 4, 28, 6, fill=BLUE, stroke=INK)
    c.line(2, 19, 30, 19, INK)
    c.rect(2, 10, 6, 18, fill=BLUE_L, stroke=INK)
    c.rect(12, 12, 7, 5, fill=BLUE_L, stroke=BLUE)
    c.rect(21, 21, 7, 5, fill=BLUE_L, stroke=BLUE)


@_reg("swimlane_v")
def _swimlane_v(c):
    c.rect(4, 2, 24, 28, fill=PAPER, stroke=INK)
    c.rect(4, 2, 24, 6, fill=BLUE, stroke=INK)
    c.line(16, 8, 16, 30, INK)
    c.rect(4, 8, 24, 5, fill=BLUE_L, stroke=INK)
    c.rect(7, 16, 6, 5, fill=BLUE_L, stroke=BLUE)
    c.rect(19, 23, 6, 5, fill=BLUE_L, stroke=BLUE)


@_reg("separator")
def _separator(c):
    c.rect(2, 4, 28, 24, fill=PAPER, stroke=INK)
    c.rect(2, 4, 28, 6, fill=BLUE_L, stroke=INK)
    c.line(16, 4, 16, 28, BLUE, 2)


@_reg("subprocess")
def _subprocess(c):
    c.rect(3, 8, 26, 16, fill=BLUE_L, stroke=BLUE)
    c.line(7, 8, 7, 24, BLUE).line(25, 8, 25, 24, BLUE)


# =========================================================================== Révision
@_reg("comment", "new_comment")
def _comment(c):
    c.rect(3, 4, 22, 17, fill=PAPER, stroke=INK, radius=2)
    c.poly([(8, 21), (8, 28), (15, 21)], fill=PAPER, stroke=INK)
    c.line(8, 10, 20, 10, INK2).line(8, 15, 17, 15, INK2)
    _plus_badge(c, 24, 23, BLUE)


@_reg("comments", "comments_pane")
def _comments(c):
    c.rect(2, 3, 20, 14, fill=PAPER, stroke=INK, radius=2)
    c.rect(10, 13, 20, 14, fill=BLUE_L, stroke=BLUE, radius=2)
    c.line(14, 19, 26, 19, BLUE).line(14, 23, 22, 23, BLUE)


@_reg("prev_comment")
def _prev_comment(c):
    _comments(c)
    c.head((4, 26), (-1, 0), 4, INK)


@_reg("next_comment")
def _next_comment(c):
    _comments(c)
    c.head((30, 6), (1, 0), 4, INK)


@_reg("lock", "protect")
def _lock(c):
    path = QPainterPath()
    path.moveTo(10, 14)
    path.lineTo(10, 10)
    path.arcTo(QRectF(10, 3, 12, 14), 180, -180)
    path.lineTo(22, 14)
    c.path(path, None, INK, 2)
    c.rect(6, 14, 20, 15, fill=YELLOW, stroke=INK, radius=2)
    c.ellipse(16, 21, 2, fill=INK, stroke=None)


@_reg("shield", "security")
def _shield(c):
    c.poly([(16, 2.5), (28, 7), (27, 17), (16, 29.5), (5, 17), (4, 7)], fill=GREEN, stroke=None)
    if c.mono is None:
        c.poly([(10.5, 16), (14.5, 20), (22, 11)], fill=None, stroke=QColor("#ffffff"), sw=2.5, closed=False)


# =========================================================================== Affichage
@_reg("presentation", "fullscreen")
def _presentation(c):
    c.rect(3, 4, 26, 18, fill=PAPER, stroke=INK)
    c.poly([(13, 9), (13, 17), (20, 13)], fill=BLUE, stroke=None)
    c.line(16, 22, 16, 26, INK).line(10, 27, 22, 27, INK)


@_reg("ruler")
def _ruler(c):
    c.rect(2, 10, 28, 12, fill=YELLOW_L, stroke=INK)
    for i, x in enumerate(range(6, 29, 4)):
        c.line(x, 10, x, 14 if i % 2 else 17, INK)


@_reg("grid")
def _grid(c):
    c.rect(3, 3, 26, 26, fill=PAPER, stroke=INK)
    for v in (9.5, 16, 22.5):
        c.line(v, 3, v, 29, INK2).line(3, v, 29, v, INK2)


@_reg("guides")
def _guides(c):
    c.rect(5, 5, 11, 9, fill=BLUE_L, stroke=BLUE)
    c.rect(16, 18, 10, 9, fill=BLUE_L, stroke=BLUE)
    c.line(16, 1, 16, 31, QColor("#d6336c"), 1, Qt.PenStyle.DashLine)


@_reg("ports")
def _ports(c):
    c.rect(5, 8, 22, 16, fill=PAPER, stroke=INK)
    for x, y in ((16, 8), (27, 16), (16, 24), (5, 16)):
        c.line(x - 2.5, y - 2.5, x + 2.5, y + 2.5, BLUE, 1.5).line(x - 2.5, y + 2.5, x + 2.5, y - 2.5, BLUE, 1.5)


@_reg("autoconnect")
def _autoconnect(c):
    c.rect(10, 10, 12, 12, fill=BLUE_L, stroke=BLUE)
    for tip, d in (((16, 2), (0, -1)), ((30, 16), (1, 0)), ((16, 30), (0, 1)), ((2, 16), (-1, 0))):
        c.head(tip, d, 5, BLUE)


@_reg("snap")
def _snap(c):
    path = QPainterPath()
    path.moveTo(7, 5)
    path.lineTo(7, 16)
    path.arcTo(QRectF(7, 7, 18, 18), 180, 180)
    path.lineTo(25, 5)
    c.path(path, None, RED, 5)
    c.line(7, 3, 7, 7, INK2, 5).line(25, 3, 25, 7, INK2, 5)


@_reg("zoom", "zoom_in")
def _zoom(c):
    _magnifier(c)
    c.line(9, 13, 17, 13, BLUE, 1.5).line(13, 9, 13, 17, BLUE, 1.5)


@_reg("zoom_out")
def _zoom_out(c):
    _magnifier(c)
    c.line(9, 13, 17, 13, BLUE, 1.5)


@_reg("zoom_100")
def _zoom_100(c):
    _magnifier(c, 14, 14, 11)
    c.text(4, 8, 20, 12, "100", 7.5, True, color=BLUE)


@_reg("fit", "fit_page")
def _fit(c):
    c.rect(2, 4, 28, 24, fill=PAPER, stroke=INK)
    c.rect(10, 9, 12, 14, fill=BLUE_L, stroke=BLUE)
    for (x, y), d in (((5, 7), (-1, -1)), ((27, 7), (1, -1)), ((5, 25), (-1, 1)), ((27, 25), (1, 1))):
        c.head((x, y), d, 3.2, BLUE)


@_reg("fit_width", "page_width")
def _page_width(c):
    c.rect(2, 4, 28, 24, fill=PAPER, stroke=INK)
    c.rect(8, 7, 16, 21, fill=BLUE_L, stroke=BLUE)
    c.head((4, 16), (-1, 0), 3, BLUE)
    c.head((28, 16), (1, 0), 3, BLUE)


@_reg("new_window")
def _new_window(c):
    c.rect(2, 4, 22, 18, fill=PAPER, stroke=INK)
    c.rect(2, 4, 22, 4, fill=VBLUE, stroke=INK)
    _plus_badge(c, 24, 24, GREEN)


@_reg("task_panes")
def _task_panes(c):
    c.rect(2, 4, 28, 24, fill=PAPER, stroke=INK)
    c.rect(20, 4, 10, 24, fill=BLUE_L, stroke=INK)
    c.line(22, 10, 28, 10, BLUE).line(22, 14, 28, 14, BLUE)


@_reg("shapes_panel", "show_shapes")
def _shapes_panel(c):
    c.rect(2, 4, 28, 24, fill=PAPER, stroke=INK)
    c.rect(2, 4, 11, 24, fill=BLUE_L, stroke=INK)
    c.rect(4, 8, 6, 4, fill=BLUE, stroke=None)
    c.ellipse(7, 18, 3, fill=ORANGE, stroke=None)


@_reg("format_panel", "show_format")
def _format_panel(c):
    c.rect(2, 4, 28, 24, fill=PAPER, stroke=INK)
    c.rect(19, 4, 11, 24, fill=BLUE_L, stroke=INK)
    c.poly([(21, 15), (25, 11), (29, 15), (25, 19)], fill=BLUE, stroke=None)


@_reg("overview", "pan_zoom", "show_overview")
def _pan_zoom(c):
    c.rect(2, 4, 28, 24, fill=PAPER, stroke=INK)
    c.rect(9, 10, 12, 10, fill=None, stroke=RED, sw=1.5)


@_reg("size_position", "show_size")
def _size_position(c):
    c.rect(4, 8, 18, 18, fill=BLUE_L, stroke=BLUE)
    c.line(4, 4, 22, 4, INK).line(27, 8, 27, 26, INK)
    c.head((4, 4), (-1, 0), 3, INK)
    c.head((22, 4), (1, 0), 3, INK)
    c.head((27, 8), (0, -1), 3, INK)
    c.head((27, 26), (0, 1), 3, INK)


@_reg("ribbon", "toggle_ribbon")
def _ribbon(c):
    c.rect(2, 4, 28, 24, fill=PAPER, stroke=INK)
    c.rect(2, 4, 28, 8, fill=VBLUE, stroke=INK)


# =========================================================================== Fichier
@_reg("open")
def _open(c):
    c.poly([(2.5, 7.5), (11, 7.5), (13.5, 10.5), (26.5, 10.5), (26.5, 26.5), (2.5, 26.5)],
           fill=QColor("#f2c45a"), stroke=QColor("#b8860b"))
    c.poly([(6.5, 14.5), (30.5, 14.5), (26.5, 26.5), (2.5, 26.5)], fill=QColor("#ffd978"),
           stroke=QColor("#b8860b"))


@_reg("save")
def _save(c):
    if c.mono is not None:
        c.rect(5, 5, 22, 22, fill=None, stroke=INK, radius=1.5, sw=1.5)
        c.rect(10, 5, 12, 7, fill=None, stroke=INK)
        c.rect(9, 17, 14, 10, fill=None, stroke=INK)
        return
    c.rect(4, 4, 24, 24, fill=VBLUE, stroke=None, radius=2)
    c.rect(9, 4, 14, 8, fill=QColor("#ffffff"), stroke=None)
    c.rect(18, 5, 3, 5, fill=VBLUE, stroke=None)
    c.rect(8, 16, 16, 12, fill=QColor("#dfe6f6"), stroke=None)


@_reg("save_as")
def _save_as(c):
    _save(c)
    c.poly([(26, 13), (30, 17), (20, 27), (15, 28), (16, 23)], fill=YELLOW, stroke=INK)


@_reg("print")
def _print(c):
    c.rect(9, 3, 14, 9, fill=PAPER, stroke=INK)
    c.rect(3, 11, 26, 12, fill=INK2, stroke=INK, radius=2)
    c.rect(9, 18, 14, 11, fill=PAPER, stroke=INK)
    c.line(12, 22, 20, 22, INK2).line(12, 25, 18, 25, INK2)


@_reg("export")
def _export(c):
    _page(c, 3, 3, 18, 26)
    c.line(13, 16, 28, 16, BLUE, 2)
    c.head((31, 16), (1, 0), 5, BLUE)


@_reg("import", "import_vsdx")
def _import(c):
    _page(c, 11, 3, 18, 26)
    c.line(1, 16, 16, 16, BLUE, 2)
    c.head((19, 16), (1, 0), 5, BLUE)


def _badged_page(c, text, color):
    _page(c, 7, 2, 20, 28)
    c.rect(3, 14, 20, 10, fill=color, stroke=None, radius=1)
    c.text(3, 14, 20, 10, text, 7 if len(text) <= 3 else 6, True,
           color=QColor("#ffffff") if c.mono is None else PAPER)


@_reg("pdf", "export_pdf")
def _pdf(c):
    _badged_page(c, "PDF", RED)


@_reg("png", "export_png", "jpg", "export_jpg")
def _png(c):
    _image(c)


@_reg("svg", "export_svg")
def _svg(c):
    _badged_page(c, "SVG", ORANGE)


@_reg("visio", "vsdx", "export_vsdx")
def _vsdx(c):
    _badged_page(c, "VSDX", VBLUE)


@_reg("close")
def _close(c):
    c.line(8, 8, 24, 24, INK, 2).line(24, 8, 8, 24, INK, 2)


@_reg("undo")
def _undo(c):
    path = QPainterPath()
    path.moveTo(8, 12)
    path.cubicTo(14, 5, 27, 7, 27, 17)
    path.cubicTo(27, 23, 22, 26, 16, 26)
    c.path(path, None, INK, 2)
    c.head((4, 15), (-1, 0.9), 6, INK)


@_reg("redo")
def _redo(c):
    path = QPainterPath()
    path.moveTo(24, 12)
    path.cubicTo(18, 5, 5, 7, 5, 17)
    path.cubicTo(5, 23, 10, 26, 16, 26)
    c.path(path, None, INK, 2)
    c.head((28, 15), (1, 0.9), 6, INK)


@_reg("properties")
def _properties(c):
    _page(c, 5, 3, 22, 26)
    for y in (11, 16, 21):
        c.ellipse(10, y, 1.3, fill=BLUE, stroke=None)
        c.line(13, y, 23, y, INK)


@_reg("recover")
def _recover(c):
    _page(c, 4, 3, 18, 25)
    _rotate_left(c)


@_reg("shapesheet")
def _shapesheet(c):
    _data(c)
    c.text(14, 16, 16, 12, "fx", 9, True, italic=True, color=BLUE)


@_reg("help", "info", "about")
def _help(c):
    c.ellipse(16, 16, 13, fill=VBLUE, stroke=None)
    c.text(3, 3, 26, 26, "?", 17, True, color=QColor("#ffffff") if c.mono is None else PAPER)


@_reg("keyboard", "shortcuts")
def _keyboard(c):
    c.rect(2, 8, 28, 17, fill=PAPER, stroke=INK, radius=2)
    for y in (12, 16):
        for x in range(6, 27, 4):
            c.rect(x - 1, y - 1, 2.5, 2.5, fill=INK, stroke=None)
    c.line(9, 21, 23, 21, INK, 1.5)


@_reg("options")
def _options(c):
    for i in range(8):
        a = i * math.pi / 4
        c.ellipse(16 + math.cos(a) * 11, 16 + math.sin(a) * 11, 3, fill=INK2, stroke=None)
    c.ellipse(16, 16, 10, fill=INK2, stroke=None)
    c.ellipse(16, 16, 4.5, fill=PAPER, stroke=None)


@_reg("share")
def _share(c):
    c.ellipse(9, 16, 4, fill=BLUE, stroke=None)
    c.ellipse(23, 8, 4, fill=BLUE, stroke=None)
    c.ellipse(23, 24, 4, fill=BLUE, stroke=None)
    c.line(9, 16, 23, 8, INK).line(9, 16, 23, 24, INK)


# =========================================================================== Fenêtre et navigation
@_reg("win_min")
def _win_min(c):
    c.line(10, 16, 22, 16, INK)


@_reg("win_max")
def _win_max(c):
    c.rect(10, 10, 12, 12, fill=None, stroke=INK)


@_reg("win_restore")
def _win_restore(c):
    c.rect(10, 12, 10, 10, fill=None, stroke=INK)
    c.line(12, 10, 22, 10, INK).line(22, 10, 22, 20, INK)


@_reg("win_close")
def _win_close(c):
    c.line(10, 10, 22, 22, INK).line(22, 10, 10, 22, INK)


@_reg("chevron_up")
def _chevron_up(c):
    c.poly([(9, 19), (16, 12), (23, 19)], fill=None, stroke=INK, sw=1.5, closed=False)


@_reg("chevron_down")
def _chevron_down(c):
    c.poly([(9, 13), (16, 20), (23, 13)], fill=None, stroke=INK, sw=1.5, closed=False)


@_reg("pin")
def _pin(c):
    c.poly([(12, 4), (20, 4), (19, 14), (23, 18), (9, 18), (13, 14)], fill=PAPER, stroke=INK)
    c.line(16, 18, 16, 28, INK)


@_reg("nav_prev")
def _nav_prev(c):
    c.poly([(20, 8), (12, 16), (20, 24)], fill=INK, stroke=None)


@_reg("nav_next")
def _nav_next(c):
    c.poly([(12, 8), (20, 16), (12, 24)], fill=INK, stroke=None)


@_reg("nav_all")
def _nav_all(c):
    c.poly([(9, 20), (16, 12), (23, 20)], fill=INK, stroke=None)


@_reg("back_arrow")
def _back_arrow(c):
    c.ellipse(16, 16, 13, fill=None, stroke=INK, sw=1.5)
    c.line(10, 16, 23, 16, INK, 1.5)
    c.poly([(15, 10), (9, 16), (15, 22)], fill=None, stroke=INK, sw=1.5, closed=False)


@_reg("dialog_launcher")
def _dialog_launcher(c):
    c.line(8, 8, 8, 24, INK).line(8, 8, 24, 8, INK)
    c.line(13, 13, 22, 22, INK)
    c.poly([(16, 24), (24, 24), (24, 16)], fill=INK, stroke=None)


@_reg("customize")
def _customize(c):
    c.line(10, 10, 22, 10, INK)
    c.poly([(10, 15), (22, 15), (16, 22)], fill=INK, stroke=None)


def _render(name: str, size: int, dpr: float, mono: QColor | None) -> QPixmap:
    device = max(1, round(size * dpr))
    pm = QPixmap(device, device)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    fn = DRAW.get(name)
    if fn is not None:
        fn(_C(p, device, dpr, mono))
    p.end()
    pm.setDevicePixelRatio(dpr)
    return pm


def icon(name: str, mono: str | None = None) -> QIcon:
    key = (name, mono)
    if key in _cache:
        return _cache[key]
    m = QColor(mono) if mono else None
    ic = QIcon()
    for size in (16, 20, 24, 32, 40, 48):
        for dpr in (1.0, 2.0):
            ic.addPixmap(_render(name, size, dpr, m))
    _cache[key] = ic
    return ic


def pixmap(name: str, size: int, dpr: float = 1.0, mono: str | None = None) -> QPixmap:
    return _render(name, size, dpr, QColor(mono) if mono else None)


# =========================================================================== aperçus de formes et styles

def stencil_pixmap(sdef, size: int = 32, theme: str = "office", dpr: float = 2.0,
                   style: dict | None = None) -> QPixmap:
    """Aperçu d'une forme (volet Formes, galeries)."""
    from .fileformat import default_shape_styles  # import local : évite un cycle
    pm = QPixmap(round(size * dpr), round(size * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.GlobalColor.transparent)
    sw, sh = sdef.size_mm
    scale = (size - 4) / max(sw, sh)
    w, h = max(sw * scale, 3), max(sh * scale, 3)
    base, _ts = default_shape_styles(sdef.type_id, theme)
    if style:
        base = dict(base, **style)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    if sdef.type_id in ("basic.text", "basic.title"):
        f = QFont("Inter")
        f.setPixelSize(max(8, size // 2 if sdef.type_id == "basic.title" else size // 3))
        f.setBold(sdef.type_id == "basic.title")
        p.setFont(f)
        p.setPen(INK)
        p.drawText(QRectF(0, 0, size, size), Qt.AlignmentFlag.AlignCenter,
                   "Titre" if sdef.type_id == "basic.title" else "Abc")
        p.end()
        return pm
    if sdef.cff:
        w, h = (size - 4, size * 0.42) if sdef.cff in ("lane_h", "frame_h") else \
            (size * 0.42, size - 4) if sdef.cff == "lane_v" else \
            (size * 0.55, size - 4) if sdef.cff == "phase_h" else (size - 4, size * 0.55)
        if sdef.cff == "frame_v":
            w, h = size - 8, size - 4
        p.translate((size - w) / 2, (size - h) / 2)
        band = {"lane_h": QRectF(0, 0, w * 0.2, h), "lane_v": QRectF(0, 0, w, h * 0.2),
                "phase_h": QRectF(0, 0, w, h * 0.22), "phase_v": QRectF(0, 0, w * 0.22, h),
                "frame_h": QRectF(0, 0, w, h * 0.3), "frame_v": QRectF(0, 0, w, h * 0.18)}[sdef.cff]
        p.setPen(QPen(QColor(base["line"]), 1.0))
        p.setBrush(QColor(base["fill"]))
        p.drawRect(band)
        p.setBrush(Qt.BrushStyle.NoBrush)
        if sdef.cff.startswith("phase"):
            if sdef.cff == "phase_h":
                p.drawLine(QPointF(w, band.bottom()), QPointF(w, h))
            else:
                p.drawLine(QPointF(band.right(), h), QPointF(w, h))
        else:
            p.drawRect(QRectF(0, 0, w, h))
            if sdef.cff == "frame_h":
                p.drawLine(QPointF(w * 0.12, band.bottom()), QPointF(w * 0.12, h))
                p.drawLine(QPointF(0, (band.bottom() + h) / 2), QPointF(w, (band.bottom() + h) / 2))
            elif sdef.cff == "frame_v":
                p.drawLine(QPointF(w / 2, band.bottom()), QPointF(w / 2, h))
        p.end()
        return pm
    outline, detail = sdef.builder(w, h)
    p.translate((size - w) / 2, (size - h) / 2)
    pen = QPen(QColor(base["line"] or "#404040"), 1.0)
    if base.get("dash") == "dash":
        pen.setStyle(Qt.PenStyle.DashLine)
    if sdef.outline_visible:
        p.setPen(pen)
        p.setBrush(QColor(base["fill"]) if base["fill"] else Qt.BrushStyle.NoBrush)
        p.drawPath(outline)
    if detail is not None:
        p.setPen(pen if base["line"] else QPen(INK, 1.0))
        p.setBrush(QColor(base["line"]) if sdef.detail_fill else Qt.BrushStyle.NoBrush)
        p.drawPath(detail)
    p.end()
    return pm


def style_swatch(style: dict, text_color: str, size: int = 40, dpr: float = 2.0) -> QPixmap:
    """Vignette « Styles rapides » : un rectangle arrondi avec le texte « Abc »."""
    pm = QPixmap(round(size * dpr), round(size * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    r = QRectF(4, 7, size - 8, size - 14)
    if style.get("shadow"):
        p.fillRect(r.translated(2, 2), QColor(0, 0, 0, 60))
    fill = style.get("fill")
    if fill:
        if style.get("gradient"):
            g = QLinearGradient(0, r.top(), 0, r.bottom())
            g.setColorAt(0, QColor(fill).lighter(145))
            g.setColorAt(1, QColor(fill))
            p.setBrush(QBrush(g))
        else:
            p.setBrush(QColor(fill))
    else:
        p.setBrush(Qt.BrushStyle.NoBrush)
    if style.get("line"):
        p.setPen(QPen(QColor(style["line"]), 1.2))
    else:
        p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(r, 3, 3)
    f = QFont("Inter")
    f.setPixelSize(max(8, size // 4))
    p.setFont(f)
    p.setPen(QColor(text_color))
    p.drawText(r, Qt.AlignmentFlag.AlignCenter, "Abc")
    p.end()
    return pm


def theme_swatch(theme: str, size: int = 48) -> QIcon:
    t = THEMES[theme]
    pm = QPixmap(size * 2, size * 2)
    pm.setDevicePixelRatio(2.0)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(QPen(QColor("#c8c6c4"), 1))
    p.setBrush(QColor("#ffffff"))
    p.drawRect(QRectF(0.5, 0.5, size - 1, size - 1))
    p.setPen(QPen(QColor(t["line"]), 1))
    p.setBrush(QColor(t["fill"]))
    p.drawRoundedRect(QRectF(6, 8, size * 0.42, size * 0.3), 2, 2)
    p.drawEllipse(QRectF(size * 0.56, size * 0.48, size * 0.34, size * 0.34))
    p.setPen(QPen(QColor(t["connector"]), 1.6))
    x1, y1 = 6 + size * 0.42, 8 + size * 0.15
    p.drawLine(QPointF(x1, y1), QPointF(size * 0.73, y1))
    p.drawLine(QPointF(size * 0.73, y1), QPointF(size * 0.73, size * 0.48))
    f = QFont("Inter")
    f.setPixelSize(max(8, size // 6))
    p.setFont(f)
    p.setPen(QColor("#444444"))
    p.drawText(QRectF(4, size * 0.62, size * 0.5, size * 0.3), Qt.AlignmentFlag.AlignLeft, "Aa")
    p.end()
    return QIcon(pm)


def app_icon() -> QIcon:
    """Icône de l'application : un diagramme blanc sur fond bleu."""
    ic = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        pm = QPixmap(size, size)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.scale(size / 64.0, size / 64.0)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#3955a3"))
        p.drawRoundedRect(QRectF(2, 2, 60, 60), 12, 12)
        p.setPen(QPen(QColor("#ffffff"), 3))
        p.drawLine(QPointF(22, 20), QPointF(42, 20))
        p.drawLine(QPointF(32, 20), QPointF(32, 44))
        p.setPen(QPen(QColor("#1e3470"), 1.5))
        p.setBrush(QColor("#ffffff"))
        p.drawRoundedRect(QRectF(9, 12, 18, 14), 3, 3)
        p.setBrush(QColor("#a9c1f2"))
        p.drawEllipse(QRectF(37, 12, 16, 16))
        p.setBrush(QColor("#ffd34d"))
        p.drawPolygon(QPolygonF([QPointF(32, 36), QPointF(42, 45), QPointF(32, 54), QPointF(22, 45)]))
        p.end()
        ic.addPixmap(pm)
    return ic


def cff_style_swatch(preset: dict, size: int = 44) -> QIcon:
    """Vignette d'un style interfonctionnel : barre de titre et trois couloirs."""
    pm = QPixmap(size * 2, size * 2)
    pm.setDevicePixelRatio(2.0)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    line = QPen(QColor(preset["line"]), 1)
    x0, y0, w, h = 4.5, 6.5, size - 9, size - 13
    p.fillRect(QRectF(x0, y0, w, h), QColor("#ffffff"))
    title = h * 0.22
    p.fillRect(QRectF(x0, y0, w, title), QColor(preset["title_fill"]))
    lane = (h - title) / 3
    for i in range(3):
        top = y0 + title + i * lane
        p.fillRect(QRectF(x0, top, w * 0.2, lane), QColor(preset["lane_fill"]))
        p.setPen(line)
        p.drawLine(QPointF(x0, top), QPointF(x0 + w, top))
    p.setPen(line)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRect(QRectF(x0, y0, w, h))
    p.drawLine(QPointF(x0 + w * 0.2, y0 + title), QPointF(x0 + w * 0.2, y0 + h))
    p.setPen(QPen(QColor(preset["title_text"]), 1.4))
    p.drawLine(QPointF(x0 + w * 0.3, y0 + title / 2), QPointF(x0 + w * 0.7, y0 + title / 2))
    p.end()
    return QIcon(pm)
