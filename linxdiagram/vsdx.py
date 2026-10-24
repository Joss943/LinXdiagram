"""Interopérabilité Microsoft Visio : import et export du format .vsdx.

Le format VSDX est un paquet OPC (ZIP) de parties XML décrit dans la
spécification ouverte [MS-VSDX]. Chaque forme y est une « ShapeSheet » :
cellules (PinX, PinY, Width, Height, Angle, LocPinX…) et sections
(Geometry, Character, Paragraph, Connection, Property…). Les points non
couverts par la documentation (sens des arcs ArcTo) suivent le comportement de
libvisio, la bibliothèque de référence issue de la rétro-ingénierie du format.

Sécurité de l'import :
* fichier borné en taille, nombre de membres et volume décompressé (zip bombs) ;
* membres chiffrés refusés, chemins des relations normalisés ;
* XML avec DOCTYPE/ENTITY refusé (XXE, « billion laughs ») ;
* aucune formule n'est évaluée : seules les valeurs calculées (V) sont lues ;
* le résultat repasse par la validation stricte du format .lxd.
"""

from __future__ import annotations

import base64
import datetime
import io
import json
import math
import posixpath
import re
import zipfile
import xml.etree.ElementTree as ET

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPainterPath

from . import APP_NAME, __version__, fields, fileformat, security, stencils, swimlanes
from .units import PX_PER_INCH

VNS = "http://schemas.microsoft.com/office/visio/2012/main"
RNS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PNS = "http://schemas.openxmlformats.org/package/2006/relationships"
CTNS = "http://schemas.openxmlformats.org/package/2006/content-types"
_VREL = "http://schemas.microsoft.com/visio/2010/relationships/"
REL_DOC = _VREL + "document"
REL_PAGES = _VREL + "pages"
REL_PAGE = _VREL + "page"
REL_MASTERS = _VREL + "masters"
REL_MASTER = _VREL + "master"
REL_WINDOWS = _VREL + "windows"
REL_IMAGE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"
REL_CORE = "http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties"
REL_APP = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties"

MAX_VSDX_BYTES = 100 * 1024 * 1024
MAX_MEMBERS = 5000
MAX_MEMBER_BYTES = 40 * 1024 * 1024
MAX_TOTAL_BYTES = 300 * 1024 * 1024
MAX_RATIO = 150
MAX_SHAPES = 50_000
MAX_DEPTH = 30

_DTD_RE = re.compile(rb"<!\s*(DOCTYPE|ENTITY)", re.IGNORECASE)
_XML_BAD_RE = re.compile("[\ud800-\udfff￾￿]")

VISIO_COLORS = ["#000000", "#ffffff", "#ff0000", "#00ff00", "#0000ff", "#ffff00", "#ff00ff",
                "#00ffff", "#800000", "#008000", "#000080", "#808000", "#800080", "#008080",
                "#c0c0c0", "#e6e6e6", "#cdcdcd", "#b3b3b3", "#9a9a9a", "#808080", "#666666",
                "#4d4d4d", "#333333", "#1a1a1a"]

LINE_CELLS = {"LineWeight", "LineColor", "LinePattern", "Rounding", "BeginArrow", "EndArrow",
              "LineCap", "LineColorTrans", "BeginArrowSize", "EndArrowSize"}
FILL_CELLS = {"FillForegnd", "FillBkgnd", "FillPattern", "FillForegndTrans", "FillBkgndTrans",
              "ShdwForegnd", "ShdwPattern"}
TEXT_CELLS = {"VerticalAlign", "LeftMargin", "RightMargin", "TopMargin", "BottomMargin"}
_DASH_TO_VISIO = {"solid": 1, "dash": 2, "dot": 3, "dashdot": 4}
_ARROW_TO_VISIO = {"none": 0, "open": 1, "triangle": 4, "diamond": 22, "circle": 10}


class VsdxError(fileformat.DocumentError):
    pass


def _v(tag: str) -> str:
    return f"{{{VNS}}}{tag}"


def _num(text, default=None):
    if text is None:
        return default
    try:
        v = float(text)
    except (TypeError, ValueError):
        return default
    return v if math.isfinite(v) else default


def _color(text) -> str | None:
    if text is None:
        return None
    text = text.strip()
    if re.fullmatch(r"#[0-9a-fA-F]{6}", text):
        return text.lower()
    if re.fullmatch(r"\d{1,3}", text):
        i = int(text)
        if i < len(VISIO_COLORS):
            return VISIO_COLORS[i]
    return None


# =========================================================================== import

class _Package:
    def __init__(self, data: bytes):
        try:
            self.zip = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile as exc:
            raise VsdxError("Ce fichier n'est pas un document Visio (.vsdx) valide.") from exc
        infos = self.zip.infolist()
        if len(infos) > MAX_MEMBERS:
            raise VsdxError("Paquet Visio anormal (trop de parties).")
        names = [info.filename for info in infos]
        if len(set(names)) != len(names):
            raise VsdxError("Paquet Visio ambigu : noms de parties dupliqués.")
        for name in names:
            parts = name.split("/")
            if (not name or name.startswith(("/", "\\")) or "\\" in name or "\x00" in name
                    or any(part in (".", "..") for part in parts)):
                raise VsdxError("Paquet Visio invalide : chemin de partie non autorisé.")
        self.infos = {i.filename: i for i in infos}
        self.total = 0

    def read(self, name: str) -> bytes | None:
        info = self.infos.get(name)
        if info is None:
            return None
        if info.flag_bits & 0x1:
            raise VsdxError("Les parties chiffrées ne sont pas prises en charge.")
        if info.file_size > MAX_MEMBER_BYTES or (
                info.file_size > 1024 * 1024 and info.file_size > MAX_RATIO * max(info.compress_size, 1)):
            raise VsdxError("Partie compressée suspecte (bombe de décompression ?).")
        with self.zip.open(info) as f:
            data = f.read(MAX_MEMBER_BYTES + 1)
        if len(data) > MAX_MEMBER_BYTES:
            raise VsdxError("Partie trop volumineuse.")
        self.total += len(data)
        if self.total > MAX_TOTAL_BYTES:
            raise VsdxError("Document Visio trop volumineux une fois décompressé.")
        return data

    def xml(self, name: str):
        data = self.read(name)
        if data is None:
            return None
        if b"\x00" in data:
            raise VsdxError(f"XML non UTF-8 refusé dans {name}.")
        if _DTD_RE.search(data):
            raise VsdxError("XML avec DTD refusé (protection contre les attaques XXE).")
        try:
            return ET.fromstring(data)
        except ET.ParseError as exc:
            raise VsdxError(f"XML invalide dans {name} : {exc}") from exc

    def rels(self, part: str) -> dict[str, tuple[str, str]]:
        d, b = posixpath.split(part)
        root = self.xml(posixpath.join(d, "_rels", b + ".rels"))
        out: dict[str, tuple[str, str]] = {}
        if root is None:
            return out
        for rel in root.findall(f"{{{PNS}}}Relationship"):
            if rel.get("TargetMode") == "External":
                continue  # aucune ressource externe n'est jamais chargée
            target = rel.get("Target", "")
            if target.startswith("/"):
                path = posixpath.normpath(target.lstrip("/"))
            else:
                path = posixpath.normpath(posixpath.join(d, target))
            if path.startswith("..") or path.startswith("/"):
                continue
            out[rel.get("Id", "")] = (rel.get("Type", ""), path)
        return out


