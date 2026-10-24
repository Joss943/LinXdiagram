"""Gabarits de formes (l'équivalent des « stencils » Visio).

Chaque forme est décrite par un générateur de géométrie qui reçoit la largeur
et la hauteur et renvoie deux chemins : le contour (rempli et tracé) et des
détails optionnels (traits internes). Les points de connexion et la zone de
texte sont exprimés en coordonnées normalisées (0..1), comme les sections
« Connections » et « TextXForm » de la ShapeSheet Visio.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable

from PyQt6.QtCore import QPointF, QRectF
from PyQt6.QtGui import QPainterPath, QTransform

Builder = Callable[[float, float], tuple[QPainterPath, "QPainterPath | None"]]

SIDES = ((0.5, 0.0), (1.0, 0.5), (0.5, 1.0), (0.0, 0.5))
SIDES_AND_CORNERS = SIDES + ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))


@dataclass(frozen=True)
class ShapeDef:
    type_id: str
    name: str
    category: str
    builder: Builder
    size_mm: tuple[float, float] = (30.0, 20.0)
    ports: tuple[tuple[float, float], ...] = SIDES
    text_rect: tuple[float, float, float, float] = (0.0, 0.0, 1.0, 1.0)
    keywords: str = ""
    style: dict = field(default_factory=dict)
    text: dict = field(default_factory=dict)
    label_outside: bool = False
    outline_visible: bool = True
    detail_fill: bool = False
    roundable: bool = False
    container: bool = False
    default_text: str = ""
    cff: str = ""  # élément de diagramme interfonctionnel : lane_h, lane_v, phase_h, phase_v, frame_h, frame_v


# ------------------------------------------------------------------ utilitaires

def _fit(path: QPainterPath, w: float, h: float) -> QPainterPath:
    """Étire un chemin construit dans le carré unité vers la boîte w×h."""
    return QTransform.fromScale(w, h).map(path)


def _unit(fn: Callable[[], tuple[QPainterPath, QPainterPath | None]]) -> Builder:
    def build(w: float, h: float):
        outline, detail = fn()
        return _fit(outline, w, h), (_fit(detail, w, h) if detail is not None else None)
    return build


def _poly_path(points) -> QPainterPath:
    p = QPainterPath()
    p.moveTo(*points[0])
    for pt in points[1:]:
        p.lineTo(*pt)
    p.closeSubpath()
    return p


def _poly(points) -> Builder:
    return _unit(lambda: (_poly_path(points), None))


def _lines(*segments) -> QPainterPath:
    p = QPainterPath()
    for seg in segments:
        p.moveTo(*seg[0])
        for pt in seg[1:]:
            p.lineTo(*pt)
    return p


def _rect(x, y, w, h) -> QPainterPath:
    p = QPainterPath()
    p.addRect(QRectF(x, y, w, h))
    return p


def _rrect(x, y, w, h, r) -> QPainterPath:
    p = QPainterPath()
    p.addRoundedRect(QRectF(x, y, w, h), r, r)
    return p


def _ellipse(cx, cy, rx, ry) -> QPainterPath:
    p = QPainterPath()
    p.addEllipse(QPointF(cx, cy), rx, ry)
    return p


def _union(*paths: QPainterPath) -> QPainterPath:
    out = QPainterPath()
    for p in paths:
        out = out.united(p)
    return out.simplified()


def regular_polygon(n: int, inner: float | None = None, start: float = -90.0):
    count = n * 2 if inner else n
    pts = []
    for i in range(count):
        a = math.radians(start + i * 360.0 / count)
        r = inner if (inner and i % 2) else 1.0
        pts.append((math.cos(a) * r, math.sin(a) * r))
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
    return [((x - minx) / (maxx - minx), (y - miny) / (maxy - miny)) for x, y in pts]


# ------------------------------------------------------------------- géométries

def rect_builder(w: float, h: float, rounding: float = 0.0):
    p = QPainterPath()
    if rounding > 0:
        r = min(rounding, w / 2, h / 2)
        p.addRoundedRect(QRectF(0, 0, w, h), r, r)
    else:
        p.addRect(QRectF(0, 0, w, h))
    return p, None


def _b_rect(w, h):
    return rect_builder(w, h)


def _b_round(w, h):
    r = min(w, h) * 0.15
    return rect_builder(w, h, r)


def _b_stadium(w, h):
    return rect_builder(w, h, min(w, h) / 2)


def _b_ellipse(w, h):
    p = QPainterPath()
    p.addEllipse(QRectF(0, 0, w, h))
    return p, None


def _cylinder(w, h, rims: int = 0):
    ry = min(h * 0.12, w * 0.25)
    p = QPainterPath()
    p.moveTo(0, ry)
    p.arcTo(QRectF(0, 0, w, 2 * ry), 180, -180)
    p.lineTo(w, h - ry)
    p.arcTo(QRectF(0, h - 2 * ry, w, 2 * ry), 0, -180)
    p.closeSubpath()
    d = QPainterPath()
    d.moveTo(0, ry)
    d.arcTo(QRectF(0, 0, w, 2 * ry), 180, 180)
    for i in range(1, rims + 1):
        y = ry + (h - 2 * ry) * i / (rims + 1)
        d.moveTo(0, y)
        d.arcTo(QRectF(0, y - ry, w, 2 * ry), 180, 180)
    return p, d


def _b_cylinder(w, h):
    return _cylinder(w, h)


def _b_database(w, h):
    return _cylinder(w, h, rims=2)


def _b_cube():
    outline = _poly_path([(0, 0.2), (0.2, 0), (1, 0), (1, 0.8), (0.8, 1), (0, 1)])
    detail = _lines([(0, 0.2), (0.8, 0.2), (1, 0)], [(0.8, 0.2), (0.8, 1)])
    return outline, detail


def _b_cloud():
    parts = [(0.25, 0.55, 0.22, 0.28), (0.45, 0.35, 0.25, 0.3), (0.7, 0.38, 0.22, 0.27),
             (0.8, 0.62, 0.2, 0.25), (0.52, 0.68, 0.3, 0.27), (0.2, 0.7, 0.18, 0.2)]
    p = _union(*(_ellipse(*c) for c in parts))
    b = p.boundingRect()
    t = QTransform().scale(1 / b.width(), 1 / b.height()).translate(-b.left(), -b.top())
    return t.map(p), None


def _b_note():
    return (_poly_path([(0, 0), (0.8, 0), (1, 0.2), (1, 1), (0, 1)]),
            _lines([(0.8, 0), (0.8, 0.2), (1, 0.2)]))


def _b_callout():
    body = _rrect(0, 0, 1, 0.78, 0.08)
    tail = _poly_path([(0.18, 0.7), (0.12, 1.0), (0.42, 0.7)])
    return _union(body, tail), None


def _b_container():
    return _rect(0, 0, 1, 1), _lines([(0, 0.14), (1, 0.14)])


def _b_document_path(x, y, w, h):
    p = QPainterPath()
    p.moveTo(x, y)
    p.lineTo(x + w, y)
    p.lineTo(x + w, y + 0.85 * h)
    p.cubicTo(x + 0.6 * w, y + 0.62 * h, x + 0.4 * w, y + 1.15 * h, x, y + 0.85 * h)
    p.closeSubpath()
    return p


def _b_document():
    return _b_document_path(0, 0, 1, 1), None


def _b_multidoc():
    return _union(_b_document_path(0.12, 0, 0.88, 0.86), _b_document_path(0.06, 0.07, 0.88, 0.86),
                  _b_document_path(0, 0.14, 0.88, 0.86)), None


def _b_subprocess():
    return _rect(0, 0, 1, 1), _lines([(0.1, 0), (0.1, 1)], [(0.9, 0), (0.9, 1)])


def _b_internal_storage():
    return _rect(0, 0, 1, 1), _lines([(0.15, 0), (0.15, 1)], [(0, 0.2), (1, 0.2)])


def _b_delay(w, h):
    p = QPainterPath()
    p.moveTo(0, 0)
    p.lineTo(w * 0.5, 0)
    p.arcTo(QRectF(0, 0, w, h), 90, -180)
    p.lineTo(0, h)
    p.closeSubpath()
    return p, None


def _b_display(w, h):
    p = QPainterPath()
    p.moveTo(0, h / 2)
    p.lineTo(w * 0.2, 0)
    p.lineTo(w * 0.8, 0)
    p.arcTo(QRectF(w * 0.6, 0, w * 0.4, h), 90, -180)
    p.lineTo(w * 0.2, h)
    p.closeSubpath()
    return p, None


def _b_annotation():
    return _rect(0, 0, 1, 1), _lines([(0.2, 0), (0, 0), (0, 1), (0.2, 1)])


def _b_server():
    outline = _rrect(0.2, 0, 0.6, 1, 0.04)
    detail = _lines([(0.28, 0.12), (0.72, 0.12)], [(0.28, 0.22), (0.72, 0.22)],
                    [(0.28, 0.32), (0.72, 0.32)], [(0.28, 0.42), (0.72, 0.42)])
    detail.addEllipse(QPointF(0.5, 0.85), 0.045, 0.035)
    return outline, detail


def _b_pc():
    monitor = _rrect(0, 0, 1, 0.68, 0.03)
    stand = _poly_path([(0.42, 0.67), (0.58, 0.67), (0.62, 0.88), (0.38, 0.88)])
    base = _rrect(0.22, 0.86, 0.56, 0.14, 0.03)
    detail = _rect(0.06, 0.07, 0.88, 0.53)
    return _union(monitor, stand, base), detail


def _b_laptop():
    screen = _rrect(0.12, 0, 0.76, 0.68, 0.03)
    base = _poly_path([(0.06, 0.72), (0.94, 0.72), (1, 0.9), (0, 0.9)])
    detail = _rect(0.17, 0.06, 0.66, 0.54)
    detail.addPath(_lines([(0.4, 0.82), (0.6, 0.82)]))
    return _union(screen, base), detail


def _b_router():
    outline = QPainterPath()
    outline.moveTo(0, 0.3)
    outline.arcTo(QRectF(0, 0.05, 1, 0.5), 180, -180)
    outline.lineTo(1, 0.7)
    outline.arcTo(QRectF(0, 0.45, 1, 0.5), 0, -180)
    outline.closeSubpath()
    detail = QPainterPath()
    detail.moveTo(0, 0.3)
    detail.arcTo(QRectF(0, 0.05, 1, 0.5), 180, 180)
    c = (0.5, 0.3)
    for dx, dy in ((0.22, 0.09), (-0.22, -0.09), (0.22, -0.09), (-0.22, 0.09)):
        detail.addPath(_lines([(c[0] + dx * 0.25, c[1] + dy * 0.25), (c[0] + dx, c[1] + dy)]))
    return outline, detail


def _b_switch():
    outline = _poly_path([(0, 0.35), (0.15, 0), (1, 0), (1, 0.65), (0.85, 1), (0, 1)])
    detail = _lines([(0, 0.35), (0.85, 0.35), (1, 0)], [(0.85, 0.35), (0.85, 1)],
                    [(0.12, 0.55), (0.7, 0.55)], [(0.6, 0.48), (0.7, 0.55), (0.6, 0.62)],
                    [(0.73, 0.82), (0.15, 0.82)], [(0.25, 0.75), (0.15, 0.82), (0.25, 0.89)])
    return outline, detail


def _b_firewall():
    detail = _lines([(0, 0.25), (1, 0.25)], [(0, 0.5), (1, 0.5)], [(0, 0.75), (1, 0.75)],
                    [(0.33, 0), (0.33, 0.25)], [(0.66, 0), (0.66, 0.25)],
                    [(0.17, 0.25), (0.17, 0.5)], [(0.5, 0.25), (0.5, 0.5)], [(0.83, 0.25), (0.83, 0.5)],
                    [(0.33, 0.5), (0.33, 0.75)], [(0.66, 0.5), (0.66, 0.75)],
                    [(0.17, 0.75), (0.17, 1)], [(0.5, 0.75), (0.5, 1)], [(0.83, 0.75), (0.83, 1)])
    return _rect(0, 0, 1, 1), detail


def _b_printer():
    body = _rrect(0, 0.25, 1, 0.5, 0.06)
    paper_in = _rect(0.2, 0, 0.6, 0.27)
    paper_out = _poly_path([(0.15, 0.7), (0.85, 0.7), (0.92, 1), (0.08, 1)])
    detail = _lines([(0.1, 0.62), (0.9, 0.62)], [(0.25, 0.82), (0.75, 0.82)])
    detail.addEllipse(QPointF(0.86, 0.38), 0.04, 0.04)
    return _union(body, paper_in, paper_out), detail


def _b_phone():
    detail = _rect(0.26, 0.1, 0.48, 0.7)
    detail.addEllipse(QPointF(0.5, 0.9), 0.05, 0.04)
    return _rrect(0.2, 0, 0.6, 1, 0.08), detail


def _b_wifi():
    box = _rrect(0.1, 0.62, 0.8, 0.38, 0.05)
    antenna = _rect(0.47, 0.3, 0.06, 0.34)
    detail = QPainterPath()
    for r in (0.12, 0.22, 0.32):
        detail.moveTo(0.5 - r * 0.9, 0.3 - r * 0.45)
        detail.quadTo(0.5, 0.3 - r * 1.25, 0.5 + r * 0.9, 0.3 - r * 0.45)
    return _union(box, antenna), detail


def _b_load_balancer():
    outline = _rrect(0.04, 0.12, 0.92, 0.76, 0.08)
    detail = _lines([(0.18, 0.36), (0.8, 0.36), (0.68, 0.24), (0.8, 0.36), (0.68, 0.48)],
                    [(0.82, 0.64), (0.2, 0.64), (0.32, 0.52), (0.2, 0.64), (0.32, 0.76)])
    return outline, detail


def _b_rack():
    outline = _rrect(0.12, 0, 0.76, 1, 0.04)
    detail = QPainterPath()
    for y in (0.2, 0.4, 0.6, 0.8):
        detail.addPath(_lines([(0.2, y), (0.8, y)]))
        detail.addEllipse(QPointF(0.29, y - 0.1), 0.035, 0.035)
        detail.addEllipse(QPointF(0.4, y - 0.1), 0.035, 0.035)
    return outline, detail


def _b_vm():
    monitor = _rrect(0.05, 0.02, 0.9, 0.7, 0.04)
    stand = _lines([(0.5, 0.72), (0.5, 0.88)], [(0.3, 0.9), (0.7, 0.9)])
    detail = _poly_path([(0.5, 0.18), (0.72, 0.3), (0.72, 0.52), (0.5, 0.64), (0.28, 0.52), (0.28, 0.3)])
    detail.addPath(_lines([(0.5, 0.18), (0.5, 0.42), (0.72, 0.3)], [(0.5, 0.42), (0.28, 0.3)],
                          [(0.5, 0.42), (0.5, 0.64)]))
    detail.addPath(stand)
    return monitor, detail


def _b_storage():
    outline = _rrect(0.12, 0.08, 0.76, 0.84, 0.06)
    detail = _lines([(0.12, 0.35), (0.88, 0.35)], [(0.12, 0.63), (0.88, 0.63)])
    for y in (0.21, 0.49, 0.77):
        detail.addEllipse(QPointF(0.72, y), 0.04, 0.04)
    return outline, detail


def _b_vpn():
    shield = _poly_path([(0.5, 0.02), (0.9, 0.17), (0.85, 0.58), (0.5, 0.96),
                         (0.15, 0.58), (0.1, 0.17)])
    detail = _rrect(0.3, 0.42, 0.4, 0.3, 0.04)
    detail.addPath(_ellipse(0.5, 0.39, 0.13, 0.13))
    detail.addPath(_lines([(0.5, 0.55), (0.5, 0.63)]))
    return shield, detail


def _b_user():
    head = _ellipse(0.5, 0.25, 0.22, 0.24)
    body = QPainterPath()
    body.moveTo(0.02, 1)
    body.lineTo(0.02, 0.88)
    body.cubicTo(0.02, 0.5, 0.98, 0.5, 0.98, 0.88)
    body.lineTo(0.98, 1)
    body.closeSubpath()
    return _union(head, body), None


def _b_class():
    return _rect(0, 0, 1, 1), _lines([(0, 0.3), (1, 0.3)], [(0, 0.65), (1, 0.65)])


def _b_actor():
    detail = _ellipse(0.5, 0.12, 0.2, 0.11)
    detail.addPath(_lines([(0.5, 0.23), (0.5, 0.62)], [(0.05, 0.36), (0.95, 0.36)],
                          [(0.08, 1), (0.5, 0.62), (0.92, 1)]))
    return _rect(0, 0, 1, 1), detail


def _b_package():
    outline = _poly_path([(0, 0), (0.4, 0), (0.4, 0.15), (1, 0.15), (1, 1), (0, 1)])
    return outline, _lines([(0, 0.15), (0.4, 0.15)])


def _b_component():
    main = _rect(0.1, 0, 0.9, 1)
    tab1 = _rect(0, 0.2, 0.2, 0.15)
    tab2 = _rect(0, 0.6, 0.2, 0.15)
    detail = _rect(0, 0.2, 0.2, 0.15)
    detail.addRect(QRectF(0, 0.6, 0.2, 0.15))
    return _union(main, tab1, tab2), detail


def _b_final_state():
    return _ellipse(0.5, 0.5, 0.5, 0.5), _ellipse(0.5, 0.5, 0.3, 0.3)


def _b_lollipop():
    return _ellipse(0.5, 0.5, 0.5, 0.5), None


def _bpmn_event(ring: str = "start"):
    outline = _ellipse(0.5, 0.5, 0.48, 0.48)
    detail = (_ellipse(0.5, 0.5, 0.38, 0.38) if ring == "intermediate" else
              _ellipse(0.5, 0.5, 0.34, 0.34) if ring == "end" else None)
    return outline, detail


def _bpmn_event_marker(kind: str) -> QPainterPath:
    if kind == "timer":
        marker = _ellipse(0.5, 0.5, 0.34, 0.34)
        marker.addPath(_lines([(0.5, 0.22), (0.5, 0.5), (0.7, 0.61)],
                              [(0.4, 0.08), (0.6, 0.08)]))
        return marker
    if kind == "message":
        marker = _rect(0.12, 0.27, 0.76, 0.48)
        marker.addPath(_lines([(0.12, 0.27), (0.5, 0.56), (0.88, 0.27)]))
        return marker
    if kind == "error":
        return _poly_path([(0.58, 0.02), (0.3, 0.48), (0.48, 0.48),
                           (0.38, 0.98), (0.74, 0.4), (0.55, 0.4)])
    if kind == "signal":
        return _poly_path([(0.5, 0.08), (0.9, 0.86), (0.1, 0.86)])
    if kind == "escalation":
        return _poly_path([(0.5, 0.06), (0.82, 0.36), (0.62, 0.36), (0.82, 0.58),
                           (0.5, 0.9), (0.18, 0.58), (0.38, 0.58), (0.18, 0.36), (0.38, 0.36)])
    return QPainterPath()


def _bpmn_typed_event(kind: str, stage: str, filled: bool = False):
    outline = _ellipse(0.5, 0.5, 0.48, 0.48)
    detail = QPainterPath()
    if stage == "intermediate":
        detail.addPath(_ellipse(0.5, 0.5, 0.38, 0.38))
    elif stage == "end":
        if filled:
            ring = _ellipse(0.5, 0.5, 0.42, 0.42).subtracted(_ellipse(0.5, 0.5, 0.33, 0.33))
            detail.addPath(ring)
        else:
            detail.addPath(_ellipse(0.5, 0.5, 0.34, 0.34))
    marker = _bpmn_event_marker(kind)
    marker_size = {"start": 0.46, "intermediate": 0.34, "end": 0.29}[stage]
    detail.addPath(_fit(marker, marker_size, marker_size).translated(
        QPointF(0.5 - marker_size / 2, 0.5 - marker_size / 2)))
    return outline, detail


def _bpmn_gateway(marker: str = "xor"):
    outline = _poly_path([(0.5, 0), (1, 0.5), (0.5, 1), (0, 0.5)])
    if marker == "parallel":
        detail = _lines([(0.5, 0.28), (0.5, 0.72)], [(0.28, 0.5), (0.72, 0.5)])
    elif marker == "inclusive":
        detail = _ellipse(0.5, 0.5, 0.14, 0.14)
    elif marker == "event":
        detail = _poly_path([(0.5, 0.23), (0.73, 0.39), (0.65, 0.67),
                             (0.35, 0.67), (0.27, 0.39)])
    elif marker == "complex":
        detail = _lines([(0.5, 0.24), (0.5, 0.76)], [(0.24, 0.5), (0.76, 0.5)],
                        [(0.31, 0.31), (0.69, 0.69)], [(0.69, 0.31), (0.31, 0.69)])
    else:
        detail = _lines([(0.38, 0.38), (0.62, 0.62)], [(0.62, 0.38), (0.38, 0.62)])
    return outline, detail


def _bpmn_task(w: float, h: float):
    p = QPainterPath()
    p.addRoundedRect(QRectF(0, 0, w, h), min(w, h) * 0.1, min(w, h) * 0.1)
    return p, None


def _bpmn_task_marker(kind: str) -> QPainterPath:
    if kind == "user":
        marker = _ellipse(0.5, 0.2, 0.15, 0.15)
        marker.addPath(_lines([(0.17, 0.9), (0.2, 0.65), (0.5, 0.48), (0.8, 0.65), (0.83, 0.9)]))
        return marker
    if kind == "service":
        marker = _ellipse(0.5, 0.5, 0.23, 0.23)
        for angle in range(0, 360, 45):
            a = math.radians(angle)
            marker.addPath(_lines([(0.5 + 0.25 * math.cos(a), 0.5 + 0.25 * math.sin(a)),
                                   (0.5 + 0.42 * math.cos(a), 0.5 + 0.42 * math.sin(a))]))
        return marker
    if kind == "script":
        marker = _poly_path([(0.22, 0.08), (0.62, 0.08), (0.8, 0.26), (0.8, 0.92), (0.22, 0.92)])
        marker.addPath(_lines([(0.62, 0.08), (0.62, 0.26), (0.8, 0.26)],
                              [(0.32, 0.48), (0.69, 0.48)], [(0.32, 0.63), (0.69, 0.63)],
                              [(0.32, 0.78), (0.58, 0.78)]))
        return marker
    if kind == "manual":
        return _poly_path([(0.16, 0.62), (0.17, 0.36), (0.29, 0.34), (0.34, 0.59),
                           (0.37, 0.14), (0.49, 0.13), (0.53, 0.57), (0.58, 0.08),
                           (0.7, 0.1), (0.69, 0.58), (0.76, 0.23), (0.87, 0.29),
                           (0.78, 0.79), (0.61, 0.92), (0.31, 0.88)])
    if kind in ("send", "receive"):
        marker = _rect(0.15, 0.35, 0.7, 0.48)
        marker.addPath(_lines([(0.15, 0.35), (0.5, 0.62), (0.85, 0.35)]))
        if kind == "send":
            marker.addPath(_lines([(0.5, 0.02), (0.5, 0.25)], [(0.37, 0.16), (0.5, 0.29), (0.63, 0.16)]))
        else:
            marker.addPath(_lines([(0.5, 0.3), (0.5, 0.05)], [(0.37, 0.17), (0.5, 0.04), (0.63, 0.17)]))
        return marker
    if kind == "rule":
        marker = _rect(0.12, 0.16, 0.76, 0.68)
        marker.addPath(_lines([(0.12, 0.4), (0.88, 0.4)], [(0.12, 0.62), (0.88, 0.62)],
                              [(0.5, 0.4), (0.5, 0.84)]))
        return marker
    return QPainterPath()


def _bpmn_typed_task(kind: str):
    def build(w: float, h: float):
        outline = QPainterPath()
        outline.addRoundedRect(QRectF(0, 0, w, h), min(w, h) * 0.1, min(w, h) * 0.1)
        marker_size = min(w, h) * 0.3
        detail = _fit(_bpmn_task_marker(kind), marker_size, marker_size).translated(
            QPointF(w * 0.06, h * 0.06))
        return outline, detail
    return build


def _bpmn_subprocess(w: float, h: float):
    p = QPainterPath()
    p.addRoundedRect(QRectF(0, 0, w, h), min(w, h) * 0.08, min(w, h) * 0.08)
    detail = _lines([(w * 0.45, h * 0.88), (w * 0.55, h * 0.88)],
                    [(w * 0.5, h * 0.83), (w * 0.5, h * 0.93)])
    return p, detail


def _floor_window(w: float, h: float):
    p = QPainterPath()
    p.addRect(QRectF(0, 0, w, h))
    detail = _lines([(w / 3, 0), (w / 3, h)], [(2 * w / 3, 0), (2 * w / 3, h)])
    return p, detail


def _floor_desk(w: float, h: float):
    p = QPainterPath()
    p.addRoundedRect(QRectF(0, 0, w, h * 0.72), min(w, h) * 0.05, min(w, h) * 0.05)
    detail = _lines([(w * 0.12, h * 0.72), (w * 0.12, h)],
                    [(w * 0.88, h * 0.72), (w * 0.88, h)])
    return p, detail


def _floor_stairs(w: float, h: float):
    p = QPainterPath()
    p.addRect(QRectF(0, 0, w, h))
    detail = _lines(*[[(0, h * i / 7), (w, h * i / 7)] for i in range(1, 7)])
    return p, detail


def _floor_door():
    leaf = _lines([(0.5, 0.5), (0.5, 0)])
    swing = QPainterPath()
    swing.arcMoveTo(QRectF(0, 0, 1, 1), 90)
    swing.arcTo(QRectF(0, 0, 1, 1), 90, -90)
    return leaf, swing


def _circuit_resistor():
    return _lines([(0, 0.5), (0.15, 0.5), (0.25, 0.25), (0.4, 0.75), (0.55, 0.25),
                   (0.7, 0.75), (0.85, 0.5), (1, 0.5)]), None


def _circuit_capacitor():
    return _lines([(0, 0.5), (0.42, 0.5)], [(0.42, 0.15), (0.42, 0.85)],
                  [(0.58, 0.15), (0.58, 0.85)], [(0.58, 0.5), (1, 0.5)]), None


def _circuit_battery():
    return _lines([(0, 0.5), (0.38, 0.5)], [(0.38, 0.2), (0.38, 0.8)],
                  [(0.55, 0.33), (0.55, 0.67)], [(0.55, 0.5), (1, 0.5)]), None


def _circuit_ground():
    return _lines([(0.5, 0), (0.5, 0.48)], [(0.2, 0.48), (0.8, 0.48)],
                  [(0.3, 0.65), (0.7, 0.65)], [(0.4, 0.82), (0.6, 0.82)]), None


def _circuit_lamp():
    outline = _ellipse(0.5, 0.5, 0.38, 0.38)
    detail = _lines([(0.3, 0.3), (0.7, 0.7)], [(0.7, 0.3), (0.3, 0.7)],
                    [(0, 0.5), (0.12, 0.5)], [(0.88, 0.5), (1, 0.5)])
    return outline, detail


def _arrow_pts(direction: str):
    right = [(0, 0.25), (0.6, 0.25), (0.6, 0), (1, 0.5), (0.6, 1), (0.6, 0.75), (0, 0.75)]
    if direction == "right":
        return right
    if direction == "left":
        return [(1 - x, y) for x, y in right]
    if direction == "down":
        return [(y, x) for x, y in right]
    return [(y, 1 - x) for x, y in right]


# ------------------------------------------------------------------ catalogue

BASIC = "Formes de base"
FLOW = "Diagramme de flux"
ARROWS_CAT = "Flèches"
ORG = "Organigramme hiérarchique"
NET = "Réseau"
UML = "UML / Logiciel"
CFF = "Diagramme de flux interfonctionnel"
BPMN = "BPMN"
CIRCUIT = "Schéma électrique"
FLOORPLAN = "Plan d’aménagement"

CATEGORIES = (BASIC, FLOW, BPMN, CFF, FLOORPLAN, CIRCUIT, ARROWS_CAT, ORG, NET, UML)

_TRI_PORTS = ((0.5, 0.0), (0.75, 0.5), (0.5, 1.0), (0.25, 0.5))
_LABEL_BELOW = (-0.6, 1.04, 2.2, 0.55)
_NO_FILL = {"fill": "", "line": "", "themed": False}

_DEFS: list[ShapeDef] = [
    # Formes de base
    ShapeDef("basic.rectangle", "Rectangle", BASIC, _b_rect, (35, 22), SIDES_AND_CORNERS,
             keywords="carré boîte rectangle process", roundable=True),
    ShapeDef("basic.rounded", "Rectangle arrondi", BASIC, _b_round, (35, 22), SIDES_AND_CORNERS,
             keywords="arrondi bouton"),
    ShapeDef("basic.square", "Carré", BASIC, _b_rect, (25, 25), SIDES_AND_CORNERS, roundable=True),
    ShapeDef("basic.ellipse", "Ellipse", BASIC, _b_ellipse, (35, 22), keywords="ovale rond"),
    ShapeDef("basic.circle", "Cercle", BASIC, _b_ellipse, (25, 25), keywords="rond disque"),
    ShapeDef("basic.triangle", "Triangle", BASIC, _poly([(0.5, 0), (1, 1), (0, 1)]), (28, 24),
             _TRI_PORTS, text_rect=(0.2, 0.4, 0.6, 0.6)),
    ShapeDef("basic.right_triangle", "Triangle rectangle", BASIC, _poly([(0, 0), (1, 1), (0, 1)]),
             (25, 25), ((0, 0.5), (0.5, 1), (0.5, 0.5), (0, 1)), text_rect=(0, 0.45, 0.6, 0.55)),
    ShapeDef("basic.diamond", "Losange", BASIC,
             _poly([(0.5, 0), (1, 0.5), (0.5, 1), (0, 0.5)]), (30, 25)),
    ShapeDef("basic.pentagon", "Pentagone", BASIC, _poly(regular_polygon(5)), (26, 25)),
    ShapeDef("basic.hexagon", "Hexagone", BASIC,
             _poly([(0.25, 0), (0.75, 0), (1, 0.5), (0.75, 1), (0.25, 1), (0, 0.5)]), (30, 25)),
    ShapeDef("basic.octagon", "Octogone", BASIC,
             _poly([(0.3, 0), (0.7, 0), (1, 0.3), (1, 0.7), (0.7, 1), (0.3, 1), (0, 0.7), (0, 0.3)]),
             (25, 25), keywords="stop"),
    ShapeDef("basic.star", "Étoile", BASIC, _poly(regular_polygon(5, inner=0.4)), (26, 25),
             text_rect=(0.25, 0.3, 0.5, 0.45)),
    ShapeDef("basic.parallelogram", "Parallélogramme", BASIC,
             _poly([(0.2, 0), (1, 0), (0.8, 1), (0, 1)]), (35, 20)),
    ShapeDef("basic.trapezoid", "Trapèze", BASIC, _poly([(0.2, 0), (0.8, 0), (1, 1), (0, 1)]), (35, 20)),
    ShapeDef("basic.cross", "Croix", BASIC,
             _poly([(0.33, 0), (0.67, 0), (0.67, 0.33), (1, 0.33), (1, 0.67), (0.67, 0.67), (0.67, 1),
                    (0.33, 1), (0.33, 0.67), (0, 0.67), (0, 0.33), (0.33, 0.33)]), (25, 25),
             keywords="plus"),
    ShapeDef("basic.cylinder", "Cylindre", BASIC, _b_cylinder, (25, 30), text_rect=(0, 0.25, 1, 0.75)),
    ShapeDef("basic.cube", "Cube", BASIC, _unit(_b_cube), (30, 28), text_rect=(0, 0.2, 0.8, 0.8),
             keywords="boîte 3d"),
    ShapeDef("basic.cloud", "Nuage", BASIC, _unit(_b_cloud), (40, 26), text_rect=(0.15, 0.2, 0.7, 0.6)),
    ShapeDef("basic.note", "Note", BASIC, _unit(_b_note), (35, 30), keywords="post-it commentaire",
             style={"fill": "#fff2cc", "line": "#bf9000", "themed": False}, text={"color": "#3f3f3f"}),
    ShapeDef("basic.callout", "Bulle", BASIC, _unit(_b_callout), (40, 26),
             text_rect=(0, 0, 1, 0.78), keywords="légende dialogue"),
    ShapeDef("basic.container", "Conteneur", BASIC, _unit(_b_container), (90, 60), SIDES_AND_CORNERS,
             text_rect=(0, 0, 1, 0.14), keywords="groupe zone cadre couloir",
             style={"fill": "#f2f6fc", "line": "#8eaadb", "themed": False},
             text={"color": "#1f3864", "bold": True, "valign": "middle", "halign": "left"},
             container=True, default_text="Conteneur"),
    ShapeDef("basic.text", "Zone de texte", BASIC, _b_rect, (40, 12), SIDES,
             keywords="texte étiquette", style=dict(_NO_FILL), text={"color": "#000000"},
             default_text="Texte"),
    ShapeDef("basic.title", "Titre", BASIC, _b_rect, (110, 16), SIDES,
             keywords="titre en-tête", style=dict(_NO_FILL),
             text={"color": "#1f3864", "size": 22.0, "bold": True}, default_text="Titre"),

    # Diagramme de flux
    ShapeDef("flow.process", "Processus", FLOW, _b_rect, (35, 22), SIDES_AND_CORNERS,
             keywords="étape action tâche", roundable=True),
    ShapeDef("flow.decision", "Décision", FLOW,
             _poly([(0.5, 0), (1, 0.5), (0.5, 1), (0, 0.5)]), (35, 25), keywords="condition si choix"),
    ShapeDef("flow.terminator", "Début / Fin", FLOW, _b_stadium, (35, 15),
             keywords="début fin terminaison départ"),
    ShapeDef("flow.data", "Données", FLOW, _poly([(0.2, 0), (1, 0), (0.8, 1), (0, 1)]), (35, 20),
             keywords="entrée sortie io"),
    ShapeDef("flow.document", "Document", FLOW, _unit(_b_document), (35, 22),
             text_rect=(0, 0, 1, 0.8)),
    ShapeDef("flow.multidocument", "Documents multiples", FLOW, _unit(_b_multidoc), (35, 24),
             text_rect=(0, 0.14, 0.88, 0.7)),
    ShapeDef("flow.subprocess", "Sous-processus", FLOW, _unit(_b_subprocess), (35, 22),
             text_rect=(0.1, 0, 0.8, 1), keywords="processus prédéfini fonction"),
    ShapeDef("flow.database", "Base de données", FLOW, _b_cylinder, (25, 28),
             text_rect=(0, 0.25, 1, 0.75), keywords="stockage données sgbd"),
    ShapeDef("flow.preparation", "Préparation", FLOW,
             _poly([(0.15, 0), (0.85, 0), (1, 0.5), (0.85, 1), (0.15, 1), (0, 0.5)]), (35, 20),
             keywords="initialisation boucle"),
    ShapeDef("flow.manual_input", "Entrée manuelle", FLOW,
             _poly([(0, 0.3), (1, 0), (1, 1), (0, 1)]), (35, 20), text_rect=(0, 0.3, 1, 0.7)),
    ShapeDef("flow.manual_operation", "Opération manuelle", FLOW,
             _poly([(0, 0), (1, 0), (0.8, 1), (0.2, 1)]), (35, 20)),
    ShapeDef("flow.delay", "Délai", FLOW, _b_delay, (30, 20), keywords="attente"),
    ShapeDef("flow.display", "Affichage", FLOW, _b_display, (35, 20), keywords="écran"),
    ShapeDef("flow.internal_storage", "Stockage interne", FLOW, _unit(_b_internal_storage), (28, 22),
             text_rect=(0.15, 0.2, 0.85, 0.8), keywords="mémoire"),
    ShapeDef("flow.connector", "Connecteur de renvoi", FLOW, _b_ellipse, (12, 12),
             keywords="cercle référence", text={"size": 9.0}),
    ShapeDef("flow.offpage", "Renvoi de page", FLOW,
             _poly([(0, 0), (1, 0), (1, 0.6), (0.5, 1), (0, 0.6)]), (15, 15),
             text_rect=(0, 0, 1, 0.6), keywords="autre page"),
    ShapeDef("flow.annotation", "Annotation", FLOW, _unit(_b_annotation), (35, 18),
             keywords="commentaire remarque", style=dict(_NO_FILL, line="#404040"),
             text={"color": "#000000", "halign": "left"}, text_rect=(0.05, 0, 0.95, 1),
             outline_visible=False),

    # Flèches
    ShapeDef("arrow.right", "Flèche droite", ARROWS_CAT, _poly(_arrow_pts("right")), (35, 18),
             text_rect=(0, 0.25, 0.75, 0.5)),
    ShapeDef("arrow.left", "Flèche gauche", ARROWS_CAT, _poly(_arrow_pts("left")), (35, 18),
             text_rect=(0.25, 0.25, 0.75, 0.5)),
    ShapeDef("arrow.up", "Flèche haut", ARROWS_CAT, _poly(_arrow_pts("up")), (18, 35),
             text_rect=(0.25, 0.3, 0.5, 0.7)),
    ShapeDef("arrow.down", "Flèche bas", ARROWS_CAT, _poly(_arrow_pts("down")), (18, 35),
             text_rect=(0.25, 0, 0.5, 0.7)),
    ShapeDef("arrow.double", "Double flèche", ARROWS_CAT,
             _poly([(0, 0.5), (0.25, 0), (0.25, 0.25), (0.75, 0.25), (0.75, 0), (1, 0.5), (0.75, 1),
                    (0.75, 0.75), (0.25, 0.75), (0.25, 1)]), (40, 18),
             text_rect=(0.2, 0.25, 0.6, 0.5)),
    ShapeDef("arrow.chevron", "Chevron", ARROWS_CAT,
             _poly([(0, 0), (0.75, 0), (1, 0.5), (0.75, 1), (0, 1), (0.25, 0.5)]), (35, 18),
             text_rect=(0.2, 0, 0.6, 1), keywords="étape processus"),
    ShapeDef("arrow.pentagon", "Pentagone fléché", ARROWS_CAT,
             _poly([(0, 0), (0.78, 0), (1, 0.5), (0.78, 1), (0, 1)]), (35, 18),
             text_rect=(0, 0, 0.85, 1), keywords="jalon étape"),

    # Organigramme hiérarchique
    ShapeDef("org.executive", "Cadre dirigeant", ORG, _b_rect, (45, 20), SIDES,
             style={"fill": "#1f4e79", "line": "#16375a", "themed": False},
             text={"color": "#ffffff", "bold": True}, default_text="Nom\nDirecteur général",
             keywords="directeur pdg chef"),
    ShapeDef("org.manager", "Responsable", ORG, _b_rect, (45, 20), SIDES,
             style={"fill": "#2e75b6", "line": "#1f4e79", "themed": False},
             text={"color": "#ffffff"}, default_text="Nom\nResponsable", keywords="manager chef"),
    ShapeDef("org.employee", "Collaborateur", ORG, _b_rect, (45, 20), SIDES,
             style={"fill": "#bdd7ee", "line": "#2e75b6", "themed": False},
             text={"color": "#1f3864"}, default_text="Nom\nFonction", keywords="employé poste"),
    ShapeDef("org.assistant", "Assistant", ORG, _b_round, (40, 18), SIDES,
             style={"fill": "#deebf7", "line": "#5b9bd5", "themed": False},
             text={"color": "#1f3864"}, default_text="Nom\nAssistant"),
    ShapeDef("org.vacancy", "Poste vacant", ORG, _b_rect, (45, 20), SIDES,
             style={"fill": "#ffffff", "line": "#7f7f7f", "dash": "dash", "themed": False},
             text={"color": "#7f7f7f", "italic": True}, default_text="Poste vacant"),

    # Réseau
    ShapeDef("net.server", "Serveur", NET, _unit(_b_server), (16, 26), text_rect=_LABEL_BELOW,
             label_outside=True, keywords="serveur machine"),
    ShapeDef("net.pc", "Ordinateur", NET, _unit(_b_pc), (24, 22), text_rect=_LABEL_BELOW,
             label_outside=True, keywords="pc poste station"),
    ShapeDef("net.laptop", "Ordinateur portable", NET, _unit(_b_laptop), (26, 18),
             text_rect=_LABEL_BELOW, label_outside=True, keywords="portable laptop"),
    ShapeDef("net.router", "Routeur", NET, _unit(_b_router), (24, 16), text_rect=_LABEL_BELOW,
             label_outside=True),
    ShapeDef("net.switch", "Commutateur", NET, _unit(_b_switch), (28, 14), text_rect=_LABEL_BELOW,
             label_outside=True, keywords="switch"),
    ShapeDef("net.firewall", "Pare-feu", NET, _unit(_b_firewall), (22, 20), text_rect=_LABEL_BELOW,
             label_outside=True, keywords="firewall sécurité",
             style={"fill": "#c55a11", "line": "#843c0c", "themed": False}),
    ShapeDef("net.cloud", "Internet", NET, _unit(_b_cloud), (34, 22), text_rect=(0.15, 0.2, 0.7, 0.6),
             keywords="nuage cloud web", default_text="Internet"),
    ShapeDef("net.database", "Base de données", NET, _b_database, (20, 26), text_rect=_LABEL_BELOW,
             label_outside=True, keywords="sgbd stockage"),
    ShapeDef("net.printer", "Imprimante", NET, _unit(_b_printer), (24, 22), text_rect=_LABEL_BELOW,
             label_outside=True),
    ShapeDef("net.phone", "Mobile", NET, _unit(_b_phone), (12, 22), text_rect=_LABEL_BELOW,
             label_outside=True, keywords="téléphone smartphone"),
    ShapeDef("net.wifi", "Point d'accès Wi-Fi", NET, _unit(_b_wifi), (22, 20), text_rect=_LABEL_BELOW,
             label_outside=True, keywords="sans fil wifi borne"),
    ShapeDef("net.load_balancer", "Équilibreur de charge", NET, _unit(_b_load_balancer), (34, 20),
             text_rect=_LABEL_BELOW, label_outside=True, keywords="load balancer répartiteur trafic réseau",
             style={"fill": "#d9eaf7", "line": "#356e9f", "themed": False}),
    ShapeDef("net.rack", "Baie de serveurs", NET, _unit(_b_rack), (22, 34), text_rect=_LABEL_BELOW,
             label_outside=True, keywords="rack armoire serveur datacenter",
             style={"fill": "#d9e2f3", "line": "#44546a", "themed": False}),
    ShapeDef("net.vm", "Machine virtuelle", NET, _unit(_b_vm), (24, 22), text_rect=_LABEL_BELOW,
             label_outside=True, keywords="virtual machine vm hyperviseur",
             style={"fill": "#eaf2f8", "line": "#356e9f", "themed": False}),
    ShapeDef("net.storage", "Stockage réseau", NET, _unit(_b_storage), (20, 26), text_rect=_LABEL_BELOW,
             label_outside=True, keywords="nas san disque stockage cloud",
             style={"fill": "#e2f0d9", "line": "#548235", "themed": False}),
    ShapeDef("net.vpn", "Passerelle VPN", NET, _unit(_b_vpn), (18, 24), text_rect=_LABEL_BELOW,
             label_outside=True, keywords="vpn tunnel accès distant sécurisé",
             style={"fill": "#d9eaf7", "line": "#356e9f", "themed": False}),
    ShapeDef("net.subnet", "Frontière réseau", NET, _unit(_b_container), (90, 60), SIDES_AND_CORNERS,
             text_rect=(0, 0, 1, 0.14), keywords="sous-réseau subnet zone sécurité vpc vlan",
             style={"fill": "#f0f5fb", "line": "#356e9f", "dash": "dash", "themed": False},
             text={"color": "#1f3864", "bold": True, "halign": "left", "valign": "middle"},
             container=True, default_text="Réseau privé"),
    ShapeDef("net.user", "Utilisateur", NET, _unit(_b_user), (18, 20), text_rect=_LABEL_BELOW,
             label_outside=True, keywords="personne client"),

    # UML / Logiciel
    ShapeDef("uml.class", "Classe", UML, _unit(_b_class), (40, 35), SIDES_AND_CORNERS,
             text_rect=(0, 0, 1, 0.3), text={"bold": True}, default_text="Classe"),
    ShapeDef("uml.actor", "Acteur", UML, _unit(_b_actor), (12, 24), text_rect=_LABEL_BELOW,
             label_outside=True, outline_visible=False, keywords="utilisateur personnage",
             default_text="Acteur"),
    ShapeDef("uml.usecase", "Cas d'utilisation", UML, _b_ellipse, (40, 20),
             keywords="use case fonctionnalité"),
    ShapeDef("uml.note", "Note UML", UML, _unit(_b_note), (35, 25),
             style={"fill": "#fff2cc", "line": "#7f6000", "themed": False}, text={"color": "#3f3f3f"}),
    ShapeDef("uml.package", "Paquetage", UML, _unit(_b_package), (40, 30),
             text_rect=(0, 0.15, 1, 0.85), keywords="package module"),
    ShapeDef("uml.component", "Composant", UML, _unit(_b_component), (40, 25),
             text_rect=(0.2, 0, 0.8, 1), keywords="module service"),
    ShapeDef("uml.node", "Nœud", UML, _unit(_b_cube), (35, 30), text_rect=(0, 0.2, 0.8, 0.8),
             keywords="machine déploiement"),
    ShapeDef("uml.state", "État", UML, _b_round, (35, 18), keywords="statut"),
    ShapeDef("uml.initial", "État initial", UML, _b_ellipse, (8, 8),
             style={"fill": "#000000", "line": "#000000", "themed": False}, keywords="début"),
    ShapeDef("uml.final", "État final", UML, _unit(_b_final_state), (9, 9),
             style={"fill": "#ffffff", "line": "#000000", "themed": False}, detail_fill=True,
             keywords="fin"),
    ShapeDef("uml.interface", "Interface", UML, _unit(_b_lollipop), (8, 8), text_rect=(-2, 1.1, 5, 1.5),
             label_outside=True, keywords="lollipop api"),

    # BPMN 2.0 : événements, activités, passerelles et données.
    ShapeDef("bpmn.start", "Événement de début", BPMN, _unit(lambda: _bpmn_event("start")), (18, 18),
             text_rect=_LABEL_BELOW, label_outside=True, keywords="start event début bpmn",
             style={"fill": "#ffffff", "line": "#404040", "themed": False}),
    ShapeDef("bpmn.intermediate", "Événement intermédiaire", BPMN,
             _unit(lambda: _bpmn_event("intermediate")), (18, 18), text_rect=_LABEL_BELOW,
             label_outside=True, keywords="intermediate event bpmn",
             style={"fill": "#ffffff", "line": "#404040", "themed": False}),
    ShapeDef("bpmn.end", "Événement de fin", BPMN, _unit(lambda: _bpmn_event("end")), (18, 18),
             text_rect=_LABEL_BELOW, label_outside=True, keywords="end event fin bpmn",
             style={"fill": "#ffffff", "line": "#404040", "line_width": 2.25, "themed": False}),
    ShapeDef("bpmn.message_start", "Début par message", BPMN,
             _unit(lambda: _bpmn_typed_event("message", "start")), (18, 18),
             text_rect=_LABEL_BELOW, label_outside=True, keywords="message start événement réception bpmn",
             style={"fill": "#ffffff", "line": "#404040", "themed": False}),
    ShapeDef("bpmn.message_intermediate", "Événement de message", BPMN,
             _unit(lambda: _bpmn_typed_event("message", "intermediate")), (18, 18),
             text_rect=_LABEL_BELOW, label_outside=True, keywords="message intermédiaire bpmn",
             style={"fill": "#ffffff", "line": "#404040", "themed": False}),
    ShapeDef("bpmn.timer_start", "Début temporisé", BPMN,
             _unit(lambda: _bpmn_typed_event("timer", "start")), (18, 18),
             text_rect=_LABEL_BELOW, label_outside=True, keywords="timer délai déclencheur horloge bpmn",
             style={"fill": "#ffffff", "line": "#404040", "themed": False}),
    ShapeDef("bpmn.timer_intermediate", "Événement temporel", BPMN,
             _unit(lambda: _bpmn_typed_event("timer", "intermediate")), (18, 18),
             text_rect=_LABEL_BELOW, label_outside=True, keywords="timer intermédiaire horloge bpmn",
             style={"fill": "#ffffff", "line": "#404040", "themed": False}),
    ShapeDef("bpmn.error_end", "Fin par erreur", BPMN,
             _unit(lambda: _bpmn_typed_event("error", "end", True)), (18, 18),
             text_rect=_LABEL_BELOW, label_outside=True, keywords="erreur exception end bpmn",
             style={"fill": "#ffffff", "line": "#404040", "line_width": 2.25, "themed": False},
             detail_fill=True),
    ShapeDef("bpmn.signal_start", "Début par signal", BPMN,
             _unit(lambda: _bpmn_typed_event("signal", "start")), (18, 18),
             text_rect=_LABEL_BELOW, label_outside=True, keywords="signal start bpmn",
             style={"fill": "#ffffff", "line": "#404040", "themed": False}),
    ShapeDef("bpmn.signal_end", "Fin par signal", BPMN,
             _unit(lambda: _bpmn_typed_event("signal", "end", True)), (18, 18),
             text_rect=_LABEL_BELOW, label_outside=True, keywords="signal end bpmn",
             style={"fill": "#ffffff", "line": "#404040", "line_width": 2.25, "themed": False},
             detail_fill=True),
    ShapeDef("bpmn.task", "Tâche", BPMN, _bpmn_task, (42, 25), keywords="activité task activity bpmn",
             style={"fill": "#ffffff", "line": "#404040", "themed": False}),
    ShapeDef("bpmn.user_task", "Tâche utilisateur", BPMN, _bpmn_typed_task("user"), (42, 25),
             keywords="user task personne humaine formulaire bpmn",
             style={"fill": "#ffffff", "line": "#404040", "themed": False}),
    ShapeDef("bpmn.service_task", "Tâche de service", BPMN, _bpmn_typed_task("service"), (42, 25),
             keywords="service automatisation api engrenage bpmn",
             style={"fill": "#ffffff", "line": "#404040", "themed": False}),
    ShapeDef("bpmn.script_task", "Tâche de script", BPMN, _bpmn_typed_task("script"), (42, 25),
             keywords="script code document bpmn",
             style={"fill": "#ffffff", "line": "#404040", "themed": False}),
    ShapeDef("bpmn.manual_task", "Tâche manuelle", BPMN, _bpmn_typed_task("manual"), (42, 25),
             keywords="manual main humaine opérateur bpmn",
             style={"fill": "#ffffff", "line": "#404040", "themed": False}),
    ShapeDef("bpmn.send_task", "Tâche d’envoi", BPMN, _bpmn_typed_task("send"), (42, 25),
             keywords="send envoyer message communication bpmn",
             style={"fill": "#ffffff", "line": "#404040", "themed": False}),
    ShapeDef("bpmn.receive_task", "Tâche de réception", BPMN, _bpmn_typed_task("receive"), (42, 25),
             keywords="receive recevoir message communication bpmn",
             style={"fill": "#ffffff", "line": "#404040", "themed": False}),
    ShapeDef("bpmn.rule_task", "Tâche de règle métier", BPMN, _bpmn_typed_task("rule"), (42, 25),
             keywords="business rule table décision bpmn",
             style={"fill": "#ffffff", "line": "#404040", "themed": False}),
    ShapeDef("bpmn.subprocess", "Sous-processus", BPMN, _bpmn_subprocess, (42, 25),
             keywords="activité imbriquée subprocess bpmn",
             style={"fill": "#ffffff", "line": "#404040", "themed": False}),
    ShapeDef("bpmn.gateway_xor", "Passerelle exclusive", BPMN, _unit(lambda: _bpmn_gateway("xor")), (22, 22),
             text_rect=_LABEL_BELOW, label_outside=True, keywords="gateway xor décision bpmn",
             style={"fill": "#ffffff", "line": "#404040", "themed": False}),
    ShapeDef("bpmn.gateway_parallel", "Passerelle parallèle", BPMN,
             _unit(lambda: _bpmn_gateway("parallel")), (22, 22), text_rect=_LABEL_BELOW,
             label_outside=True, keywords="gateway parallel parallèle bpmn",
             style={"fill": "#ffffff", "line": "#404040", "themed": False}),
    ShapeDef("bpmn.gateway_inclusive", "Passerelle inclusive", BPMN,
             _unit(lambda: _bpmn_gateway("inclusive")), (22, 22), text_rect=_LABEL_BELOW,
             label_outside=True, keywords="gateway inclusive bpmn",
             style={"fill": "#ffffff", "line": "#404040", "themed": False}),
    ShapeDef("bpmn.gateway_event", "Passerelle événementielle", BPMN,
             _unit(lambda: _bpmn_gateway("event")), (22, 22), text_rect=_LABEL_BELOW,
             label_outside=True, keywords="gateway événement event bpmn",
             style={"fill": "#ffffff", "line": "#404040", "themed": False}),
    ShapeDef("bpmn.gateway_complex", "Passerelle complexe", BPMN,
             _unit(lambda: _bpmn_gateway("complex")), (22, 22), text_rect=_LABEL_BELOW,
             label_outside=True, keywords="gateway règle complexe bpmn",
             style={"fill": "#ffffff", "line": "#404040", "themed": False}),
    ShapeDef("bpmn.data", "Objet de données", BPMN, _unit(_b_note), (22, 28),
             text_rect=(0.05, 0.2, 0.75, 0.7), keywords="data object document bpmn",
             style={"fill": "#ffffff", "line": "#404040", "themed": False}),
    ShapeDef("bpmn.datastore", "Magasin de données", BPMN, _b_cylinder, (24, 28),
             text_rect=(0, 0.25, 1, 0.65), keywords="data store base de données bpmn",
             style={"fill": "#ffffff", "line": "#404040", "themed": False}),

    # Plan d'aménagement et mobilier de bureau.
    ShapeDef("floor.room", "Pièce", FLOORPLAN, _b_rect, (180, 120), SIDES_AND_CORNERS,
             text_rect=(0.03, 0.03, 0.94, 0.18), keywords="room plan pièce bureau",
             style={"fill": "#f8f9fb", "line": "#404040", "line_width": 2.0, "themed": False},
             text={"halign": "left", "valign": "top"}, container=True, default_text="Pièce"),
    ShapeDef("floor.wall", "Mur", FLOORPLAN, _b_rect, (60, 12), SIDES_AND_CORNERS,
             keywords="wall cloison",
             style={"fill": "#7f7f7f", "line": "#404040", "themed": False}),
    ShapeDef("floor.door", "Porte", FLOORPLAN, _unit(_floor_door), (30, 30),
             keywords="door ouverture",
             style={"fill": "", "line": "#404040", "line_width": 1.5, "themed": False}),
    ShapeDef("floor.window", "Fenêtre", FLOORPLAN, _floor_window, (42, 10),
             keywords="window baie vitrée",
             style={"fill": "#d9eaf7", "line": "#404040", "themed": False}),
    ShapeDef("floor.desk", "Bureau", FLOORPLAN, _floor_desk, (38, 25), keywords="desk mobilier",
             style={"fill": "#d6c2a1", "line": "#6b5b45", "themed": False}),
    ShapeDef("floor.table", "Table", FLOORPLAN, _b_ellipse, (40, 28), keywords="table mobilier",
             style={"fill": "#d6c2a1", "line": "#6b5b45", "themed": False}),
    ShapeDef("floor.chair", "Chaise", FLOORPLAN, _b_round, (22, 22), keywords="chair siège mobilier",
             style={"fill": "#b4c7e7", "line": "#44546a", "themed": False}),
    ShapeDef("floor.bed", "Lit", FLOORPLAN, _unit(_b_container), (45, 65),
             text_rect=(0.08, 0.2, 0.84, 0.75), keywords="bed chambre mobilier",
             style={"fill": "#e2f0d9", "line": "#548235", "themed": False}),
    ShapeDef("floor.stairs", "Escalier", FLOORPLAN, _floor_stairs, (35, 65),
             keywords="stairs marches",
             style={"fill": "#eeeeee", "line": "#404040", "themed": False}),

    # Symboles électriques de base.
    ShapeDef("circuit.resistor", "Résistance", CIRCUIT, _unit(_circuit_resistor), (40, 12),
             keywords="resistor ohm composant",
             style={"fill": "", "line": "#202020", "themed": False}),
    ShapeDef("circuit.capacitor", "Condensateur", CIRCUIT, _unit(_circuit_capacitor), (24, 18),
             keywords="capacitor capacité composant",
             style={"fill": "", "line": "#202020", "themed": False}),
    ShapeDef("circuit.battery", "Pile", CIRCUIT, _unit(_circuit_battery), (24, 18),
             keywords="battery batterie alimentation",
             style={"fill": "", "line": "#202020", "themed": False}),
    ShapeDef("circuit.ground", "Masse", CIRCUIT, _unit(_circuit_ground), (18, 20),
             keywords="ground terre électrique",
             style={"fill": "", "line": "#202020", "themed": False}),
    ShapeDef("circuit.lamp", "Lampe", CIRCUIT, _unit(_circuit_lamp), (20, 20),
             keywords="ampoule light",
             style={"fill": "#fff2cc", "line": "#202020", "themed": False}),
]

_CFF_STYLE = {"fill": "#dce6f2", "line": "#7f9cc9", "themed": False}
_CFF_TEXT = {"color": "#1f3864", "size": 12.0}
_DEFS += [
    ShapeDef("cff.lane_h", "Couloir", CFF, _b_rect, (230, 35), (), keywords="couloir swimlane fonction acteur "
             "interfonctionnel horizontal", style=dict(_CFF_STYLE), text=dict(_CFF_TEXT), container=True,
             default_text="Fonction", cff="lane_h"),
    ShapeDef("cff.lane_v", "Couloir vertical", CFF, _b_rect, (40, 150), (), keywords="couloir swimlane fonction "
             "interfonctionnel vertical colonne", style=dict(_CFF_STYLE), text=dict(_CFF_TEXT), container=True,
             default_text="Fonction", cff="lane_v"),
    ShapeDef("cff.phase_h", "Séparateur", CFF, _b_rect, (60, 80), (), keywords="séparateur phase étape "
             "jalon interfonctionnel", style={"fill": "#eef2f9", "line": "#7f9cc9", "themed": False},
             text=dict(_CFF_TEXT), container=True, default_text="Phase", cff="phase_h"),
    ShapeDef("cff.phase_v", "Séparateur vertical", CFF, _b_rect, (150, 50), (), keywords="séparateur phase "
             "interfonctionnel vertical", style={"fill": "#eef2f9", "line": "#7f9cc9", "themed": False},
             text=dict(_CFF_TEXT), container=True, default_text="Phase", cff="phase_v"),
    ShapeDef("cff.frame_h", "Cadre", CFF, _b_rect, (230, 115), (),
             keywords="cadre titre interfonctionnel couloirs horizontal", style=dict(_CFF_STYLE),
             text={"color": "#1f3864", "size": 14.0, "bold": True}, container=True,
             default_text="Titre du diagramme", cff="frame_h"),
    ShapeDef("cff.frame_v", "Cadre vertical", CFF, _b_rect, (130, 160), (),
             keywords="cadre titre interfonctionnel couloirs vertical", style=dict(_CFF_STYLE),
             text={"color": "#1f3864", "size": 14.0, "bold": True}, container=True,
             default_text="Titre du diagramme", cff="frame_v"),
]

# Formes non présentées dans les gabarits mais nécessaires (images, import VSDX).
_HIDDEN: list[ShapeDef] = [
    ShapeDef("special.image", "Image", "", _b_rect, (40, 30), SIDES_AND_CORNERS,
             style=dict(_NO_FILL), text_rect=_LABEL_BELOW, label_outside=True),
    ShapeDef("special.custom", "Forme personnalisée", "", _b_rect, (30, 20), SIDES_AND_CORNERS),
]

SHAPES: dict[str, ShapeDef] = {d.type_id: d for d in _DEFS + _HIDDEN}
FALLBACK_TYPE = "basic.rectangle"


def get(type_id: str) -> ShapeDef:
    return SHAPES.get(type_id) or SHAPES[FALLBACK_TYPE]


def by_category(category: str) -> list[ShapeDef]:
    return [d for d in _DEFS if d.category == category]


def search(query: str) -> list[ShapeDef]:
    q = query.strip().lower()
    if not q:
        return []
    out = []
    for d in _DEFS:
        hay = f"{d.name} {d.keywords} {d.category}".lower()
        if all(word in hay for word in q.split()):
            out.append(d)
    return out


def custom_path(commands: list, w: float, h: float) -> QPainterPath:
    """Chemin d'une forme personnalisée (géométrie importée d'un fichier Visio).

    Commandes normalisées : ["M",x,y] ["L",x,y] ["Q",x1,y1,x,y] ["C",x1,y1,x2,y2,x,y]
    ["E",cx,cy,rx,ry] ["Z"].
    """
    p = QPainterPath()
    for cmd in commands:
        op = cmd[0]
        v = cmd[1:]
        if op == "M":
            p.moveTo(v[0] * w, v[1] * h)
        elif op == "L":
            p.lineTo(v[0] * w, v[1] * h)
        elif op == "Q":
            p.quadTo(v[0] * w, v[1] * h, v[2] * w, v[3] * h)
        elif op == "C":
            p.cubicTo(v[0] * w, v[1] * h, v[2] * w, v[3] * h, v[4] * w, v[5] * h)
        elif op == "E":
            p.addEllipse(QPointF(v[0] * w, v[1] * h), abs(v[2]) * w, abs(v[3]) * h)
        elif op == "Z":
            p.closeSubpath()
    return p
