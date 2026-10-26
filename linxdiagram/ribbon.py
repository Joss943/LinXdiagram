"""Ruban façon Microsoft Office : onglets colorés, groupes, grands et petits
boutons dessinés à la main, boutons partagés, galeries et lanceurs de boîte de dialogue."""

from __future__ import annotations

from PyQt6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QAction, QColor, QFontMetrics, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PyQt6.QtWidgets import (QButtonGroup, QFrame, QGridLayout, QHBoxLayout, QLabel, QLayout, QMenu,
                             QPushButton, QSizePolicy, QStackedWidget, QToolButton, QVBoxLayout,
                             QWidget, QWidgetAction)

from . import icons
from .style import T

LARGE, SMALL, ICON = range(3)
LARGE_H = 68
SMALL_H = 22


def _chevron(p: QPainter, x: float, y: float, color: QColor) -> None:
    pen = QPen(color, 1.0)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    path = QPainterPath()
    path.moveTo(x - 3, y - 1.5)
    path.lineTo(x, y + 1.5)
    path.lineTo(x + 3, y - 1.5)
    p.drawPath(path)


def _split_label(text: str, fm: QFontMetrics, max_w: int = 64) -> list[str]:
    """Libellé sur deux lignes au plus, coupé au mot le plus équilibré (comme Office)."""
    words = text.split()
    if len(words) <= 1 or fm.horizontalAdvance(text) <= max_w:
        return [text]
    best = None
    for i in range(1, len(words)):
        a, b = " ".join(words[:i]), " ".join(words[i:])
        w = max(fm.horizontalAdvance(a), fm.horizontalAdvance(b))
        if best is None or w < best[0]:
            best = (w, [a, b])
    return best[1]


