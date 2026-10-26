"""Document : pages, réglages, pile d'annulation, enregistrement."""

from __future__ import annotations

import secrets

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui import QUndoStack

from . import fields, fileformat
from .scene import DiagramScene


class Document(QObject):
    pagesChanged = pyqtSignal()
    pageShown = pyqtSignal(object)
    settingsChanged = pyqtSignal()
    toolChanged = pyqtSignal(str)
    formatPainterDone = pyqtSignal()

    def __init__(self, data: dict | None = None, parent: QObject | None = None):
        super().__init__(parent)
        self.undo_stack = QUndoStack(self)
        self.undo_stack.setUndoLimit(1000)
        self.path: str | None = None
        self.password: str | None = None
        self.uid = secrets.token_hex(8)
        self.tool = "select"
        self.quick_shape: str | None = None
        self.imported_from: str | None = None
        data = data or {"settings": {}, "properties": {}, "pages": [fileformat.default_page()]}
        self.settings = fileformat.clean_settings(data.get("settings"))
        self.settings["autoconnect"] = True
        self.properties = fileformat.clean_properties(data.get("properties"))
        self.pages: list[DiagramScene] = [DiagramScene(self, p) for p in data["pages"]]
        self.undo_stack.indexChanged.connect(self._refresh_dependents)
        self.pagesChanged.connect(self.refresh_fields)
        self.refresh_fields()
        self.undo_stack.setClean()

    # -------------------------------------------------------------- arrière-plans
    def _refresh_dependents(self, _index: int = 0) -> None:
        """Après chaque modification, les pages qui affichent un arrière-plan sont redessinées.

        On s'appuie sur la pile d'annulation plutôt que sur QGraphicsScene.changed : le rendu
        d'un arrière-plan modifie temporairement ses étiquettes de champs, ce qui relancerait
        sinon le dessin sans fin."""
        for p in self.pages:
            if p.background_scene() is not None:
                p.update()

    def refresh_fields(self) -> None:
        """Recalcule les champs affichés (numéros de page, propriétés du document…)."""
        for p in self.pages:
            for it in p.all_items():
                if fields.has_fields(it.text):
                    it.layout_label()
                    it.update()

    def background_pages(self) -> list[DiagramScene]:
        return [p for p in self.pages if p.page_kind == "background"]

    def printable_pages(self) -> list[DiagramScene]:
        """Pages imprimées et exportées : les arrière-plans n'apparaissent qu'à travers les pages
        de premier plan qui les utilisent, comme dans Visio."""
        return [p for p in self.pages if p.page_kind == "foreground"] or list(self.pages)

    # -------------------------------------------------------------- état
    def is_modified(self) -> bool:
        return not self.undo_stack.isClean()

    def set_tool(self, tool: str) -> None:
        if tool == self.tool:
            return
        self.tool = tool
        for p in self.pages:
            if p.editing_item is not None:
                p.editing_item.finish_edit()
            p.clear_hover()
        self.toolChanged.emit(tool)

    def show_page(self, scene: DiagramScene) -> None:
        self.pageShown.emit(scene)

    def apply_settings(self, settings: dict) -> None:
        self.settings.update(settings)
        for p in self.pages:
            p.update()
        self.settingsChanged.emit()

    # -------------------------------------------------------------- pages
    def insert_page(self, index: int, scene: DiagramScene) -> None:
        index = max(0, min(index, len(self.pages)))
        self.pages.insert(index, scene)
        self.pagesChanged.emit()
        self.show_page(scene)

    def take_page(self, scene: DiagramScene) -> None:
        if scene in self.pages and len(self.pages) > 1:
            self.pages.remove(scene)
            self.pagesChanged.emit()

    def unique_page_name(self, base: str = "Page") -> str:
        names = {p.page_name for p in self.pages}
        n = len(self.pages) + 1
        while f"{base}-{n}" in names:
            n += 1
        return f"{base}-{n}"

    def make_page(self, like: DiagramScene | None = None, data: dict | None = None) -> DiagramScene:
        page = data or fileformat.default_page(self.unique_page_name())
        if like is not None and data is None:
            page["width"], page["height"] = like.page_w, like.page_h
        return DiagramScene(self, page)

    # -------------------------------------------------------------- sérialisation
    def to_dict(self) -> dict:
        settings = {k: v for k, v in self.settings.items() if k != "autoconnect"}
        return {"settings": settings, "properties": dict(self.properties),
                "pages": [p.to_dict() for p in self.pages]}

    def save(self, path: str) -> None:
        fileformat.save_file(path, self.to_dict(), self.password)
        self.path = path
        self.imported_from = None
        self.undo_stack.setClean()