class _Sheet:
    """ShapeSheet avec héritage : forme → forme maître → feuilles de style."""

    def __init__(self, elem, master: "_Sheet | None" = None, styles: dict | None = None):
        self.elem = elem
        self.master = master
        self.styles = styles if styles is not None else {}
        self.cells = {c.get("N"): c for c in elem.findall(_v("Cell"))}
        self.sections: dict[str, list] = {}
        for s in elem.findall(_v("Section")):
            self.sections.setdefault(s.get("N"), []).append(s)

    def _style_for(self, name: str, section: str | None = None):
        attr = None
        if name in LINE_CELLS:
            attr = "LineStyle"
        elif name in FILL_CELLS:
            attr = "FillStyle"
        elif name in TEXT_CELLS or section in ("Character", "Paragraph"):
            attr = "TextStyle"
        if attr is None:
            return None
        sid = self.elem.get(attr)
        sheet = self
        while sid is None and sheet.master is not None:
            sheet = sheet.master
            sid = sheet.elem.get(attr)
        style = self.styles.get(sid)
        return style if style is not self else None

    def raw(self, name: str, depth: int = 0):
        if depth > MAX_DEPTH:
            return None
        c = self.cells.get(name)
        if c is not None and c.get("V") is not None:
            return c.get("V")
        if self.master is not None:
            v = self.master.raw(name, depth + 1)
            if v is not None:
                return v
        style = self._style_for(name)
        return style.raw(name, depth + 1) if style is not None else None

    def formula(self, name: str):
        c = self.cells.get(name)
        return c.get("F") if c is not None else None

    def num(self, name: str, default=None):
        return _num(self.raw(name), default)

    def row_cell(self, section: str, cell: str, row_ix: str = "0", depth: int = 0):
        if depth > MAX_DEPTH:
            return None
        for sec in self.sections.get(section, []):
            for row in sec.findall(_v("Row")):
                if row.get("IX", "0") == row_ix:
                    for c in row.findall(_v("Cell")):
                        if c.get("N") == cell and c.get("V") is not None:
                            return c.get("V")
        if self.master is not None:
            v = self.master.row_cell(section, cell, row_ix, depth + 1)
            if v is not None:
                return v
        style = self._style_for(cell, section)
        return style.row_cell(section, cell, row_ix, depth + 1) if style is not None else None

    def named_rows(self, section: str) -> list[tuple[str, dict[str, str]]]:
        rows: dict[str, dict[str, str]] = {}
        order: list[str] = []
        sheets = []
        s = self
        while s is not None and len(sheets) < MAX_DEPTH:
            sheets.append(s)
            s = s.master
        for sheet in reversed(sheets):
            for sec in sheet.sections.get(section, []):
                for row in sec.findall(_v("Row")):
                    key = row.get("N") or row.get("IX") or ""
                    if row.get("Del") == "1":
                        rows.pop(key, None)
                        continue
                    if key not in rows:
                        rows[key] = {}
                        order.append(key)
                    for c in row.findall(_v("Cell")):
                        if c.get("V") is not None:
                            rows[key][c.get("N")] = c.get("V")
        return [(k, rows[k]) for k in order if k in rows]

    def text(self) -> str | None:
        t = self.elem.find(_v("Text"))
        if t is not None:
            return "".join(t.itertext())
        if self.master is not None:
            return self.master.text()
        return None

    def geometry(self, w: float, h: float, depth: int = 0) -> dict:
        """Sections Geometry fusionnées avec le maître ; chaque cellule garde la
        taille (w, h) de la feuille qui l'a définie, pour la mise à l'échelle."""
        if depth > MAX_DEPTH:
            return {}
        merged: dict = {}
        if self.master is not None:
            mw = self.master.num("Width", w) or w
            mh = self.master.num("Height", h) or h
            merged = self.master.geometry(mw, mh, depth + 1)
        for sec in self.sections.get("Geometry", []):
            ix = int(_num(sec.get("IX"), 0) or 0)
            if sec.get("Del") == "1":
                merged.pop(ix, None)
                continue
            target = merged.setdefault(ix, {"cells": {}, "rows": {}})
            for c in sec.findall(_v("Cell")):
                if c.get("V") is not None:
                    target["cells"][c.get("N")] = c.get("V")
            for row in sec.findall(_v("Row")):
                rix = int(_num(row.get("IX"), len(target["rows"]) + 1) or 0)
                if row.get("Del") == "1":
                    target["rows"].pop(rix, None)
                    continue
                r = target["rows"].setdefault(rix, {"T": row.get("T"), "cells": {}})
                if row.get("T"):
                    r["T"] = row.get("T")
                for c in row.findall(_v("Cell")):
                    if c.get("V") is not None or c.get("F"):
                        r["cells"][c.get("N")] = (c.get("V"), c.get("F"), w, h)
        return merged


def _arc3(s, p, e):
    """Arc de cercle passant par s, p, e → segments de Bézier cubiques."""
    ax, ay = s
    bx, by = p
    cx, cy = e
    d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1e-12:
        return None
    a2, b2, c2 = ax * ax + ay * ay, bx * bx + by * by, cx * cx + cy * cy
    ux = (a2 * (by - cy) + b2 * (cy - ay) + c2 * (ay - by)) / d
    uy = (a2 * (cx - bx) + b2 * (ax - cx) + c2 * (bx - ax)) / d
    r = math.hypot(ax - ux, ay - uy)
    t0 = math.atan2(ay - uy, ax - ux)
    t1 = math.atan2(by - uy, bx - ux)
    t2 = math.atan2(cy - uy, cx - ux)
    tau = 2 * math.pi
    if (t1 - t0) % tau <= (t2 - t0) % tau:
        sweep = (t2 - t0) % tau
    else:
        sweep = -((t0 - t2) % tau)
    n = max(1, math.ceil(abs(sweep) / (math.pi / 2) - 1e-9))
    seg = sweep / n
    k = 4.0 / 3.0 * math.tan(seg / 4)
    out = []
    for i in range(n):
        a = t0 + i * seg
        b = a + seg
        p0 = (ux + r * math.cos(a), uy + r * math.sin(a))
        p3 = (ux + r * math.cos(b), uy + r * math.sin(b))
        c1 = (p0[0] - k * r * math.sin(a), p0[1] + k * r * math.cos(a))
        c2_ = (p3[0] + k * r * math.sin(b), p3[1] - k * r * math.cos(b))
        out.append((c1, c2_, p3))
    return out


def _ellipse_cubics(c, u, v):
    """Ellipse de centre c et demi-axes vectoriels u, v (4 segments exacts)."""
    k = 4.0 / 3.0 * math.tan(math.pi / 8)

    def pt(t):
        return (c[0] + u[0] * math.cos(t) + v[0] * math.sin(t),
                c[1] + u[1] * math.cos(t) + v[1] * math.sin(t))

    def der(t):
        return (-u[0] * math.sin(t) + v[0] * math.cos(t), -u[1] * math.sin(t) + v[1] * math.cos(t))

    start = pt(0)
    segs = []
    for i in range(4):
        a, b = i * math.pi / 2, (i + 1) * math.pi / 2
        p0, p3, d0, d3 = pt(a), pt(b), der(a), der(b)
        segs.append(((p0[0] + k * d0[0], p0[1] + k * d0[1]),
                     (p3[0] - k * d3[0], p3[1] - k * d3[1]), p3))
    return start, segs


_POLY_NUM = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")


def _geometry_to_commands(sheet: _Sheet, W: float, H: float):
    """Convertit les sections Geometry en commandes normalisées (y vers le bas)."""
    W = max(W, 1e-4)
    H = max(H, 1e-4)
    sections = sheet.geometry(W, H)
    cmds: list[list] = []
    any_fill = False
    any_line = False
    details: list[list] = []

    def norm(p):
        return p[0] / W, 1.0 - p[1] / H

    for ix in sorted(sections):
        sec = sections[ix]
        flags = {k: sec["cells"].get(k) == "1" for k in ("NoFill", "NoLine", "NoShow")}
        if flags["NoShow"]:
            continue
        out = cmds if not flags["NoFill"] else details
        if not flags["NoFill"]:
            any_fill = True
        if not flags["NoLine"]:
            any_line = True
        cur = (0.0, 0.0)
        start = None
        sub: list[list] = []

        for rix in sorted(sec["rows"]):
            row = sec["rows"][rix]
            t = row["T"] or ""
            cells = row["cells"]
            rel = t.startswith("Rel")

            def val(name, axis):
                c = cells.get(name)
                if c is None:
                    return None
                v = _num(c[0])
                if v is None:
                    return None
                if rel:
                    return v * (W if axis == "x" else H)
                ref = c[2] if axis == "x" else c[3]
                return v * ((W / ref) if axis == "x" and ref else (H / ref) if ref else 1.0)

            def point(xn="X", yn="Y"):
                x, y = val(xn, "x"), val(yn, "y")
                if x is None or y is None:
                    return None
                return (x, y)

            end = point()
            if t in ("MoveTo", "RelMoveTo"):
                if end is None:
                    continue
                if sub:
                    out.extend(sub)
                    sub = []
                sub.append(["M", *norm(end)])
                cur = start = end
            elif t in ("LineTo", "RelLineTo", "NURBSTo", "SplineStart", "SplineKnot"):
                if end is None:
                    continue
                if start is None:
                    sub.append(["M", *norm(cur)])
                    start = cur
                sub.append(["L", *norm(end)])
                cur = end
            elif t == "PolylineTo":
                if end is None:
                    continue
                f = (cells.get("A") or (None, None))[1] or ""
                nums = [_num(n) for n in _POLY_NUM.findall(f)]
                if len(nums) >= 2 and all(n is not None for n in nums):
                    xt, yt = nums[0], nums[1]
                    for i in range(2, len(nums) - 1, 2):
                        px = nums[i] * W if xt else nums[i] * W / max(cells["X"][2], 1e-9)
                        py = nums[i + 1] * H if yt else nums[i + 1] * H / max(cells["X"][3], 1e-9)
                        sub.append(["L", *norm((px, py))])
                sub.append(["L", *norm(end)])
                cur = end
            elif t == "ArcTo":
                if end is None:
                    continue
                bow = _num((cells.get("A") or ("0",))[0], 0.0) or 0.0
                ref = cells.get("A")
                if ref and not rel and ref[2] and ref[3]:
                    bow *= math.sqrt((W / ref[2]) * (H / ref[3]))
                dx, dy = end[0] - cur[0], end[1] - cur[1]
                length = math.hypot(dx, dy)
                arcs = None
                if abs(bow) > 1e-9 and length > 1e-9:
                    # Bombement positif : à droite du sens de parcours (repère y vers le haut).
                    mid = ((cur[0] + end[0]) / 2 + bow * dy / length,
                           (cur[1] + end[1]) / 2 - bow * dx / length)
                    arcs = _arc3(cur, mid, end)
                if arcs:
                    for c1, c2, p3 in arcs:
                        sub.append(["C", *norm(c1), *norm(c2), *norm(p3)])
                else:
                    sub.append(["L", *norm(end)])
                cur = end
            elif t in ("EllipticalArcTo", "RelEllipticalArcTo"):
                ctrl = point("A", "B")
                if end is None:
                    continue
                angle = _num((cells.get("C") or ("0",))[0], 0.0) or 0.0
                ratio = _num((cells.get("D") or ("1",))[0], 1.0) or 1.0
                arcs = None
                if ctrl is not None and abs(ratio) > 1e-9:
                    ca, sa = math.cos(-angle), math.sin(-angle)

                    def to_c(p):
                        x, y = p[0] * ca - p[1] * sa, p[0] * sa + p[1] * ca
                        return (x / ratio, y)

                    def from_c(p):
                        x, y = p[0] * ratio, p[1]
                        return (x * ca + y * sa, -x * sa + y * ca)
                    res = _arc3(to_c(cur), to_c(ctrl), to_c(end))
                    if res:
                        arcs = [(from_c(c1), from_c(c2), from_c(p3)) for c1, c2, p3 in res]
                if arcs:
                    for c1, c2, p3 in arcs:
                        sub.append(["C", *norm(c1), *norm(c2), *norm(p3)])
                else:
                    sub.append(["L", *norm(end)])
                cur = end
            elif t == "RelCubBezTo":
                c1, c2 = point("A", "B"), point("C", "D")
                if end is None or c1 is None or c2 is None:
                    continue
                sub.append(["C", *norm(c1), *norm(c2), *norm(end)])
                cur = end
            elif t == "RelQuadBezTo":
                c1 = point("A", "B")
                if end is None or c1 is None:
                    continue
                sub.append(["Q", *norm(c1), *norm(end)])
                cur = end
            elif t == "Ellipse":
                a, c = point("A", "B"), point("C", "D")
                if end is None or a is None or c is None:
                    continue
                if sub:
                    out.extend(sub)
                    sub = []
                center = end
                st, segs = _ellipse_cubics(center, (a[0] - center[0], a[1] - center[1]),
                                           (c[0] - center[0], c[1] - center[1]))
                sub.append(["M", *norm(st)])
                for c1, c2, p3 in segs:
                    sub.append(["C", *norm(c1), *norm(c2), *norm(p3)])
                sub.append(["Z"])
                start = None
            if len(cmds) + len(details) + len(sub) > fileformat.MAX_PATH_COMMANDS:
                raise VsdxError("Géométrie trop complexe.")
        if sub:
            if start is not None and not flags["NoFill"] and \
                    math.dist(start, cur) < 1e-6 * max(W, H) and sub[-1][0] != "Z":
                sub.append(["Z"])
            out.extend(sub)
    return cmds + details, any_fill, any_line


