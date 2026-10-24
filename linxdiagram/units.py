"""Unités, tailles de page, thèmes et styles par défaut.

Les coordonnées internes sont en pixels logiques à 96 ppp (1 po = 96 px),
comme l'unité interne de Visio est le pouce : la conversion vers VSDX est
donc une simple division par 96.
"""

from __future__ import annotations

PX_PER_INCH = 96.0
PX_PER_MM = PX_PER_INCH / 25.4

GRID_MM = 5.0
GRID_PX = GRID_MM * PX_PER_MM

MIN_SIZE_PX = 4.0
MAX_COORD_PX = 1_000_000.0


def mm_to_px(v: float) -> float:
    return v * PX_PER_MM


def px_to_mm(v: float) -> float:
    return v / PX_PER_MM


# Formats de page (largeur, hauteur) en mm, orientation portrait.
PAGE_SIZES: dict[str, tuple[float, float]] = {
    "A4": (210.0, 297.0),
    "A3": (297.0, 420.0),
    "A5": (148.0, 210.0),
    "Lettre US": (215.9, 279.4),
    "Légal US": (215.9, 355.6),
    "Tabloïd": (279.4, 431.8),
}
DEFAULT_PAGE = "A4"

# Thèmes de couleurs (onglet Création > Thèmes), à la manière des thèmes Visio.
THEMES: dict[str, dict[str, str]] = {
    "office": {"name": "Classique", "fill": "#5b9bd5", "line": "#41719c", "text": "#ffffff",
               "label": "#1f1f1f", "connector": "#41719c"},
    "simple": {"name": "Simple", "fill": "#ffffff", "line": "#000000", "text": "#000000",
               "label": "#000000", "connector": "#000000"},
    "pastel": {"name": "Pastel", "fill": "#deebf7", "line": "#5b9bd5", "text": "#1f3864",
               "label": "#1f3864", "connector": "#5b9bd5"},
    "ardoise": {"name": "Ardoise", "fill": "#44546a", "line": "#333f50", "text": "#ffffff",
                "label": "#222a35", "connector": "#44546a"},
    "verdure": {"name": "Verdure", "fill": "#70ad47", "line": "#507e32", "text": "#ffffff",
                "label": "#1f1f1f", "connector": "#507e32"},
    "ambre": {"name": "Ambre", "fill": "#ed7d31", "line": "#ae5a21", "text": "#ffffff",
              "label": "#1f1f1f", "connector": "#ae5a21"},
    "lavande": {"name": "Lavande", "fill": "#8e7cc3", "line": "#674ea7", "text": "#ffffff",
                "label": "#1f1f1f", "connector": "#674ea7"},
}
DEFAULT_THEME = "office"

DASHES = ("solid", "dash", "dot", "dashdot")
DASH_LABELS = {"solid": "Continu", "dash": "Tirets", "dot": "Pointillés", "dashdot": "Tiret-point"}
ARROWS = ("none", "triangle", "open", "diamond", "circle")
ARROW_LABELS = {"none": "Aucune", "triangle": "Flèche pleine", "open": "Flèche ouverte",
                "diamond": "Losange", "circle": "Cercle"}
ROUTES = ("orthogonal", "straight", "curved")
ROUTE_LABELS = {"orthogonal": "Angle droit", "straight": "Droit", "curved": "Courbe"}
HALIGNS = ("left", "center", "right", "justify")
VALIGNS = ("top", "middle", "bottom")

_default_font = "Sans Serif"


def default_font() -> str:
    return _default_font


def set_default_font(family: str) -> None:
    global _default_font
    _default_font = family


def shape_style(theme: str = DEFAULT_THEME) -> dict:
    t = THEMES.get(theme, THEMES[DEFAULT_THEME])
    return {"fill": t["fill"], "transparency": 0.0, "gradient": False, "line": t["line"],
            "line_width": 1.0, "dash": "solid", "rounding": 0.0, "shadow": False, "glow": "",
            "glow_size": 8.0, "themed": True}


def text_style(theme: str = DEFAULT_THEME, label: bool = False) -> dict:
    t = THEMES.get(theme, THEMES[DEFAULT_THEME])
    return {"font": default_font(), "size": 11.0, "bold": False, "italic": False,
            "underline": False, "strike": False, "color": t["label"] if label else t["text"],
            "halign": "center", "valign": "top" if label else "middle"}


def connector_style(theme: str = DEFAULT_THEME, route: str = "orthogonal") -> dict:
    t = THEMES.get(theme, THEMES[DEFAULT_THEME])
    return {"line": t["connector"], "line_width": 1.0, "dash": "solid", "arrow_start": "none",
            "arrow_end": "triangle", "route": route, "themed": True}


def connector_text_style(theme: str = DEFAULT_THEME) -> dict:
    s = text_style(theme, label=True)
    s["size"] = 10.0
    s["valign"] = "middle"
    return s
