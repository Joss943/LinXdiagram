"""Charte graphique calquée sur Visio (thème Office « En couleur »).

Barre de titre et onglets du ruban dans la couleur de Visio, ruban gris clair,
volets blancs, contrôles plats aux bordures fines, comme dans Microsoft 365.
"""

from __future__ import annotations

import os

from PyQt6.QtGui import QColor, QFont, QPalette
from PyQt6.QtWidgets import QApplication

from . import security

FONT_UI = "Inter"

# Microsoft 365 / Office 2024 : accents plus vifs, surfaces claires et hiérarchie nette
# entre barre de titre, onglets, ruban et espace de dessin.
LIGHT = {
    "accent": "#0078d4", "accent_hover": "#106ebe", "accent_pressed": "#005a9e",
    "accent_text": "#ffffff", "accent_soft": "#deecf9", "accent_line": "#0078d4",
    "titlebar": "#31549a", "tabbar": "#fafbfc", "tab_text": "#ffffff", "tab_ink": "#242424",
    "ribbon": "#ffffff", "ribbon_border": "#e0e0e0", "separator": "#e0e0e0",
    "window": "#f4f6f8", "surface": "#ffffff", "surface2": "#f7f9fb",
    "text": "#242424", "text2": "#616161", "text3": "#a8a8a8",
    "hover": "#f1f4f7", "pressed": "#e5ebf2", "checked": "#deecf9",
    "input_border": "#c8d0d9", "input_bottom": "#616161", "border": "#dfe4ea", "canvas": "#e7e9ec",
    "selection": "#d8ebfa", "tooltip": "#ffffff", "close_hover": "#c42b1c",
}

DARK = {
    "accent": "#75b8f0", "accent_hover": "#3d3d3d", "accent_pressed": "#4a4a4a",
    "accent_text": "#ffffff", "accent_soft": "#293b4e", "accent_line": "#75b8f0",
    "titlebar": "#1f1f1f", "tabbar": "#1f1f1f", "tab_text": "#f5f5f5", "tab_ink": "#f5f5f5",
    "ribbon": "#2b2b2b", "ribbon_border": "#3d3d3d", "separator": "#474747",
    "window": "#1f1f1f", "surface": "#292929", "surface2": "#2e2e2e",
    "text": "#f5f5f5", "text2": "#c7c7c7", "text3": "#8a8a8a",
    "hover": "#383838", "pressed": "#454545", "checked": "#2f3a57",
    "input_border": "#4d4d4d", "input_bottom": "#a8a8a8", "border": "#3d3d3d", "canvas": "#141414",
    "selection": "#2f3a57", "tooltip": "#2b2b2b", "close_hover": "#c42b1c",
}

T: dict[str, str] = dict(LIGHT)
_dark = False


def is_dark() -> bool:
    return _dark


def _asset_dir() -> str:
    base = os.environ.get("XDG_RUNTIME_DIR")
    if not base or not os.path.isdir(base):
        base = os.path.join(os.path.expanduser("~"), ".cache")
    return security.private_dir(os.path.join(base, "linxdiagram-ui"))


def _write_assets(t: dict) -> dict[str, str]:
    """Petites images vectorielles pour les feuilles de style (flèches, coches)."""
    d = _asset_dir()
    ink = t["text2"]
    files = {
        "down": f'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><path d="M2 3.5 5 6.5 8 3.5" '
                f'fill="none" stroke="{ink}" stroke-width="1.2"/></svg>',
        "down_light": '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><path d="M2 3.5 5 6.5 8 3.5" '
                      'fill="none" stroke="#ffffff" stroke-width="1.2"/></svg>',
        "up": f'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><path d="M2 6.5 5 3.5 8 6.5" '
              f'fill="none" stroke="{ink}" stroke-width="1.2"/></svg>',
        "right": f'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><path d="M3.5 2 6.5 5 3.5 8" '
                 f'fill="none" stroke="{ink}" stroke-width="1.2"/></svg>',
        "check": f'<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12"><path d="M2.5 6.5 5 9 9.5 3.5" '
                 f'fill="none" stroke="#ffffff" stroke-width="1.6"/></svg>',
        "radio": '<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12">'
                 f'<circle cx="6" cy="6" r="3" fill="{t["accent"]}"/></svg>',
    }
    out = {}
    for name, svg in files.items():
        path = os.path.join(d, f"{name}{'-dark' if t is DARK or _dark else ''}.svg")
        security.atomic_write(path, svg.encode("ascii"), private=True)
        out[name] = path
    return out