class _Affine:
    """Transformation affine plane (repère Visio, y vers le haut, en pouces)."""

    def __init__(self, a=1.0, b=0.0, c=0.0, d=1.0, e=0.0, f=0.0):
        self.m = (a, b, c, d, e, f)

    def map(self, x, y):
        a, b, c, d, e, f = self.m
        return a * x + c * y + e, b * x + d * y + f

    def then(self, other: "_Affine") -> "_Affine":
        """self appliquée d'abord, puis other."""
        a, b, c, d, e, f = self.m
        A, B, C, D, E, F = other.m
        return _Affine(A * a + C * b, B * a + D * b, A * c + C * d, B * c + D * d,
                       A * e + C * f + E, B * e + D * f + F)


def _local_to_parent(sheet: _Sheet, W: float, H: float) -> _Affine:
    px, py = sheet.num("PinX", 0.0), sheet.num("PinY", 0.0)
    lx, ly = sheet.num("LocPinX", W / 2), sheet.num("LocPinY", H / 2)
    ang = sheet.num("Angle", 0.0) or 0.0
    fx = -1.0 if sheet.num("FlipX", 0.0) else 1.0
    fy = -1.0 if sheet.num("FlipY", 0.0) else 1.0
    ca, sa = math.cos(ang), math.sin(ang)
    t = _Affine(e=-lx, f=-ly)
    t = t.then(_Affine(fx, 0, 0, fy, 0, 0))
    t = t.then(_Affine(ca, sa, -sa, ca, 0, 0))
    return t.then(_Affine(e=px, f=py))


