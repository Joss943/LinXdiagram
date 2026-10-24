"""Tests d'interface : on simule souris et clavier comme un utilisateur de Visio."""

import os
import tempfile
import unittest

from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtTest import QTest

from tests.helpers import qapp

from linxdiagram import app as appmod, fileformat, templates
from linxdiagram.document import Document
from linxdiagram.items import ShapeItem

L = Qt.MouseButton.LeftButton
NOMOD = Qt.KeyboardModifier.NoModifier


class UiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = qapp()
        appmod.apply_theme(cls.app, False)
        cls.ctx = appmod.AppContext(cls.app)

    def setUp(self):
        self.w = self.ctx.new_window()
        self.w.resize(1400, 900)
        self.w.hide_backstage()
        self.app.processEvents()
        self.view = self.w.view
        self.sc = self.w.scene()
        self.vp = self.view.viewport()
        self.view.set_zoom(1.0)
        self.view.centerOn(QPointF(300, 300))
        self.app.processEvents()

    def tearDown(self):
        self.w.doc.undo_stack.setClean()
        self.w.close()
        self.app.processEvents()

    def P(self, x, y):
        return self.view.mapFromScene(QPointF(x, y))

    def drag(self, a: QPoint, b: QPoint, steps=8):
        QTest.mousePress(self.vp, L, NOMOD, a)
        for i in range(1, steps + 1):
            QTest.mouseMove(self.vp, QPoint(a.x() + (b.x() - a.x()) * i // steps,
                                            a.y() + (b.y() - a.y()) * i // steps))
            self.app.processEvents()
        QTest.mouseRelease(self.vp, L, NOMOD, b)
        self.app.processEvents()

    def test_move_resize_rotate_with_undo(self):
        a = self.sc.add_shape("flow.process", QPointF(200, 200))
        c0 = a.pos()
        self.sc.clearSelection()
        QTest.mouseClick(self.vp, L, NOMOD, self.P(c0.x() - 30, c0.y()))
        self.assertIs(self.sc.single_selected, a)
        n = self.w.doc.undo_stack.count()
        self.drag(self.P(c0.x() - 30, c0.y()), self.P(c0.x() + 70, c0.y() + 40))
        self.assertGreater(a.pos().x(), c0.x() + 60)
        self.assertEqual(self.w.doc.undo_stack.count(), n + 1)
        self.assertEqual(self.w.doc.undo_stack.undoText(), "Déplacer")
        w0, h0 = a.w, a.h
        br = a.mapToScene(a.handle_points()[4])
        self.drag(self.P(br.x(), br.y()), self.P(br.x() + 60, br.y() + 30))
        self.assertGreater(a.w, w0 + 40)
        self.assertGreater(a.h, h0 + 20)
        rot = a.mapToScene(a.handle_points()[8])
        cen = a.scenePos()
        self.drag(self.P(rot.x(), rot.y()), self.P(cen.x() + 200, cen.y()))
        self.assertAlmostEqual(a.rotation(), 90, delta=5)
        for _ in range(3):
            self.w.doc.undo_stack.undo()
        self.assertAlmostEqual(a.pos().x(), c0.x())
        self.assertAlmostEqual(a.rotation(), 0)

    def test_connect_from_port_and_follow(self):
        a = self.sc.add_shape("flow.process", QPointF(200, 200))
        b = self.sc.add_shape("flow.decision", QPointF(500, 420))
        self.sc.clearSelection()
        port, _ = a.port_scene(1)
        QTest.mouseMove(self.vp, self.P(port.x(), port.y()))
        self.app.processEvents()
        self.assertIsNotNone(self.sc.hover_port)
        self.drag(self.P(port.x(), port.y()), self.P(b.pos().x(), b.pos().y()))
        conns = self.sc.connectors()
        self.assertEqual(len(conns), 1)
        self.assertEqual((conns[0].src["shape"], conns[0].dst["shape"]), (a.id, b.id))
        end_before = conns[0].end_points()[1]
        self.drag(self.P(b.pos().x(), b.pos().y() + 10), self.P(b.pos().x() + 80, b.pos().y() + 60))
        self.assertNotEqual(conns[0].end_points()[1], end_before)

    def test_autoconnect_and_typing(self):
        a = self.sc.add_shape("flow.process", QPointF(200, 200))
        self.sc.clearSelection()
        QTest.mouseMove(self.vp, self.P(a.pos().x(), a.pos().y()))
        pts = self.sc._autoconnect_points(a)
        QTest.mouseMove(self.vp, self.P(pts[2].x(), pts[2].y()))
        self.app.processEvents()
        self.assertEqual(self.sc.hover_arrow, 2)
        QTest.mouseClick(self.vp, L, NOMOD, self.P(pts[2].x(), pts[2].y()))
        self.app.processEvents()
        self.assertEqual(len(self.sc.shapes()), 2)
        self.assertEqual(len(self.sc.connectors()), 1)
        new = self.sc.single_selected
        self.assertIsInstance(new, ShapeItem)
        self.assertGreater(new.pos().y(), a.pos().y() + 50)
        self.view.setFocus()
        QTest.keyClicks(self.view, "Bonjour")
        self.assertTrue(new.editing)
        QTest.keyClick(self.view, Qt.Key.Key_Escape)
        self.assertEqual(new.text, "Bonjour")
        self.assertEqual(self.w.doc.undo_stack.undoText(), "Modifier le texte")

    def test_delete_cascades_to_connectors_and_undo(self):
        doc = Document(templates.build("sample"))
        self.w.set_document(doc)
        sc = self.w.scene()
        s3 = sc.item_by_id("s3")
        sc.select_items([s3])
        self.view.setFocus()
        QTest.keyClick(self.w, Qt.Key.Key_Delete)
        self.assertIsNone(sc.item_by_id("s3"))
        self.assertEqual(len(sc.connectors()), 5)
        doc.undo_stack.undo()
        self.assertIsNotNone(sc.item_by_id("s3"))
        self.assertEqual(len(sc.connectors()), 8)

    def test_rubber_band_nudge_copy_paste(self):
        for x in (150, 300, 450):
            self.sc.add_shape("basic.rectangle", QPointF(x, 200))
        self.sc.clearSelection()
        r = self.sc.drawing_rect().adjusted(-40, -40, 40, 40)
        self.drag(self.P(r.left(), r.top()), self.P(r.right(), r.bottom()))
        self.assertEqual(len(self.sc.selected_shapes()), 3)
        before = [s.pos().x() for s in self.sc.selected_shapes()]
        self.view.setFocus()
        QTest.keyClick(self.view, Qt.Key.Key_Right)
        self.assertTrue(all(s.pos().x() > b for s, b in zip(self.sc.selected_shapes(), before)))
        self.w.a["copy"].trigger()
        self.w.a["paste"].trigger()
        self.assertEqual(len(self.sc.shapes()), 6)

    def test_tools(self):
        a = self.sc.add_shape("basic.rectangle", QPointF(150, 150))
        b = self.sc.add_shape("basic.rectangle", QPointF(450, 350))
        self.w.doc.set_tool("connector")
        self.drag(self.P(a.pos().x(), a.pos().y()), self.P(b.pos().x(), b.pos().y()))
        self.assertEqual(len(self.sc.connectors()), 1)
        self.w.doc.set_tool("ellipse")
        self.drag(self.P(600, 100), self.P(700, 160))
        self.assertTrue(any(s.type_id == "basic.ellipse" for s in self.sc.shapes()))
        self.w.doc.set_tool("select")

    def test_save_and_reopen_through_window(self):
        doc = Document(templates.build("sample"))
        self.w.set_document(doc)
        path = os.path.join(tempfile.mkdtemp(), "commande.lxd")
        self.assertTrue(self.w._write(path))
        self.assertFalse(doc.is_modified())
        data, warnings, _pw = fileformat.load_file(path)
        self.assertEqual(warnings, [])
        self.assertEqual(len(data["pages"][0]["shapes"]), 10)
        vsdx_path = path.replace(".lxd", ".vsdx")
        self.assertTrue(self.w._write(vsdx_path))
        self.assertEqual(doc.path, vsdx_path)

    def test_text_paste_is_plain(self):
        a = self.sc.add_shape("basic.rectangle", QPointF(150, 150))
        self.sc.select_items([a])
        a.start_edit()
        from PyQt6.QtCore import QMimeData
        md = QMimeData()
        md.setHtml('<img src="file:///etc/passwd"><b>gras</b>')
        md.setText("texte\x07 brut")
        self.app.clipboard().setMimeData(md)
        a.label.paste_plain()
        a.finish_edit()
        self.assertEqual(a.text, "texte brut")


if __name__ == "__main__":
    unittest.main()
