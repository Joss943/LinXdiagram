"""« Créer à partir de données » (Visualiseur de données de Visio) : génère un
organigramme ou un diagramme de flux à partir d'un tableau CSV."""

from __future__ import annotations

import csv
import io
import unicodedata

from . import fileformat, security, stencils, swimlanes
from .layout import layered_layout
from .units import connector_style, connector_text_style, mm_to_px

MAX_ROWS = 2000

_TYPES = {
    "processus": "flow.process", "process": "flow.process", "etape": "flow.process",
    "decision": "flow.decision", "debut": "flow.terminator", "fin": "flow.terminator",
    "start": "flow.terminator", "end": "flow.terminator", "donnees": "flow.data", "data": "flow.data",
    "document": "flow.document", "sous-processus": "flow.subprocess", "base de donnees": "flow.database",
}


class DataError(Exception):
    pass


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFD", (s or "").strip().lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def _column(headers: list[str], *names: str) -> int | None:
    norm = [_norm(h) for h in headers]
    for n in names:
        if n in norm:
            return norm.index(n)
    return None


def parse_csv(data: bytes) -> tuple[list[str], list[list[str]]]:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("latin-1")
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    rows = list(csv.reader(io.StringIO(text), dialect))
    rows = [r for r in rows if any(c.strip() for c in r)]
    if len(rows) < 2:
        raise DataError("Le fichier doit contenir une ligne d'en-têtes et au moins une ligne de données.")
    if len(rows) > MAX_ROWS + 1:
        raise DataError(f"Trop de lignes (maximum {MAX_ROWS}).")
    clean = [[security.clean_line(c, 500) for c in r] for r in rows]
    return clean[0], clean[1:]


def build_page(kind: str, headers: list[str], rows: list[list[str]], name: str, theme: str) -> dict:
    c_id = _column(headers, "id", "identifiant", "code")
    c_text = _column(headers, "nom", "name", "description", "texte", "libelle de l'etape", "etape")
    if c_id is None or c_text is None:
        raise DataError("Colonnes « ID » et « Nom » (ou « Description ») obligatoires.")
    c_role = _column(headers, "fonction", "poste", "titre", "role")
    c_parent = _column(headers, "responsable", "parent", "manager", "superieur")
    c_type = _column(headers, "type", "forme", "type de forme")
    c_next = _column(headers, "suivant", "suivants", "next", "vers", "etape suivante")
    c_label = _column(headers, "libelle", "label", "condition")
    c_lane = _column(headers, "fonction", "couloir", "acteur", "role", "service", "departement",
                     "responsable de l'etape") if kind == "flow" else None
    if kind == "org" and c_parent is None:
        raise DataError("Colonne « Responsable » (ID du supérieur) introuvable.")
    if kind == "flow" and c_next is None:
        raise DataError("Colonne « Suivant » introuvable.")

    def cell(row, c):
        return row[c].strip() if c is not None and c < len(row) else ""

    shapes, edges, ids = [], [], {}
    for n, row in enumerate(rows):
        key = cell(row, c_id)
        if not key or key in ids:
            continue
        sid = f"d{n}"
        ids[key] = sid
        text = cell(row, c_text)
        if kind == "org":
            role = cell(row, c_role)
            type_id = "org.executive" if not cell(row, c_parent) else "org.employee"
            label = f"{text}\n{role}" if role else text
        else:
            type_id = _TYPES.get(_norm(cell(row, c_type)), "flow.process")
            label = text
        sdef = stencils.get(type_id)
        style, ts = fileformat.default_shape_styles(type_id, theme)
        w, h = mm_to_px(sdef.size_mm[0] + 10), mm_to_px(sdef.size_mm[1] + 2)
        shapes.append({"id": sid, "type": type_id, "x": 0.0, "y": 0.0, "w": w, "h": h, "rotation": 0.0,
                       "flip_h": False, "flip_v": False, "z": float(n), "text": label, "style": style,
                       "text_style": ts, "data": {headers[i]: v for i, v in enumerate(row)
                                                  if i < len(headers) and headers[i] and v}})
    for row in rows:
        src = ids.get(cell(row, c_id))
        if src is None:
            continue
        if kind == "org":
            parent = ids.get(cell(row, c_parent))
            if parent:
                edges.append((parent, src, ""))
        else:
            for nxt in cell(row, c_next).replace(",", ";").split(";"):
                dst = ids.get(nxt.strip())
                if dst:
                    edges.append((src, dst, cell(row, c_label)))
    if kind == "org":
        managers = {a for a, _b, _t in edges}
        for s in shapes:
            if s["id"] in managers and s["type"] == "org.employee":
                s["type"] = "org.manager"
                s["style"], s["text_style"] = fileformat.default_shape_styles("org.manager", theme)
    if c_lane is not None:
        lane_of = {ids[cell(r, c_id)]: cell(r, c_lane) or "Sans fonction"
                   for r in rows if cell(r, c_id) in ids}
        return _cross_functional(name, theme, shapes, edges, lane_of)
    nodes = [(s["id"], 0.0, float(i), s["w"], s["h"]) for i, s in enumerate(shapes)]
    pos = layered_layout(nodes, [(a, b) for a, b, _t in edges], "TB", gap_major=mm_to_px(14),
                         gap_minor=mm_to_px(8))
    if pos:
        min_x = min(pos[s["id"]][0] - s["w"] / 2 for s in shapes)
        min_y = min(pos[s["id"]][1] - s["h"] / 2 for s in shapes)
        for s in shapes:
            x, y = pos[s["id"]]
            s["x"], s["y"] = x - min_x + mm_to_px(15), y - min_y + mm_to_px(15)
    right = max((s["x"] + s["w"] / 2 for s in shapes), default=0) + mm_to_px(15)
    bottom = max((s["y"] + s["h"] / 2 for s in shapes), default=0) + mm_to_px(15)
    connectors = []
    for n, (a, b, label) in enumerate(edges):
        connectors.append({"id": f"e{n}", "kind": "connector", "src": {"shape": a, "port": -1, "x": 0, "y": 0},
                           "dst": {"shape": b, "port": -1, "x": 0, "y": 0}, "z": 10000.0 + n,
                           "text": label, "style": connector_style(theme, "orthogonal"),
                           "text_style": connector_text_style(theme), "data": {}})
    page = fileformat.default_page(name)
    page["width"] = max(page["width"], right)
    page["height"] = max(page["height"], bottom)
    page["shapes"], page["connectors"] = shapes, connectors
    doc, _w = fileformat.validate_document({"format": fileformat.FORMAT, "version": fileformat.VERSION,
                                             "settings": {"theme": theme}, "pages": [page]})
    return doc["pages"][0]