class _Importer:
    def __init__(self, pkg: _Package):
        self.pkg = pkg
        self.warnings: list[str] = []
        self.styles: dict[str, _Sheet] = {}
        self.fonts: dict[str, str] = {}
        self.masters: dict[str, tuple[str, str]] = {}  # ID -> (NameU, part)
        self._master_cache: dict[str, dict] = {}
        self.count = 0
        self.layer_names: list[str] = []

    def warn(self, msg: str) -> None:
        if msg not in self.warnings:
            self.warnings.append(msg)

    def run(self) -> dict:
        root_rels = self.pkg.rels("")
        doc_part = next((p for t, p in root_rels.values() if t == REL_DOC), "visio/document.xml")
        doc_xml = self.pkg.xml(doc_part)
        if doc_xml is None:
            raise VsdxError("Partie principale du document Visio introuvable.")
        self._load_styles(doc_xml)
        doc_rels = self.pkg.rels(doc_part)
        pages_part = next((p for t, p in doc_rels.values() if t == REL_PAGES), None)
        masters_part = next((p for t, p in doc_rels.values() if t == REL_MASTERS), None)
        if masters_part:
            self._load_masters(masters_part)
        if not pages_part:
            raise VsdxError("Aucune page dans ce document Visio.")
        pages_xml = self.pkg.xml(pages_part)
        page_rels = self.pkg.rels(pages_part)
        pages = []
        id_to_name: dict[str, str] = {}
        backrefs: list[tuple[dict, str]] = []
        for page in pages_xml.findall(_v("Page")):
            sheet_elem = page.find(_v("PageSheet"))
            ps = _Sheet(sheet_elem) if sheet_elem is not None else None
            pw = (ps.num("PageWidth", 8.5) if ps else 8.5) or 8.5
            ph = (ps.num("PageHeight", 11.0) if ps else 11.0) or 11.0
            rel = page.find(_v("Rel"))
            rid = rel.get(f"{{{RNS}}}id") if rel is not None else None
            part = page_rels.get(rid, ("", None))[1] if rid else None
            name = security.clean_line(page.get("Name") or page.get("NameU") or "", 100) \
                or f"Page-{len(pages) + 1}"
            self.layer_names = []
            if ps is not None:
                for _key, cells in ps.named_rows("Layer"):
                    self.layer_names.append(security.clean_line(cells.get("Name") or cells.get("NameUniv") or
                                                                f"Calque {len(self.layer_names) + 1}", 64))
            page_dict = self._load_page(part, name, pw, ph)
            if ps is not None:
                for key, cells in ps.named_rows("User"):
                    if key == "LinXGuides":
                        raw = [g.split(":") for g in (cells.get("Value") or "").split(";") if ":" in g]
                        page_dict["guides"] = fileformat.clean_guides(
                            [{"o": o, "pos": (_num(v, None) or 0.0) * PX_PER_INCH} for o, v in raw[:200]])
            id_to_name[page.get("ID", "")] = page_dict["name"]
            page_dict["is_background"] = page.get("Background") in ("1", "true")
            if page.get("BackPage"):
                backrefs.append((page_dict, page.get("BackPage")))
            if ps is not None:
                seen = set()
                for _key, cells in ps.named_rows("Layer"):
                    lname = security.clean_line(cells.get("Name") or cells.get("NameUniv") or "", 64)
                    if lname and lname not in seen:
                        seen.add(lname)
                        page_dict["layers"].append({"name": lname, "visible": cells.get("Visible", "1") != "0",
                                                    "printable": cells.get("Print", "1") != "0",
                                                    "locked": cells.get("Lock", "0") == "1"})
            pages.append(page_dict)
            if len(pages) >= fileformat.MAX_PAGES:
                break
        if not pages:
            raise VsdxError("Aucune page dans ce document Visio.")
        for page_dict, back_id in backrefs:
            page_dict["backpage"] = id_to_name.get(back_id, "")
        return {"format": fileformat.FORMAT, "version": fileformat.VERSION,
                "settings": {"route": "orthogonal"}, "properties": {}, "pages": pages}

    def _load_styles(self, doc_xml) -> None:
        for fn in doc_xml.iter(_v("FaceName")):
            for key in ("ID", "NameU", "Name"):
                if fn.get(key) is not None:
                    self.fonts.setdefault(fn.get("ID") or fn.get("NameU"), fn.get("NameU") or fn.get("Name"))
        sheets = doc_xml.find(_v("StyleSheets"))
        if sheets is None:
            return
        for st in sheets.findall(_v("StyleSheet")):
            self.styles[st.get("ID")] = _Sheet(st, None, self.styles)

    def _load_masters(self, part: str) -> None:
        xml = self.pkg.xml(part)
        if xml is None:
            return
        rels = self.pkg.rels(part)
        for m in xml.findall(_v("Master")):
            rel = m.find(_v("Rel"))
            rid = rel.get(f"{{{RNS}}}id") if rel is not None else None
            if rid in rels:
                self.masters[m.get("ID")] = (m.get("NameU") or m.get("Name") or "", rels[rid][1])

    def _master_shapes(self, master_id: str) -> dict:
        if master_id in self._master_cache:
            return self._master_cache[master_id]
        result: dict = {"top": None, "by_id": {}}
        self._master_cache[master_id] = result
        if master_id not in self.masters:
            return result
        xml = self.pkg.xml(self.masters[master_id][1])
        if xml is None:
            return result
        shapes = xml.find(_v("Shapes"))
        if shapes is None:
            return result
        top = shapes.findall(_v("Shape"))
        if top:
            result["top"] = _Sheet(top[0], None, self.styles)

        def walk(container, depth=0):
            if depth > MAX_DEPTH:
                return
            for s in container.findall(_v("Shape")):
                result["by_id"][s.get("ID")] = _Sheet(s, None, self.styles)
                sub = s.find(_v("Shapes"))
                if sub is not None:
                    walk(sub, depth + 1)
        walk(shapes)
        return result

    def _sheet(self, elem, parent_master: str | None) -> _Sheet:
        master_id = elem.get("Master") or parent_master
        master = None
        if master_id:
            ms = self._master_shapes(master_id)
            if elem.get("MasterShape"):
                master = ms["by_id"].get(elem.get("MasterShape"))
            elif elem.get("Master"):
                master = ms["top"]
        return _Sheet(elem, master, self.styles)

    def _load_page(self, part: str | None, name: str, pw: float, ph: float) -> dict:
        page = {"name": name, "width": pw * PX_PER_INCH, "height": ph * PX_PER_INCH,
                "background": "#ffffff", "layers": [], "shapes": [], "connectors": []}
        if not part:
            return page
        xml = self.pkg.xml(part)
        if xml is None:
            return page
        self.page_h = ph
        self.page_rels = self.pkg.rels(part)
        self.id_map: dict[str, str] = {}
        self.conn_states: dict[str, dict] = {}
        self.page_index = getattr(self, "page_index", 0) + 1
        self.prefix = f"p{self.page_index}_"
        shapes = xml.find(_v("Shapes"))
        if shapes is not None:
            self._walk(shapes, _Affine(), 0.0, None, "", page, 0)
        connects = xml.find(_v("Connects"))
        if connects is not None:
            for c in connects.findall(_v("Connect")):
                conn = self.conn_states.get(c.get("FromSheet"))
                target = self.id_map.get(c.get("ToSheet"))
                if conn is None or target is None:
                    continue
                cell = c.get("FromCell", "")
                end = conn["src"] if cell.startswith("Begin") else conn["dst"] if cell.startswith("End") \
                    else None
                if end is not None:
                    end["shape"] = target
                    end["port"] = -1
        return page

    def _walk(self, container, parent: _Affine, parent_angle: float, parent_master, group: str,
              page: dict, depth: int) -> None:
        if depth > MAX_DEPTH:
            self.warn("Imbrication de groupes trop profonde : une partie a été ignorée.")
            return
        for elem in container.findall(_v("Shape")):
            self.count += 1
            if self.count > MAX_SHAPES:
                raise VsdxError("Trop de formes dans ce document Visio.")
            sheet = self._sheet(elem, parent_master)
            user_rows = dict(sheet.named_rows("User"))
            if user_rows.get("LinXDataGraphicSnapshot", {}).get("Value") == "1":
                # Rattache l'instantané au parent LinXdiagram ; si le parent a été supprimé dans Visio,
                # l'annotation reste importable comme une forme autonome.
                source_id = user_rows.get("LinXDataGraphicSource", {}).get("Value", "")
                source_lxd_id = self.id_map.get(source_id)
                source = next((s for s in page["shapes"] if s["id"] == source_lxd_id), None)
                graphic = _data_graphic_from_rows(user_rows)
                if source is not None and graphic and graphic["field"] in source.get("data", {}):
                    current = source.get("data_graphic", {})
                    if ("status_colors" not in graphic and current.get("field") == graphic["field"]
                            and current.get("display") == graphic["display"]
                            and current.get("status_colors")):
                        graphic["status_colors"] = current["status_colors"]
                    source["data_graphic"] = graphic
                    continue
            W = abs(sheet.num("Width", 0.0) or 0.0)
            H = abs(sheet.num("Height", 0.0) or 0.0)
            is_1d = sheet.raw("BeginX") is not None and sheet.raw("EndX") is not None
            if is_1d:
                self._connector(sheet, elem, parent, page)
                continue
            to_page = _local_to_parent(sheet, W, H).then(parent)
            angle = parent_angle + (sheet.num("Angle", 0.0) or 0.0)
            kind = elem.get("Type", "Shape")
            cff_type = self._cff_type(elem, sheet, W, H)
            if cff_type is not None:
                self._shape(sheet, elem, to_page, angle, W, H, group, page, forced_type=cff_type)
                continue
            if kind == "Group":
                gid = f"g{self.prefix}{elem.get('ID')}"
                sub = elem.find(_v("Shapes"))
                has_own = bool(sheet.sections.get("Geometry")) or bool((sheet.text() or "").strip())
                if has_own:
                    self._shape(sheet, elem, to_page, angle, W, H, gid, page)
                if sub is not None:
                    self._walk(sub, to_page, angle, elem.get("Master") or parent_master, gid, page,
                               depth + 1)
                continue
            self._shape(sheet, elem, to_page, angle, W, H, group, page)

    def _text_style(self, sheet: _Sheet) -> dict:
        font_raw = sheet.row_cell("Character", "Font")
        font = None
        if font_raw is not None:
            font = self.fonts.get(font_raw, None if font_raw.isdigit() else font_raw)
        if font in (None, "", "Themed"):
            font = None
        size = _num(sheet.row_cell("Character", "Size"), None)
        style_bits = int(_num(sheet.row_cell("Character", "Style"), 0) or 0)
        halign = int(_num(sheet.row_cell("Paragraph", "HorzAlign"), 1) or 0)
        valign = int(_num(sheet.raw("VerticalAlign"), 1) or 0)
        out = {
            "size": size * 72.0 if size else 11.0,
            "bold": bool(style_bits & 1), "italic": bool(style_bits & 2),
            "underline": bool(style_bits & 4),
            "color": _color(sheet.row_cell("Character", "Color")) or "#000000",
            "halign": ("left", "center", "right", "center")[min(max(halign, 0), 3)],
            "valign": ("top", "middle", "bottom")[min(max(valign, 0), 2)],
        }
        if font:
            out["font"] = font
        return out

    def _line_style(self, sheet: _Sheet) -> dict:
        pattern = int(_num(sheet.raw("LinePattern"), 1) or 0)
        weight = sheet.num("LineWeight", 0.75 / 72.0) or (0.75 / 72.0)
        dash = {1: "solid", 2: "dash", 3: "dot", 4: "dashdot"}.get(pattern, "dash")
        return {"line": "" if pattern == 0 else (_color(sheet.raw("LineColor")) or "#000000"),
                "line_width": max(0.25, weight * PX_PER_INCH), "dash": dash}

    def _data(self, sheet: _Sheet) -> dict:
        data = {}
        for key, cells in sheet.named_rows("Property"):
            label = cells.get("Label") or key.replace("Row_", "Donnée ")
            value = cells.get("Value")
            if value is not None and value != "":
                data[label] = value
        return data

    def _cff_type(self, elem, sheet: _Sheet, W: float, H: float) -> str | None:
        """Couloirs, séparateurs et cadres des diagrammes interfonctionnels Visio."""
        for key, cells in sheet.named_rows("User"):
            if key == "LinXType" and cells.get("Value", "").startswith("cff."):
                return cells["Value"]
        name = (self.masters.get(elem.get("Master") or "", ("",))[0] + " " + (elem.get("NameU") or "")).lower()
        if any(k in name for k in ("swimlane", "couloir")):
            return "cff.lane_h" if W >= H else "cff.lane_v"
        if any(k in name for k in ("separator", "séparateur", "phase")):
            return "cff.phase_h" if H >= W else "cff.phase_v"
        if any(k in name for k in ("cff container", "cross-functional", "interfonctionnel")):
            return "cff.frame_h" if W >= H else "cff.frame_v"
        return None

    def _shape(self, sheet: _Sheet, elem, to_page: _Affine, angle: float, W: float, H: float,
               group: str, page: dict, forced_type: str | None = None) -> None:
        if W < 1e-6 or H < 1e-6:
            if not (sheet.text() or "").strip():
                return
            W, H = max(W, 0.3), max(H, 0.2)
        cx, cy = to_page.map(W / 2, H / 2)
        sid = f"{self.prefix}{elem.get('ID')}"
        self.id_map[elem.get("ID")] = sid
        user_rows = dict(sheet.named_rows("User"))
        type_id = forced_type
        for key, cells in user_rows.items():
            if type_id is None and key == "LinXType" and cells.get("Value") in stencils.SHAPES:
                type_id = cells["Value"]
        cmds, any_fill, any_line = ([], True, True)
        image = ""
        if elem.get("Type") == "Foreign":
            image = self._foreign_image(elem)
            type_id = "special.image" if image else "special.custom"
        elif type_id is None:
            cmds, any_fill, any_line = _geometry_to_commands(sheet, W, H)
            type_id = "special.custom" if cmds else "basic.text"
        fill_pattern = int(_num(sheet.raw("FillPattern"), 1) or 0)
        line = self._line_style(sheet)
        style = {
            "fill": "" if (fill_pattern == 0 or not any_fill) else
            (_color(sheet.raw("FillForegnd")) or "#ffffff"),
            "transparency": min(100.0, max(0.0, (sheet.num("FillForegndTrans", 0.0) or 0.0) * 100)),
            "line": line["line"] if any_line else "", "line_width": line["line_width"],
            "dash": line["dash"], "themed": False,
        }
        if type_id == "basic.text":
            style["fill"] = style["line"] = ""
        text = (sheet.text() or "").replace("\r\n", "\n").replace(" ", "\n").rstrip("\n")
        if forced_type and not text.strip():
            for sub in elem.iter(_v("Text")):
                text = "".join(sub.itertext()).strip()
                if text:
                    break
        st = {"id": sid, "type": type_id, "x": cx * PX_PER_INCH, "y": (self.page_h - cy) * PX_PER_INCH,
              "w": W * PX_PER_INCH, "h": H * PX_PER_INCH,
              "rotation": -math.degrees(angle), "flip_h": bool(sheet.num("FlipX", 0)),
              "flip_v": bool(sheet.num("FlipY", 0)), "z": float(self.count), "text": text,
              "style": style, "text_style": self._text_style(sheet), "data": self._data(sheet),
              "link": "", "group": group}
        data_graphic = _data_graphic_from_rows(user_rows)
        if data_graphic:
            st["data_graphic"] = data_graphic
        locks = [sheet.num(n, 0) for n in ("LockMoveX", "LockMoveY", "LockDelete")]
        st["locked"] = all(bool(v) for v in locks)
        tip = sheet.raw("Comment")
        if tip and tip not in ("0", "Themed"):
            st["tip"] = tip
        member = sheet.raw("LayerMember")
        if member:
            first = member.split(";")[0].strip()
            if first.isdigit() and int(first) < len(self.layer_names):
                st["layer"] = self.layer_names[int(first)]
        if forced_type:
            role = swimlanes.KIND_OF[forced_type][0]
            st["z"] = {"frame": swimlanes.Z_FRAME, "lane": swimlanes.Z_LANE,
                       "phase": swimlanes.Z_PHASE}[role] + self.count / 1000.0
        rows = sheet.named_rows("Hyperlink")
        if rows:
            st["link"] = rows[0][1].get("Address", "")
        if type_id == "special.custom":
            st["path"] = cmds
        if type_id == "special.image":
            st["image"] = image
        tw, th = sheet.num("TxtWidth"), sheet.num("TxtHeight")
        if tw and th and W > 0 and H > 0:
            tpx = sheet.num("TxtPinX", W / 2)
            tpy = sheet.num("TxtPinY", H / 2)
            tlx = sheet.num("TxtLocPinX", tw / 2)
            tly = sheet.num("TxtLocPinY", th / 2)
            left = (tpx - tlx) / W
            top = 1.0 - (tpy - tly + th) / H
            st["text_rect"] = [left, top, tw / W, th / H]
        page["shapes"].append(st)

    def _foreign_image(self, elem) -> str:
        fd = elem.find(_v("ForeignData"))
        rel = fd.find(_v("Rel")) if fd is not None else None
        rid = rel.get(f"{{{RNS}}}id") if rel is not None else None
        if not rid or rid not in self.page_rels:
            return ""
        data = self.pkg.read(self.page_rels[rid][1])
        if not data or not (data.startswith(b"\x89PNG\r\n\x1a\n") or data.startswith(b"\xff\xd8\xff")):
            self.warn("Certaines images (EMF, WMF, OLE…) ne sont pas prises en charge et ont été "
                      "remplacées par un cadre.")
            return ""
        if len(data) > fileformat.MAX_IMAGE_BYTES:
            self.warn("Une image trop volumineuse a été ignorée.")
            return ""
        return base64.b64encode(data).decode("ascii")

    def _connector(self, sheet: _Sheet, elem, parent: _Affine, page: dict) -> None:
        bx, by = parent.map(sheet.num("BeginX", 0.0), sheet.num("BeginY", 0.0))
        ex, ey = parent.map(sheet.num("EndX", 0.0), sheet.num("EndY", 0.0))
        cid = f"{self.prefix}c{elem.get('ID')}"
        route_ext = int(_num(sheet.raw("ConLineRouteExt"), 0) or 0)
        geom_points = 0
        axis_aligned = True
        W = abs(sheet.num("Width", 0.0) or 0.0)
        H = abs(sheet.num("Height", 0.0) or 0.0)
        cmds, _, _ = _geometry_to_commands(sheet, max(W, 1e-3), max(H, 1e-3))
        prev = None
        for c in cmds:
            if c[0] in ("M", "L"):
                geom_points += 1
                if prev is not None and abs(prev[0] - c[1]) > 1e-6 and abs(prev[1] - c[2]) > 1e-6:
                    axis_aligned = False
                prev = (c[1], c[2])
        name = (elem.get("NameU") or "") + " " + (self.masters.get(elem.get("Master") or "", ("",))[0])
        if route_ext == 2:
            route = "curved"
        elif geom_points > 2 and axis_aligned:
            route = "orthogonal"
        elif "connector" in name.lower() or "connecteur" in name.lower():
            route = "orthogonal"
        else:
            route = "straight"
        line = self._line_style(sheet)
        begin = int(_num(sheet.raw("BeginArrow"), 0) or 0)
        end = int(_num(sheet.raw("EndArrow"), 0) or 0)
        ts = self._text_style(sheet)
        ts["valign"] = "middle"
        st = {"id": cid, "kind": "connector",
              "src": {"shape": "", "port": -1, "x": bx * PX_PER_INCH,
                      "y": (self.page_h - by) * PX_PER_INCH},
              "dst": {"shape": "", "port": -1, "x": ex * PX_PER_INCH,
                      "y": (self.page_h - ey) * PX_PER_INCH},
              "z": float(self.count), "text": (sheet.text() or "").strip(),
              "style": {"line": line["line"] or "#000000", "line_width": line["line_width"],
                        "dash": line["dash"],
                        "arrow_start": "none" if begin == 0 else ("open" if begin == 1 else "triangle"),
                        "arrow_end": "none" if end == 0 else ("open" if end == 1 else "triangle"),
                        "route": route, "themed": False},
              "text_style": ts, "data": self._data(sheet)}
        self.conn_states[elem.get("ID")] = st
        page["connectors"].append(st)


