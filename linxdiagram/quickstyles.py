"""Styles rapides et variantes (onglets Accueil > Styles de forme, Création > Variantes)."""

from __future__ import annotations

from PyQt6.QtGui import QColor

from .units import THEMES

ACCENTS = ("#5b9bd5", "#ed7d31", "#a5a5a5", "#ffc000", "#4472c4", "#70ad47", "#44546a")
ACCENT_NAMES = ("Accent 1", "Accent 2", "Accent 3", "Accent 4", "Accent 5", "Accent 6", "Foncé")
ROWS = ("Contour coloré", "Effet discret", "Effet modéré", "Effet intense", "Remplissage foncé")
VARIANTS = (("standard", "Standard"), ("outline", "Contour"), ("light", "Clair"), ("dark", "Foncé"))


def tint(color: str, amount: float) -> str:
    """Éclaircit (amount > 0) ou assombrit (amount < 0) à la manière d'Office."""
    c = QColor(color)
    h, s, l, _ = c.getHslF()
    if amount >= 0:
        l = l + (1 - l) * amount
    else:
        l = l * (1 + amount)
    return QColor.fromHslF(max(h, 0.0), s, min(max(l, 0.0), 1.0)).name()


def quick_style(row: int, color: str) -> tuple[dict, str]:
    """Retourne (changements de style, couleur du texte) pour une vignette de la galerie."""
    if row == 0:
        return ({"fill": "#ffffff", "line": color, "line_width": 1.33, "gradient": False, "shadow": False,
                 "glow": "", "transparency": 0.0}, tint(color, -0.5))
    if row == 1:
        return ({"fill": tint(color, 0.8), "line": color, "line_width": 1.0, "gradient": False,
                 "shadow": False, "glow": "", "transparency": 0.0}, "#262626")
    if row == 2:
        return ({"fill": color, "line": tint(color, -0.25), "line_width": 1.0, "gradient": False,
                 "shadow": False, "glow": "", "transparency": 0.0}, "#ffffff")
    if row == 3:
        return ({"fill": color, "line": tint(color, -0.25), "line_width": 1.0, "gradient": True,
                 "shadow": True, "glow": "", "transparency": 0.0}, "#ffffff")
    return ({"fill": tint(color, -0.5), "line": "", "line_width": 1.0, "gradient": False,
             "shadow": False, "glow": "", "transparency": 0.0}, "#ffffff")


def gallery_items():
    """(ligne, couleur, info-bulle) dans l'ordre d'affichage de la galerie."""
    out = []
    for r, row_name in enumerate(ROWS):
        for color, name in zip(ACCENTS, ACCENT_NAMES):
            out.append((r, color, f"{row_name} — {name}"))
    return out


def theme_colors(theme: str, variant: str) -> dict:
    """Couleurs d'un thème décliné selon une variante."""
    t = dict(THEMES.get(theme, THEMES["office"]))
    if variant == "outline":
        t.update(fill="#ffffff", line=t["fill"], text=tint(t["fill"], -0.45))
    elif variant == "light":
        t.update(fill=tint(t["fill"], 0.75), line=t["fill"], text=tint(t["fill"], -0.55))
    elif variant == "dark":
        t.update(fill=tint(t["fill"], -0.35), line=tint(t["fill"], -0.55), text="#ffffff")
    return t
