"""Opérations sur les formes, comme Développeur > Opérations de Visio.

Union, Combiner, Fragmenter, Intersecter et Soustraire travaillent sur les contours
des formes dans le repère de la page ; le résultat devient une forme personnalisée dont
la géométrie est normalisée (0..1) dans son rectangle englobant.
"""

from __future__ import annotations

from PyQt6.QtCore import QRectF
from PyQt6.QtGui import QPainterPath

OPERATIONS = {
    "union": "Union",
    "combine": "Combiner",
    "fragment": "Fragmenter",
    "intersect": "Intersecter",
    "subtract": "Soustraire",
}
MIN_AREA = 4.0  # px² : les éclats plus petits sont ignorés


def _area(p: QPainterPath) -> float:
    r = p.boundingRect()
    return r.width() * r.height() if not p.isEmpty() else 0.0


def _solid(p: QPainterPath) -> QPainterPath:
    """Contour « plein » (règle non nulle) pour les opérations booléennes."""
    q = QPainterPath(p)
    q.setFillRule(p.fillRule())
    return q.simplified()


def apply(op: str, paths: list[QPainterPath]) -> list[QPainterPath]:
    """Résultat de l'opération ; ``paths[0]`` est la sélection principale."""
    paths = [_solid(p) for p in paths if not p.isEmpty()]
    if not paths:
        return []
    if op == "union":
        out = paths[0]
        for p in paths[1:]:
            out = out.united(p)
        return [out.simplified()]
    if op == "combine":
        # Comme Visio : les zones qui se chevauchent un nombre pair de fois deviennent des trous.
        out = QPainterPath()
        out.setFillRule(out.fillRule().OddEvenFill)
        for p in paths:
            out.addPath(p)
        return [out]
    if op == "intersect":
        out = paths[0]
        for p in paths[1:]:
            out = out.intersected(p)
        return [out.simplified()] if _area(out) > MIN_AREA else []
    if op == "subtract":
        out = paths[0]
        for p in paths[1:]:
            out = out.subtracted(p)
        return [out.simplified()] if _area(out) > MIN_AREA else []
    if op == "fragment":
        pieces: list[QPainterPath] = []
        for s in paths:
            nxt = []
            covered = QPainterPath()
            for piece in pieces:
                inter = piece.intersected(s)
                rest = piece.subtracted(s)
                for q in (inter, rest):
                    if _area(q) > MIN_AREA:
                        nxt.append(q.simplified())
                covered = covered.united(piece)
            new = s.subtracted(covered) if pieces else s
            if _area(new) > MIN_AREA:
                nxt.append(new.simplified())
            pieces = nxt
        return pieces
    raise ValueError(op)


def to_commands(path: QPainterPath) -> tuple[QRectF, list]:
    """Rectangle englobant (repère de la page) et commandes normalisées M/L/C/Z."""
    r = path.boundingRect()
    w, h = max(r.width(), 1e-6), max(r.height(), 1e-6)

    def n(x: float, y: float) -> list[float]:
        return [round((x - r.left()) / w, 6), round((y - r.top()) / h, 6)]

    cmds: list = []
    i = 0
    count = path.elementCount()
    start = None
    while i < count:
        e = path.elementAt(i)
        if e.isMoveTo():
            if start is not None:
                cmds.append(["Z"])
            cmds.append(["M", *n(e.x, e.y)])
            start = (e.x, e.y)
            i += 1
        elif e.isLineTo():
            cmds.append(["L", *n(e.x, e.y)])
            i += 1
        elif e.isCurveTo() and i + 2 < count:
            c2, end = path.elementAt(i + 1), path.elementAt(i + 2)
            cmds.append(["C", *n(e.x, e.y), *n(c2.x, c2.y), *n(end.x, end.y)])
            i += 3
        else:
            i += 1
    if start is not None:
        cmds.append(["Z"])
    return r, cmds