def import_vsdx(path: str) -> tuple[dict, list[str]]:
    """Importe un fichier .vsdx ; retourne (document validé, avertissements)."""
    try:
        data = security.read_file_limited(path, MAX_VSDX_BYTES)
    except security.SecurityError as exc:
        raise VsdxError(str(exc)) from exc
    return import_vsdx_bytes(data)


def import_vsdx_bytes(data: bytes) -> tuple[dict, list[str]]:
    imp = _Importer(_Package(data))
    try:
        raw = imp.run()
    except (KeyError, ValueError, AttributeError, TypeError) as exc:
        raise VsdxError(f"Document Visio non pris en charge ({type(exc).__name__}).") from exc
    # Toutes les pages repassent par la validation stricte du format natif.
    for p in raw["pages"]:
        for s in p["shapes"]:
            tr = s.pop("text_rect", None)
            if tr:
                s["text_rect"] = tr
    doc, warnings = fileformat.validate_document(raw)
    imp.warn("Les formules ShapeSheet ne sont pas exécutées : seules leurs valeurs sont importées.")
    return doc, imp.warnings + warnings


# =========================================================================== export

_XML_DECL = b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n'


def _tostring(elem, default_ns: str = VNS) -> bytes:
    """Sérialise avec l'espace de noms par défaut (pas de préfixes « ns0: »)."""
    ET.register_namespace("", default_ns)
    ET.register_namespace("r", RNS)
    return _XML_DECL + ET.tostring(elem, encoding="utf-8", xml_declaration=False)


def _f(v: float) -> str:
    if not math.isfinite(v):
        v = 0.0
    s = f"{v:.9f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def _xml_text(s: str) -> str:
    return _XML_BAD_RE.sub("", s)


def _el(parent, tag, **attrs):
    e = ET.SubElement(parent, _v(tag))
    for k, v in attrs.items():
        if v is not None:
            e.set(k, v)
    return e


def _cell(parent, name: str, value, unit: str | None = None, formula: str | None = None):
    if isinstance(value, float):
        value = _f(value)
    elif isinstance(value, bool):
        value = "1" if value else "0"
    elif isinstance(value, int):
        value = str(value)
    c = _el(parent, "Cell", N=name, V=_xml_text(str(value)))
    if unit:
        c.set("U", unit)
    if formula:
        c.set("F", _xml_text(formula))
    return c


def _data_graphic_from_rows(rows: dict) -> dict:
    colors = []
    raw = rows.get("LinXDataGraphicColors", {}).get("Value", "")
    if isinstance(raw, str) and len(raw) <= 16_384:
        try:
            colors = json.loads(raw)
        except (TypeError, ValueError):
            pass
    return fileformat.clean_data_graphic({
        "field": rows.get("LinXDataGraphicField", {}).get("Value", ""),
        "display": rows.get("LinXDataGraphicDisplay", {}).get("Value", ""),
        "status_colors": colors,
    })


def _str_formula(s: str) -> str:
    return '"' + s.replace('"', '""') + '"'


def _path_subpaths(path: QPainterPath, w: float, h: float):
    """QPainterPath (repère 0..w, 0..h, y vers le bas) → sous-chemins normalisés."""
    subs = []
    cur = None
    i = 0
    n = path.elementCount()
    ET_ = QPainterPath.ElementType
    while i < n:
        e = path.elementAt(i)
        if e.type == ET_.MoveToElement:
            cur = [("M", e.x / w, e.y / h)]
            subs.append(cur)
            i += 1
        elif e.type == ET_.LineToElement:
            if cur is None:
                cur = [("M", 0.0, 0.0)]
                subs.append(cur)
            cur.append(("L", e.x / w, e.y / h))
            i += 1
        elif e.type == ET_.CurveToElement and i + 2 < n:
            c2 = path.elementAt(i + 1)
            p3 = path.elementAt(i + 2)
            if cur is None:
                cur = [("M", 0.0, 0.0)]
                subs.append(cur)
            cur.append(("C", e.x / w, e.y / h, c2.x / w, c2.y / h, p3.x / w, p3.y / h))
            i += 3
        else:
            i += 1
    return subs


def _geometry_section(shape_el, ix: int, sub, no_fill: bool, no_line: bool) -> None:
    sec = _el(shape_el, "Section", N="Geometry", IX=str(ix))
    _cell(sec, "NoFill", no_fill)
    _cell(sec, "NoLine", no_line)
    _cell(sec, "NoShow", False)
    _cell(sec, "NoSnap", False)
    _cell(sec, "NoQuickDrag", False)
    first = sub[0]
    for r, cmd in enumerate(sub, start=1):
        if cmd[0] == "M":
            row = _el(sec, "Row", T="RelMoveTo", IX=str(r))
            _cell(row, "X", cmd[1])
            _cell(row, "Y", 1.0 - cmd[2])
        elif cmd[0] == "L":
            row = _el(sec, "Row", T="RelLineTo", IX=str(r))
            _cell(row, "X", cmd[1])
            _cell(row, "Y", 1.0 - cmd[2])
        else:
            row = _el(sec, "Row", T="RelCubBezTo", IX=str(r))
            _cell(row, "X", cmd[5])
            _cell(row, "Y", 1.0 - cmd[6])
            _cell(row, "A", cmd[1])
            _cell(row, "B", 1.0 - cmd[2])
            _cell(row, "C", cmd[3])
            _cell(row, "D", 1.0 - cmd[4])
    last = sub[-1]
    end = (last[-2], last[-1])
    if not no_fill and (abs(end[0] - first[1]) > 1e-9 or abs(end[1] - first[2]) > 1e-9):
        row = _el(sec, "Row", T="RelLineTo", IX=str(len(sub) + 1))
        _cell(row, "X", first[1])
        _cell(row, "Y", 1.0 - first[2])


