"""Volets de tâches à la manière de Visio : Formes, Format de la forme, Taille et
position, Données de forme, Commentaires, Problèmes, Panoramique et zoom."""

from __future__ import annotations

import os

from PyQt6.QtCore import QMimeData, QRect, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QIcon, QPainter
from PyQt6.QtWidgets import (QSizePolicy, QAbstractItemView, QButtonGroup, QCheckBox, QComboBox, QDoubleSpinBox,
                             QFontComboBox, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel,
                             QLineEdit, QListView, QListWidget, QListWidgetItem, QMenu,
                             QPlainTextEdit, QPushButton, QRadioButton, QScrollArea, QSlider,
                             QSpinBox, QSplitter, QStackedWidget, QStyle, QStyledItemDelegate,
                             QTableWidget, QTableWidgetItem, QToolButton, QTreeWidget,
                             QTreeWidgetItem, QVBoxLayout, QWidget)

from . import icons, security, stencils
from .canvas import STENCIL_MIME, OverviewView
from .commands import PageCommand
from .items import ConnectorItem, ShapeItem
from .style import T
from .units import (ARROW_LABELS, ARROWS, DASH_LABELS, DASHES, PAGE_SIZES, PX_PER_MM,
                    ROUTE_LABELS, ROUTES)
from .widgets import ColorButton

PT_PER_PX = 72.0 / 96.0


# =========================================================================== cadre de volet

class TaskPane(QWidget):
    """Volet avec titre et bouton de fermeture, comme les fenêtres de Visio."""

    closed = pyqtSignal()

    def __init__(self, title: str, body: QWidget):
        super().__init__()
        self.setObjectName("TaskPane")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        head = QHBoxLayout()
        head.setContentsMargins(12, 8, 6, 4)
        self.title = QLabel(title)
        self.title.setObjectName("PaneTitle")
        head.addWidget(self.title)
        head.addStretch(1)
        close = QToolButton()
        close.setObjectName("PaneClose")
        close.setIcon(icons.icon("win_close"))
        close.setIconSize(QSize(14, 14))
        close.setToolTip("Fermer")
        close.clicked.connect(self._close)
        head.addWidget(close)
        lay.addLayout(head)
        lay.addWidget(body, 1)
        self.body = body

    def _close(self) -> None:
        self.hide()
        self.closed.emit()


# =========================================================================== Formes

def _wrap_two_lines(text: str, fm, width: int) -> list[str]:
    """Nom de forme sur deux lignes au plus, avec « … » si un mot ne tient pas (jamais coupé net)."""
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if fm.horizontalAdvance(trial) <= width or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    if len(lines) > 2:
        lines = [lines[0], " ".join(lines[1:])]
    return [fm.elidedText(line, Qt.TextElideMode.ElideRight, width) for line in lines]