class RibbonButton(QToolButton):
    """Bouton de ruban : grand (icône 32 + libellé dessous), petit (icône 16 +
    libellé à droite) ou icône seule ; avec menu simple ou bouton partagé."""

    def __init__(self, action: QAction | None = None, kind: int = SMALL, *, text: str | None = None,
                 icon_name: str | None = None, menu: QMenu | None = None, split: bool = False,
                 tooltip: str | None = None):
        super().__init__()
        self.kind = kind
        self._menu = menu
        self._split = split and action is not None
        self._menu_open = False
        self._hover_menu = False
        self._text_override = text
        self.setObjectName("RibbonButton")
        self.setMouseTracking(True)
        self.setAutoRaise(True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        if action is not None:
            self.setDefaultAction(action)
        if text is not None:
            self.setText(text)
        if icon_name is not None:
            self.setIcon(icons.icon(icon_name))
        if tooltip:
            self.setToolTip(tooltip)
        elif action is None and text:
            self.setToolTip(f"<b>{text}</b>")
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def set_menu(self, menu: QMenu) -> None:
        self._menu = menu

    # ---------------------------------------------------------------- géométrie
    def _label(self) -> str:
        return (self._text_override or self.text()).replace("&", "").replace("…", "")

    def sizeHint(self) -> QSize:  # noqa: N802
        fm = QFontMetrics(self.font())
        text = self._label()
        if self.kind == LARGE:
            lines = _split_label(text, fm)
            w = max(fm.horizontalAdvance(line) for line in lines)
            if self._menu is not None and len(lines) == 1:
                pass
            elif self._menu is not None:
                w = max(w, fm.horizontalAdvance(lines[-1]) + 12)
            return QSize(max(44, w + 12), LARGE_H)
        if self.kind == ICON:
            return QSize(24 + (12 if self._menu is not None else 0), SMALL_H)
        w = 4 + 16 + 6 + fm.horizontalAdvance(text) + 6
        if self._menu is not None:
            w += 12
        return QSize(w, SMALL_H)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return self.sizeHint()

    def _menu_zone(self) -> QRect:
        r = self.rect()
        if self._menu is None:
            return QRect()
        if not self._split:
            return r
        if self.kind == LARGE:
            return QRect(0, 38, r.width(), r.height() - 38)
        return QRect(r.width() - 13, 0, 13, r.height())

    # ---------------------------------------------------------------- souris
    def mouseMoveEvent(self, e):  # noqa: N802
        inside = self._menu_zone().contains(e.position().toPoint())
        if inside != self._hover_menu:
            self._hover_menu = inside
            self.update()
        super().mouseMoveEvent(e)

    def leaveEvent(self, e):  # noqa: N802
        self._hover_menu = False
        self.update()
        super().leaveEvent(e)

    def mousePressEvent(self, e):  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton and self._menu is not None and \
                self._menu_zone().contains(e.position().toPoint()):
            self._show_menu()
            return
        super().mousePressEvent(e)

    def _show_menu(self) -> None:
        self._menu_open = True
        self.update()
        self._menu.exec(self.mapToGlobal(QPoint(0, self.height())))
        self._menu_open = False
        self.update()

    # ---------------------------------------------------------------- dessin
    def paintEvent(self, e):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        enabled = self.isEnabled()
        hover = self.underMouse() and enabled
        down = self.isDown() or self._menu_open
        checked = self.isChecked()
        hover_c, press_c = QColor(T["hover"]), QColor(T["pressed"])
        radius = 4.0

        def fill(rect: QRectF, color: QColor) -> None:
            path = QPainterPath()
            path.addRoundedRect(rect, radius, radius)
            p.fillPath(path, color)
        if checked:
            fill(r, QColor(T["checked"]))
        if hover or down:
            if self._split and self._menu is not None:
                mz = QRectF(self._menu_zone())
                main = QRectF(r)
                if self.kind == LARGE:
                    main.setBottom(mz.top())
                else:
                    main.setRight(mz.left())
                fill(r, hover_c)
                fill(mz if (self._hover_menu or self._menu_open) else main, press_c)
            else:
                fill(r, press_c if down else hover_c)
        ink = QColor(T["text"] if enabled else T["text3"])
        mode = QIcon.Mode.Normal if enabled else QIcon.Mode.Disabled
        fm = QFontMetrics(self.font())
        p.setFont(self.font())
        if self.kind == LARGE:
            pm = self.icon().pixmap(QSize(32, 32), self.devicePixelRatioF(), mode)
            p.drawPixmap(QPointF((self.width() - 32) / 2, 3), pm)
            lines = _split_label(self._label(), fm)
            y = 38
            p.setPen(ink)
            for i, line in enumerate(lines):
                last = i == len(lines) - 1
                lw = fm.horizontalAdvance(line)
                extra = 10 if (self._menu is not None and last and len(lines) > 1) else 0
                x = (self.width() - lw - extra) / 2
                p.drawText(QPointF(x, y + fm.ascent()), line)
                if extra:
                    _chevron(p, x + lw + 6, y + fm.ascent() - fm.ascent() / 2 + 1, QColor(T["text2"]))
                y += fm.height()
            if self._menu is not None and len(lines) == 1:
                _chevron(p, self.width() / 2, y + 5, QColor(T["text2"]))
        else:
            pm = self.icon().pixmap(QSize(16, 16), self.devicePixelRatioF(), mode)
            x = 4 if self.kind == SMALL else (self.width() - (12 if self._menu else 0) - 16) / 2
            p.drawPixmap(QPointF(x, (self.height() - 16) / 2), pm)
            if self.kind == SMALL and self._label():
                p.setPen(ink)
                p.drawText(QPointF(26, (self.height() + fm.ascent() - fm.descent()) / 2), self._label())
            if self._menu is not None:
                _chevron(p, self.width() - 7, self.height() / 2 + 0.5, QColor(T["text2"]))
        p.end()


class RibbonGroup(QWidget):
    """Groupe du ruban : contenu, libellé en bas et éventuel lanceur ↘."""

    def __init__(self, title: str, launcher=None, launcher_tip: str | None = None):
        super().__init__()
        self.setObjectName("RibbonGroup")
        self.title = title
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        # Contenu complet du groupe ; quand la place manque, il est replié dans un bouton
        # (comme Office) et s'affiche dans une fenêtre surgissante.
        self.inner = QWidget()
        root.addWidget(self.inner)
        self._popup = QMenu(self)
        self._popup.setObjectName("RibbonGroupPopup")
        self._holder = QWidget()
        hl = QHBoxLayout(self._holder)
        hl.setContentsMargins(2, 2, 2, 2)
        act = QWidgetAction(self._popup)
        act.setDefaultWidget(self._holder)
        self._popup.addAction(act)
        self._popup.aboutToShow.connect(self._lend_content)
        self._popup.aboutToHide.connect(self._take_back_content)
        self.collapsed_btn = RibbonButton(None, LARGE, text=title, menu=self._popup,
                                          tooltip=f"<b>{title}</b>")
        self.collapsed_btn.hide()
        root.addWidget(self.collapsed_btn, 0, Qt.AlignmentFlag.AlignTop)
        self.collapsed = False
        outer = QVBoxLayout(self.inner)
        outer.setContentsMargins(4, 2, 6, 0)
        outer.setSpacing(0)
        self.content = QHBoxLayout()
        self.content.setSpacing(1)
        self.content.setContentsMargins(0, 0, 0, 0)
        outer.addLayout(self.content, 1)
        bottom = QHBoxLayout()
        bottom.setContentsMargins(0, 0, 0, 1)
        bottom.setSpacing(0)
        bottom.addStretch(1)
        label = QLabel(title)
        label.setObjectName("RibbonGroupLabel")
        bottom.addWidget(label)
        bottom.addStretch(1)
        if launcher is not None:
            b = QToolButton()
            b.setObjectName("RibbonLauncher")
            b.setIcon(icons.icon("dialog_launcher"))
            b.setIconSize(QSize(12, 12))
            b.setFixedSize(16, 16)
            b.setToolTip(launcher_tip or f"Plus d'options : {title}")
            b.clicked.connect(launcher)
            bottom.addWidget(b)
        outer.addLayout(bottom)

    # ---------------------------------------------------------------- repli
    def full_width(self) -> int:
        self.inner.layout().activate()
        return self.inner.sizeHint().width()

    def galleries(self) -> list["RibbonGallery"]:
        return self.inner.findChildren(RibbonGallery)

    def collapsed_width(self) -> int:
        return self.collapsed_btn.sizeHint().width() + 8

    def set_collapsed(self, collapsed: bool) -> None:
        if collapsed == self.collapsed:
            return
        if collapsed:
            self.full_width()
            first = next((b for b in self.inner.findChildren(RibbonButton) if not b.icon().isNull()), None)
            if first is not None:
                self.collapsed_btn.setIcon(first.icon())
        self.collapsed = collapsed
        self.inner.setVisible(not collapsed)
        self.collapsed_btn.setVisible(collapsed)

    def _lend_content(self) -> None:
        self._holder.layout().addWidget(self.inner)
        self.inner.show()
        for b in self.inner.findChildren(QToolButton):
            if not b.property("_closes_popup"):
                b.setProperty("_closes_popup", True)
                b.clicked.connect(lambda _=False: self._popup.isVisible() and self._popup.close())
        self._holder.adjustSize()

    def _take_back_content(self) -> None:
        self.layout().insertWidget(0, self.inner)
        self.inner.setVisible(not self.collapsed)

    def paintEvent(self, e):  # noqa: N802
        p = QPainter(self)
        p.setPen(QPen(QColor(T["separator"]), 1))
        x = self.width() - 0.5
        p.drawLine(QPointF(x, 8), QPointF(x, self.height() - 8))
        p.end()

    def add(self, w: QWidget, align=Qt.AlignmentFlag.AlignTop) -> QWidget:
        self.content.addWidget(w, 0, align)
        return w

    def large(self, action: QAction | None = None, **kw) -> RibbonButton:
        b = RibbonButton(action, LARGE, **kw)
        return self.add(b)

    def column(self, *items) -> QWidget:
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 1, 0, 0)
        lay.setSpacing(0)
        for it in items:
            if isinstance(it, QAction):
                it = RibbonButton(it, SMALL)
            lay.addWidget(it, 0, Qt.AlignmentFlag.AlignLeft)
        lay.addStretch(1)
        self.content.addWidget(box)
        return box

    @staticmethod
    def row(*items, spacing: int = 1) -> QWidget:
        box = QWidget()
        lay = QHBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(spacing)
        for it in items:
            if it is None:
                sep = QFrame()
                sep.setFixedSize(7, SMALL_H)
                lay.addWidget(sep)
                continue
            if isinstance(it, QAction):
                it = RibbonButton(it, ICON)
            lay.addWidget(it)
        lay.addStretch(1)
        return box