def _text_cells(shape_el, ts: dict, fonts: dict) -> None:
    _cell(shape_el, "VerticalAlign", {"top": 0, "middle": 1, "bottom": 2}[ts["valign"]])
    sec = _el(shape_el, "Section", N="Character")
    row = _el(sec, "Row", IX="0")
    fonts.setdefault(ts["font"], len(fonts) + 1)
    _cell(row, "Font", ts["font"])
    _cell(row, "Color", ts["color"])
    _cell(row, "Style", (1 if ts["bold"] else 0) | (2 if ts["italic"] else 0) |
          (4 if ts["underline"] else 0))
    _cell(row, "Size", ts["size"] / 72.0, "PT")
    sec = _el(shape_el, "Section", N="Paragraph")
    row = _el(sec, "Row", IX="0")
    _cell(row, "HorzAlign", {"left": 0, "center": 1, "right": 2}[ts["halign"]])


def _data_sections(shape_el, data: dict, link: str, type_id: str | None, container: bool = False,
                   data_graphic: dict | None = None) -> None:
    if type_id or data_graphic:
        sec = _el(shape_el, "Section", N="User")
        if type_id:
            row = _el(sec, "Row", N="LinXType")
            _cell(row, "Value", type_id, "STR", _str_formula(type_id))
            _cell(row, "Prompt", "")
            if container:  # cadre, couloir ou phase : conteneur Visio
                row = _el(sec, "Row", N="msvStructureType")
                _cell(row, "Value", "Container", "STR", _str_formula("Container"))
                _cell(row, "Prompt", "")
        if data_graphic:
            for name, value in (("LinXDataGraphicField", data_graphic.get("field", "")),
                                ("LinXDataGraphicDisplay", data_graphic.get("display", ""))):
                row = _el(sec, "Row", N=name)
                _cell(row, "Value", value, "STR", _str_formula(value))
                _cell(row, "Prompt", "")
            colors = data_graphic.get("status_colors", [])
            if colors:
                value = json.dumps(colors, ensure_ascii=False, separators=(",", ":"))
                row = _el(sec, "Row", N="LinXDataGraphicColors")
                _cell(row, "Value", value, "STR", _str_formula(value))
                _cell(row, "Prompt", "")
    if data:
        sec = _el(shape_el, "Section", N="Property")
        used = set()
        for i, (k, v) in enumerate(data.items(), start=1):
            name = re.sub(r"[^A-Za-z0-9_]", "_", k)[:30] or f"Row_{i}"
            if name in used or name[0].isdigit():
                name = f"Row_{i}"
            used.add(name)
            row = _el(sec, "Row", N=name)
            _cell(row, "Value", v, "STR", _str_formula(v))
            _cell(row, "Prompt", "")
            _cell(row, "Label", k)
            _cell(row, "Type", 0)
    if link:
        sec = _el(shape_el, "Section", N="Hyperlink")
        row = _el(sec, "Row", N="Row_1")
        _cell(row, "Address", link)
        _cell(row, "Description", "")
        _cell(row, "NewWindow", False)


def _data_graphic_snapshot(shapes_el, it, sid: int, source_id: int, page_h: float, fonts: dict,
                           layer_index: int | None) -> None:
    """Exporte le graphique comme annotation vectorielle figée, faute de binding Visio natif."""
    from PyQt6.QtCore import QRectF
    from PyQt6.QtGui import QFont, QFontMetricsF

    text = it.data_graphic_text()
    if not text:
        return
    rect = it.data_graphic_rect(1.0)
    if rect.isNull():
        return
    center = it.mapToScene(rect.center())
    width, height = rect.width() / PX_PER_INCH, rect.height() / PX_PER_INCH
    width_px, height_px = rect.width(), rect.height()
    fill, ink, border = it.data_graphic_palette()
    el = _el(shapes_el, "Shape", ID=str(sid), NameU=f"Data graphic.{sid}",
             Name=f"Graphique de données.{sid}", Type="Shape", LineStyle="0",
             FillStyle="0", TextStyle="0")
    _cell(el, "PinX", center.x() / PX_PER_INCH)
    _cell(el, "PinY", page_h - center.y() / PX_PER_INCH)
    _cell(el, "Width", width)
    _cell(el, "Height", height)
    _cell(el, "LocPinX", width / 2, None, "Width*0.5")
    _cell(el, "LocPinY", height / 2, None, "Height*0.5")
    _cell(el, "Angle", -math.radians(it.rotation()))
    _cell(el, "LineWeight", 0.6, "PT")
    _cell(el, "LineColor", border)
    _cell(el, "LinePattern", 1)
    _cell(el, "FillForegnd", fill)
    _cell(el, "FillPattern", 1)
    _cell(el, "FillForegndTrans", 0.0)
    if layer_index is not None:
        _cell(el, "LayerMember", str(layer_index), "STR")
    sec = _el(el, "Section", N="User")
    row = _el(sec, "Row", N="LinXDataGraphicSnapshot")
    _cell(row, "Value", "1", "STR", _str_formula("1"))
    _cell(row, "Prompt", "")
    row = _el(sec, "Row", N="LinXDataGraphicSource")
    _cell(row, "Value", str(source_id), "STR", _str_formula(str(source_id)))
    _cell(row, "Prompt", "")
    for name, value in (("LinXDataGraphicField", it.data_graphic.get("field", "")),
                        ("LinXDataGraphicDisplay", it.data_graphic.get("display", ""))):
        row = _el(sec, "Row", N=name)
        _cell(row, "Value", value, "STR", _str_formula(value))
        _cell(row, "Prompt", "")
    colors = it.data_graphic.get("status_colors", [])
    if colors:
        value = json.dumps(colors, ensure_ascii=False, separators=(",", ":"))
        row = _el(sec, "Row", N="LinXDataGraphicColors")
        _cell(row, "Value", value, "STR", _str_formula(value))
        _cell(row, "Prompt", "")
    _cell(el, "TxtPinX", width / 2)
    _cell(el, "TxtPinY", height / 2)
    _cell(el, "TxtWidth", width)
    _cell(el, "TxtHeight", height)
    _cell(el, "TxtLocPinX", width / 2)
    _cell(el, "TxtLocPinY", height / 2)
    margin = 8.0 / PX_PER_INCH
    for name in ("LeftMargin", "RightMargin"):
        _cell(el, name, margin)
    font = QFont("Arial")
    font.setPixelSize(11)
    shown = QFontMetricsF(font).elidedText(text, Qt.TextElideMode.ElideRight,
                                          max(1.0, width_px - 16.0))
    _text_cells(el, {"font": "Arial", "color": ink, "size": 8.25, "bold": False,
                     "italic": False, "underline": False, "valign": "middle", "halign": "left"}, fonts)
    path = QPainterPath()
    path.addRoundedRect(QRectF(0.0, 0.0, width_px, height_px), 5.0, 5.0)
    for sub in _path_subpaths(path, width_px, height_px):
        _geometry_section(el, 0, sub, False, False)
    _el(el, "Text").text = _xml_text(shown)


def _relationships(members: list[str], containers: list[str], ids: dict[str, int]) -> str:
    """Cellule Relationships : DEPENDSON(1, membres) côté conteneur, DEPENDSON(4, conteneurs)
    côté membre, avec des références Sheet.N comme les écrit Visio."""
    parts = []
    for kind, refs in ((1, members), (4, containers)):
        sheets = [f"Sheet.{ids[r]}!SheetRef()" for r in refs if r in ids]
        if sheets:
            parts.append(f"DEPENDSON({kind},{','.join(sheets)})")
    return f"SUM({','.join(parts)})" if parts else ""