class _ShapeDelegate(QStyledItemDelegate):
    def paint(self, p: QPainter, option, index) -> None:
        r = option.rect.adjusted(1, 1, -1, -1)
        state = option.state
        if state & QStyle.StateFlag.State_Selected:
            p.fillRect(r, QColor(T["selection"]))
        elif state & QStyle.StateFlag.State_MouseOver:
            p.fillRect(r, QColor(T["hover"]))
        ic: QIcon = index.data(Qt.ItemDataRole.DecorationRole)
        if ic is not None:
            pm = ic.pixmap(QSize(32, 32), option.widget.devicePixelRatioF() if option.widget else 1.0)
            p.drawPixmap(r.left() + 4, r.top() + (r.height() - 32) // 2, pm)
        p.setPen(QColor(T["text"]))
        p.setFont(option.font)
        tr = QRect(r.left() + 42, r.top() + 1, r.width() - 44, r.height() - 2)
        text = index.data(Qt.ItemDataRole.DisplayRole) or ""
        fm = p.fontMetrics()
        lines = _wrap_two_lines(text, fm, tr.width())
        y = tr.top() + (tr.height() - len(lines) * fm.height()) // 2
        for line in lines:
            p.drawText(QRect(tr.left(), y, tr.width(), fm.height()), Qt.AlignmentFlag.AlignVCenter, line)
            y += fm.height()

    def sizeHint(self, option, index) -> QSize:  # noqa: N802
        return QSize(120, 40)


class ShapeList(QListWidget):
    activated_type = pyqtSignal(str)
    selected_type = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.setObjectName("ShapeList")
        self.setViewMode(QListView.ViewMode.ListMode)
        self.setFlow(QListView.Flow.LeftToRight)
        self.setWrapping(True)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setUniformItemSizes(True)
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setMouseTracking(True)
        self.viewport().setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setItemDelegate(_ShapeDelegate(self))
        self.itemDoubleClicked.connect(lambda it: self.activated_type.emit(it.data(Qt.ItemDataRole.UserRole)))
        self.currentItemChanged.connect(
            lambda it, _p: self.selected_type.emit(it.data(Qt.ItemDataRole.UserRole)) if it else None)

    def set_shapes(self, defs) -> None:
        self.clear()
        for d in defs:
            it = QListWidgetItem(QIcon(icons.stencil_pixmap(d, 32)), d.name)
            it.setData(Qt.ItemDataRole.UserRole, d.type_id)
            it.setToolTip(f"<b>{d.name}</b><br>Faites glisser la forme sur la page.")
            self.addItem(it)
        self._update_grid()

    def _update_grid(self) -> None:
        # On réserve toujours la place de la barre de défilement : sinon son apparition
        # ferait passer la liste de deux colonnes à une seule.
        avail = self.width() - self.verticalScrollBar().sizeHint().width() - 2 * self.frameWidth() - 4
        w = max(96, avail // 2)
        if self.gridSize().width() != w:
            self.setGridSize(QSize(w, 42))

    def resizeEvent(self, e):  # noqa: N802
        super().resizeEvent(e)
        self._update_grid()

    def mimeTypes(self):  # noqa: N802
        return [STENCIL_MIME]

    def mimeData(self, items):  # noqa: N802
        md = QMimeData()
        items = list(items)
        if items:
            md.setData(STENCIL_MIME, items[0].data(Qt.ItemDataRole.UserRole).encode("ascii"))
        return md


QUICK = "Formes rapides"


class ShapesPane(QWidget):
    shapeActivated = pyqtSignal(str)
    quickShapeChanged = pyqtSignal(str)
    categoriesChanged = pyqtSignal()
    closed = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setObjectName("TaskPane")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMinimumWidth(230)
        self.open_cats: list[str] = [stencils.BASIC, stencils.FLOW, stencils.ARROWS_CAT]
        self.current = stencils.BASIC
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        head = QHBoxLayout()
        head.setContentsMargins(12, 8, 6, 2)
        title = QLabel("Formes")
        title.setObjectName("PaneTitle")
        head.addWidget(title)
        head.addStretch(1)
        close = QToolButton()
        close.setObjectName("PaneClose")
        close.setIcon(icons.icon("win_close"))
        close.setIconSize(QSize(14, 14))
        close.setToolTip("Fermer le volet Formes")
        close.clicked.connect(self.closed.emit)
        head.addWidget(close)
        lay.addLayout(head)
        tabs = QHBoxLayout()
        tabs.setContentsMargins(10, 0, 10, 4)
        tabs.setSpacing(10)
        self.tab_group = QButtonGroup(self)
        for i, text in enumerate(("FORMES", "RECHERCHER")):
            b = QPushButton(text)
            b.setObjectName("StencilTab")
            b.setCheckable(True)
            b.setChecked(i == 0)
            self.tab_group.addButton(b, i)
            tabs.addWidget(b)
        tabs.addStretch(1)
        lay.addLayout(tabs)
        self.stack = QStackedWidget()
        lay.addWidget(self.stack, 1)
        self.tab_group.idClicked.connect(self._tab)

        page = QWidget()
        pl = QVBoxLayout(page)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(0)
        self.more = QPushButton("Plus de formes      ›")
        self.more.setObjectName("StencilRow")
        self.more.clicked.connect(self._more_menu)
        pl.addWidget(self.more)
        self.rows_box = QWidget()
        self.rows = QVBoxLayout(self.rows_box)
        self.rows.setContentsMargins(0, 0, 0, 0)
        self.rows.setSpacing(0)
        pl.addWidget(self.rows_box)
        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background: {T['border']};")
        pl.addWidget(sep)
        self.list = ShapeList()
        self._wire(self.list)
        pl.addWidget(self.list, 1)
        self.stack.addWidget(page)

        search = QWidget()
        sl = QVBoxLayout(search)
        sl.setContentsMargins(10, 4, 10, 4)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Rechercher des formes")
        self.search.setClearButtonEnabled(True)
        self.search.addAction(icons.icon("search"), QLineEdit.ActionPosition.TrailingPosition)
        self.search.textChanged.connect(self._search)
        sl.addWidget(self.search)
        self.search_hint = QLabel("Tapez un mot-clé : processus, serveur, flèche…")
        self.search_hint.setObjectName("Hint")
        self.search_hint.setWordWrap(True)
        sl.addWidget(self.search_hint)
        self.results = ShapeList()
        self._wire(self.results)
        sl.addWidget(self.results, 1)
        self.stack.addWidget(search)
        self._row_group = QButtonGroup(self)
        self._row_group.setExclusive(True)
        self._rebuild_rows()

    def _wire(self, lst: ShapeList) -> None:
        lst.activated_type.connect(self.shapeActivated)
        lst.selected_type.connect(self.quickShapeChanged)

    def _tab(self, i: int) -> None:
        self.stack.setCurrentIndex(i)
        if i == 1:
            self.search.setFocus()

    def _rebuild_rows(self) -> None:
        while self.rows.count():
            w = self.rows.takeAt(0).widget()
            if w is not None:
                self._row_group.removeButton(w)
                w.hide()
                w.setParent(None)
                w.deleteLater()
        self.categoriesChanged.emit()
        for cat in [QUICK] + self.open_cats:
            b = QPushButton(cat)
            b.setObjectName("StencilRow")
            b.setCheckable(True)
            b.setChecked(cat == self.current)
            b.clicked.connect(lambda _=False, c=cat: self.show_category(c))
            self._row_group.addButton(b)
            self.rows.addWidget(b)
        self.show_category(self.current if (self.current in self.open_cats or self.current == QUICK)
                           else self.open_cats[0])

    def show_category(self, cat: str) -> None:
        self.current = cat
        for b in self._row_group.buttons():
            b.setChecked(b.text() == cat)
        if cat == QUICK:
            defs = [d for c in self.open_cats for d in stencils.by_category(c)[:4]]
        else:
            defs = stencils.by_category(cat)
        self.list.set_shapes(defs)

    def open_category(self, cat: str, select: bool = True) -> None:
        if cat in stencils.CATEGORIES and cat not in self.open_cats:
            self.open_cats.insert(0, cat)
        if select:
            self.current = cat
        self._rebuild_rows()
        self.tab_group.button(0).setChecked(True)
        self.stack.setCurrentIndex(0)

    def set_open(self, cats: list[str], select: str | None = None) -> None:
        self.open_cats = [c for c in cats if c in stencils.CATEGORIES] or [stencils.BASIC]
        self.current = select or self.open_cats[0]
        self._rebuild_rows()

    def _more_menu(self) -> None:
        menu = QMenu(self)
        for cat in stencils.CATEGORIES:
            a = menu.addAction(icons.icon("shapes_panel"), cat)
            a.setCheckable(True)
            a.setChecked(cat in self.open_cats)
            a.triggered.connect(lambda on, c=cat: self._toggle_cat(c, on))
        menu.addSeparator()
        menu.addAction(icons.icon("search"), "Rechercher des formes…", self.focus_search)
        menu.exec(self.more.mapToGlobal(self.more.rect().topRight()))

    def _toggle_cat(self, cat: str, on: bool) -> None:
        if on:
            self.open_category(cat)
        elif cat in self.open_cats and len(self.open_cats) > 1:
            self.open_cats.remove(cat)
            if self.current == cat:
                self.current = self.open_cats[0]
            self._rebuild_rows()

    def _search(self, text: str) -> None:
        found = stencils.search(text)
        self.results.set_shapes(found)
        if not text.strip():
            self.search_hint.setText("Tapez un mot-clé : processus, serveur, flèche…")
        else:
            self.search_hint.setText(f"{len(found)} résultat(s)" if found else "Aucune forme trouvée.")

    def focus_search(self) -> None:
        self.tab_group.button(1).setChecked(True)
        self._tab(1)
        self.search.selectAll()

    def quick_shapes(self) -> list:
        cat = self.current if self.current in self.open_cats else self.open_cats[0]
        shapes = [d for d in stencils.by_category(cat) if not d.cff][:4]
        return shapes or stencils.by_category(stencils.FLOW)[:4]


# =========================================================================== éléments de formulaire

class Section(QWidget):
    def __init__(self, title: str, expanded: bool = True):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.title = title
        self.header = QToolButton()
        self.header.setObjectName("SectionHeader")
        self.header.setCheckable(True)
        self.header.setChecked(expanded)
        self.header.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.header.toggled.connect(self._toggle)
        lay.addWidget(self.header)
        self.body = QWidget()
        self.grid = QGridLayout(self.body)
        self.grid.setContentsMargins(14, 2, 12, 10)
        self.grid.setHorizontalSpacing(10)
        self.grid.setVerticalSpacing(6)
        self.grid.setColumnStretch(0, 1)
        lay.addWidget(self.body)
        self._toggle(expanded)

    def _toggle(self, on: bool) -> None:
        self.header.setText(("▾  " if on else "▸  ") + self.title)
        self.body.setVisible(on)

    def row(self, label: str | None, widget: QWidget) -> QWidget:
        r = self.grid.rowCount()
        if label is None:
            self.grid.addWidget(widget, r, 0, 1, 2)
        else:
            lab = QLabel(label)
            lab.setStyleSheet(f"color: {T['text']};")
            self.grid.addWidget(lab, r, 0)
            # Le champ prend la place disponible (jamais de débordement à droite du volet).
            lab.setWordWrap(True)
            widget.setMinimumWidth(96)
            widget.setMaximumWidth(150)
            widget.setSizePolicy(QSizePolicy.Policy.Expanding, widget.sizePolicy().verticalPolicy())
            self.grid.addWidget(widget, r, 1)
        return widget


def _spin(lo, hi, suffix, decimals=1, step=1.0) -> QDoubleSpinBox:
    s = QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setDecimals(decimals)
    s.setSuffix(suffix)
    s.setSingleStep(step)
    s.setKeyboardTracking(False)
    s.setAccelerated(True)
    return s


class _SliderSpin(QWidget):
    """Curseur + champ, comme « Transparence » dans Office."""

    valueChanged = pyqtSignal(int)

    def __init__(self, lo=0, hi=100, suffix=" %"):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(lo, hi)
        self.spin = QSpinBox()
        self.spin.setRange(lo, hi)
        self.spin.setSuffix(suffix)
        self.spin.setFixedWidth(64)
        self.spin.setKeyboardTracking(False)
        lay.addWidget(self.slider, 1)
        lay.addWidget(self.spin)
        self.slider.valueChanged.connect(self.spin.setValue)
        self.spin.valueChanged.connect(self.slider.setValue)
        self.slider.sliderReleased.connect(lambda: self.valueChanged.emit(self.slider.value()))
        self.spin.valueChanged.connect(lambda v: self.valueChanged.emit(v) if not self.slider.isSliderDown() else None)

    def setValue(self, v: int) -> None:  # noqa: N802
        self.blockSignals(True)
        self.slider.blockSignals(True)
        self.spin.blockSignals(True)
        self.slider.setValue(v)
        self.spin.setValue(v)
        self.slider.blockSignals(False)
        self.spin.blockSignals(False)
        self.blockSignals(False)


class _Toggles(QWidget):
    def __init__(self, entries, exclusive):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(1)
        self.buttons: dict[str, QToolButton] = {}
        self.group = QButtonGroup(self)
        self.group.setExclusive(exclusive)
        for key, ic, tip in entries:
            b = QToolButton()
            b.setIcon(icons.icon(ic))
            b.setIconSize(QSize(16, 16))
            b.setCheckable(True)
            b.setAutoRaise(True)
            b.setToolTip(tip)
            b.setFixedSize(26, 24)
            self.group.addButton(b)
            self.buttons[key] = b
            lay.addWidget(b)
        lay.addStretch(1)


def _scroll(body: QWidget) -> QScrollArea:
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.Shape.NoFrame)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    body.setObjectName("TaskPaneBody")
    area.setWidget(body)
    return area


# =========================================================================== Format de la forme

class FormatPane(QWidget):
    TABS = (("fill", "Remplissage et trait"), ("effects", "Effets"), ("text", "Texte"),
            ("size_position", "Taille et propriétés"))

    def __init__(self, window):
        super().__init__()
        self.win = window
        self._updating = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.sub = QLabel("")
        self.sub.setObjectName("Hint")
        self.sub.setContentsMargins(12, 0, 12, 4)
        lay.addWidget(self.sub)
        tabs = QHBoxLayout()
        tabs.setContentsMargins(10, 0, 10, 4)
        tabs.setSpacing(2)
        self.tab_group = QButtonGroup(self)
        self.tab_buttons = []
        for i, (ic, tip) in enumerate(self.TABS):
            b = QToolButton()
            b.setObjectName("PaneTabIcon")
            b.setIcon(icons.icon(ic))
            b.setIconSize(QSize(20, 20))
            b.setCheckable(True)
            b.setToolTip(tip)
            b.setChecked(i == 0)
            self.tab_group.addButton(b, i)
            self.tab_buttons.append(b)
            tabs.addWidget(b)
        tabs.addStretch(1)
        self.tabs_box = QWidget()
        self.tabs_box.setLayout(tabs)
        lay.addWidget(self.tabs_box)
        self.stack = QStackedWidget()
        lay.addWidget(self.stack, 1)
        self.tab_group.idClicked.connect(self.stack.setCurrentIndex)
        self._page_fill()
        self._page_effects()
        self._page_text()
        self._page_size()
        self._page_page()

    # ------------------------------------------------------------------ pages
    def _new_page(self) -> QVBoxLayout:
        body = QWidget()
        v = QVBoxLayout(body)
        v.setContentsMargins(10, 4, 10, 10)
        v.setSpacing(4)
        self.stack.addWidget(_scroll(body))
        return v

    def _page_fill(self) -> None:
        v = self._new_page()
        s = self.sec_fill = Section("Remplissage")
        self.fill_mode = QButtonGroup(self)
        for i, t in enumerate(("Aucun remplissage", "Remplissage uni", "Remplissage dégradé")):
            rb = QRadioButton(t)
            self.fill_mode.addButton(rb, i)
            s.row(None, rb)
        self.fill_mode.idClicked.connect(self._fill_mode)
        self.fill_color = ColorButton("fill", "Couleur de remplissage", none_label="Aucun remplissage", swatch=True)
        self.fill_color.colorPicked.connect(lambda c: self._shape({"fill": c}, "Remplissage"))
        s.row("Couleur", self.fill_color)
        self.transp = _SliderSpin()
        self.transp.valueChanged.connect(lambda val: self._shape({"transparency": float(val)}, "Transparence", "tr"))
        s.row("Transparence", self.transp)
        v.addWidget(s)
        s = self.sec_line = Section("Trait")
        self.line_mode = QButtonGroup(self)
        for i, t in enumerate(("Aucun trait", "Trait plein")):
            rb = QRadioButton(t)
            self.line_mode.addButton(rb, i)
            s.row(None, rb)
        self.line_mode.idClicked.connect(self._line_mode)
        self.line_color = ColorButton("line_color", "Couleur du trait", "#41719c", none_label="Aucun trait", swatch=True)
        self.line_color.colorPicked.connect(lambda c: self._line({"line": c}, "Couleur du trait"))
        s.row("Couleur", self.line_color)
        self.line_width = _spin(0.25, 36, " pt", 2, 0.25)
        self.line_width.valueChanged.connect(lambda val: self._line({"line_width": val / PT_PER_PX}, "Épaisseur", "lw"))
        s.row("Largeur", self.line_width)
        self.dash = QComboBox()
        for d in DASHES:
            self.dash.addItem(DASH_LABELS[d], d)
        self.dash.currentIndexChanged.connect(lambda i: self._line({"dash": self.dash.itemData(i)}, "Type de tiret"))
        s.row("Type de tiret", self.dash)
        self.rounding = _spin(0, 100, " mm")
        self.rounding.valueChanged.connect(lambda val: self._shape({"rounding": val}, "Arrondi", "rd"))
        self.rounding_row = s.row("Arrondi des angles", self.rounding)
        self.route = QComboBox()
        for r in ROUTES:
            self.route.addItem(ROUTE_LABELS[r], r)
        self.route.currentIndexChanged.connect(lambda i: self._conn({"route": self.route.itemData(i)}, "Type de connecteur"))
        self.route_row = s.row("Type de connecteur", self.route)
        self.arrow_start, self.arrow_end = QComboBox(), QComboBox()
        for combo, key, label in ((self.arrow_start, "arrow_start", "Début de flèche"),
                                  (self.arrow_end, "arrow_end", "Fin de flèche")):
            for a in ARROWS:
                combo.addItem(ARROW_LABELS[a], a)
            combo.currentIndexChanged.connect(lambda i, c=combo, k=key: self._conn({k: c.itemData(i)}, "Flèche"))
            s.row(label, combo)
        v.addWidget(s)
        v.addStretch(1)

    def _page_effects(self) -> None:
        v = self._new_page()
        s = Section("Ombre")
        self.shadow = QCheckBox("Ombre portée")
        self.shadow.toggled.connect(lambda b: self._shape({"shadow": b}, "Ombre"))
        s.row(None, self.shadow)
        v.addWidget(s)
        s = Section("Lueur")
        self.glow = ColorButton("glow", "Couleur de la lueur", "#ffc000", none_label="Aucune lueur", swatch=True)
        self.glow.colorPicked.connect(lambda c: self._shape({"glow": c}, "Lueur"))
        s.row("Couleur", self.glow)
        self.glow_size = _spin(1, 50, " pt")
        self.glow_size.valueChanged.connect(lambda val: self._shape({"glow_size": val}, "Taille de la lueur", "gs"))
        s.row("Taille", self.glow_size)
        v.addWidget(s)
        s = Section("Dégradé")
        self.gradient = QCheckBox("Dégradé vertical")
        self.gradient.toggled.connect(lambda b: self._shape({"gradient": b}, "Dégradé"))
        s.row(None, self.gradient)
        v.addWidget(s)
        v.addStretch(1)

    def _page_text(self) -> None:
        v = self._new_page()
        s = Section("Police")
        self.font = QFontComboBox()
        self.font.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.font.setMinimumContentsLength(8)
        self.font.currentFontChanged.connect(lambda f: self._text({"font": f.family()}, "Police"))
        s.row("Police", self.font)
        self.size = _spin(1, 400, " pt")
        self.size.valueChanged.connect(lambda val: self._text({"size": val}, "Taille", "fs"))
        s.row("Taille", self.size)
        self.styles = _Toggles([("bold", "bold", "Gras"), ("italic", "italic", "Italique"),
                                ("underline", "underline", "Souligné"), ("strike", "strike", "Barré")], False)
        for k, b in self.styles.buttons.items():
            b.toggled.connect(lambda on, key=k: self._text({key: on}, "Style du texte"))
        s.row("Style", self.styles)
        self.text_color = ColorButton("font_color", "Couleur de police", "#000000", allow_none=False, swatch=True)
        self.text_color.colorPicked.connect(lambda c: self._text({"color": c}, "Couleur de police"))
        s.row("Couleur", self.text_color)
        v.addWidget(s)
        s = Section("Paragraphe")
        self.halign = _Toggles([("left", "align_text_left", "Gauche"), ("center", "align_text_center", "Centré"),
                                ("right", "align_text_right", "Droite"), ("justify", "justify", "Justifié")], True)
        for k, b in self.halign.buttons.items():
            b.clicked.connect(lambda _=False, key=k: self._text({"halign": key}, "Alignement"))
        s.row("Horizontal", self.halign)
        self.valign = _Toggles([("top", "valign_top", "Haut"), ("middle", "valign_middle", "Milieu"),
                                ("bottom", "valign_bottom", "Bas")], True)
        for k, b in self.valign.buttons.items():
            b.clicked.connect(lambda _=False, key=k: self._text({"valign": key}, "Alignement vertical"))
        s.row("Vertical", self.valign)
        v.addWidget(s)
        v.addStretch(1)

    def _page_size(self) -> None:
        v = self._new_page()
        s = self.sec_geom = Section("Taille et position")
        self.gx, self.gy = _spin(-100000, 100000, " mm"), _spin(-100000, 100000, " mm")
        self.gw, self.gh = _spin(0.5, 100000, " mm"), _spin(0.5, 100000, " mm")
        self.ga = _spin(-180, 180, " °")
        for label, spin, key in (("Position X", self.gx, "x"), ("Position Y", self.gy, "y"),
                                 ("Largeur", self.gw, "w"), ("Hauteur", self.gh, "h"), ("Angle", self.ga, "rotation")):
            spin.valueChanged.connect(lambda val, k=key: self._geom(k, val))
            s.row(label, spin)
        self.lock = QCheckBox("Verrouiller la forme")
        self.lock.toggled.connect(self._lock)
        s.row(None, self.lock)
        v.addWidget(s)
        s = self.sec_props = Section("Propriétés")
        self.tip = QLineEdit()
        self.tip.setPlaceholderText("Texte affiché au survol")
        self.tip.editingFinished.connect(self._tip)
        s.row("Info-bulle", self.tip)
        self.link = QLineEdit()
        self.link.setPlaceholderText("https://…")
        self.link.editingFinished.connect(self._link)
        s.row("Lien", self.link)
        self.layer = QComboBox()
        self.layer.activated.connect(self._layer)
        s.row("Calque", self.layer)
        v.addWidget(s)
        v.addStretch(1)

    def _page_page(self) -> None:
        v = self._new_page()
        s = Section("Mise en page")
        self.page_name = QLineEdit()
        self.page_name.editingFinished.connect(lambda: self._page({"name": security.clean_line(
            self.page_name.text(), 100) or self._scene().page_name}, "Renommer la page"))
        s.row("Nom", self.page_name)
        self.page_size = QComboBox()
        for name in PAGE_SIZES:
            self.page_size.addItem(name, name)
        self.page_size.addItem("Personnalisé", "")
        self.page_size.activated.connect(self._page_format)
        s.row("Format", self.page_size)
        self.orientation = QComboBox()
        self.orientation.addItems(["Portrait", "Paysage"])
        self.orientation.activated.connect(self._orientation)
        s.row("Orientation", self.orientation)
        self.page_w, self.page_h = _spin(20, 10000, " mm"), _spin(20, 10000, " mm")
        self.page_w.valueChanged.connect(lambda val: self._page({"width": val * PX_PER_MM}, "Taille de page"))
        self.page_h.valueChanged.connect(lambda val: self._page({"height": val * PX_PER_MM}, "Taille de page"))
        s.row("Largeur", self.page_w)
        s.row("Hauteur", self.page_h)
        self.auto_size = QCheckBox("Taille automatique")
        self.auto_size.toggled.connect(lambda b: self._page({"auto_size": b}, "Taille automatique"))
        s.row(None, self.auto_size)
        self.page_bg = ColorButton("background", "Couleur d'arrière-plan", "#ffffff", allow_none=False, swatch=True)
        self.page_bg.colorPicked.connect(lambda c: self._page({"background": c}, "Arrière-plan"))
        s.row("Arrière-plan", self.page_bg)
        v.addWidget(s)
        v.addStretch(1)

    # ------------------------------------------------------------------ application
    def _scene(self):
        return self.win.scene()

    def _ok(self) -> bool:
        return not self._updating and self._scene() is not None

    def _shape(self, changes, text, merge=None):
        if self._ok():
            self._scene().apply_shape_style(changes, text, merge)

    def _line(self, changes, text, merge=None):
        if self._ok():
            self._scene().apply_line_to_selection(changes, text, merge)

    def _text(self, changes, text, merge=None):
        if self._ok():
            self._scene().apply_text_style(changes, text, merge)

    def _conn(self, changes, text):
        if self._ok():
            self._scene().apply_connector_style(changes, text=text)

    def _fill_mode(self, mode: int) -> None:
        if not self._ok():
            return
        if mode == 0:
            self._shape({"fill": "", "gradient": False}, "Aucun remplissage")
        else:
            shapes = self._scene().selected_shapes()
            fill = next((s.style["fill"] for s in shapes if s.style["fill"]), "") or self.fill_color.current or "#5b9bd5"
            self._shape({"fill": fill, "gradient": mode == 2}, "Remplissage")

    def _line_mode(self, mode: int) -> None:
        if self._ok():
            self._line({"line": "" if mode == 0 else (self.line_color.current or "#41719c")}, "Trait")

    def _geom(self, key: str, value: float) -> None:
        sc = self._scene()
        if not self._ok() or not isinstance(sc.single_selected, ShapeItem):
            return
        val = value if key == "rotation" else (max(value * PX_PER_MM, 1.0) if key in ("w", "h") else value * PX_PER_MM)
        sc.set_geometry(sc.single_selected, **{key: val})

    def _lock(self, on: bool) -> None:
        if self._ok():
            self._scene().set_locked(self._scene().selected_shapes(), on)

    def _tip(self) -> None:
        sc = self._scene()
        if self._ok() and isinstance(sc.single_selected, ShapeItem):
            text = security.clean_line(self.tip.text(), 500)
            if text != sc.single_selected.tip:
                sc.set_tip(sc.single_selected, text)

    def _link(self) -> None:
        sc = self._scene()
        if not self._ok() or not isinstance(sc.single_selected, ShapeItem):
            return
        text = self.link.text().strip()
        url = security.safe_url(text) if text and not text.startswith("page:") else text
        if text and not url:
            self.link.setStyleSheet("border: 1px solid #d13438;")
            self.link.setToolTip("Seuls les liens http://, https://, mailto: et page: sont autorisés.")
            return
        self.link.setStyleSheet("")
        if url != sc.single_selected.link:
            def set_link(it, st):
                st["link"] = url
            sc.modify([sc.single_selected], set_link, "Lien hypertexte")

    def _layer(self, _i: int) -> None:
        if self._ok():
            name = self.layer.currentData() or ""
            self._scene().assign_layer(self._scene().selected_all(), name)

    def _page(self, changes: dict, text: str) -> None:
        sc = self._scene()
        if not self._ok():
            return
        before = sc.page_props()
        after = dict(before, **changes)
        if after != before:
            self.win.doc.undo_stack.push(PageCommand(self.win.doc, text, scene=sc, before=before, after=after))

    def _page_format(self, i: int) -> None:
        name = self.page_size.itemData(i)
        if not name or not self._ok():
            return
        w, h = PAGE_SIZES[name]
        if self.orientation.currentIndex() == 1:
            w, h = h, w
        self._page({"width": w * PX_PER_MM, "height": h * PX_PER_MM}, f"Format {name}")

    def _orientation(self, i: int) -> None:
        sc = self._scene()
        if self._ok() and (sc.page_w > sc.page_h) != (i == 1):
            self._page({"width": sc.page_h, "height": sc.page_w}, "Orientation")

    # ------------------------------------------------------------------ rafraîchissement
    def refresh(self) -> None:
        self._updating = True
        try:
            self._refresh()
        finally:
            self._updating = False

    def _refresh(self) -> None:
        sc = self._scene()
        if sc is None:
            return
        sel = sc.selected_all()
        shapes = [i for i in sel if isinstance(i, ShapeItem)]
        conns = [i for i in sel if isinstance(i, ConnectorItem)]
        if not sel:
            self.tabs_box.hide()
            self.stack.setCurrentIndex(4)
            self.sub.setText("Aucune forme sélectionnée : propriétés de la page.")
            self._refresh_page(sc)
            return
        self.tabs_box.show()
        idx = self.tab_group.checkedId()
        self.stack.setCurrentIndex(max(0, idx))
        if len(sel) == 1:
            self.sub.setText(shapes[0].sdef.name if shapes else "Connecteur")
        else:
            self.sub.setText(f"{len(sel)} objets sélectionnés")
        ref = shapes[0] if shapes else conns[0]
        st = ref.style
        self.sec_fill.setVisible(bool(shapes))
        if shapes:
            s0 = shapes[0].style
            self.fill_mode.button(0 if not s0["fill"] else (2 if s0["gradient"] else 1)).setChecked(True)
            self.fill_color.current = s0["fill"] or self.fill_color.current
            self.fill_color._refresh()
            self.transp.setValue(int(s0["transparency"]))
            self.rounding.setValue(s0["rounding"])
            self.shadow.setChecked(s0["shadow"])
            self.gradient.setChecked(s0["gradient"])
            self.glow.current = s0.get("glow", "")
            self.glow._refresh()
            self.glow_size.setValue(s0.get("glow_size", 8.0))
        self.rounding_row.setEnabled(any(s.sdef.roundable for s in shapes))
        self.line_mode.button(0 if not st["line"] else 1).setChecked(True)
        if st["line"]:
            self.line_color.current = st["line"]
            self.line_color._refresh()
        self.line_width.setValue(st["line_width"] * PT_PER_PX)
        self.dash.setCurrentIndex(max(0, self.dash.findData(st["dash"])))
        for w in (self.route_row, self.arrow_start, self.arrow_end):
            w.setEnabled(bool(conns))
        if conns:
            cs = conns[0].style
            self.route.setCurrentIndex(max(0, self.route.findData(cs["route"])))
            self.arrow_start.setCurrentIndex(max(0, self.arrow_start.findData(cs["arrow_start"])))
            self.arrow_end.setCurrentIndex(max(0, self.arrow_end.findData(cs["arrow_end"])))
        ts = ref.text_style
        self.font.setCurrentFont(QFont(ts["font"]))
        self.size.setValue(ts["size"])
        for k in ("bold", "italic", "underline", "strike"):
            self.styles.buttons[k].setChecked(bool(ts.get(k)))
        self.halign.buttons.get(ts["halign"], self.halign.buttons["center"]).setChecked(True)
        self.valign.buttons[ts["valign"]].setChecked(True)
        self.text_color.current = ts["color"]
        self.text_color._refresh()
        single = sc.single_selected
        self.sec_geom.setEnabled(isinstance(single, ShapeItem))
        self.sec_props.setEnabled(single is not None)
        if isinstance(single, ShapeItem):
            self.gx.setValue(single.pos().x() / PX_PER_MM)
            self.gy.setValue(single.pos().y() / PX_PER_MM)
            self.gw.setValue(single.w / PX_PER_MM)
            self.gh.setValue(single.h / PX_PER_MM)
            self.ga.setValue(single.rotation())
            self.lock.setChecked(single.locked)
            self.tip.setText(single.tip)
            self.link.setText(single.link)
            self.link.setStyleSheet("")
        self.layer.clear()
        self.layer.addItem("(aucun)", "")
        for lay in sc.layers:
            self.layer.addItem(lay["name"], lay["name"])
        if single is not None:
            self.layer.setCurrentIndex(max(0, self.layer.findData(single.layer)))

    def _refresh_page(self, sc) -> None:
        self.page_name.setText(sc.page_name)
        w_mm, h_mm = sc.page_w / PX_PER_MM, sc.page_h / PX_PER_MM
        self.page_w.setValue(w_mm)
        self.page_h.setValue(h_mm)
        self.orientation.setCurrentIndex(1 if sc.page_w > sc.page_h else 0)
        match = ""
        for name, (w, h) in PAGE_SIZES.items():
            if {round(w), round(h)} == {round(w_mm), round(h_mm)}:
                match = name
        self.page_size.setCurrentIndex(self.page_size.findData(match))
        self.auto_size.setChecked(sc.auto_size)
        self.page_bg.current = sc.page_bg
        self.page_bg._refresh()


# =========================================================================== Taille et position

class SizePositionPane(QWidget):
    def __init__(self, window):
        super().__init__()
        self.win = window
        self._updating = False
        grid = QGridLayout(self)
        grid.setContentsMargins(12, 4, 12, 8)
        grid.setVerticalSpacing(5)
        self.fields = {}
        for r, (key, label, suffix, lo, hi) in enumerate((
                ("x", "X", " mm", -1e5, 1e5), ("y", "Y", " mm", -1e5, 1e5),
                ("w", "Largeur", " mm", 0.5, 1e5), ("h", "Hauteur", " mm", 0.5, 1e5),
                ("rotation", "Angle", " °", -180, 180))):
            grid.addWidget(QLabel(label), r, 0)
            s = _spin(lo, hi, suffix)
            s.valueChanged.connect(lambda val, k=key: self._apply(k, val))
            grid.addWidget(s, r, 1)
            self.fields[key] = s
        grid.addWidget(QLabel("Point d'ancrage"), 5, 0)
        pin = QLabel("Centre-centre")
        pin.setObjectName("Hint")
        grid.addWidget(pin, 5, 1)
        grid.setRowStretch(6, 1)

    def _apply(self, key: str, value: float) -> None:
        sc = self.win.scene()
        if self._updating or sc is None or not isinstance(sc.single_selected, ShapeItem):
            return
        val = value if key == "rotation" else (max(value * PX_PER_MM, 1.0) if key in ("w", "h") else value * PX_PER_MM)
        sc.set_geometry(sc.single_selected, **{key: val})

    def refresh(self) -> None:
        sc = self.win.scene()
        s = sc.single_selected if sc is not None else None
        self._updating = True
        for f in self.fields.values():
            f.setEnabled(isinstance(s, ShapeItem))
        if isinstance(s, ShapeItem):
            self.fields["x"].setValue(s.pos().x() / PX_PER_MM)
            self.fields["y"].setValue(s.pos().y() / PX_PER_MM)
            self.fields["w"].setValue(s.w / PX_PER_MM)
            self.fields["h"].setValue(s.h / PX_PER_MM)
            self.fields["rotation"].setValue(s.rotation())
        self._updating = False


# =========================================================================== Données de forme

class ShapeDataPane(QWidget):
    def __init__(self, window):
        super().__init__()
        self.win = window
        self._updating = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 2, 10, 8)
        self.hint = QLabel("Sélectionnez une forme pour voir ses données.")
        self.hint.setObjectName("Hint")
        self.hint.setWordWrap(True)
        lay.addWidget(self.hint)
        self.link_status = QLabel()
        self.link_status.setTextFormat(Qt.TextFormat.PlainText)
        self.link_status.setObjectName("Hint")
        self.link_status.setWordWrap(True)
        self.link_status.hide()
        lay.addWidget(self.link_status)
        self.graphic_status = QLabel()
        self.graphic_status.setTextFormat(Qt.TextFormat.PlainText)
        self.graphic_status.setObjectName("Hint")
        self.graphic_status.setWordWrap(True)
        self.graphic_status.hide()
        lay.addWidget(self.graphic_status)
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Propriété", "Valeur"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.cellChanged.connect(lambda _r, _c: self._commit())
        lay.addWidget(self.table, 1)
        row = QHBoxLayout()
        add = QPushButton("Ajouter")
        rem = QPushButton("Supprimer")
        add.clicked.connect(self._add)
        rem.clicked.connect(self._remove)
        row.addWidget(add)
        row.addWidget(rem)
        row.addStretch(1)
        lay.addLayout(row)

    def _item(self):
        sc = self.win.scene()
        return sc.single_selected if sc is not None else None

    def refresh(self) -> None:
        it = self._item()
        self._updating = True
        self.table.setRowCount(0)
        self.table.setEnabled(it is not None)
        self.hint.setVisible(it is None)
        linked = it.data_links if it is not None else []
        self.link_status.setVisible(bool(linked))
        if linked:
            lines = []
            for link in linked:
                source = os.path.basename(link.get("path", "")) or "fichier local"
                key = link.get("source_key", "")
                target = "texte de la forme" if link.get("shape_key") == "__text__" else link.get("shape_key", "")
                lines.append(f"CSV lié : {source} · {key} ↔ {target}")
            self.link_status.setText("\n".join(lines))
        graphic = it.data_graphic if it is not None else {}
        self.graphic_status.setVisible(bool(graphic))
        if graphic:
            display = {"label_value": "étiquette et valeur", "value": "valeur seule",
                       "status": "pastille de statut"}.get(graphic.get("display"), "graphique")
            self.graphic_status.setText(f"Graphique de données : {graphic.get('field', '')} · {display}")
        if it is not None:
            for k, v in it.data.items():
                r = self.table.rowCount()
                self.table.insertRow(r)
                self.table.setItem(r, 0, QTableWidgetItem(k))
                self.table.setItem(r, 1, QTableWidgetItem(v))
        self._updating = False

    def _commit(self) -> None:
        it = self._item()
        if self._updating or it is None:
            return
        data = {}
        for r in range(self.table.rowCount()):
            k, v = self.table.item(r, 0), self.table.item(r, 1)
            key = security.clean_line(k.text() if k else "", 100)
            if key:
                data[key] = security.clean_line(v.text() if v else "", 2000)

        def set_data(_it, st):
            st["data"] = data
        self.win.scene().modify([it], set_data, "Données de forme")

    def _add(self) -> None:
        if self._item() is None:
            return
        self._updating = True
        r = self.table.rowCount()
        self.table.insertRow(r)
        self.table.setItem(r, 0, QTableWidgetItem(f"Propriété {r + 1}"))
        self.table.setItem(r, 1, QTableWidgetItem(""))
        self._updating = False
        self._commit()
        self.table.editItem(self.table.item(r, 1))

    def _remove(self) -> None:
        r = self.table.currentRow()
        if r >= 0:
            self.table.removeRow(r)
            self._commit()


