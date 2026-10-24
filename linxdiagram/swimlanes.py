"""Diagrammes de flux interfonctionnels (couloirs), comme dans Visio.

Une structure comprend un cadre facultatif avec barre de titre, des couloirs
accolés (horizontaux ou verticaux) et des séparateurs de phases. Ce module ne
dépend pas de Qt : il calcule la géométrie à partir de rectangles simples, ce
qui permet de le tester isolément et de l'utiliser pour les modèles.
"""

from __future__ import annotations

from dataclasses import dataclass

from .units import mm_to_px

TITLE = mm_to_px(10)
PHASE = mm_to_px(8)
HEADER = mm_to_px(12)
MIN_LANE = mm_to_px(15)
MIN_PHASE = mm_to_px(15)
DEFAULT_LANE = mm_to_px(35)
DEFAULT_PHASE = mm_to_px(60)
DEFAULT_LENGTH = mm_to_px(230)

LANE = {"h": "cff.lane_h", "v": "cff.lane_v"}
PHASE_T = {"h": "cff.phase_h", "v": "cff.phase_v"}
FRAME = {"h": "cff.frame_h", "v": "cff.frame_v"}
KIND_OF = {"cff.lane_h": ("lane", "h"), "cff.lane_v": ("lane", "v"), "cff.phase_h": ("phase", "h"),
           "cff.phase_v": ("phase", "v"), "cff.frame_h": ("frame", "h"), "cff.frame_v": ("frame", "v")}
Z_FRAME, Z_LANE, Z_PHASE = -3000.0, -2000.0, -1000.0

# Galerie « Styles » de l'onglet interfonctionnel (barre de titre, en-têtes, traits).
STYLES = [
    {"name": "Bleu", "title_fill": "#dce6f2", "title_text": "#1f3864", "lane_fill": "#dce6f2",
     "lane_text": "#1f3864", "line": "#7f9cc9"},
    {"name": "Bleu contrasté", "title_fill": "#1f3864", "title_text": "#ffffff", "lane_fill": "#b4c7e7",
     "lane_text": "#1f3864", "line": "#2f5597"},
    {"name": "Gris", "title_fill": "#d9d9d9", "title_text": "#262626", "lane_fill": "#ededed",
     "lane_text": "#262626", "line": "#a6a6a6"},
    {"name": "Graphite", "title_fill": "#404040", "title_text": "#ffffff", "lane_fill": "#d9d9d9",
     "lane_text": "#262626", "line": "#595959"},
    {"name": "Vert", "title_fill": "#c6e0b4", "title_text": "#375623", "lane_fill": "#e2efda",
     "lane_text": "#375623", "line": "#8db27a"},
    {"name": "Orange", "title_fill": "#f8cbad", "title_text": "#833c0b", "lane_fill": "#fbe5d6",
     "lane_text": "#833c0b", "line": "#e0a37a"},
    {"name": "Violet", "title_fill": "#d0c4e4", "title_text": "#3f3151", "lane_fill": "#e4dfec",
     "lane_text": "#3f3151", "line": "#9f8fbf"},
    {"name": "Sans couleur", "title_fill": "#ffffff", "title_text": "#262626", "lane_fill": "#ffffff",
     "lane_text": "#262626", "line": "#595959"},
]


def is_cff(type_id: str) -> bool:
    return type_id in KIND_OF


@dataclass
class Box:
    id: str
    left: float
    top: float
    w: float
    h: float

    @property
    def cx(self) -> float:
        return self.left + self.w / 2

    @property
    def cy(self) -> float:
        return self.top + self.h / 2

    def contains(self, x: float, y: float) -> bool:
        return self.left <= x <= self.left + self.w and self.top <= y <= self.top + self.h


