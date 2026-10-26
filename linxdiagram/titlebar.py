"""Barre de titre façon Office : barre d'outils Accès rapide, titre du document,
zone « Rechercher (Alt+Q) » et boutons de fenêtre. La fenêtre est sans cadre ;
son déplacement et son redimensionnement passent par le gestionnaire de fenêtres
(startSystemMove / startSystemResize), ce qui fonctionne sous Wayland et X11."""

from __future__ import annotations

import unicodedata

from PyQt6.QtCore import QEvent, QObject, QPoint, QRect, QSize, Qt
from PyQt6.QtGui import QAction, QCursor, QStandardItem, QStandardItemModel
from PyQt6.QtWidgets import (QApplication, QCompleter, QHBoxLayout, QLabel, QLineEdit, QMenu,
                             QToolButton, QWidget)

from . import icons

MARGIN = 6


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFD", text.lower())
    return "".join(ch for ch in text if unicodedata.category(ch) != "Mn")


class CommandSearch(QLineEdit):
    """« Rechercher (Alt+Q) » : trouve une commande par son nom et l'exécute."""

    def __init__(self, window):
        super().__init__()
        self.win = window
        self.setObjectName("CommandSearch")
        self.setPlaceholderText("Rechercher (Alt+Q)")
        # 320 px comme Office, mais la zone rétrécit sur un petit écran au lieu d'élargir la fenêtre.
        self.setMinimumWidth(140)
        self.setMaximumWidth(320)
        self.setClearButtonEnabled(True)
        self.addAction(icons.icon("search", "#ffffff"), QLineEdit.ActionPosition.LeadingPosition)
        self.model = QStandardItemModel(self)
        self.completer = QCompleter(self.model, self)
        self.completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self.completer.setCompletionRole(Qt.ItemDataRole.UserRole + 1)
        self.completer.setMaxVisibleItems(12)
        self.completer.activated.connect(self._run)
        self.setCompleter(self.completer)
        self.returnPressed.connect(lambda: self._run(self.text()))
        self._entries: dict[str, object] = {}

    def set_entries(self, entries: list[tuple[str, object, object]]) -> None:
        """entries : (libellé, icône, cible) ; la cible est une QAction ou une fonction."""
        self.model.clear()
        self._entries.clear()
        for label, ic, target in entries:
            it = QStandardItem(label)
            if ic is not None:
                it.setIcon(ic)
            it.setData(f"{label} | {_norm(label)}", Qt.ItemDataRole.UserRole + 1)
            self.model.appendRow(it)
            self._entries[label] = target
        self._entries_norm = {_norm(k): v for k, v in self._entries.items()}

    def _run(self, text: str) -> None:
        label = text.split(" | ")[0]
        target = self._entries.get(label) or self._entries_norm.get(_norm(label))
        if target is None:
            for k, v in self._entries_norm.items():
                if _norm(label) and _norm(label) in k:
                    target = v
                    break
        self.clear()
        self.clearFocus()
        if isinstance(target, QAction):
            if target.isEnabled():
                target.trigger()
        elif callable(target):
            target()