def _page_xml(scene, images: list[tuple[str, bytes]], fonts: dict) -> tuple[bytes, list]:
    layer_ids = {lay["name"]: i for i, lay in enumerate(getattr(scene, "layers", []))}
    from .items import ConnectorItem, ShapeItem  # import local : évite un cycle au chargement

    root = ET.Element(_v("PageContents"))
    root.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    shapes_el = _el(root, "Shapes")
    connects: list[tuple[int, str, int, str, int]] = []
    ids: dict[str, int] = {}
    page_rels: list[tuple[str, str]] = []
    ph = scene.page_h / PX_PER_INCH
    items = sorted(scene.all_items(), key=lambda i: i.zValue())
    for n, it in enumerate(items, start=1):
        ids[it.id] = n
    member_of = scene.cff_memberships() if hasattr(scene, "cff_memberships") else {}
    members: dict[str, list[str]] = {}
    for k, owners in member_of.items():
        for c in owners:
            members.setdefault(c, []).append(k)
    for it in items:
        sid = ids[it.id]
        if isinstance(it, ShapeItem):
            st = it.state()
            sdef = it.sdef
            W, H = st["w"] / PX_PER_INCH, st["h"] / PX_PER_INCH
            kind = "Foreign" if st["type"] == "special.image" and it.image_b64 else "Shape"
            el = _el(shapes_el, "Shape", ID=str(sid), NameU=f"Shape.{sid}", Name=f"Forme.{sid}",
                     Type=kind, LineStyle="0", FillStyle="0", TextStyle="0")
            _cell(el, "PinX", st["x"] / PX_PER_INCH)
            _cell(el, "PinY", ph - st["y"] / PX_PER_INCH)
            _cell(el, "Width", W)
            _cell(el, "Height", H)
            _cell(el, "LocPinX", W / 2, None, "Width*0.5")
            _cell(el, "LocPinY", H / 2, None, "Height*0.5")
            _cell(el, "Angle", -math.radians(st["rotation"]))
            _cell(el, "FlipX", st["flip_h"])
            _cell(el, "FlipY", st["flip_v"])
            style = st["style"]
            _cell(el, "LineWeight", style["line_width"] / PX_PER_INCH, "PT")
            _cell(el, "LineColor", style["line"] or "#000000")
            _cell(el, "LinePattern", _DASH_TO_VISIO[style["dash"]] if style["line"] else 0)
            _cell(el, "FillForegnd", style["fill"] or "#ffffff")
            _cell(el, "FillPattern", 1 if style["fill"] else 0)
            _cell(el, "FillForegndTrans", style["transparency"] / 100.0)
            if st.get("locked"):
                for lock in ("LockWidth", "LockHeight", "LockMoveX", "LockMoveY", "LockRotate", "LockDelete"):
                    _cell(el, lock, True)
            if st.get("tip"):
                _cell(el, "Comment", st["tip"], "STR", _str_formula(st["tip"]))
            layer_index = layer_ids.get(st.get("layer", ""))
            if layer_index is not None:
                _cell(el, "LayerMember", str(layer_index), "STR")
            rel = _relationships(members.get(it.id, []), member_of.get(it.id, []), ids)
            if rel:
                _cell(el, "Relationships", 0, None, rel)
            tx, ty, tw, th = it.text_rect_norm()
            tw_in, th_in = tw * W, th * H
            if it.vertical_text():
                tw_in, th_in = th_in, tw_in  # le bloc de texte est tourné de 90°
                _cell(el, "TxtAngle", math.pi / 2)
            _cell(el, "TxtPinX", (tx + tw / 2) * W)
            _cell(el, "TxtPinY", (1.0 - (ty + th / 2)) * H)
            _cell(el, "TxtWidth", tw_in)
            _cell(el, "TxtHeight", th_in)
            _cell(el, "TxtLocPinX", tw_in / 2)
            _cell(el, "TxtLocPinY", th_in / 2)
            if kind == "Foreign":
                _cell(el, "ImgOffsetX", 0.0)
                _cell(el, "ImgOffsetY", 0.0)
                _cell(el, "ImgWidth", W)
                _cell(el, "ImgHeight", H)
            _text_cells(el, st["text_style"], fonts)
            if sdef.ports:
                sec = _el(el, "Section", N="Connection")
                for i, (nx, ny) in enumerate(sdef.ports):
                    row = _el(sec, "Row", IX=str(i))
                    _cell(row, "X", nx * W, None, f"Width*{_f(nx)}")
                    _cell(row, "Y", (1 - ny) * H, None, f"Height*{_f(1 - ny)}")
                    _cell(row, "DirX", 0.0)
                    _cell(row, "DirY", 0.0)
                    _cell(row, "Type", 0)
            _data_sections(el, st["data"], st["link"], st["type"], bool(sdef.container),
                           st.get("data_graphic"))
            outline, detail = it.export_paths()
            ix = 0
            if kind == "Foreign":
                rect = QPainterPath()
                rect.addRect(0, 0, st["w"], st["h"])
                outline, detail = rect, None
            for sub in _path_subpaths(outline, st["w"], st["h"]):
                no_fill = not style["fill"] or not sdef.outline_visible or kind == "Foreign"
                _geometry_section(el, ix, sub, no_fill, not style["line"] or not sdef.outline_visible)
                ix += 1
            if detail is not None:
                for sub in _path_subpaths(detail, st["w"], st["h"]):
                    _geometry_section(el, ix, sub, True, False)
                    ix += 1
            if kind == "Foreign":
                rid = f"rId{len(page_rels) + 1}"
                media = f"image{len(images) + 1}.png"
                raw = base64.b64decode(it.image_b64)
                if raw.startswith(b"\xff\xd8\xff"):
                    media = media.replace(".png", ".jpeg")
                images.append((media, raw))
                page_rels.append((rid, media))
                fd = _el(el, "ForeignData", ForeignType="Bitmap",
                         CompressionType="JPEG" if media.endswith("jpeg") else "PNG")
                rel = ET.SubElement(fd, _v("Rel"))
                rel.set(f"{{{RNS}}}id", rid)
            if st["text"]:
                _el(el, "Text").text = _xml_text(fields.resolve(st["text"], scene))
        elif isinstance(it, ConnectorItem):
            st = it.state()
            p1, p2 = it.end_points()
            bx, by = p1.x() / PX_PER_INCH, ph - p1.y() / PX_PER_INCH
            ex, ey = p2.x() / PX_PER_INCH, ph - p2.y() / PX_PER_INCH
            el = _el(shapes_el, "Shape", ID=str(sid), NameU=f"Dynamic connector.{sid}",
                     Name=f"Connecteur dynamique.{sid}", Type="Shape", LineStyle="0",
                     FillStyle="0", TextStyle="0")
            W, H = ex - bx, ey - by
            _cell(el, "PinX", (bx + ex) / 2)
            _cell(el, "PinY", (by + ey) / 2)
            _cell(el, "Width", W)
            _cell(el, "Height", H)
            _cell(el, "LocPinX", W / 2, None, "Width*0.5")
            _cell(el, "LocPinY", H / 2, None, "Height*0.5")
            _cell(el, "Angle", 0.0)
            glue = {}
            for which, cell_x, cell_y, trig in (("src", "BeginX", "BeginY", "BegTrigger"),
                                                ("dst", "EndX", "EndY", "EndTrigger")):
                end = st[which]
                target = ids.get(end["shape"]) if end["shape"] else None
                glue[which] = target
                x, y = (bx, by) if which == "src" else (ex, ey)
                if target is not None:
                    _cell(el, cell_x, x, None, "_WALKGLUE(BegTrigger,EndTrigger,WalkPreference)")
                    _cell(el, cell_y, y, None, "_WALKGLUE(BegTrigger,EndTrigger,WalkPreference)")
                    _cell(el, trig, 2.0, None, f"_XFTRIGGER(Sheet.{target}!EventXFMod)")
                else:
                    _cell(el, cell_x, x)
                    _cell(el, cell_y, y)
            _cell(el, "ObjType", 2)
            style = st["style"]
            _cell(el, "LineWeight", style["line_width"] / PX_PER_INCH, "PT")
            _cell(el, "LineColor", style["line"])
            _cell(el, "LinePattern", _DASH_TO_VISIO[style["dash"]])
            _cell(el, "BeginArrow", _ARROW_TO_VISIO[style["arrow_start"]])
            _cell(el, "EndArrow", _ARROW_TO_VISIO[style["arrow_end"]])
            _cell(el, "BeginArrowSize", 2)
            _cell(el, "EndArrowSize", 2)
            _cell(el, "ConLineRouteExt", {"straight": 1, "curved": 2}.get(style["route"], 0))
            _cell(el, "ShapeRouteStyle", 1 if style["route"] == "orthogonal" else 0)
            mid = it.path_scene().pointAtPercent(0.5)
            _cell(el, "TxtPinX", mid.x() / PX_PER_INCH - bx)
            _cell(el, "TxtPinY", ph - mid.y() / PX_PER_INCH - by)
            _cell(el, "TxtWidth", 1.5)
            _cell(el, "TxtHeight", 0.3)
            _cell(el, "TxtLocPinX", 0.75)
            _cell(el, "TxtLocPinY", 0.15)
            _text_cells(el, st["text_style"], fonts)
            _data_sections(el, st["data"], "", None)
            sec = _el(el, "Section", N="Geometry", IX="0")
            _cell(sec, "NoFill", True)
            _cell(sec, "NoLine", False)
            _cell(sec, "NoShow", False)
            _cell(sec, "NoSnap", False)
            polys = it.path_scene().toSubpathPolygons()
            pts = [(p.x(), p.y()) for poly in polys for p in poly]
            if len(pts) < 2:
                pts = [(p1.x(), p1.y()), (p2.x(), p2.y())]
            pts[0] = (p1.x(), p1.y())
            pts[-1] = (p2.x(), p2.y())
            for r, (x, y) in enumerate(pts, start=1):
                row = _el(sec, "Row", T="MoveTo" if r == 1 else "LineTo", IX=str(r))
                _cell(row, "X", x / PX_PER_INCH - bx)
                _cell(row, "Y", (ph - y / PX_PER_INCH) - by)
            if st["text"]:
                _el(el, "Text").text = _xml_text(fields.resolve(st["text"], scene))
            for which, part, from_part in (("src", "BeginX", 9), ("dst", "EndX", 12)):
                if glue[which] is not None:
                    connects.append((sid, part, from_part, glue[which]))
    # Visio n'a pas de ShapeSheet standard pour conserver l'association LinXdiagram :
    # on ajoute un instantané vectoriel déplaçable séparément, qui reprend l'aspect visible.
    next_id = len(ids) + 1
    for it in items:
        if not isinstance(it, ShapeItem) or not it.data_graphic_text():
            continue
        _data_graphic_snapshot(shapes_el, it, next_id, ids[it.id], ph, fonts,
                               layer_ids.get(it.layer) if it.layer else None)
        next_id += 1
    if connects:
        con_el = _el(root, "Connects")
        for sid, part, from_part, target in connects:
            _el(con_el, "Connect", FromSheet=str(sid), FromCell=part, FromPart=str(from_part),
                ToSheet=str(target), ToCell="PinX", ToPart="3")
    return _tostring(root), page_rels


def _rels_xml(rels: list[tuple[str, str, str]]) -> bytes:
    root = ET.Element(f"{{{PNS}}}Relationships")
    for rid, rtype, target in rels:
        r = ET.SubElement(root, f"{{{PNS}}}Relationship")
        r.set("Id", rid)
        r.set("Type", rtype)
        r.set("Target", target)
    return _tostring(root, PNS)


