"""Sélecteur de couleurs façon Office (couleurs du thème, couleurs standard, autres couleurs)."""

from __future__ import annotations

from PyQt6.QtCore import QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import (QColorDialog, QGridLayout, QHBoxLayout, QLabel, QMenu, QToolButton,
                             QVBoxLayout, QWidget, QWidgetAction)

from . import icons

OFFICE_BASE = ["#ffffff", "#000000", "#e7e6e6", "#44546a", "#5b9bd5", "#ed7d31", "#a5a5a5",
               "#ffc000", "#4472c4", "#70ad47"]
STANDARD = ["#c00000", "#ff0000", "#ffc000", "#ffff00", "#92d050", "#00b050", "#00b0f0",
            "#0070c0", "#002060", "#7030a0"]


def _variants(hex_color: str) -> list[str]:
    c = QColor(hex_color)
    h, s, l, _ = c.getHslF()
    if l > 0.95:
        levels = [0.95, 0.85, 0.75, 0.65, 0.5]
    elif l < 0.05:
        levels = [0.5, 0.35, 0.25, 0.15, 0.05]
    else:
        levels = [l + (1 - l) * 0.8, l + (1 - l) * 0.6, l + (1 - l) * 0.4, l * 0.75, l * 0.5]
    out = []
    for lv in levels:
        v = QColor.fromHslF(max(h, 0.0), s, min(max(lv, 0.0), 1.0))
        out.append(v.name())
    return out


class _Palette(QWidget):
    picked = pyqtSignal(str)

    def __init__(self, allow_none: bool, none_label: str):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)
        lay.addWidget(self._title("Couleurs du thème"))
        grid = QGridLayout()
        grid.setSpacing(2)
        for col, base in enumerate(OFFICE_BASE):
            grid.addWidget(self._swatch(base), 0, col)
            for row, v in enumerate(_variants(base), start=1):
                grid.addWidget(self._swatch(v), row, col)
        lay.addLayout(grid)
        lay.addWidget(self._title("Couleurs standard"))
        row = QHBoxLayout()
        row.setSpacing(2)
        for c in STANDARD:
            row.addWidget(self._swatch(c))
        lay.addLayout(row)
        if allow_none:
            b = QToolButton()
            b.setText(none_label)
            b.setAutoRaise(True)
            b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
            b.clicked.connect(lambda: self.picked.emit(""))
            lay.addWidget(b)
        more = QToolButton()
        more.setText("Autres couleurs…")
        more.setAutoRaise(True)
        more.clicked.connect(self._more)
        lay.addWidget(more)

    @staticmethod
    def _title(text: str) -> QLabel:
        lab = QLabel(text)
        lab.setStyleSheet("font-weight: 600;")
        return lab

    def _swatch(self, color: str) -> QToolButton:
        b = QToolButton()
        b.setFixedSize(18, 16)
        b.setToolTip(color)
        b.setStyleSheet(f"QToolButton {{ background: {color}; border: 1px solid #b0b0b0; }}"
                        "QToolButton:hover { border: 2px solid #f59e0b; }")
        b.clicked.connect(lambda _=False, c=color: self.picked.emit(c))
        return b

    def _more(self) -> None:
        c = QColorDialog.getColor(QColor("#5b9bd5"), self, "Choisir une couleur")
        if c.isValid():
            self.picked.emit(c.name())


class ColorButton(QToolButton):
    """Bouton « couleur » façon Office : clic = dernière couleur, flèche = palette."""

    colorPicked = pyqtSignal(str)

    def __init__(self, icon_name: str, text: str, initial: str = "#5b9bd5", allow_none: bool = True,
                 none_label: str = "Aucun", parent: QWidget | None = None, swatch: bool = False):
        super().__init__(parent)
        self.swatch = swatch
        self.icon_name = icon_name
        self.current = initial
        self.setText(text)
        self.setToolTip(text)
        self.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        menu = QMenu(self)
        self._palette_args = (allow_none, none_label)
        self._palette_built = False
        menu.aboutToShow.connect(self._ensure_palette)
        self.setMenu(menu)
        self.clicked.connect(lambda: self.colorPicked.emit(self.current))
        self._refresh()

    def _ensure_palette(self) -> None:
        """La palette (70 pastilles) n'est construite qu'à la première ouverture."""
        if self._palette_built:
            return
        self._palette_built = True
        menu = self.menu()
        palette = _Palette(*self._palette_args)
        act = QWidgetAction(menu)
        act.setDefaultWidget(palette)
        first = menu.actions()[0] if menu.actions() else None
        if first is not None:
            menu.insertAction(first, act)
        else:
            menu.addAction(act)
        palette.picked.connect(self._picked)
        palette.picked.connect(lambda _c: menu.close())

    def _picked(self, color: str) -> None:
        self.current = color
        self._refresh()
        self.colorPicked.emit(color)

    def _refresh(self) -> None:
        if self.swatch:
            pm = QPixmap(140, 28)
            pm.setDevicePixelRatio(2.0)
            pm.fill(Qt.GlobalColor.transparent)
            p = QPainter(pm)
            if self.current:
                p.fillRect(QRectF(0, 0, 70, 14), QColor(self.current))
                p.setPen(QColor("#8a8886"))
                p.drawRect(QRectF(0.5, 0.5, 69, 13))
            else:
                p.setPen(QColor("#8a8886"))
                p.drawRect(QRectF(0.5, 0.5, 69, 13))
                p.drawLine(1, 13, 69, 1)
            p.end()
            self.setIcon(QIcon(pm))
            self.setIconSize(QSize(70, 14))
            self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
            return
        base = icons.icon(self.icon_name)
        ic = QIcon()
        for size in (16, 24, 32):
            pm = QPixmap(size * 2, size * 2)
            pm.setDevicePixelRatio(2.0)
            pm.fill(Qt.GlobalColor.transparent)
            p = QPainter(pm)
            p.drawPixmap(0, 0, base.pixmap(size, round(size * 0.78)))
            if self.current:
                p.fillRect(QRectF(size * 0.08, size * 0.8, size * 0.84, size * 0.18), QColor(self.current))
            else:
                p.setPen(QColor("#9ca3af"))
                p.drawRect(QRectF(size * 0.08, size * 0.8, size * 0.84, size * 0.16))
            p.end()
            ic.addPixmap(pm)
        self.setIcon(ic)