# =========================================================================== Commentaires

class CommentsPane(QWidget):
    def __init__(self, window):
        super().__init__()
        self.win = window
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 2, 10, 8)
        self.list = QTreeWidget()
        self.list.setHeaderHidden(True)
        self.list.setRootIsDecorated(False)
        self.list.setWordWrap(True)
        self.list.itemClicked.connect(self._select)
        lay.addWidget(self.list, 1)
        self.edit = QPlainTextEdit()
        self.edit.setPlaceholderText("Écrire un commentaire sur la forme sélectionnée…")
        self.edit.setFixedHeight(70)
        lay.addWidget(self.edit)
        row = QHBoxLayout()
        self.post = QPushButton("Publier")
        self.post.setDefault(True)
        self.post.clicked.connect(self._post)
        self.delete = QPushButton("Supprimer")
        self.delete.clicked.connect(self._delete)
        row.addWidget(self.post)
        row.addWidget(self.delete)
        row.addStretch(1)
        lay.addLayout(row)

    def refresh(self) -> None:
        sc = self.win.scene()
        self.list.clear()
        if sc is None:
            return
        for shape in sc.commented_shapes():
            for i, c in enumerate(shape.comments):
                it = QTreeWidgetItem([f"{c['author']} — {c['date']}\n« {shape.text or shape.sdef.name} »\n{c['text']}"])
                it.setData(0, Qt.ItemDataRole.UserRole, (shape.id, i))
                self.list.addTopLevelItem(it)
        if not self.list.topLevelItemCount():
            it = QTreeWidgetItem(["Aucun commentaire sur cette page."])
            it.setFlags(Qt.ItemFlag.NoItemFlags)
            self.list.addTopLevelItem(it)
        single = sc.single_selected
        self.post.setEnabled(isinstance(single, ShapeItem))
        self.edit.setEnabled(isinstance(single, ShapeItem))

    def _select(self, it) -> None:
        data = it.data(0, Qt.ItemDataRole.UserRole)
        sc = self.win.scene()
        if data and sc is not None:
            shape = sc.item_by_id(data[0])
            if shape is not None:
                sc.select_items([shape])
                self.win.view.centerOn(shape)

    def _post(self) -> None:
        sc = self.win.scene()
        text = security.clean_text(self.edit.toPlainText(), 5000).strip()
        if sc is None or not isinstance(sc.single_selected, ShapeItem) or not text:
            return
        sc.add_comment(sc.single_selected, text, self.win.user_name())
        self.edit.clear()

    def _delete(self) -> None:
        it = self.list.currentItem()
        data = it.data(0, Qt.ItemDataRole.UserRole) if it else None
        sc = self.win.scene()
        if data and sc is not None:
            shape = sc.item_by_id(data[0])
            if shape is not None:
                sc.delete_comment(shape, data[1])


