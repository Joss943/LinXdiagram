"""Format de fichier .lxd : JSON strictement validé, éventuellement chiffré.

Principes de sécurité :
* aucun mécanisme d'exécution (pas de macros, pas de pickle, pas d'eval) ;
* liste blanche des clés : tout champ inconnu est ignoré ;
* bornes sur les tailles, les nombres (finis) et les quantités d'objets ;
* images limitées aux formats PNG/JPEG, décodées plus tard avec plafond mémoire ;
* empreinte SHA-256 du contenu pour détecter une altération accidentelle.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import math
import ntpath
import os
import re
import unicodedata
from typing import Callable

from . import FILE_EXT, __version__, APP_NAME
from . import security, stencils
from .units import (ARROWS, DASHES, HALIGNS, MAX_COORD_PX, PAGE_SIZES, ROUTES, THEMES,
                    VALIGNS, DEFAULT_PAGE, DEFAULT_THEME, connector_style, connector_text_style,
                    mm_to_px, shape_style, text_style)

FORMAT = "linxdiagram"
CLIP_FORMAT = "linxdiagram-clip"
VERSION = 1

MAX_FILE_BYTES = 96 * 1024 * 1024
MAX_PAGES = 500
MAX_ITEMS_PER_PAGE = 50_000
MAX_ITEMS_TOTAL = 200_000
MAX_TEXT = 20_000
MAX_DATA_FIELDS = 100
MAX_DATA_LINKS_PER_SHAPE = 10
MAX_IMAGE_BYTES = 16 * 1024 * 1024
MAX_PATH_COMMANDS = 20_000
MAX_INDENT = 8

_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
_ARITY = {"M": 2, "L": 2, "Q": 4, "C": 6, "E": 4, "Z": 0}


class DocumentError(Exception):
    """Fichier illisible ou refusé ; le message est destiné à l'utilisateur."""


class PasswordRequired(DocumentError):
    pass


# ------------------------------------------------------------------- primitives

def _num(v, lo: float, hi: float, default: float) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return default
    v = float(v)
    if not math.isfinite(v):
        return default
    return min(max(v, lo), hi)


def _int(v, lo: int, hi: int, default: int) -> int:
    if isinstance(v, bool) or not isinstance(v, int):
        return default
    return min(max(v, lo), hi)


def _bool(v, default: bool) -> bool:
    return v if isinstance(v, bool) else default


def _choice(v, choices, default):
    return v if v in choices else default


def _color(v, default: str, allow_none: bool = True) -> str:
    if v == "" and allow_none:
        return ""
    if isinstance(v, str) and _COLOR_RE.match(v):
        return v.lower()
    return default


def _line(v, maxlen: int, default: str = "") -> str:
    return security.clean_line(v, maxlen) if isinstance(v, str) else default


def _text(v, maxlen: int = MAX_TEXT) -> str:
    return security.clean_text(v, maxlen) if isinstance(v, str) else ""


def _dict(v) -> dict:
    return v if isinstance(v, dict) else {}


# ------------------------------------------------------------------- styles

def clean_shape_style(raw, base: dict) -> dict:
    raw = _dict(raw)
    return {
        "fill": _color(raw.get("fill", base["fill"]), base["fill"]),
        "transparency": _num(raw.get("transparency"), 0, 100, base["transparency"]),
        "gradient": _bool(raw.get("gradient"), base["gradient"]),
        "line": _color(raw.get("line", base["line"]), base["line"]),
        "line_width": _num(raw.get("line_width"), 0.25, 50, base["line_width"]),
        "dash": _choice(raw.get("dash"), DASHES, base["dash"]),
        "rounding": _num(raw.get("rounding"), 0, 500, base["rounding"]),
        "shadow": _bool(raw.get("shadow"), base["shadow"]),
        "glow": _color(raw.get("glow", base.get("glow", "")), base.get("glow", "")),
        "glow_size": _num(raw.get("glow_size"), 1, 50, base.get("glow_size", 8.0)),
        "themed": _bool(raw.get("themed"), base["themed"]),
    }


