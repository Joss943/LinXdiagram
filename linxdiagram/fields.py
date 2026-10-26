"""Champs de texte (Insertion > Champ, comme dans Visio) : date, heure, numéro de page,
nombre de pages, nom de la page, nom du fichier, titre et auteur du document.

Un champ s'écrit ``{{nom}}`` dans le texte d'une forme. Il est remplacé par sa valeur à
l'affichage, à l'impression et à l'export ; en mode édition, le code du champ est visible.
"""

from __future__ import annotations

import datetime
import os
import re

FIELDS = {
    "date": "Date",
    "date_longue": "Date (format long)",
    "heure": "Heure",
    "page": "Numéro de page",
    "pages": "Nombre de pages",
    "nom_page": "Nom de la page",
    "fichier": "Nom du fichier",
    "titre": "Titre du document",
    "auteur": "Auteur du document",
}
_RE = re.compile(r"\{\{([a-z_]+)\}\}")
_DAYS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
_MONTHS = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre",
           "octobre", "novembre", "décembre")


def token(name: str) -> str:
    return "{{" + name + "}}"


def has_fields(text: str) -> bool:
    return "{{" in text and _RE.search(text) is not None


def values(scene, now: datetime.datetime | None = None) -> dict[str, str]:
    now = now or datetime.datetime.now()
    doc = getattr(scene, "doc", None)
    pages = [p for p in getattr(doc, "pages", []) if not getattr(p, "is_background", False)]
    number = str(pages.index(scene) + 1) if scene in pages else ""
    path = getattr(doc, "path", None)
    props = getattr(doc, "properties", {}) or {}
    return {
        "date": now.strftime("%d/%m/%Y"),
        "date_longue": f"{_DAYS[now.weekday()]} {now.day} {_MONTHS[now.month - 1]} {now.year}",
        "heure": now.strftime("%H:%M"),
        "page": number,
        "pages": str(len(pages)),
        "nom_page": getattr(scene, "page_name", ""),
        "fichier": os.path.basename(path) if path else "Sans titre",
        "titre": props.get("title", ""),
        "auteur": props.get("author", ""),
    }


def resolve(text: str, scene, now: datetime.datetime | None = None) -> str:
    if not has_fields(text) or scene is None:
        return text
    vals = values(scene, now)
    return _RE.sub(lambda m: vals.get(m.group(1), m.group(0)), text)