# =========================================================================== Problèmes

class IssuesPane(QWidget):
    def __init__(self, window):
        super().__init__()
        self.win = window
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 2, 10, 8)
        top = QHBoxLayout()
        self.summary = QLabel("Cliquez sur « Vérifier le diagramme ».")
        self.summary.setObjectName("Hint")
        top.addWidget(self.summary, 1)
        again = QPushButton("Vérifier")
        again.clicked.connect(self.run)
        top.addWidget(again)
        lay.addLayout(top)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Type", "Description"])
        self.tree.setRootIsDecorated(False)
        self.tree.setWordWrap(True)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.tree.itemClicked.connect(self._select)
        lay.addWidget(self.tree, 1)

    def run(self) -> int:
        sc = self.win.scene()
        self.tree.clear()
        if sc is None:
            return 0
        issues = sc.check_diagram()
        for kind, text, ids in issues:
            it = QTreeWidgetItem([kind, text])
            it.setData(0, Qt.ItemDataRole.UserRole, ids)
            it.setForeground(0, QColor("#d13438" if kind == "Erreur" else "#b8860b" if kind == "Avertissement"
                                       else T["text2"]))
            self.tree.addTopLevelItem(it)
        self.summary.setText(f"{len(issues)} problème(s) trouvé(s) sur « {sc.page_name} »." if issues
                             else "Aucun problème trouvé.")
        return len(issues)

    def _select(self, it) -> None:
        sc = self.win.scene()
        ids = it.data(0, Qt.ItemDataRole.UserRole) or []
        items = [sc.item_by_id(i) for i in ids if sc.item_by_id(i) is not None]
        if items:
            sc.select_items(items)
            self.win.view.centerOn(items[0])


