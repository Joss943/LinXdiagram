"""Gabarit « Favoris » (Mes formes), comme dans Visio : des formes ou des sélections
enregistrées par l'utilisateur et réutilisables par glisser-déposer.

Chaque favori est stocké au format du presse-papiers interne, déjà strictement validé
au collage (fileformat.load_clip) : un fichier de favoris modifié à la main ne peut rien
injecter d'autre que des formes valides.
"""

from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass

from . import fileformat, security

CATEGORY = "Favoris"
PREFIX = "fav:"
MAX_ITEMS = 200
MAX_CLIP = 2_000_000


@dataclass
class FavoriteDef:
    """Entrée du volet Formes (mêmes attributs utiles qu'une ShapeDef)."""
    type_id: str
    name: str
    pixmap: object = None
    category: str = CATEGORY
    cff: str = ""


class Favorites:
    def __init__(self, path: str | None):
        self.path = path
        self.items: list[tuple[str, bytes]] = []
        self._thumbs: dict[int, object] = {}
        self._load()

    def _load(self) -> None:
        if not self.path or not os.path.isfile(self.path):
            return
        try:
            raw = fileformat.parse_json(security.read_file_limited(self.path, 50_000_000))
        except (OSError, ValueError, fileformat.DocumentError):
            return
        for entry in (raw.get("items", []) if isinstance(raw, dict) else [])[:MAX_ITEMS]:
            if not isinstance(entry, dict):
                continue
            name = security.clean_line(str(entry.get("name", "")), 100) or "Forme"
            try:
                clip = base64.b64decode(str(entry.get("clip", "")), validate=True)
                if len(clip) > MAX_CLIP:
                    continue
                shapes, _conns = fileformat.load_clip(clip, "office", "orthogonal")
            except (ValueError, fileformat.DocumentError):
                continue
            if shapes:
                self.items.append((name, clip))

    def save(self) -> None:
        if not self.path:
            return
        data = {"version": 1, "items": [{"name": n, "clip": base64.b64encode(c).decode("ascii")}
                                        for n, c in self.items]}
        security.atomic_write(self.path, json.dumps(data, ensure_ascii=False).encode("utf-8"), private=True)

    def add(self, name: str, clip: bytes) -> bool:
        if len(self.items) >= MAX_ITEMS or len(clip) > MAX_CLIP:
            return False
        self.items.append((security.clean_line(name, 100) or "Forme", clip))
        self._thumbs.clear()
        self.save()
        return True

    def remove(self, index: int) -> None:
        if 0 <= index < len(self.items):
            del self.items[index]
            self._thumbs.clear()
            self.save()

    def rename(self, index: int, name: str) -> None:
        name = security.clean_line(name, 100)
        if 0 <= index < len(self.items) and name:
            self.items[index] = (name, self.items[index][1])
            self.save()

    @staticmethod
    def index_of(type_id: str) -> int | None:
        if type_id.startswith(PREFIX):
            try:
                return int(type_id[len(PREFIX):])
            except ValueError:
                return None
        return None

    def defs(self) -> list[FavoriteDef]:
        return [FavoriteDef(f"{PREFIX}{i}", name, self.thumbnail(i)) for i, (name, _c) in enumerate(self.items)]

    def thumbnail(self, index: int, size: int = 32):
        if index in self._thumbs:
            return self._thumbs[index]
        from PyQt6.QtCore import QRectF, Qt
        from PyQt6.QtGui import QPainter, QPixmap
        from .document import Document
        from .export import exporting
        shapes, conns = fileformat.load_clip(self.items[index][1], "office", "orthogonal")
        page = fileformat.default_page("Favori")
        page["shapes"], page["connectors"] = shapes, conns
        doc = Document({"format": fileformat.FORMAT, "version": fileformat.VERSION, "settings": {},
                        "properties": {}, "pages": [page]})
        sc = doc.pages[0]
        pm = QPixmap(size * 2, size * 2)
        pm.setDevicePixelRatio(2.0)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        with exporting(sc, transparent=True):
            sc.render(p, QRectF(1, 1, size - 2, size - 2), sc.drawing_rect(), Qt.AspectRatioMode.KeepAspectRatio)
        p.end()
        self._thumbs[index] = pm
        return pm

    def center_of(self, index: int):
        """Centre du favori dans ses coordonnées d'origine (pour le déposer sous la souris)."""
        from PyQt6.QtCore import QPointF, QRectF
        shapes, _c = fileformat.load_clip(self.items[index][1], "office", "orthogonal")
        r = None
        for st in shapes:
            b = QRectF(st["x"] - st["w"] / 2, st["y"] - st["h"] / 2, st["w"], st["h"])
            r = b if r is None else r.united(b)
        return r.center() if r is not None else QPointF()