def _cross_functional(name: str, theme: str, shapes: list[dict], edges, lane_of: dict[str, str]) -> dict:
    """Diagramme de flux interfonctionnel : une ligne par fonction, les étapes de gauche à droite
    dans l'ordre du processus (comme le Visualiseur de données de Visio)."""
    lanes: list[str] = []
    for s in shapes:
        lane = lane_of.get(s["id"], "Sans fonction")
        if lane not in lanes:
            lanes.append(lane)
    nodes = [(s["id"], float(i), 0.0, s["w"], s["h"]) for i, s in enumerate(shapes)]
    pos = layered_layout(nodes, [(a, b) for a, b, _t in edges], "LR", gap_major=mm_to_px(14),
                         gap_minor=mm_to_px(8))
    column_x = sorted({round(p[0], 1) for p in pos.values()})
    col_index = {x: i for i, x in enumerate(column_x)}
    step = max((s["w"] for s in shapes), default=mm_to_px(45)) + mm_to_px(15)
    stack: dict[tuple[str, int], list[dict]] = {}
    for s in shapes:
        col = col_index[round(pos[s["id"]][0], 1)]
        stack.setdefault((lane_of.get(s["id"], "Sans fonction"), col), []).append(s)
    lane_size = {lane: max([mm_to_px(32)] + [len(v) * mm_to_px(24) + mm_to_px(8)
                                             for (ln, _c), v in stack.items() if ln == lane])
                 for lane in lanes}
    left, top = mm_to_px(15), mm_to_px(15)
    length = swimlanes.HEADER + mm_to_px(20) + len(column_x) * step
    lane_boxes, y = [], top + swimlanes.TITLE
    for i, lane in enumerate(lanes):
        lane_boxes.append(swimlanes.Box(f"lane{i}", left, y, length, lane_size[lane]))
        y += lane_size[lane]
    frame = swimlanes.Box("frame", left, top, length, y - top)
    geo = swimlanes.layout("h", frame, lane_boxes, [])
    out_shapes = []
    style, ts = fileformat.default_shape_styles("cff.frame_h", theme)
    gl, gt, gw, gh = geo["frame"]
    out_shapes.append({"id": "cff_frame", "type": "cff.frame_h", "x": gl + gw / 2, "y": gt + gh / 2, "w": gw,
                       "h": gh, "rotation": 0.0, "flip_h": False, "flip_v": False, "z": swimlanes.Z_FRAME,
                       "text": name, "style": style, "text_style": ts, "data": {}})
    lane_top = {}
    for i, lane in enumerate(lanes):
        gl, gt, gw, gh = geo[f"lane{i}"]
        lane_top[lane] = (gt, gh)
        style, ts = fileformat.default_shape_styles("cff.lane_h", theme)
        out_shapes.append({"id": f"cff_lane{i}", "type": "cff.lane_h", "x": gl + gw / 2, "y": gt + gh / 2,
                           "w": gw, "h": gh, "rotation": 0.0, "flip_h": False, "flip_v": False,
                           "z": swimlanes.Z_LANE + i, "text": lane, "style": style, "text_style": ts, "data": {}})
    for (lane, col), group in stack.items():
        gt, gh = lane_top[lane]
        n = len(group)
        for k, s in enumerate(group):
            s["x"] = left + swimlanes.HEADER + mm_to_px(10) + col * step + step / 2
            s["y"] = gt + gh * (k + 1) / (n + 1)
            out_shapes.append(s)
    connectors = []
    for n, (a, b, label) in enumerate(edges):
        connectors.append({"id": f"e{n}", "kind": "connector", "src": {"shape": a, "port": -1, "x": 0, "y": 0},
                           "dst": {"shape": b, "port": -1, "x": 0, "y": 0}, "z": 10000.0 + n,
                           "text": label, "style": connector_style(theme, "orthogonal"),
                           "text_style": connector_text_style(theme), "data": {}})
    page = fileformat.default_page(name)
    page["width"] = max(mm_to_px(297), left + length + mm_to_px(15))
    page["height"] = max(mm_to_px(210), y + mm_to_px(15))
    page["shapes"], page["connectors"] = out_shapes, connectors
    doc, _w = fileformat.validate_document({"format": fileformat.FORMAT, "version": fileformat.VERSION,
                                             "settings": {"theme": theme}, "pages": [page]})
    return doc["pages"][0]
