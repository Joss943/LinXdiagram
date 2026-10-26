"""Champs de texte (Insertion > Champ), comme dans Visio.

Un champ s'écrit ``{{Nom}}`` dans le texte d'une forme ; il est remplacé à l'affichage, à
l'impression et à l'export par sa valeur courante. Le texte brut reste visible pendant
l'édition. Les noms inconnus sont laissés tels quels : aucun code n'est évalué.
"""

from __future__ import annotations

import os
import re
import time

FIELD_RE = re.compile(r"\{\{([^{}\n]{1,120})\}\}")
DATA_PREFIX = "Donnée:"

# (nom du champ, description affichée dans la boîte de dialogue)
FIELDS: tuple[tuple[str, str], ...] = (
    ("Page", "Numéro de la page"),
    ("Pages", "Nombre de pages"),
    ("Nom de la page", "Nom de la page"),
    ("Date", "Date du jour"),
    ("Heure", "Heure actuelle"),
    ("Titre", "Titre du document"),
    ("Sujet", "Sujet du document"),
    ("Auteur", "Auteur du document"),
    ("Société", "Société"),
    ("Mots clés", "Mots clés du document"),
    ("Nom du fichier", "Nom du fichier"),
)


def has_fields(text: str) -> bool:
    return "{{" in text and FIELD_RE.search(text) is not None


def _value(name: str, scene, shape) -> str | None:
    doc = getattr(scene, "doc", None) if scene is not None else None
    if name.startswith(DATA_PREFIX):
        key = name[len(DATA_PREFIX):].strip()
        data = getattr(shape, "data", None) or {}
        return data.get(key, "")
    if name == "Date":
        return time.strftime("%d/%m/%Y")
    if name == "Heure":
        return time.strftime("%H:%M")
    pages = getattr(doc, "pages", None) if doc is not None else None
    if doc is None or pages is None:
        return None
    if name == "Page":
        foreground = [p for p in pages if p.page_kind == "foreground"]
        if scene in foreground:
            return str(foreground.index(scene) + 1)
        return str(pages.index(scene) + 1) if scene in pages else "1"
    if name == "Pages":
        return str(sum(1 for p in pages if p.page_kind == "foreground") or len(pages))
    if name == "Nom de la page":
        return scene.page_name
    if name == "Nom du fichier":
        return os.path.basename(doc.path) if doc.path else "Dessin"
    props = {"Titre": "title", "Sujet": "subject", "Auteur": "author", "Société": "company",
             "Mots clés": "keywords"}
    if name in props:
        return doc.properties.get(props[name], "")
    return None


def expand(text: str, scene, shape=None) -> str:
    """Remplace les champs connus par leur valeur."""
    if not has_fields(text):
        return text

    def sub(m: re.Match) -> str:
        value = _value(m.group(1).strip(), scene, shape)
        return m.group(0) if value is None else value
    return FIELD_RE.sub(sub, text)


def token(name: str) -> str:
    return "{{" + name + "}}"
