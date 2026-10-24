"""Conteneurs Visio, Favoris (Mes formes) et repères dans les fichiers .vsdx."""

import base64
import json
import os
import re
import tempfile
import unittest
import zipfile

from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtTest import QTest

from tests.helpers import qapp

from linxdiagram import app as appmod, favorites, stencils, vsdx
from linxdiagram.document import Document

L = Qt.MouseButton.LeftButton
NOMOD = Qt.KeyboardModifier.NoModifier


class ContainerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = qapp()
        appmod.apply_theme(cls.app, False)
        cls.ctx = appmod.AppContext(cls.app)
        cls.ctx.favorites = favorites.Favorites(os.path.join(tempfile.mkdtemp(), "favoris.json"))

    def setUp(self):
        self.w = self.ctx.new_window()
        self.w.resize(1400, 900)
        self.w.hide_backstage()
        self.app.processEvents()
        self.view, self.sc = self.w.view, self.w.scene()
        self.vp = self.view.viewport()
        self.view.set_zoom(1.0)
        self.view.centerOn(QPointF(400, 400))
        self.app.processEvents()

    def tearDown(self):
        self.w.doc.undo_stack.setClean()
        self.w.close()

    def _wrap(self):
        a = self.sc.add_shape("flow.process", QPointF(300, 300))
        b = self.sc.add_shape("flow.decision", QPointF(450, 330))
        self.sc.select_items([a, b])
        self.w._insert("basic.container")
        c = self.sc.single_selected
        return a, b, c

    def test_insert_around_selection_and_tab(self):
        a, b, c = self._wrap()
        self.assertTrue(self.sc.is_plain_container(c))
        self.assertEqual({s.id for s in self.sc.container_members(c)}, {a.id, b.id})
        self.assertLess(c.zValue(), min(a.zValue(), b.zValue()))
        self.app.processEvents()
        self.assertFalse(self.w.ribbon.tab_buttons["Format du conteneur"].isHidden())
        self.sc.clearSelection()
        self.app.processEvents()
        self.assertTrue(self.w.ribbon.tab_buttons["Format du conteneur"].isHidden())

    def test_dragging_container_carries_members(self):
        a, b, c = self._wrap()
        self.sc.clearSelection()
        before = {s.id: QPointF(s.pos()) for s in (a, b)}
        header = c.scene_box().topLeft() + QPointF(20, 6)
        start = self.view.mapFromScene(header)
        end = start + QPoint(80, 50)
        QTest.mousePress(self.vp, L, NOMOD, start)
        for i in range(1, 9):
            QTest.mouseMove(self.vp, start + (end - start) * i / 8)
            self.app.processEvents()
        QTest.mouseRelease(self.vp, L, NOMOD, end)
        self.app.processEvents()
        moved = c.pos() - QPointF(0, 0)
        for s in (a, b):
            d = s.pos() - before[s.id]
            self.assertGreater(abs(d.x()), 40, s.type_id)
        self.w.doc.undo_stack.undo()
        for s in (a, b):
            self.assertAlmostEqual(s.pos().x(), before[s.id].x(), places=3)
        self.assertIsNotNone(moved)

    def test_fit_style_select_disband_and_vsdx(self):
        a, b, c = self._wrap()
        self.sc.modify([c], lambda _i, st: st.update(w=st["w"] + 300, h=st["h"] + 200), "agrandir")
        big = c.scene_box()
        self.w.a["container_fit"].trigger()
        self.assertLess(c.scene_box().width(), big.width())
        for s in (a, b):
            self.assertTrue(c.scene_box().contains(s.scene_box()))
        self.w._container_style("container.band")
        self.assertEqual(c.type_id, "container.band")
        self.assertEqual(c.style["line"], stencils.get("container.band").style["line"])
        path = os.path.join(tempfile.mkdtemp(), "conteneur.vsdx")
        vsdx.export_vsdx(self.w.doc, path)
        with zipfile.ZipFile(path) as z:
            xml = z.read("visio/pages/page1.xml").decode()
        self.assertIn('N="msvStructureType"', xml)
        self.assertTrue(re.search(r'DEPENDSON\(1,Sheet\.\d+!SheetRef\(\),Sheet\.\d+!SheetRef\(\)\)', xml))
        self.w.a["container_select"].trigger()
        self.assertEqual({s.id for s in self.sc.selected_shapes()}, {a.id, b.id})
        self.sc.select_items([c])
        self.w.a["container_disband"].trigger()
        self.assertIsNone(self.sc.item_by_id(c.id))
        self.assertEqual(len(self.sc.shapes()), 2)

    def test_favorites_add_insert_and_persist(self):
        favs = self.ctx.favorites
        n = len(favs.items)
        a = self.sc.add_shape("flow.process", QPointF(200, 200))
        self.sc.modify([a], lambda _i, st: st.update(text="Valider"), "t")
        self.sc.select_items([a])
        from unittest import mock
        with mock.patch("PyQt6.QtWidgets.QInputDialog.getText", return_value=("Valider", True)):
            self.w.add_to_favorites()
        self.assertEqual(len(favs.items), n + 1)
        self.assertEqual(self.w.shapes_panel.current, favorites.CATEGORY)
        names = [self.w.shapes_panel.list.item(i).text() for i in range(self.w.shapes_panel.list.count())]
        self.assertIn("Valider", names)
        self.w.insert_favorite(n, QPointF(600, 500))
        new = [s for s in self.sc.shapes() if s is not a]
        self.assertEqual(len(new), 1)
        self.assertEqual(new[0].text, "Valider")
        self.assertAlmostEqual(new[0].scene_box().center().x(), 600, delta=1)
        again = favorites.Favorites(favs.path)
        self.assertEqual(again.items[n][0], "Valider")

    def test_tampered_favorites_file_is_ignored(self):
        path = os.path.join(tempfile.mkdtemp(), "favoris.json")
        bad = base64.b64encode(b'{"format":"autre"}').decode()
        with open(path, "w") as f:
            json.dump({"items": [{"name": "x", "clip": bad}, {"name": "y", "clip": "!!"}, "z"]}, f)
        self.assertEqual(favorites.Favorites(path).items, [])


class GuidesVsdxTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = qapp()

    def test_guides_roundtrip(self):
        doc = Document()
        doc.pages[0].add_guide("v", 250.0)
        doc.pages[0].add_guide("h", 400.0)
        path = os.path.join(tempfile.mkdtemp(), "reperes.vsdx")
        vsdx.export_vsdx(doc, path)
        data, _w = vsdx.import_vsdx(path)
        got = sorted((g["o"], round(g["pos"], 1)) for g in data["pages"][0]["guides"])
        self.assertEqual(got, [("h", 400.0), ("v", 250.0)])


if __name__ == "__main__":
    unittest.main()