class TitleBar(QWidget):
    def __init__(self, window, quick_actions: list[QAction], undo_menu: QMenu | None = None):
        super().__init__(window)
        self.win = window
        self.setObjectName("TitleBar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(38)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 0, 0, 0)
        lay.setSpacing(0)
        logo = QLabel()
        logo.setPixmap(icons.app_icon().pixmap(20, 20))
        lay.addWidget(logo)
        lay.addSpacing(8)
        self.qat: list[QToolButton] = []
        for act in quick_actions:
            b = QToolButton()
            b.setDefaultAction(act)
            b.setIcon(icons.icon(act.property("icon_name") or "", "#ffffff"))
            b.setIconSize(QSize(16, 16))
            b.setFixedSize(32, 38)
            if act.property("icon_name") == "undo" and undo_menu is not None:
                b.setMenu(undo_menu)
                b.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
                b.setFixedSize(42, 38)
            act.changed.connect(lambda b=b, a=act: b.setIcon(icons.icon(a.property("icon_name") or "", "#ffffff")))
            lay.addWidget(b)
            self.qat.append(b)
        lay.addStretch(1)
        self.title = QLabel()
        self.title.setObjectName("Title")
        self.title.setTextFormat(Qt.TextFormat.PlainText)
        self.title.setMinimumWidth(140)
        lay.addWidget(self.title)
        lay.addSpacing(14)
        self.search = CommandSearch(window)
        self.search.setFixedHeight(27)
        lay.addWidget(self.search)
        lay.addStretch(1)
        self.btn_min = self._win_button("win_min", "Réduire", window.showMinimized)
        self.btn_max = self._win_button("win_max", "Agrandir", self._toggle_max)
        self.btn_close = self._win_button("win_close", "Fermer", window.close)
        self.btn_close.setObjectName("WinClose")
        for b in (self.btn_min, self.btn_max, self.btn_close):
            lay.addWidget(b)

    def _win_button(self, icon_name: str, tip: str, slot) -> QToolButton:
        b = QToolButton()
        b.setIcon(icons.icon(icon_name, "#ffffff"))
        b.setIconSize(QSize(16, 16))
        b.setFixedSize(42, 38)
        b.setToolTip(tip)
        b.clicked.connect(slot)
        return b

    def _toggle_max(self) -> None:
        if self.win.isMaximized():
            self.win.showNormal()
        else:
            self.win.showMaximized()

    def update_state(self) -> None:
        maxed = self.win.isMaximized()
        self.btn_max.setIcon(icons.icon("win_restore" if maxed else "win_max", "#ffffff"))
        self.btn_max.setToolTip("Niveau inférieur" if maxed else "Agrandir")

    def set_title(self, text: str) -> None:
        self.title.setText(text)

    def mousePressEvent(self, e):  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton:
            handle = self.win.windowHandle()
            if handle is not None and handle.startSystemMove():
                e.accept()
                return
        super().mousePressEvent(e)

    def mouseDoubleClickEvent(self, e):  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton:
            self._toggle_max()


class FramelessResizer(QObject):
    """Redimensionnement d'une fenêtre sans cadre par ses bords."""

    def __init__(self, window):
        super().__init__(window)
        self.win = window
        self._override = False
        window.winId()  # crée la QWindow : on filtre ses seuls événements souris
        window.windowHandle().installEventFilter(self)

    def _edges(self, gpos: QPoint) -> Qt.Edge:
        if self.win.isMaximized() or self.win.isFullScreen():
            return Qt.Edge(0)
        g: QRect = self.win.frameGeometry()
        edges = Qt.Edge(0)
        if abs(gpos.x() - g.left()) <= MARGIN:
            edges |= Qt.Edge.LeftEdge
        elif abs(gpos.x() - g.right()) <= MARGIN:
            edges |= Qt.Edge.RightEdge
        if abs(gpos.y() - g.top()) <= MARGIN:
            edges |= Qt.Edge.TopEdge
        elif abs(gpos.y() - g.bottom()) <= MARGIN:
            edges |= Qt.Edge.BottomEdge
        return edges

    @staticmethod
    def _cursor(edges) -> Qt.CursorShape | None:
        E = Qt.Edge
        if edges in (E.LeftEdge | E.TopEdge, E.RightEdge | E.BottomEdge):
            return Qt.CursorShape.SizeFDiagCursor
        if edges in (E.RightEdge | E.TopEdge, E.LeftEdge | E.BottomEdge):
            return Qt.CursorShape.SizeBDiagCursor
        if edges in (E.LeftEdge, E.RightEdge):
            return Qt.CursorShape.SizeHorCursor
        if edges in (E.TopEdge, E.BottomEdge):
            return Qt.CursorShape.SizeVerCursor
        return None

    def _set_override(self, cursor) -> None:
        if cursor is None and self._override:
            QApplication.restoreOverrideCursor()
            self._override = False
        elif cursor is not None:
            if self._override:
                QApplication.changeOverrideCursor(QCursor(cursor))
            else:
                QApplication.setOverrideCursor(QCursor(cursor))
                self._override = True

    def eventFilter(self, obj, ev):  # noqa: N802
        t = ev.type()
        if t == QEvent.Type.Leave:
            self._set_override(None)
            return False
        if t not in (QEvent.Type.MouseMove, QEvent.Type.MouseButtonPress):
            return False
        if t == QEvent.Type.MouseMove and ev.buttons() != Qt.MouseButton.NoButton:
            return False
        gpos = QCursor.pos()
        edges = self._edges(gpos)
        if t == QEvent.Type.MouseButtonPress:
            if edges and ev.button() == Qt.MouseButton.LeftButton:
                handle = self.win.windowHandle()
                if handle is not None and handle.startSystemResize(edges):
                    self._set_override(None)
                    return True
            return False
        self._set_override(self._cursor(edges) if edges else None)
        return False