def clean_text_style(raw, base: dict) -> dict:
    raw = _dict(raw)
    font = _line(raw.get("font"), 100) or base["font"]
    return {
        "font": font,
        "size": _num(raw.get("size"), 1, 400, base["size"]),
        "bold": _bool(raw.get("bold"), base["bold"]),
        "italic": _bool(raw.get("italic"), base["italic"]),
        "underline": _bool(raw.get("underline"), base["underline"]),
        "strike": _bool(raw.get("strike"), base.get("strike", False)),
        "color": _color(raw.get("color"), base["color"], allow_none=False),
        "halign": _choice(raw.get("halign"), HALIGNS, base["halign"]),
        "valign": _choice(raw.get("valign"), VALIGNS, base["valign"]),
        "bullets": _bool(raw.get("bullets"), base.get("bullets", False)),
        "indent": _int(raw.get("indent"), 0, MAX_INDENT, base.get("indent", 0)),
        "spacing": _num(raw.get("spacing"), 0.5, 3.0, base.get("spacing", 1.0)),
    }


def clean_connector_style(raw, base: dict) -> dict:
    raw = _dict(raw)
    return {
        "line": _color(raw.get("line"), base["line"], allow_none=False),
        "line_width": _num(raw.get("line_width"), 0.25, 50, base["line_width"]),
        "dash": _choice(raw.get("dash"), DASHES, base["dash"]),
        "arrow_start": _choice(raw.get("arrow_start"), ARROWS, base["arrow_start"]),
        "arrow_end": _choice(raw.get("arrow_end"), ARROWS, base["arrow_end"]),
        "route": _choice(raw.get("route"), ROUTES, base["route"]),
        "themed": _bool(raw.get("themed"), base["themed"]),
    }


def default_shape_styles(type_id: str, theme: str) -> tuple[dict, dict]:
    sdef = stencils.get(type_id)
    style = shape_style(theme)
    style.update(sdef.style)
    tstyle = text_style(theme, label=sdef.label_outside)
    tstyle.update(sdef.text)
    return style, tstyle


def clean_data(raw) -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in _dict(raw).items():
        if len(out) >= MAX_DATA_FIELDS:
            break
        key = _line(k, 100)
        if not key:
            continue
        if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v):
            v = repr(v)
        if isinstance(v, str):
            out[key] = security.clean_line(v, 2000)
    return out


MAX_COMMENTS = 200
MAX_LAYERS = 50


def clean_comments(raw) -> list[dict]:
    out = []
    if not isinstance(raw, list):
        return out
    for c in raw[:MAX_COMMENTS]:
        c = _dict(c)
        text = _text(c.get("text"), 5000).strip()
        if not text:
            continue
        out.append({"author": _line(c.get("author"), 100) or "Anonyme",
                    "date": _line(c.get("date"), 40), "text": text})
    return out


def clean_layers(raw) -> list[dict]:
    out, seen = [], set()
    if not isinstance(raw, list):
        return out
    for lay in raw[:MAX_LAYERS]:
        lay = _dict(lay)
        name = _line(lay.get("name"), 64)
        if not name or name in seen:
            continue
        seen.add(name)
        out.append({"name": name, "visible": _bool(lay.get("visible"), True),
                    "locked": _bool(lay.get("locked"), False),
                    "printable": _bool(lay.get("printable"), True)})
    return out


def clean_link(raw) -> str:
    """Lien externe sûr (http, https, mailto) ou lien interne vers une page."""
    if isinstance(raw, str) and raw.startswith("page:"):
        name = security.clean_line(raw[5:], 100)
        return f"page:{name}" if name else ""
    return security.safe_url(raw) or "" if isinstance(raw, str) else ""


def clean_data_link(raw) -> dict:
    """Métadonnées de liaison vers un fichier local, sans accès réseau automatique."""
    raw = _dict(raw)
    path = raw.get("path")
    if (not isinstance(path, str) or not path or len(path) > 2048 or "\x00" in path
            or not (os.path.isabs(path) or ntpath.isabs(path)) or path.startswith(("//", "\\\\"))):
        return {}
    source_key = _line(raw.get("source_key"), 100)
    shape_key = _line(raw.get("shape_key"), 100)
    if not source_key or not shape_key:
        return {}
    field_map: dict[str, str] = {}
    targets: set[str] = set()
    raw_map = raw.get("field_map")
    if isinstance(raw_map, dict):
        for index, (source, target) in enumerate(raw_map.items()):
            if index >= MAX_DATA_FIELDS:
                break
            source = _line(source, 100)
            target = _line(target, 100)
            if source and target and source not in field_map and target not in targets:
                field_map[source] = target
                targets.add(target)
    else:
        source_fields = raw.get("fields")
        if isinstance(source_fields, list):
            for field in source_fields[:MAX_DATA_FIELDS]:
                field = _line(field, 100)
                if field and field not in field_map:
                    field_map[field] = field
                    targets.add(field)
    if source_key not in field_map:
        if len(field_map) >= MAX_DATA_FIELDS:
            return {}
        target = source_key
        if target in targets:
            return {}
        field_map[source_key] = target
        targets.add(target)
    fields = list(field_map.values())
    return {"path": path, "source_key": source_key, "shape_key": shape_key,
            "fields": fields, "field_map": field_map}


