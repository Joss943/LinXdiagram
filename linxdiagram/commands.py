"""Commandes annulables (Ctrl+Z / Ctrl+Y).

Les commandes manipulent des identifiants et des états sérialisés plutôt que
des pointeurs vers des objets graphiques : un objet supprimé puis restauré est
reconstruit à l'identique depuis son état.
"""

from __future__ import annotations

import time

from PyQt6.QtGui import QUndoCommand


def _shapes_first(states):
    return sorted(states, key=lambda s: s.get("kind") == "connector")


class AddItemsCommand(QUndoCommand):
    def __init__(self, scene, states: list[dict], text: str, select: bool = True):
        super().__init__(text)
        self.scene = scene
        self.states = _shapes_first(states)
        self.select = select

    def redo(self):
        self.scene.doc.show_page(self.scene)
        items = [self.scene.add_item_from_state(s) for s in self.states]
        if self.select:
            self.scene.select_items([it for it in items if it.kind == "shape" or len(items) == 1])
        self.scene.update_scene_rect()

    def undo(self):
        self.scene.doc.show_page(self.scene)
        for s in reversed(self.states):
            self.scene.remove_item_by_id(s["id"])


class RemoveItemsCommand(QUndoCommand):
    def __init__(self, scene, states: list[dict], text: str):
        super().__init__(text)
        self.scene = scene
        self.states = _shapes_first(states)

    def redo(self):
        self.scene.doc.show_page(self.scene)
        for s in reversed(self.states):
            self.scene.remove_item_by_id(s["id"])

    def undo(self):
        self.scene.doc.show_page(self.scene)
        self.scene.select_items([self.scene.add_item_from_state(s) for s in self.states])


class StateCommand(QUndoCommand):
    """Bascule un ensemble d'objets entre deux états (déplacement, style, texte…)."""

    _ID = 4242

    def __init__(self, scene, before: dict, after: dict, text: str, merge_key: str | None = None):
        super().__init__(text)
        self.scene = scene
        self.before = before
        self.after = after
        self.merge_key = merge_key
        self._skip = True

    def id(self):  # noqa: A003 (API Qt)
        return self._ID if self.merge_key else -1

    def mergeWith(self, other):  # noqa: N802
        if not isinstance(other, StateCommand) or other.merge_key != self.merge_key \
                or other.scene is not self.scene or set(other.after) != set(self.after):
            return False
        self.after = other.after
        return True

    def _apply(self, states: dict) -> None:
        self.scene.doc.show_page(self.scene)
        ordered = _shapes_first(states.values())
        for st in ordered:
            item = self.scene.item_by_id(st["id"])
            if item is not None:
                item.set_state(st)
        self.scene.refresh_connectors()
        self.scene.apply_layers()
        self.scene.update_scene_rect()
        self.scene.selection_info_changed()

    def redo(self):
        if self._skip:
            self._skip = False
            return
        self._apply(self.after)

    def undo(self):
        self._apply(self.before)


class PageCommand(QUndoCommand):
    """Ajout, suppression, renommage ou mise en page d'une page."""

    def __init__(self, doc, text: str, *, add=None, remove=None, index: int = -1,
                 scene=None, before: dict | None = None, after: dict | None = None):
        super().__init__(text)
        self.doc = doc
        self.add = add
        self.remove = remove
        self.index = index
        self.scene = scene
        self.before = before
        self.after = after

    def redo(self):
        if self.add is not None:
            self.doc.insert_page(self.index, self.add)
        elif self.remove is not None:
            self.index = self.doc.pages.index(self.remove)
            self.doc.take_page(self.remove)
        elif self.scene is not None:
            self.scene.set_page_props(self.after)
            self.doc.show_page(self.scene)

    def undo(self):
        if self.add is not None:
            self.doc.take_page(self.add)
        elif self.remove is not None:
            self.doc.insert_page(self.index, self.remove)
        elif self.scene is not None:
            self.scene.set_page_props(self.before)
            self.doc.show_page(self.scene)


class DocSettingsCommand(QUndoCommand):
    def __init__(self, doc, before: dict, after: dict, text: str):
        super().__init__(text)
        self.doc = doc
        self.before = before
        self.after = after

    def redo(self):
        self.doc.apply_settings(self.after)

    def undo(self):
        self.doc.apply_settings(self.before)


class ReorderPagesCommand(QUndoCommand):
    """Nouvel ordre des pages (onglets glissés ou « Réorganiser les pages »)."""

    _ID = 4343

    def __init__(self, doc, before: list, after: list, text: str = "Réorganiser les pages"):
        super().__init__(text)
        self.doc = doc
        self.before = list(before)
        self.after = list(after)
        self.when = time.monotonic()

    def id(self):  # noqa: A003 (API Qt)
        return self._ID

    def mergeWith(self, other):  # noqa: N802
        # Un même glisser d'onglet produit plusieurs déplacements : une seule annulation.
        if (not isinstance(other, ReorderPagesCommand) or other.doc is not self.doc
                or other.when - self.when > 2.0):
            return False
        self.after = list(other.after)
        self.when = other.when
        return True

    def redo(self):
        self.doc.set_page_order(self.after)

    def undo(self):
        self.doc.set_page_order(self.before)