def apply(app: QApplication, dark: bool) -> None:
    global _dark
    _dark = dark
    T.clear()
    T.update(DARK if dark else LIGHT)
    app.setStyle("Fusion")
    font = QFont(FONT_UI)
    font.setPixelSize(12)
    font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    app.setFont(font)
    pal = QPalette()
    R = QPalette.ColorRole
    for role, key in ((R.Window, "window"), (R.WindowText, "text"), (R.Base, "surface"),
                      (R.AlternateBase, "surface2"), (R.Text, "text"), (R.Button, "surface"),
                      (R.ButtonText, "text"), (R.Mid, "border"), (R.Midlight, "hover"),
                      (R.Highlight, "accent"), (R.ToolTipBase, "tooltip"), (R.ToolTipText, "text"),
                      (R.PlaceholderText, "text3"), (R.Light, "surface"), (R.Dark, "separator")):
        pal.setColor(role, QColor(T[key]))
    pal.setColor(R.HighlightedText, QColor("#ffffff"))
    for role in (R.WindowText, R.Text, R.ButtonText):
        pal.setColor(QPalette.ColorGroup.Disabled, role, QColor(T["text3"]))
    app.setPalette(pal)
    a = _write_assets(T)
    t = T
    app.setStyleSheet(f"""
    /* Taille fixe comme dans Visio (9 pt) : sans cette règle, Qt reprend la taille du bureau
       (11 pt sous GNOME) pour tout widget stylé, et libellés et boutons débordent. */
    * {{ font-family: "{FONT_UI}"; font-size: 12px; }}
    QToolTip {{ background: {t['tooltip']}; color: {t['text']}; border: 1px solid {t['border']};
               padding: 6px 8px; }}

    /* ---------- barre de titre et onglets ---------- */
    #TitleBar {{ background: {t['titlebar']}; }}
    #TitleBar QLabel#Title {{ color: {t['tab_text']}; font-size: 12px; }}
    #TitleBar QToolButton {{ background: transparent; border: none; border-radius: 0; padding: 4px; }}
    #TitleBar QToolButton:hover {{ background: {t['accent_hover']}; }}
    #TitleBar QToolButton:pressed {{ background: {t['accent_pressed']}; }}
    #TitleBar QToolButton#WinClose:hover {{ background: {t['close_hover']}; }}
    #TitleBar QToolButton::menu-button {{ border: none; background: transparent; width: 12px; }}
    #TitleBar QToolButton::menu-button:hover {{ background: {t['accent_hover']}; }}
    #TitleBar QToolButton::menu-arrow {{ image: url({a['down_light']}); width: 8px; height: 8px; }}
    #TitleBar QLineEdit#CommandSearch {{ background: rgba(255,255,255,0.18); border: 1px solid transparent;
        border-radius: 4px; color: {t['tab_text']}; padding: 3px 8px; min-height: 18px; }}
    #TitleBar QLineEdit#CommandSearch:focus {{ background: {t['surface']}; color: {t['text']};
        border: 1px solid {t['accent']}; }}
    #RibbonTabBar {{ background: {t['tabbar']}; }}
    QPushButton#RibbonTab {{ color: {t['tab_ink']}; background: transparent; border: none;
        border-bottom: 3px solid transparent; border-radius: 0; padding: 6px 10px 3px 10px; font-size: 12px;
        margin: 2px 1px 0 1px; }}
    QPushButton#RibbonTab:hover {{ background: {t['pressed'] if not dark else t['hover']};
        border-top-left-radius: 4px; border-top-right-radius: 4px; }}
    QPushButton#RibbonTab:checked {{ color: {t['accent_line']}; border-bottom: 3px solid {t['accent_line']}; }}
    QPushButton#FileTab {{ color: {t['tab_ink']}; background: transparent; border: none; border-radius: 4px;
        padding: 6px 12px 6px 12px; font-size: 12px; margin: 2px 1px 0 6px; }}
    QPushButton#FileTab:hover {{ background: {t['pressed'] if not dark else t['hover']}; }}
    #TabBarTools QToolButton {{ background: transparent; border: none; border-radius: 4px; color: {t['tab_ink']};
        padding: 3px 6px; }}
    #TabBarTools QToolButton:hover {{ background: {t['pressed'] if not dark else t['hover']}; }}

    /* ---------- ruban : carte blanche arrondie ---------- */
    #RibbonBody {{ background: {t['window']}; }}
    #RibbonCard {{ background: {t['ribbon']}; border: 1px solid {t['ribbon_border']}; border-radius: 8px; }}
    QMenu#RibbonGroupPopup {{ background: {t['ribbon']}; border-radius: 6px; padding: 4px; }}
    QLabel#RibbonGroupLabel {{ color: {t['text2']}; font-size: 11px; }}
    QFrame#RibbonSep {{ background: {t['separator']}; max-width: 1px; min-width: 1px; }}
    QToolButton#RibbonLauncher {{ border: none; background: transparent; padding: 0; border-radius: 3px; }}
    QToolButton#RibbonLauncher:hover {{ background: {t['pressed']}; }}
    QToolButton#RibbonCollapse {{ border: none; background: transparent; border-radius: 4px; }}
    QToolButton#RibbonCollapse:hover {{ background: {t['pressed']}; }}
    #RibbonBody QComboBox {{ min-height: 20px; max-height: 22px; }}
    #RibbonBody QCheckBox {{ spacing: 6px; padding: 2px 4px; }}

    /* ---------- contrôles de saisie ---------- */
    QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{ background: {t['surface']}; color: {t['text']};
        border: 1px solid {t['input_border']}; border-bottom-color: {t['input_bottom']}; border-radius: 4px;
        padding: 2px 6px; min-height: 18px; selection-background-color: {t['accent']}; }}
    QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover, QComboBox:hover {{ border-color: {t['text3']};
        border-bottom-color: {t['text']}; }}
    QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
        border-bottom: 2px solid {t['accent']}; }}
    QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled {{
        color: {t['text3']}; border-color: {t['border']}; }}
    QComboBox::drop-down {{ border: none; width: 18px; }}
    QComboBox::down-arrow {{ image: url({a['down']}); width: 10px; height: 10px; }}
    QComboBox QAbstractItemView {{ background: {t['surface']}; border: 1px solid {t['border']};
        selection-background-color: {t['hover']}; selection-color: {t['text']}; outline: 0; }}
    QSpinBox::up-button, QDoubleSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::down-button {{
        border: none; width: 14px; background: transparent; }}
    QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{ image: url({a['up']}); width: 8px; height: 8px; }}
    QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{ image: url({a['down']}); width: 8px; height: 8px; }}
    QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover, QSpinBox::down-button:hover,
    QDoubleSpinBox::down-button:hover {{ background: {t['hover']}; }}
    QPushButton {{ background: {t['surface']}; color: {t['text']}; border: 1px solid {t['input_border']};
        border-radius: 4px; padding: 4px 14px; min-height: 18px; }}
    QPushButton:hover {{ background: {t['hover']}; }}
    QPushButton:pressed {{ background: {t['pressed']}; }}
    QPushButton:default {{ background: {t['accent']}; color: #ffffff; border-color: {t['accent']}; }}
    QPushButton:default:hover {{ background: {t['accent_hover'] if not dark else t['accent']}; }}
    QCheckBox, QRadioButton {{ color: {t['text']}; spacing: 7px; }}
    QCheckBox::indicator {{ width: 14px; height: 14px; border: 1px solid {t['text2']};
        border-radius: 3px; background: {t['surface']}; }}
    QCheckBox::indicator:hover {{ border-color: {t['text']}; }}
    QCheckBox::indicator:checked {{ background: {t['accent']}; border-color: {t['accent']};
        image: url({a['check']}); }}
    QRadioButton::indicator {{ width: 14px; height: 14px; border: 1px solid {t['text2']};
        border-radius: 7px; background: {t['surface']}; }}
    QRadioButton::indicator:checked {{ border-color: {t['accent']}; image: url({a['radio']}); }}
    QSlider::groove:horizontal {{ height: 2px; background: {t['separator']}; border-radius: 1px; }}
    QSlider::sub-page:horizontal {{ background: {t['text2']}; border-radius: 1px; }}
    QSlider::handle:horizontal {{ background: {t['text2']}; width: 8px; height: 14px; margin: -6px 0;
        border-radius: 2px; }}
    QSlider::handle:horizontal:hover {{ background: {t['text']}; }}

    /* ---------- menus ---------- */
    QMenu {{ background: {t['surface']}; color: {t['text']}; border: 1px solid {t['border']}; padding: 4px; }}
    QMenu::item {{ padding: 6px 28px 6px 12px; background: transparent; border-radius: 4px; }}
    QMenu::item:selected {{ background: {t['hover']}; }}
    QMenu::item:disabled {{ color: {t['text3']}; }}
    QMenu::separator {{ height: 1px; background: {t['border']}; margin: 4px 0; }}
    QMenu::icon {{ padding-left: 8px; }}
    QMenu::right-arrow {{ image: url({a['right']}); width: 10px; height: 10px; }}

    /* ---------- barres de défilement fines ---------- */
    QScrollBar:vertical {{ background: transparent; width: 12px; margin: 0; }}
    QScrollBar:horizontal {{ background: transparent; height: 12px; margin: 0; }}
    QScrollBar::handle:vertical {{ background: {t['separator']}; border-radius: 3px; min-height: 28px; margin: 2px 3px; }}
    QScrollBar::handle:horizontal {{ background: {t['separator']}; border-radius: 3px; min-width: 28px; margin: 3px 2px; }}
    QScrollBar::handle:hover {{ background: {t['text2']}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
    QAbstractScrollArea::corner {{ background: transparent; }}

    /* ---------- volets de tâches ---------- */
    #TaskPane, #TaskPane QScrollArea, #TaskPaneBody {{ background: {t['surface']}; }}
    QLabel#PaneTitle {{ color: {t['text']}; font-size: 16px; padding: 2px 0; }}
    QToolButton#PaneClose, QToolButton#PaneMenu {{ border: none; background: transparent; padding: 2px; }}
    QToolButton#PaneClose:hover, QToolButton#PaneMenu:hover {{ background: {t['hover']}; }}
    QToolButton#SectionHeader {{ border: none; background: transparent; color: {t['text']};
        font-weight: 600; text-align: left; padding: 6px 0; }}
    QToolButton#PaneTabIcon {{ border: none; border-bottom: 2px solid transparent; background: transparent;
        padding: 4px 8px; }}
    QToolButton#PaneTabIcon:hover {{ background: {t['hover']}; }}
    QToolButton#PaneTabIcon:checked {{ border-bottom: 2px solid {t['accent_line']}; }}
    QPushButton#StencilTab {{ border: none; background: transparent; color: {t['text2']}; padding: 4px 6px;
        font-size: 11px; font-weight: 600; letter-spacing: 0.5px; }}
    QPushButton#StencilTab:checked {{ color: {t['accent_line']}; border-bottom: 2px solid {t['accent_line']}; }}
    QPushButton#StencilRow {{ border: none; background: transparent; color: {t['text']}; text-align: left;
        padding: 5px 8px; border-radius: 4px; margin: 0 4px; }}
    QPushButton#StencilRow:hover {{ background: {t['hover']}; }}
    QPushButton#StencilRow:checked {{ background: {t['selection']}; font-weight: 600; }}
    QLabel#Hint {{ color: {t['text2']}; font-size: 11px; }}
    QListView#ShapeList {{ background: {t['surface']}; border: none; outline: 0; }}
    QTableWidget {{ background: {t['surface']}; gridline-color: {t['border']}; border: 1px solid {t['border']}; }}
    QHeaderView::section {{ background: {t['surface2']}; border: none; border-bottom: 1px solid {t['border']};
        padding: 4px; color: {t['text2']}; }}
    QSplitter::handle {{ background: {t['border']}; }}
    QSplitter::handle:horizontal {{ width: 1px; }}
    QSplitter::handle:vertical {{ height: 1px; }}

    /* ---------- pages et barre d'état ---------- */
    #PageBar {{ background: {t['window']}; border-top: 1px solid {t['border']}; }}
    #PageBar QToolButton {{ border: none; background: transparent; padding: 3px; }}
    #PageBar QToolButton:hover {{ background: {t['hover']}; }}
    QTabBar#PageTabs::tab {{ background: transparent; color: {t['text']}; border: none;
        border-right: 1px solid {t['border']}; padding: 4px 14px; min-width: 40px; }}
    QTabBar#PageTabs::tab:hover {{ background: {t['hover']}; }}
    QTabBar#PageTabs::tab:selected {{ background: {t['surface']}; color: {t['accent_line']};
        font-weight: 600; border-bottom: 2px solid {t['accent_line']}; }}
    QStatusBar {{ background: {t['window']}; color: {t['text2']}; border-top: 1px solid {t['border']}; }}
    QStatusBar QLabel {{ color: {t['text2']}; padding: 0 8px; }}
    QStatusBar QToolButton {{ border: none; background: transparent; padding: 2px; }}
    QStatusBar QToolButton:hover {{ background: {t['hover']}; }}
    QStatusBar::item {{ border: none; }}

    /* ---------- Backstage ---------- */
    #Backstage {{ background: {t['surface']}; }}
    #BackstageNav {{ background: {t['accent'] if not dark else '#1b1a19'}; }}
    #BackstageNav QPushButton {{ color: #ffffff; background: transparent; border: none; text-align: left;
        padding: 9px 24px; font-size: 13px; border-radius: 0; }}
    #BackstageNav QPushButton:hover {{ background: rgba(255,255,255,0.14); }}
    #BackstageNav QPushButton:checked {{ background: rgba(0,0,0,0.22); }}
    #BackstageNav QToolButton {{ border: none; background: transparent; border-radius: 16px; }}
    #BackstageNav QToolButton:hover {{ background: rgba(255,255,255,0.14); }}
    #BackstagePage {{ background: {t['surface']}; }}
    QLabel#BackstageTitle {{ font-size: 28px; font-weight: 300; color: {t['text']}; }}
    QLabel#BackstageSection {{ font-size: 15px; color: {t['text']}; }}
    QToolButton#TemplateTile {{ border: 1px solid transparent; background: transparent; border-radius: 2px; }}
    QToolButton#TemplateTile:hover {{ background: {t['hover']}; border-color: {t['border']}; }}
    QTreeWidget#RecentList {{ border: none; background: {t['surface']}; }}
    QTreeWidget#RecentList::item {{ padding: 6px 2px; }}
    QTreeWidget#RecentList::item:hover {{ background: {t['hover']}; }}
    QTreeWidget#RecentList::item:selected {{ background: {t['selection']}; color: {t['text']}; }}

    /* ---------- fenêtre sans cadre ---------- */
    #WindowFrame {{ background: {t['window']}; }}
    """)