def clean_data_links(raw, legacy=None) -> list[dict]:
    """Charge plusieurs sources locales et migre l'ancien lien unique si nécessaire."""
    candidates = raw[:MAX_DATA_LINKS_PER_SHAPE] if isinstance(raw, list) else []
    if isinstance(legacy, dict):
        candidates.append(legacy)
    out, seen, used_fields = [], set(), set()
    for candidate in candidates:
        link = clean_data_link(candidate)
        if not link:
            continue
        key = (os.path.normcase(link["path"]), link["source_key"], link["shape_key"])
        if key in seen:
            continue
        mapping = {}
        entries = sorted(link["field_map"].items(), key=lambda pair: pair[0] != link["source_key"])
        for source, target in entries:
            if target not in used_fields and len(used_fields) + len(mapping) < MAX_DATA_FIELDS:
                mapping[source] = target
        if link["source_key"] not in mapping:
            continue
        link["field_map"] = mapping
        link["fields"] = list(mapping.values())
        seen.add(key)
        used_fields.update(mapping.values())
        out.append(link)
        if len(out) >= MAX_DATA_LINKS_PER_SHAPE:
            break
    return out


def normalize_status_key(value: str) -> str:
    """Compare les libellés de statut sans tenir compte de la casse ou des accents."""
    normalized = unicodedata.normalize("NFKD", str(value)).casefold().strip()
    return "".join(char for char in normalized if not unicodedata.combining(char))


def clean_data_graphic(raw) -> dict:
    """Liaison d'une pastille visible à une propriété de forme."""
    raw = _dict(raw)
    field = _line(raw.get("field"), 100)
    display = raw.get("display", "label_value")
    if not field or not isinstance(display, str) or display not in {"label_value", "value", "status"}:
        return {}
    out = {"field": field, "display": display}
    if display == "status" and isinstance(raw.get("status_colors"), list):
        colors, seen = [], set()
        for rule in raw["status_colors"][:50]:
            rule = _dict(rule)
            value = _line(rule.get("value"), 200)
            key = normalize_status_key(value)
            color = _color(rule.get("color"), "", allow_none=False)
            if not key or key in seen or not color:
                continue
            seen.add(key)
            colors.append({"value": value, "color": color})
        if colors:
            out["status_colors"] = colors
    return out


def clean_image(raw) -> str:
    if not isinstance(raw, str) or not raw:
        return ""
    if len(raw) > MAX_IMAGE_BYTES * 4 // 3 + 8:
        raise DocumentError("Image intégrée trop volumineuse.")
    try:
        data = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise DocumentError("Image intégrée corrompue.") from exc
    if not (data.startswith(b"\x89PNG\r\n\x1a\n") or data.startswith(b"\xff\xd8\xff")):
        raise DocumentError("Format d'image intégrée non autorisé (PNG ou JPEG uniquement).")
    return raw


def clean_path(raw) -> list:
    if not isinstance(raw, list):
        return []
    if len(raw) > MAX_PATH_COMMANDS:
        raise DocumentError("Géométrie de forme trop complexe.")
    out = []
    for cmd in raw:
        if not isinstance(cmd, list) or not cmd or cmd[0] not in _ARITY:
            continue
        n = _ARITY[cmd[0]]
        if len(cmd) != n + 1:
            continue
        vals = [_num(v, -10, 10, float("nan")) for v in cmd[1:]]
        if any(math.isnan(v) for v in vals):
            continue
        out.append([cmd[0]] + vals)
    return out


# ------------------------------------------------------------------- objets