def export_vsdx(document, path: str) -> None:
    """Écrit le document au format Visio .vsdx (écriture atomique)."""
    from .items import ShapeItem

    base_shape_count = sum(len(scene.all_items()) for scene in document.pages)
    graphic_count = sum(1 for scene in document.pages for it in scene.shapes()
                        if isinstance(it, ShapeItem) and it.data_graphic_text())
    if base_shape_count + graphic_count > MAX_SHAPES:
        raise VsdxError("L'export des graphiques de données dépasserait la limite de formes VSDX.")
    fonts: dict[str, int] = {}
    images: list[tuple[str, bytes]] = []
    page_parts = []
    for scene in document.pages:
        xml, rels = _page_xml(scene, images, fonts)
        page_parts.append((xml, rels))

    ct = ET.Element(f"{{{CTNS}}}Types")
    for ext, mime in (("rels", "application/vnd.openxmlformats-package.relationships+xml"),
                      ("xml", "application/xml"), ("png", "image/png"), ("jpeg", "image/jpeg")):
        d = ET.SubElement(ct, f"{{{CTNS}}}Default")
        d.set("Extension", ext)
        d.set("ContentType", mime)
    overrides = [("/visio/document.xml", "application/vnd.ms-visio.drawing.main+xml"),
                 ("/visio/pages/pages.xml", "application/vnd.ms-visio.pages+xml"),
                 ("/visio/windows.xml", "application/vnd.ms-visio.windows+xml"),
                 ("/docProps/core.xml", "application/vnd.openxmlformats-package.core-properties+xml"),
                 ("/docProps/app.xml",
                  "application/vnd.openxmlformats-officedocument.extended-properties+xml")]
    overrides += [(f"/visio/pages/page{i + 1}.xml", "application/vnd.ms-visio.page+xml")
                  for i in range(len(page_parts))]
    for part, mime in overrides:
        o = ET.SubElement(ct, f"{{{CTNS}}}Override")
        o.set("PartName", part)
        o.set("ContentType", mime)

    vdoc = ET.Element(_v("VisioDocument"))
    vdoc.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    ds = _el(vdoc, "DocumentSettings", TopPage="0", DefaultTextStyle="0", DefaultLineStyle="0",
             DefaultFillStyle="0", DefaultGuideStyle="0")
    for tag, val in (("GlueSettings", "9"), ("SnapSettings", "65847"), ("SnapExtensions", "34"),
                     ("DynamicGridEnabled", "1"), ("ProtectStyles", "0"), ("ProtectShapes", "0"),
                     ("ProtectMasters", "0"), ("ProtectBkgnds", "0")):
        _el(ds, tag).text = val
    colors = _el(vdoc, "Colors")
    for i, c in enumerate(VISIO_COLORS):
        _el(colors, "ColorEntry", IX=str(i), RGB=c.upper())
    faces = _el(vdoc, "FaceNames")
    for name, fid in fonts.items():
        _el(faces, "FaceName", ID=str(fid), NameU=_xml_text(name), Name=_xml_text(name))
    sheets = _el(vdoc, "StyleSheets")
    ss = _el(sheets, "StyleSheet", ID="0", NameU="No Style", Name="Aucun style",
             LineStyle="0", FillStyle="0", TextStyle="0")
    for name, val in (("EnableLineProps", True), ("EnableFillProps", True),
                      ("EnableTextProps", True), ("HideForApply", False),
                      ("LineWeight", 0.75 / 72), ("LineColor", "#000000"), ("LinePattern", 1),
                      ("Rounding", 0.0), ("BeginArrow", 0), ("EndArrow", 0), ("LineCap", 0),
                      ("BeginArrowSize", 2), ("EndArrowSize", 2), ("LineColorTrans", 0.0),
                      ("FillForegnd", "#ffffff"), ("FillBkgnd", "#000000"), ("FillPattern", 1),
                      ("ShdwForegnd", "#000000"), ("ShdwPattern", 0), ("FillForegndTrans", 0.0),
                      ("LeftMargin", 4 / 72), ("RightMargin", 4 / 72), ("TopMargin", 4 / 72),
                      ("BottomMargin", 4 / 72), ("VerticalAlign", 1), ("TextBkgnd", 0)):
        _cell(ss, name, val)

    pages_el = ET.Element(_v("Pages"))
    page_list_rels = []
    page_ids = {scene.page_name: i for i, scene in enumerate(document.pages)}
    for i, scene in enumerate(document.pages):
        name = _xml_text(scene.page_name)
        p = _el(pages_el, "Page", ID=str(i), NameU=name, Name=name)
        if scene.is_background:
            p.set("Background", "1")
        back = scene.backpage_scene()
        if back is not None:
            p.set("BackPage", str(page_ids[back.page_name]))
        sheet = _el(p, "PageSheet", LineStyle="0", FillStyle="0", TextStyle="0")
        _cell(sheet, "PageWidth", scene.page_w / PX_PER_INCH)
        _cell(sheet, "PageHeight", scene.page_h / PX_PER_INCH)
        _cell(sheet, "ShdwOffsetX", 0.125)
        _cell(sheet, "ShdwOffsetY", -0.125)
        _cell(sheet, "PageScale", 1.0, "MM")
        _cell(sheet, "DrawingScale", 1.0, "MM")
        _cell(sheet, "DrawingSizeType", 0)
        _cell(sheet, "DrawingScaleType", 0)
        _cell(sheet, "PrintPageOrientation", 2 if scene.page_w > scene.page_h else 1)
        if getattr(scene, "layers", None):
            sec = _el(sheet, "Section", N="Layer")
            for li, lay in enumerate(scene.layers):
                row = _el(sec, "Row", IX=str(li))
                _cell(row, "Name", lay["name"], "STR")
                _cell(row, "NameUniv", lay["name"], "STR")
                _cell(row, "Visible", lay["visible"])
                _cell(row, "Print", lay["printable"])
                _cell(row, "Lock", lay["locked"])
                _cell(row, "Active", False)
                _cell(row, "Snap", True)
                _cell(row, "Glue", True)
        if getattr(scene, "ruler_guides", None):
            # Repères de LinXdiagram (en pouces, origine en haut à gauche) : relus par LinXdiagram.
            value = ";".join(f"{g['o']}:{g['pos'] / PX_PER_INCH:.4f}" for g in scene.ruler_guides)
            sec = _el(sheet, "Section", N="User")
            row = _el(sec, "Row", N="LinXGuides")
            _cell(row, "Value", value, "STR", _str_formula(value))
            _cell(row, "Prompt", "")
        rel = ET.SubElement(p, _v("Rel"))
        rel.set(f"{{{RNS}}}id", f"rId{i + 1}")
        page_list_rels.append((f"rId{i + 1}", REL_PAGE, f"page{i + 1}.xml"))

    windows = ET.Element(_v("Windows"))
    windows.set("ClientWidth", "1600")
    windows.set("ClientHeight", "900")
    win = _el(windows, "Window", ID="0", WindowType="Drawing", WindowState="1073741824",
              ContainerType="Page", Page="0", ViewScale="-1")
    for tag, val in (("ShowRulers", "1"), ("ShowGrid", "1"), ("ShowPageBreaks", "0"),
                     ("ShowGuides", "1"), ("ShowConnectionPoints", "1"), ("GlueSettings", "9"),
                     ("SnapSettings", "65847"), ("SnapExtensions", "34"),
                     ("DynamicGridEnabled", "1")):
        _el(win, tag).text = val

    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    props = document.properties
    core = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/'
        'core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:dcterms="http://purl.org/dc/terms/" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        f"<dc:title>{_esc(props.get('title', ''))}</dc:title>"
        f"<dc:subject>{_esc(props.get('subject', ''))}</dc:subject>"
        f"<dc:creator>{_esc(props.get('author', ''))}</dc:creator>"
        f'<dcterms:created xsi:type="dcterms:W3CDTF">{now}</dcterms:created>'
        f'<dcterms:modified xsi:type="dcterms:W3CDTF">{now}</dcterms:modified>'
        "</cp:coreProperties>").encode("utf-8")
    app = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/'
        'extended-properties" xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/'
        f'docPropsVTypes"><Application>{APP_NAME} {__version__}</Application>'
        "<AppVersion>16.0000</AppVersion></Properties>").encode("utf-8")

    def tostring(e):
        return _tostring(e, CTNS if e is ct else VNS)

    with security.atomic_target(path, private=True) as tmp:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("[Content_Types].xml", tostring(ct))
            z.writestr("_rels/.rels", _rels_xml([("rId1", REL_DOC, "visio/document.xml"),
                                                 ("rId2", REL_CORE, "docProps/core.xml"),
                                                 ("rId3", REL_APP, "docProps/app.xml")]))
            z.writestr("docProps/core.xml", core)
            z.writestr("docProps/app.xml", app)
            z.writestr("visio/document.xml", tostring(vdoc))
            z.writestr("visio/_rels/document.xml.rels",
                       _rels_xml([("rId1", REL_PAGES, "pages/pages.xml"),
                                  ("rId2", REL_WINDOWS, "windows.xml")]))
            z.writestr("visio/windows.xml", tostring(windows))
            z.writestr("visio/pages/pages.xml", tostring(pages_el))
            z.writestr("visio/pages/_rels/pages.xml.rels", _rels_xml(page_list_rels))
            for i, (xml, rels) in enumerate(page_parts):
                z.writestr(f"visio/pages/page{i + 1}.xml", xml)
                if rels:
                    z.writestr(f"visio/pages/_rels/page{i + 1}.xml.rels",
                               _rels_xml([(rid, REL_IMAGE, f"../media/{media}")
                                          for rid, media in rels]))
            for media, raw in images:
                z.writestr(f"visio/media/{media}", raw)


def _esc(s: str) -> str:
    return (_xml_text(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