def layout(orientation: str, frame: Box | None, lanes: list[Box], phases: list[Box],
           title: bool = True, separators: bool = True) -> dict[str, tuple[float, float, float, float]]:
    """Géométrie (gauche, haut, largeur, hauteur) de chaque élément, couloirs accolés.

    L'ordre des couloirs suit leur position actuelle : glisser un couloir le réordonne.
    Le cadre reste l'ancre ; à défaut, le premier couloir.
    """
    out: dict[str, tuple[float, float, float, float]] = {}
    if not lanes:
        if frame is not None:
            out[frame.id] = (frame.left, frame.top, frame.w, frame.h)
        return out
    horizontal = orientation == "h"
    lanes = sorted(lanes, key=lambda b: b.cy if horizontal else b.cx)
    phases = sorted(phases, key=lambda b: b.cx if horizontal else b.cy)
    t = TITLE if (frame is not None and title) else 0.0
    band = PHASE if (phases and separators) else 0.0
    if frame is not None:
        fx, fy = frame.left, frame.top
        length = (frame.w if horizontal else frame.h - t - (0 if horizontal else 0))
    else:
        fx = min(b.left for b in lanes)
        fy = min(b.top for b in lanes)
        length = max((b.w if horizontal else b.h) for b in lanes)
    if horizontal:
        length = max(length, HEADER + MIN_PHASE * max(1, len(phases)))
        pos = HEADER
        for i, p in enumerate(phases):
            size = max(p.w, MIN_PHASE)
            if i == len(phases) - 1:
                size = max(size, length - pos)
            pos += size
        length = max(length, pos)
        y = fy + t + band
        for lane in lanes:
            h = max(lane.h, MIN_LANE)
            out[lane.id] = (fx, y, length, h)
            y += h
        lanes_h = y - (fy + t + band)
        x = fx + HEADER
        for i, p in enumerate(phases):
            size = max(p.w, MIN_PHASE)
            if i == len(phases) - 1:
                size = fx + length - x
            out[p.id] = (x, fy + t, size, band + lanes_h)
            x += size
        if frame is not None:
            out[frame.id] = (fx, fy, length, y - fy)
    else:
        length = max(length, HEADER + MIN_PHASE * max(1, len(phases)))
        pos = HEADER
        for i, p in enumerate(phases):
            size = max(p.h, MIN_PHASE)
            if i == len(phases) - 1:
                size = max(size, length - pos)
            pos += size
        length = max(length, pos)
        x = fx + band
        top = fy + t
        for lane in lanes:
            w = max(lane.w, MIN_LANE)
            out[lane.id] = (x, top, w, length)
            x += w
        lanes_w = x - (fx + band)
        y = top + HEADER
        for i, p in enumerate(phases):
            size = max(p.h, MIN_PHASE)
            if i == len(phases) - 1:
                size = top + length - y
            out[p.id] = (fx, y, band + lanes_w, size)
            y += size
        if frame is not None:
            out[frame.id] = (fx, fy, x - fx, t + length)
    return out


def origin(orientation: str, frame: Box | None, lanes: list[Box], title: bool = True) -> tuple[float, float]:
    """Coin haut-gauche de la zone des couloirs (sous la barre de titre)."""
    if frame is not None:
        return frame.left, frame.top + (TITLE if title else 0.0)
    return min(b.left for b in lanes), min(b.top for b in lanes)


def transpose(ox: float, oy: float, x: float, y: float) -> tuple[float, float]:
    """Changement d'orientation : l'axe des couloirs et l'axe du processus s'échangent."""
    return ox + (y - oy), oy + (x - ox)


def memberships(frame: Box | None, lanes: list[Box], phases: list[Box],
                shapes: list[Box]) -> dict[str, list[str]]:
    """Conteneurs dont chaque élément est membre (relation 4 de la cellule Relationships de Visio)."""
    out: dict[str, list[str]] = {}
    for b in lanes + phases:
        if frame is not None:
            out[b.id] = [frame.id]
    for s in shapes:
        owners = [c.id for c in lanes + phases if c.contains(s.cx, s.cy)]
        if frame is not None and (owners or frame.contains(s.cx, s.cy)):
            owners.insert(0, frame.id)
        if owners:
            out[s.id] = owners
    return out


def member_lane(lanes: list[Box], x: float, y: float, prefer: str | None = None) -> str | None:
    """Couloir contenant le point (le couloir « préféré », par ex. celui qu'on glisse, d'abord)."""
    ordered = sorted(lanes, key=lambda b: b.id != prefer)
    for b in ordered:
        if b.contains(x, y):
            return b.id
    return None


def new_structure(orientation: str, left: float, top: float, n_lanes: int = 3,
                  length: float = DEFAULT_LENGTH, lane_size: float = DEFAULT_LANE,
                  with_frame: bool = True) -> list[tuple[str, str, Box]]:
    """Éléments d'une nouvelle structure : (rôle, type, boîte). Les identifiants sont
    provisoires (« frame », « lane0 »…) et remplacés par l'appelant."""
    items: list[tuple[str, str, Box]] = []
    horizontal = orientation == "h"
    lanes = []
    for i in range(n_lanes):
        if horizontal:
            b = Box(f"lane{i}", left, top + i * lane_size + 1, length, lane_size)
        else:
            b = Box(f"lane{i}", left + i * lane_size + 1, top, lane_size, length)
        lanes.append(b)
    frame = None
    if with_frame:
        frame = Box("frame", left, top, length if horizontal else n_lanes * lane_size,
                    (n_lanes * lane_size + TITLE) if horizontal else (length + TITLE))
    geo = layout(orientation, frame, lanes, [])
    if frame is not None:
        items.append(("frame", FRAME[orientation], Box("frame", *geo["frame"])))
    for b in lanes:
        items.append(("lane", LANE[orientation], Box(b.id, *geo[b.id])))
    return items