def clean_shape(raw, theme: str) -> dict | None:
    raw = _dict(raw)
    sid = raw.get("id")
    if not isinstance(sid, str) or not _ID_RE.match(sid):
        return None
    type_id = raw.get("type")
    if not isinstance(type_id, str) or type_id not in stencils.SHAPES:
        type_id = stencils.FALLBACK_TYPE
    style_base, text_base = default_shape_styles(type_id, theme)
    shape = {
        "id": sid,
        "type": type_id,
        "x": _num(raw.get("x"), -MAX_COORD_PX, MAX_COORD_PX, 0.0),
        "y": _num(raw.get("y"), -MAX_COORD_PX, MAX_COORD_PX, 0.0),
        "w": _num(raw.get("w"), 1.0, MAX_COORD_PX, 100.0),
        "h": _num(raw.get("h"), 1.0, MAX_COORD_PX, 60.0),
        "rotation": _num(raw.get("rotation"), -360, 360, 0.0),
        "flip_h": _bool(raw.get("flip_h"), False),
        "flip_v": _bool(raw.get("flip_v"), False),
        "z": _num(raw.get("z"), -1e9, 1e9, 0.0),
        "text": _text(raw.get("text")),
        "style": clean_shape_style(raw.get("style"), style_base),
        "text_style": clean_text_style(raw.get("text_style"), text_base),
        "data": clean_data(raw.get("data")),
        "link": clean_link(raw.get("link", "")),
        "group": _line(raw.get("group"), 64) if _ID_RE.match(str(raw.get("group", ""))) else "",
        "locked": _bool(raw.get("locked"), False),
        "tip": _line(raw.get("tip"), 500),
        "comments": clean_comments(raw.get("comments")),
        "layer": _line(raw.get("layer"), 64),
    }
    data_links = clean_data_links(raw.get("data_links"), raw.get("data_link"))
    if data_links:
        shape["data_links"] = data_links
    data_graphic = clean_data_graphic(raw.get("data_graphic"))
    if data_graphic:
        shape["data_graphic"] = data_graphic
    if stencils.get(type_id).cff and isinstance(raw.get("cff"), dict):
        opts = {k: _bool(raw["cff"].get(k), d) for k, d in (("title", True), ("hidden", False),
                                                            ("rotate", False)) if k in raw["cff"]}
        if opts:
            shape["cff"] = opts
    if type_id == "special.image":
        shape["image"] = clean_image(raw.get("image"))
    if type_id == "special.custom":
        shape["path"] = clean_path(raw.get("path"))
    tr = raw.get("text_rect")
    if isinstance(tr, list) and len(tr) == 4:
        vals = [_num(v, -10, 10, float("nan")) for v in tr]
        if not any(math.isnan(v) for v in vals) and vals[2] > 0.01 and vals[3] > 0.01:
            shape["text_rect"] = vals
    return shape


def _clean_end(raw) -> dict:
    raw = _dict(raw)
    shape = raw.get("shape", "")
    if not isinstance(shape, str) or (shape and not _ID_RE.match(shape)):
        shape = ""
    return {
        "shape": shape,
        "port": _int(raw.get("port"), -1, 1000, -1),
        "x": _num(raw.get("x"), -MAX_COORD_PX, MAX_COORD_PX, 0.0),
        "y": _num(raw.get("y"), -MAX_COORD_PX, MAX_COORD_PX, 0.0),
    }


def clean_connector(raw, theme: str, route: str) -> dict | None:
    raw = _dict(raw)
    cid = raw.get("id")
    if not isinstance(cid, str) or not _ID_RE.match(cid):
        return None
    return {
        "id": cid,
        "kind": "connector",
        "src": _clean_end(raw.get("src")),
        "dst": _clean_end(raw.get("dst")),
        "z": _num(raw.get("z"), -1e9, 1e9, 0.0),
        "text": _text(raw.get("text"), 2000),
        "style": clean_connector_style(raw.get("style"), connector_style(theme, route)),
        "text_style": clean_text_style(raw.get("text_style"), connector_text_style(theme)),
        "data": clean_data(raw.get("data")),
        "layer": _line(raw.get("layer"), 64),
    }