class RibbonGallery(QWidget):
    """Galerie intégrée (Styles rapides, Thèmes…) avec flèches et bouton « Plus »."""

    activated = pyqtSignal(object)

    def __init__(self, items: list[tuple[QPixmap, str, object]], cell: QSize = QSize(46, 46),
                 visible: int = 6, popup_cols: int = 7, section_titles: dict[int, str] | None = None):
        super().__init__()
        self.items = items
        self.cell = cell
        self.visible = visible
        self.popup_cols = popup_cols
        self.offset = 0
        self.hover = -1
        self.current = None
        self.section_titles = section_titles or {}
        self.max_visible = visible
        self.setMouseTracking(True)
        self.setFixedSize(cell.width() * visible + 18, LARGE_H - 2)

    def set_visible_count(self, n: int) -> None:
        """Comme Office : la galerie montre moins de vignettes quand la place manque."""
        n = max(2, min(n, self.max_visible))
        if n != self.visible:
            self.visible = n
            self.offset = min(self.offset, max(0, len(self.items) - n))
            self.setFixedSize(self.cell.width() * n + 18, LARGE_H - 2)

    def set_items(self, items) -> None:
        self.items = items
        self.offset = 0
        self.update()

    def set_current(self, data) -> None:
        self.current = data
        self.update()

    def _cell_rect(self, i: int) -> QRectF:
        top = (self.height() - self.cell.height()) / 2
        return QRectF(1 + (i - self.offset) * self.cell.width(), top, self.cell.width(), self.cell.height())

    def _strip(self) -> QRectF:
        return QRectF(self.width() - 16, 0, 16, self.height())

    def paintEvent(self, e):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor(T["surface"]))
        p.setPen(QPen(QColor(T["border"]), 1))
        p.drawRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5))
        for i in range(self.offset, min(len(self.items), self.offset + self.visible)):
            r = self._cell_rect(i)
            pm, _tip, data = self.items[i]
            if data == self.current and data is not None:
                p.fillRect(r.adjusted(1, 1, -1, -1), QColor(T["selection"]))
            if i == self.hover:
                p.setPen(QPen(QColor(T["accent"]), 1))
                p.drawRect(r.adjusted(1.5, 1.5, -1.5, -1.5))
            size = pm.deviceIndependentSize()
            p.drawPixmap(QPointF(r.center().x() - size.width() / 2, r.center().y() - size.height() / 2), pm)
        s = self._strip()
        p.setPen(QPen(QColor(T["border"]), 1))
        p.drawLine(QPointF(s.left() + 0.5, 0), QPointF(s.left() + 0.5, self.height()))
        third = self.height() / 3
        for k in range(3):
            cy = third * k + third / 2
            if k == 0:
                path = QPainterPath()
                path.moveTo(s.center().x() - 3, cy + 1.5)
                path.lineTo(s.center().x(), cy - 1.5)
                path.lineTo(s.center().x() + 3, cy + 1.5)
            else:
                path = QPainterPath()
                path.moveTo(s.center().x() - 3, cy - 1.5)
                path.lineTo(s.center().x(), cy + 1.5)
                path.lineTo(s.center().x() + 3, cy - 1.5)
                if k == 2:
                    path.moveTo(s.center().x() - 3, cy - 4)
                    path.lineTo(s.center().x() + 3, cy - 4)
            p.setPen(QPen(QColor(T["text2"]), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(path)
        p.end()

    def _index_at(self, pos: QPointF) -> int:
        for i in range(self.offset, min(len(self.items), self.offset + self.visible)):
            if self._cell_rect(i).contains(pos):
                return i
        return -1

    def mouseMoveEvent(self, e):  # noqa: N802
        i = self._index_at(e.position())
        if i != self.hover:
            self.hover = i
            self.setToolTip(self.items[i][1] if i >= 0 else "")
            self.update()

    def leaveEvent(self, e):  # noqa: N802
        self.hover = -1
        self.update()

    def mousePressEvent(self, e):  # noqa: N802
        pos = e.position()
        s = self._strip()
        if s.contains(pos):
            third = self.height() / 3
            if pos.y() < third:
                self.offset = max(0, self.offset - self.visible)
            elif pos.y() < 2 * third:
                if self.offset + self.visible < len(self.items):
                    self.offset += self.visible
            else:
                self.show_popup()
            self.update()
            return
        i = self._index_at(pos)
        if i >= 0:
            self.activated.emit(self.items[i][2])

    def show_popup(self) -> None:
        menu = QMenu(self)
        holder = QWidget()
        grid = QGridLayout(holder)
        grid.setContentsMargins(6, 6, 6, 6)
        grid.setSpacing(2)
        row = 0
        col = 0
        for i, (pm, tip, data) in enumerate(self.items):
            if i in self.section_titles:
                if col:
                    row += 1
                    col = 0
                lab = QLabel(self.section_titles[i])
                lab.setStyleSheet(f"font-weight: 600; color: {T['text2']}; padding: 4px 0 2px 0;")
                grid.addWidget(lab, row, 0, 1, self.popup_cols)
                row += 1
            b = QToolButton()
            b.setIcon(QIcon(pm))
            b.setIconSize(pm.deviceIndependentSize().toSize())
            b.setFixedSize(self.cell)
            b.setAutoRaise(True)
            b.setToolTip(tip)
            b.clicked.connect(lambda _=False, d=data: (menu.close(), self.activated.emit(d)))
            grid.addWidget(b, row, col)
            col += 1
            if col >= self.popup_cols:
                col = 0
                row += 1
        act = QWidgetAction(menu)
        act.setDefaultWidget(holder)
        menu.addAction(act)
        menu.exec(self.mapToGlobal(QPoint(0, 0)))


class RibbonPage(QWidget):
    """Page du ruban qui s'adapte à la largeur : les groupes de droite se replient d'abord."""

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(80, LARGE_H)

    def groups(self) -> list[RibbonGroup]:
        lay = self.layout()
        return [lay.itemAt(i).widget() for i in range(lay.count())
                if isinstance(lay.itemAt(i).widget(), RibbonGroup)]

    def fit(self) -> None:
        groups = self.groups()
        if not groups:
            return
        avail = self.width()
        for g in groups:
            g.set_collapsed(False)
            for gal in g.galleries():
                gal.set_visible_count(gal.max_visible)
        widths = [g.full_width() for g in groups]
        total = sum(widths)
        # 1) les galeries rétrécissent (de droite à gauche), 2) puis les groupes se replient.
        for i in range(len(groups) - 1, -1, -1):
            for gal in groups[i].galleries():
                while total > avail and gal.visible > 3:
                    gal.set_visible_count(gal.visible - 1)
                    total -= gal.cell.width()
                    widths[i] -= gal.cell.width()
        collapse = [False] * len(groups)
        for i in range(len(groups) - 1, -1, -1):
            if total <= avail:
                break
            collapse[i] = True
            total += groups[i].collapsed_width() - widths[i]
        for g, c in zip(groups, collapse):
            g.set_collapsed(c)

    def resizeEvent(self, e):  # noqa: N802
        super().resizeEvent(e)
        self.fit()

    def showEvent(self, e):  # noqa: N802
        super().showEvent(e)
        self.fit()


class Ribbon(QWidget):
    """Barre d'onglets dans la couleur de l'application + corps du ruban."""

    fileRequested = pyqtSignal()
    collapsedChanged = pyqtSignal(bool)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("Ribbon")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.tabbar = QWidget()
        self.tabbar.setObjectName("RibbonTabBar")
        self.tabbar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.tabbar.setFixedHeight(36)
        # Les onglets peuvent être rognés sur une fenêtre étroite, comme dans Office : ils
        # n'imposent pas de largeur minimale à la fenêtre (le ruban replie déjà ses groupes).
        self.tabbar.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        tl = QHBoxLayout(self.tabbar)
        tl.setContentsMargins(0, 0, 6, 0)
        tl.setSpacing(0)
        file_btn = QPushButton("Fichier")
        file_btn.setObjectName("FileTab")
        file_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        file_btn.clicked.connect(self.fileRequested)
        tl.addWidget(file_btn)
        self._tabs_layout = QHBoxLayout()
        self._tabs_layout.setSpacing(0)
        tl.addLayout(self._tabs_layout)
        tl.addStretch(1)
        self.tools = QWidget()
        self.tools.setObjectName("TabBarTools")
        self.tools_layout = QHBoxLayout(self.tools)
        self.tools_layout.setContentsMargins(0, 0, 0, 0)
        self.tools_layout.setSpacing(2)
        tl.addWidget(self.tools)
        lay.addWidget(self.tabbar)
        self.body = QWidget()
        self.body.setObjectName("RibbonBody")
        self.body.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.body.setFixedHeight(LARGE_H + 34)
        outer = QHBoxLayout(self.body)
        outer.setContentsMargins(6, 2, 6, 6)
        card = QWidget()
        card.setObjectName("RibbonCard")
        card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        outer.addWidget(card)
        bl = QHBoxLayout(card)
        bl.setContentsMargins(4, 3, 2, 2)
        bl.setSpacing(0)
        self.stack = QStackedWidget()
        bl.addWidget(self.stack, 1)
        self.collapse_btn = QToolButton()
        self.collapse_btn.setObjectName("RibbonCollapse")
        self.collapse_btn.setIcon(icons.icon("chevron_up"))
        self.collapse_btn.setIconSize(QSize(14, 14))
        self.collapse_btn.setToolTip("Réduire le ruban (Ctrl+F1)")
        self.collapse_btn.clicked.connect(lambda: self.set_collapsed(True))
        bl.addWidget(self.collapse_btn, 0, Qt.AlignmentFlag.AlignBottom)
        lay.addWidget(self.body)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self._collapsed = False
        self.pages: dict[str, QWidget] = {}
        self.tab_buttons: dict[str, QPushButton] = {}

    def add_page(self, title: str) -> QHBoxLayout:
        btn = QPushButton(title)
        btn.setObjectName("RibbonTab")
        btn.setCheckable(True)
        idx = self.stack.count()
        btn.clicked.connect(lambda _=False, i=idx: self._select(i))
        btn.installEventFilter(self)
        self.group.addButton(btn, idx)
        self._tabs_layout.addWidget(btn)
        self.tab_buttons[title] = btn
        page = RibbonPage()
        pl = QHBoxLayout(page)
        pl.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(0)
        self.stack.addWidget(page)
        self.pages[title] = page
        if idx == 0:
            btn.setChecked(True)
        return pl

    def finish_pages(self) -> None:
        for i in range(self.stack.count()):
            self.stack.widget(i).layout().addStretch(1)

    def set_tab_visible(self, title: str, visible: bool) -> None:
        """Onglet contextuel (ex. « Diagramme de flux interfonctionnel ») affiché à la demande."""
        btn = self.tab_buttons.get(title)
        if btn is None or btn.isHidden() != visible:
            return
        btn.setVisible(visible)
        if not visible and self.stack.currentWidget() is self.pages[title]:
            self.select_page(next(iter(self.pages)))

    def select_page(self, title: str) -> None:
        page = self.pages.get(title)
        if page is not None:
            i = self.stack.indexOf(page)
            self.group.button(i).setChecked(True)
            self._select(i)

    def _select(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        if self._collapsed:
            self.set_collapsed(False)

    def eventFilter(self, obj, ev):  # noqa: N802
        if ev.type() == ev.Type.MouseButtonDblClick:
            self.set_collapsed(not self._collapsed)
            return True
        return super().eventFilter(obj, ev)

    def set_collapsed(self, collapsed: bool) -> None:
        self._collapsed = collapsed
        self.body.setVisible(not collapsed)
        self.collapsedChanged.emit(collapsed)

    def is_collapsed(self) -> bool:
        return self._collapsed
