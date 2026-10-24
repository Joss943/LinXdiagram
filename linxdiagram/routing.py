"""Routage des connecteurs (indépendant de Qt, donc testable seul).

Le connecteur « angle droit » imite le connecteur dynamique de Visio : il
sort perpendiculairement au côté de la forme, évite de rebrousser chemin et
de traverser les formes reliées, et minimise le nombre de coudes.
"""

from __future__ import annotations

import math

Point = tuple[float, float]
Dir = tuple[float, float] | None
Rect = tuple[float, float, float, float]  # gauche, haut, droite, bas

STUB = 18.0
_EPS = 1e-6


def _same(a: Point, b: Point) -> bool:
    return abs(a[0] - b[0]) < _EPS and abs(a[1] - b[1]) < _EPS


def simplify(points: list[Point]) -> list[Point]:
    out: list[Point] = []
    for p in points:
        if out and _same(out[-1], p):
            continue
        out.append(p)
    i = 1
    while i < len(out) - 1:
        a, b, c = out[i - 1], out[i], out[i + 1]
        if (abs(a[0] - b[0]) < _EPS and abs(b[0] - c[0]) < _EPS) or \
                (abs(a[1] - b[1]) < _EPS and abs(b[1] - c[1]) < _EPS):
            out.pop(i)
        else:
            i += 1
    return out


def _segments(points: list[Point]):
    return [(a, b) for a, b in zip(points, points[1:]) if not _same(a, b)]


def _seg_hits_rect(a: Point, b: Point, r: Rect) -> bool:
    left, top, right, bottom = r
    if abs(a[1] - b[1]) < _EPS:  # horizontal
        y = a[1]
        return top < y < bottom and max(a[0], b[0]) > left and min(a[0], b[0]) < right
    if abs(a[0] - b[0]) < _EPS:  # vertical
        x = a[0]
        return left < x < right and max(a[1], b[1]) > top and min(a[1], b[1]) < bottom
    return False


def _along(v, d, sign: int) -> bool:
    """v est-il colinéaire à d, dans le sens indiqué (1 : même sens, -1 : opposé) ?"""
    cross = v[0] * d[1] - v[1] * d[0]
    dot = v[0] * d[0] + v[1] * d[1]
    return abs(cross) < _EPS and dot * sign > 0


def _score(points: list[Point], d1: Dir, d2: Dir, rects: list[Rect]) -> float:
    segs = _segments(points)
    if not segs:
        return 0.0
    vecs = [(b[0] - a[0], b[1] - a[1]) for a, b in segs]
    bends = reversals = 0
    for s, t in zip(vecs, vecs[1:]):
        cross = s[0] * t[1] - s[1] * t[0]
        dot = s[0] * t[0] + s[1] * t[1]
        if abs(cross) > _EPS:
            bends += 1
        elif dot < 0:
            reversals += 1
    if d1 is not None and vecs[0][0] * d1[0] + vecs[0][1] * d1[1] < -_EPS:
        reversals += 1
    if d2 is not None and vecs[-1][0] * d2[0] + vecs[-1][1] * d2[1] > _EPS:
        reversals += 1
    # Comme Visio : on quitte et on aborde un côté perpendiculairement à celui-ci.
    skew = 0
    if d1 is not None and not _along(vecs[0], d1, 1):
        skew += 1
    if d2 is not None and not _along(vecs[-1], d2, -1):
        skew += 1
    crossings = 0
    for a, b in segs:
        for r in rects:
            if _seg_hits_rect(a, b, r):
                crossings += 1
    length = sum(abs(v[0]) + abs(v[1]) for v in vecs)
    return reversals * 1000 + skew * 400 + crossings * 300 + bends * 12 + length * 0.01


def _shrink(r: Rect, m: float) -> Rect:
    return (r[0] + m, r[1] + m, r[2] - m, r[3] - m)


def route_orthogonal(p1: Point, d1: Dir, p2: Point, d2: Dir,
                     r1: Rect | None = None, r2: Rect | None = None) -> list[Point]:
    """Calcule une polyligne orthogonale de p1 vers p2.

    ``d1``/``d2`` sont les directions de sortie (vecteurs unitaires d'axe)
    des points de connexion, ou None pour une extrémité libre ; ``r1``/``r2``
    les rectangles des formes reliées, à éviter.
    """
    rects = [_shrink(r, 1.0) for r in (r1, r2) if r is not None]
    a = (p1[0] + d1[0] * STUB, p1[1] + d1[1] * STUB) if d1 else p1
    b = (p2[0] + d2[0] * STUB, p2[1] + d2[1] * STUB) if d2 else p2

    candidates: list[list[Point]] = []

    def add(mid: list[Point], stubbed: bool) -> None:
        if stubbed:
            candidates.append([p1, a] + mid + [b, p2])
        else:
            candidates.append([p1] + mid + [p2])

    for s, e, stubbed in ((p1, p2, False), (a, b, True)):
        mx = (s[0] + e[0]) / 2
        my = (s[1] + e[1]) / 2
        add([(e[0], s[1])], stubbed)
        add([(s[0], e[1])], stubbed)
        add([(mx, s[1]), (mx, e[1])], stubbed)
        add([(s[0], my), (e[0], my)], stubbed)

    # Contournements par l'extérieur des formes (et des points d'attache).
    xs = [a[0], b[0]] + [v for r in rects for v in (r[0], r[2])]
    ys = [a[1], b[1]] + [v for r in rects for v in (r[1], r[3])]
    left, right = min(xs) - STUB, max(xs) + STUB
    top, bottom = min(ys) - STUB, max(ys) + STUB
    for y in (top, bottom):
        add([(a[0], y), (b[0], y)], True)
    for x in (left, right):
        add([(x, a[1]), (x, b[1])], True)

    best = min(candidates, key=lambda pts: _score(pts, d1, d2, rects))
    return simplify(best)


def curve_controls(p1: Point, d1: Dir, p2: Point, d2: Dir) -> tuple[Point, Point]:
    """Points de contrôle d'une courbe de Bézier cubique entre deux extrémités."""
    dx, dy = p2[0] - p1[0], p2[1] - p1[1]
    dist = math.hypot(dx, dy)
    k = max(30.0, dist * 0.4)

    def default(sign: float) -> tuple[float, float]:
        if abs(dx) >= abs(dy):
            return (math.copysign(1.0, dx * sign) if dx else sign, 0.0)
        return (0.0, math.copysign(1.0, dy * sign) if dy else sign)

    u1 = d1 if d1 is not None else default(1.0)
    u2 = d2 if d2 is not None else default(-1.0)
    return (p1[0] + u1[0] * k, p1[1] + u1[1] * k), (p2[0] + u2[0] * k, p2[1] + u2[1] * k)


def axis_direction(dx: float, dy: float) -> tuple[float, float]:
    """Arrondit un vecteur à la direction d'axe la plus proche."""
    if abs(dx) >= abs(dy):
        return (1.0 if dx >= 0 else -1.0, 0.0)
    return (0.0, 1.0 if dy >= 0 else -1.0)