def clean_items(shapes_raw, connectors_raw, theme: str, route: str,
                warnings: list[str], counter: list[int]) -> tuple[list[dict], list[dict]]:
    if not isinstance(shapes_raw, list) or not isinstance(connectors_raw, list):
        raise DocumentError("Structure de page invalide.")
    if len(shapes_raw) + len(connectors_raw) > MAX_ITEMS_PER_PAGE:
        raise DocumentError("Trop d'objets sur une page.")
    counter[0] += len(shapes_raw) + len(connectors_raw)
    if counter[0] > MAX_ITEMS_TOTAL:
        raise DocumentError("Trop d'objets dans le document.")
    seen: set[str] = set()
    shapes = []
    for raw in shapes_raw:
        s = clean_shape(raw, theme)
        if s is None or s["id"] in seen:
            warnings.append("Une forme invalide a été ignorée.")
            continue
        if isinstance(raw, dict) and raw.get("type") not in stencils.SHAPES:
            warnings.append(f"Type de forme inconnu « {_line(raw.get('type'), 40)} » remplacé "
                            "par un rectangle.")
        seen.add(s["id"])
        shapes.append(s)
    shape_ids = {s["id"] for s in shapes}
    connectors = []
    for raw in connectors_raw:
        c = clean_connector(raw, theme, route)
        if c is None or c["id"] in seen:
            warnings.append("Un connecteur invalide a été ignoré.")
            continue
        for end in (c["src"], c["dst"]):
            if end["shape"] and end["shape"] not in shape_ids:
                end["shape"] = ""
                end["port"] = -1
        seen.add(c["id"])
        connectors.append(c)
    return shapes, connectors


def clean_settings(raw) -> dict:
    raw = _dict(raw)
    return {
        "grid": _bool(raw.get("grid"), True),
        "snap": _bool(raw.get("snap"), True),
        "guides": _bool(raw.get("guides"), True),
        "ports": _bool(raw.get("ports"), True),
        "rulers": _bool(raw.get("rulers"), True),
        "route": _choice(raw.get("route"), ROUTES, "orthogonal"),
        "theme": _choice(raw.get("theme"), tuple(THEMES), DEFAULT_THEME),
        "line_jumps": _bool(raw.get("line_jumps"), True),
        "variant": _choice(raw.get("variant"), ("standard", "outline", "light", "dark"), "standard"),
    }


def clean_properties(raw) -> dict:
    raw = _dict(raw)
    return {k: _line(raw.get(k), 300) for k in ("title", "subject", "author", "company", "keywords")}


MAX_GUIDES = 200


def clean_guides(raw) -> list[dict]:
    """Repères de la page : {"o": "h" ou "v", "pos": coordonnée en px}."""
    out = []
    for g in raw if isinstance(raw, list) else []:
        g = _dict(g)
        if g.get("o") not in ("h", "v"):
            continue
        pos = _num(g.get("pos"), -MAX_COORD_PX, MAX_COORD_PX, float("nan"))
        if math.isnan(pos):
            continue
        out.append({"o": g["o"], "pos": pos})
        if len(out) >= MAX_GUIDES:
            break
    return out


def default_page(name: str = "Page-1") -> dict:
    w, h = PAGE_SIZES[DEFAULT_PAGE]
    return {"name": name, "width": mm_to_px(w), "height": mm_to_px(h), "background": "#ffffff",
            "auto_size": False, "layers": [], "guides": [], "is_background": False,
            "backpage": "", "shapes": [], "connectors": []}


# ------------------------------------------------------------------- document