# =========================================================================== Panoramique et zoom

class PanZoomPane(QWidget):
    def __init__(self, window):
        super().__init__()
        self.win = window
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 2, 8, 8)
        self.overview = OverviewView(window.view)
        lay.addWidget(self.overview, 1)

    def refresh(self) -> None:
        self.overview._sync()


# =========================================================================== Explorateur de dessin

class DrawingExplorerPane(QWidget):
    """Explorateur filtrable des formes et connecteurs, sur une page ou tout le document."""

    ROLE_IDS = int(Qt.ItemDataRole.UserRole)
    ROLE_KIND = ROLE_IDS + 1
    ROLE_PAGE = ROLE_IDS + 2
    MAX_OBJECT_ROWS = 12_000
    ALL_LAYERS = "__all_layers__"
    NO_LAYER = "__no_layer__"

    def __init__(self, window):
        super().__init__()
        self.win = window
        self._doc = None
        self._doc_slots = []
        self._scene = None
        self._rows_by_id: dict[tuple[int, str], QTreeWidgetItem] = {}
        self._page_rows: dict[int, QTreeWidgetItem] = {}
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(160)
        self._timer.timeout.connect(self._rebuild)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 2, 8, 8)
        lay.setSpacing(6)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Rechercher des formes et connecteurs")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.schedule_refresh)
        lay.addWidget(self.search)

        scope_row = QHBoxLayout()
        scope_row.setContentsMargins(2, 0, 2, 0)
        self.all_pages = QCheckBox("Toutes les pages")
        self.all_pages.setToolTip("Parcourir et rechercher les objets de toutes les pages du document.")
        self.all_pages.setChecked(window.settings.value("panes/drawing_all_pages", False, type=bool))
        self.all_pages.toggled.connect(self._scope_changed)
        scope_row.addWidget(self.all_pages)
        scope_row.addStretch(1)
        lay.addLayout(scope_row)

        layer_row = QHBoxLayout()
        layer_row.setContentsMargins(2, 0, 2, 0)
        layer_row.addWidget(QLabel("Calque :"))
        self.layer_filter = QComboBox()
        self.layer_filter.addItem("Tous les calques", self.ALL_LAYERS)
        self.layer_filter.currentIndexChanged.connect(self.schedule_refresh)
        layer_row.addWidget(self.layer_filter, 1)
        self.layer_filter_box = QWidget()
        self.layer_filter_box.setLayout(layer_row)
        self.layer_filter_box.hide()
        lay.addWidget(self.layer_filter_box)

        self.summary = QLabel()
        self.summary.setObjectName("Hint")
        self.summary.setWordWrap(True)
        lay.addWidget(self.summary)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Objet", "Type"])
        self.tree.setRootIsDecorated(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setUniformRowHeights(True)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.itemSelectionChanged.connect(self._selection_changed)
        self.tree.itemDoubleClicked.connect(self._activate)
        lay.addWidget(self.tree, 1)

    def _scope_changed(self, on: bool) -> None:
        self.win.settings.setValue("panes/drawing_all_pages", on)
        self._refresh_layer_options()
        self.schedule_refresh()

    def refresh(self) -> None:
        doc = self.win.doc
        if doc is not self._doc:
            for signal, slot in self._doc_slots:
                try:
                    signal.disconnect(slot)
                except (TypeError, RuntimeError):
                    pass
            self._doc = doc
            self._doc_slots = []
            if doc is not None:
                for signal in (doc.pagesChanged, doc.undo_stack.indexChanged):
                    slot = self._document_changed
                    signal.connect(slot)
                    self._doc_slots.append((signal, slot))
        scene = self.win.scene()
        self._scene = scene
        if self.isVisible():
            self._refresh_layer_options()
        self.schedule_refresh()

    def _document_changed(self, *_args) -> None:
        if self.isVisible():
            self._refresh_layer_options()
        self.schedule_refresh()

    def _refresh_layer_options(self) -> None:
        doc = self.win.doc
        active = self.win.scene()
        if doc is None or active is None:
            self.layer_filter_box.hide()
            return
        pages = doc.pages if self.all_pages.isChecked() else [active]
        names = {layer.get("name", "") for page in pages for layer in page.layers if layer.get("name")}
        current = self.layer_filter.currentData()
        options = [("Tous les calques", self.ALL_LAYERS)]
        options.extend((name, name) for name in sorted(names, key=str.casefold))
        options.append(("Sans calque", self.NO_LAYER))
        self.layer_filter.blockSignals(True)
        try:
            self.layer_filter.clear()
            for label, value in options:
                self.layer_filter.addItem(label, value)
            indices = [i for i in range(self.layer_filter.count()) if self.layer_filter.itemData(i) == current]
            self.layer_filter.setCurrentIndex(indices[0] if indices else 0)
        finally:
            self.layer_filter.blockSignals(False)
        self.layer_filter_box.show()

    def schedule_refresh(self, *_args) -> None:
        if self.isVisible():
            self._timer.start()

    @staticmethod
    def _label(item) -> tuple[str, str]:
        if isinstance(item, ShapeItem):
            label = next((line.strip() for line in item.text.splitlines() if line.strip()), item.sdef.name)
            return label, item.sdef.name
        label = next((line.strip() for line in item.text.splitlines() if line.strip()), "Connecteur")
        return label, "Connecteur"

    def _rebuild(self) -> None:
        doc = self.win.doc
        active = self.win.scene()
        self._scene = active
        if doc is None or active is None:
            self.tree.clear()
            self._rows_by_id.clear()
            self._page_rows.clear()
            self.summary.clear()
            return

        needle = self.search.text().strip().casefold()
        active_index = doc.pages.index(active)
        pages = list(enumerate(doc.pages)) if self.all_pages.isChecked() else [(active_index, active)]
        if self.all_pages.isChecked():
            pages.sort(key=lambda entry: (entry[0] != active_index, entry[0]))
        selected_layer = self.layer_filter.currentData() or self.ALL_LAYERS

        def in_layer(item) -> bool:
            if selected_layer == self.ALL_LAYERS:
                return True
            if selected_layer == self.NO_LAYER:
                return not item.layer
            return item.layer == selected_layer

        page_entries = []
        matching_total = 0
        for page_index, scene in pages:
            groups: dict[str, list] = {}
            entries = []
            for item in scene.all_items():
                if isinstance(item, ShapeItem) and item.group:
                    groups.setdefault(item.group, []).append(item)
                else:
                    entries.append((item.zValue(), item, None))
            for group_id, members in groups.items():
                entries.append((max(member.zValue() for member in members), None, (group_id, members)))

            page_label = f"Page {page_index + 1} {scene.page_name}".casefold()
            page_matches = bool(needle) and needle in page_label
            visible_entries = []
            for _z, item, group in sorted(entries, key=lambda entry: entry[0], reverse=True):
                if group is not None:
                    group_id, members = group
                    group_matches = needle in f"groupe {group_id}".casefold() if needle else False
                    visible_members = [member for member in members if in_layer(member)
                                       and (not needle or page_matches or group_matches
                                            or self._item_matches(member, needle))]
                    if visible_members:
                        visible_members.sort(key=lambda value: value.zValue(), reverse=True)
                        visible_entries.append((None, (group_id, visible_members)))
                        matching_total += len(visible_members)
                elif in_layer(item) and (not needle or page_matches or self._item_matches(item, needle)):
                    visible_entries.append((item, None))
                    matching_total += 1
            if visible_entries or (self.all_pages.isChecked() and (not needle or page_matches)):
                page_entries.append((page_index, scene, visible_entries))

        self._rows_by_id.clear()
        self._page_rows.clear()
        self.tree.blockSignals(True)
        try:
            self.tree.clear()
            shown = 0
            truncated = False
            for page_index, scene, entries in page_entries:
                page_root = None
                if self.all_pages.isChecked():
                    page_root = QTreeWidgetItem([scene.page_name, f"Page {page_index + 1}"])
                    page_root.setIcon(0, icons.icon("page_size"))
                    page_root.setData(0, self.ROLE_KIND, "page")
                    page_root.setData(0, self.ROLE_PAGE, page_index)
                    page_object_count = sum(len(group[1]) if group else 1 for _item, group in entries)
                    page_root.setToolTip(0, security.tooltip_html(f"{scene.page_name}\nPage {page_index + 1} · "
                                                                  f"{page_object_count} objet(s)"))
                    self.tree.addTopLevelItem(page_root)
                    self._page_rows[page_index] = page_root
                    page_root.setExpanded(True)

                parent_item = page_root
                for item, group in entries:
                    remaining = self.MAX_OBJECT_ROWS - shown
                    if remaining <= 0:
                        truncated = True
                        break
                    if group is not None:
                        group_id, members = group
                        members = members[:remaining]
                        if len(members) < len(group[1]):
                            truncated = True
                        parent = QTreeWidgetItem([f"Groupe ({len(members)})", "Groupe"])
                        parent.setData(0, self.ROLE_IDS, [member.id for member in members])
                        parent.setData(0, self.ROLE_KIND, "group")
                        parent.setData(0, self.ROLE_PAGE, page_index)
                        parent.setIcon(0, icons.icon("group"))
                        if parent_item is None:
                            self.tree.addTopLevelItem(parent)
                        else:
                            parent_item.addChild(parent)
                        parent.setExpanded(True)
                        for member in members:
                            child = self._add_item(parent, member, page_index)
                            self._rows_by_id[(page_index, member.id)] = child
                        shown += len(members)
                    else:
                        row = self._add_item(parent_item, item, page_index)
                        self._rows_by_id[(page_index, item.id)] = row
                        shown += 1
                if truncated:
                    break

            selected = {item.id for item in active.selected_all()}
            for item_id in selected:
                row = self._rows_by_id.get((active_index, item_id))
                if row is not None:
                    row.setSelected(True)
            if self.all_pages.isChecked() and not selected:
                row = self._page_rows.get(active_index)
                if row is not None:
                    row.setSelected(True)
        finally:
            self.tree.blockSignals(False)

        if truncated:
            shown_text = f"{shown:,}".replace(",", " ")
            total_text = f"{matching_total:,}".replace(",", " ")
            self.summary.setText(f"{shown_text} objets affichés sur {total_text}. Affinez la recherche pour réduire la liste.")
        elif self.all_pages.isChecked():
            total_text = f"{matching_total:,}".replace(",", " ")
            layer_label = self.layer_filter.currentText()
            suffix = f" · {layer_label}" if selected_layer != self.ALL_LAYERS else ""
            self.summary.setText(f"{total_text} objet(s) · {len(page_entries)} page(s){suffix}")
        else:
            total_text = f"{matching_total:,}".replace(",", " ")
            layer_label = self.layer_filter.currentText()
            suffix = f" · {layer_label}" if selected_layer != self.ALL_LAYERS else ""
            self.summary.setText(f"{total_text} objet(s) · {active.page_name}{suffix}")

    @staticmethod
    def _item_matches(item, needle: str) -> bool:
        label, kind = DrawingExplorerPane._label(item)
        if any(needle in value.casefold() for value in (label, kind, item.id)):
            return True
        if isinstance(item, ShapeItem):
            for key, value in item.data.items():
                if needle in key.casefold() or needle in value.casefold():
                    return True
        return False

    def _add_item(self, parent, item, page_index: int) -> QTreeWidgetItem:
        label, kind = self._label(item)
        row = QTreeWidgetItem([label, kind])
        row.setData(0, self.ROLE_IDS, [item.id])
        row.setData(0, self.ROLE_KIND, "object")
        row.setData(0, self.ROLE_PAGE, page_index)
        row.setToolTip(0, security.tooltip_html(f"{label}\n{kind}\nID : {item.id}"))
        row.setToolTip(1, security.tooltip_html(f"ID : {item.id}"))
        if isinstance(item, ShapeItem):
            row.setIcon(0, QIcon(icons.stencil_pixmap(item.sdef, 24)))
            if item.locked:
                row.setText(0, f"{label} — verrouillée")
        else:
            row.setIcon(0, icons.icon("connector"))
        if parent is None:
            self.tree.addTopLevelItem(row)
        else:
            parent.addChild(row)
        return row

    def _selection_changed(self) -> None:
        doc = self.win.doc
        if doc is None or not doc.pages:
            return
        selected_rows = self.tree.selectedItems()
        if not selected_rows:
            scene = self.win.scene()
            if scene is not None:
                scene.select_items([])
            return
        current = self.tree.currentItem()
        target_index = current.data(0, self.ROLE_PAGE) if current is not None else None
        if target_index is None and selected_rows:
            target_index = selected_rows[-1].data(0, self.ROLE_PAGE)
        if target_index is None or not 0 <= target_index < len(doc.pages):
            return
        target_index = int(target_index)
        target_rows = [row for row in selected_rows if row.data(0, self.ROLE_PAGE) == target_index]
        self.tree.blockSignals(True)
        try:
            for row in selected_rows:
                if row.data(0, self.ROLE_PAGE) != target_index:
                    row.setSelected(False)
        finally:
            self.tree.blockSignals(False)
        scene = doc.pages[target_index]
        if scene is not self.win.scene():
            self.win.show_page(scene)
        if current is not None and current.data(0, self.ROLE_KIND) == "page":
            scene.select_items([])
            return
        ids = []
        for row in target_rows:
            if row.data(0, self.ROLE_KIND) == "page":
                continue
            ids.extend(row.data(0, self.ROLE_IDS) or [])
        items = list({item_id: scene.item_by_id(item_id) for item_id in ids
                      if scene.item_by_id(item_id) is not None}.values())
        scene.select_items(items)
        if items:
            self.win.view.centerOn(items[0])

    def sync_selection(self) -> None:
        scene = self.win.scene()
        doc = self.win.doc
        if scene is None or doc is None:
            return
        page_index = doc.pages.index(scene)
        selected = {item.id for item in scene.selected_all()}
        self.tree.blockSignals(True)
        try:
            self.tree.clearSelection()
            for item_id in selected:
                row = self._rows_by_id.get((page_index, item_id))
                if row is not None and not row.isHidden():
                    row.setSelected(True)
            if not selected and self.all_pages.isChecked():
                row = self._page_rows.get(page_index)
                if row is not None:
                    row.setSelected(True)
        finally:
            self.tree.blockSignals(False)

    def _activate(self, row, _column: int) -> None:
        doc = self.win.doc
        if doc is None:
            return
        page_index = row.data(0, self.ROLE_PAGE)
        if page_index is None or not 0 <= page_index < len(doc.pages):
            return
        scene = doc.pages[int(page_index)]
        if scene is not self.win.scene():
            self.win.show_page(scene)
        if row.data(0, self.ROLE_KIND) == "page":
            return
        ids = row.data(0, self.ROLE_IDS) or []
        if len(ids) == 1:
            item = scene.item_by_id(ids[0])
            if isinstance(item, ShapeItem):
                item.start_edit(select_all=True)


class TaskPaneArea(QSplitter):
    """Zone de droite où s'empilent les volets ouverts."""

    visibilityChanged = pyqtSignal(str, bool)

    def __init__(self):
        super().__init__(Qt.Orientation.Vertical)
        self.panes: dict[str, TaskPane] = {}
        self.setChildrenCollapsible(False)

    def add(self, key: str, title: str, body: QWidget) -> TaskPane:
        pane = TaskPane(title, body)
        pane.closed.connect(lambda k=key: self._closed(k))
        self.addWidget(pane)
        pane.hide()
        self.panes[key] = pane
        return pane

    def _closed(self, key: str) -> None:
        self.visibilityChanged.emit(key, False)
        self._update_self()

    def set_visible(self, key: str, on: bool) -> None:
        pane = self.panes[key]
        pane.setVisible(on)
        self.visibilityChanged.emit(key, on)
        self._update_self()

    def is_visible(self, key: str) -> bool:
        return self.panes[key].isVisible()

    def _update_self(self) -> None:
        self.setVisible(any(not p.isHidden() for p in self.panes.values()))