def pages_digest(pages) -> str:
    canon = json.dumps(pages, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def validate_document(raw) -> tuple[dict, list[str]]:
    if not isinstance(raw, dict) or raw.get("format") != FORMAT:
        raise DocumentError("Ce fichier n'est pas un document LinXdiagram.")
    version = raw.get("version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise DocumentError("Version de document invalide.")
    if version > VERSION:
        raise DocumentError("Ce document a été créé par une version plus récente de "
                            f"{APP_NAME}. Mettez l'application à jour.")
    warnings: list[str] = []
    integrity = _dict(raw.get("integrity")).get("sha256")
    pages_raw = raw.get("pages")
    if not isinstance(pages_raw, list) or not pages_raw:
        raise DocumentError("Le document ne contient aucune page.")
    if len(pages_raw) > MAX_PAGES:
        raise DocumentError("Le document contient trop de pages.")
    if isinstance(integrity, str) and integrity != pages_digest(pages_raw):
        warnings.append("L'empreinte d'intégrité ne correspond pas : le fichier a été modifié "
                        "en dehors de LinXdiagram ou est endommagé.")
    settings = clean_settings(raw.get("settings"))
    counter = [0]
    pages = []
    for i, praw in enumerate(pages_raw):
        praw = _dict(praw)
        shapes, connectors = clean_items(praw.get("shapes", []), praw.get("connectors", []),
                                         settings["theme"], settings["route"], warnings, counter)
        pages.append({
            "name": _line(praw.get("name"), 100) or f"Page-{i + 1}",
            "width": _num(praw.get("width"), 50, 50_000, mm_to_px(210)),
            "height": _num(praw.get("height"), 50, 50_000, mm_to_px(297)),
            "background": _color(praw.get("background"), "#ffffff", allow_none=False),
            "auto_size": _bool(praw.get("auto_size"), False),
            "layers": clean_layers(praw.get("layers")),
            "guides": clean_guides(praw.get("guides")),
            "is_background": _bool(praw.get("is_background"), False),
            "backpage": _line(praw.get("backpage"), 100),
            "shapes": shapes,
            "connectors": connectors,
        })
    doc = {"format": FORMAT, "version": VERSION, "settings": settings,
           "properties": clean_properties(raw.get("properties")), "pages": pages}
    return doc, _dedupe(warnings)


def _dedupe(items: list[str]) -> list[str]:
    seen = []
    for w in items:
        if w not in seen:
            seen.append(w)
    return seen


def _reject_constant(name: str):
    raise DocumentError(f"Valeur numérique interdite ({name}).")


def _no_duplicate_keys(pairs):
    out = {}
    for k, v in pairs:
        if k in out:
            raise DocumentError("Clé JSON dupliquée : fichier ambigu, refusé.")
        out[k] = v
    return out


def parse_json(data: bytes):
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DocumentError("Le fichier n'est pas encodé en UTF-8.") from exc
    try:
        return json.loads(text, parse_constant=_reject_constant,
                          object_pairs_hook=_no_duplicate_keys)
    except DocumentError:
        raise
    except RecursionError as exc:
        raise DocumentError("Structure JSON trop imbriquée.") from exc
    except ValueError as exc:
        raise DocumentError(f"Fichier JSON invalide : {exc}") from exc


def load_bytes(data: bytes, ask_password: Callable[[], str | None] | None = None
               ) -> tuple[dict, list[str], str | None]:
    """Décode un fichier .lxd. Retourne (document, avertissements, mot de passe)."""
    raw = parse_json(data)
    password = None
    if security.is_encrypted_envelope(raw):
        if ask_password is None:
            raise PasswordRequired("Ce document est protégé par mot de passe.")
        while True:
            password = ask_password()
            if password is None:
                raise PasswordRequired("Ouverture annulée.")
            try:
                plain = security.decrypt_payload(raw, password)
                break
            except security.WrongPasswordError:
                continue
        raw = parse_json(plain)
    doc, warnings = validate_document(raw)
    return doc, warnings, password


def load_file(path: str, ask_password=None) -> tuple[dict, list[str], str | None]:
    try:
        data = security.read_file_limited(path, MAX_FILE_BYTES)
    except security.SecurityError as exc:
        raise DocumentError(str(exc)) from exc
    return load_bytes(data, ask_password)


def dump_bytes(doc: dict, password: str | None = None) -> bytes:
    out = {"format": FORMAT, "version": VERSION, "generator": f"{APP_NAME} {__version__}",
           "settings": doc["settings"], "properties": doc.get("properties", {}),
           "pages": doc["pages"], "integrity": {"sha256": pages_digest(doc["pages"])}}
    data = json.dumps(out, ensure_ascii=False, indent=1, allow_nan=False).encode("utf-8")
    if password:
        return security.encrypt_payload(data, password)
    return data


def save_file(path: str, doc: dict, password: str | None = None) -> None:
    security.atomic_write(path, dump_bytes(doc, password), private=True)


def ensure_extension(path: str) -> str:
    return path if path.lower().endswith(FILE_EXT) else path + FILE_EXT


# ------------------------------------------------------------------- presse-papiers

def dump_clip(shapes: list[dict], connectors: list[dict]) -> bytes:
    return json.dumps({"format": CLIP_FORMAT, "version": VERSION, "shapes": shapes,
                       "connectors": connectors}, ensure_ascii=False).encode("utf-8")


def load_clip(data: bytes, theme: str, route: str) -> tuple[list[dict], list[dict]]:
    if len(data) > MAX_FILE_BYTES:
        raise DocumentError("Contenu du presse-papiers trop volumineux.")
    raw = parse_json(data)
    if not isinstance(raw, dict) or raw.get("format") != CLIP_FORMAT:
        raise DocumentError("Contenu du presse-papiers non reconnu.")
    return clean_items(raw.get("shapes", []), raw.get("connectors", []), theme, route, [], [0])

