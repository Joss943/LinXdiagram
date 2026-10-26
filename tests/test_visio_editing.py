"""Gestes d'édition de Visio : Ctrl + glisser, copie en image, collage spécial, pinceau
persistant, repères et organisation des fenêtres."""

import unittest
from unittest import mock

from PyQt6.QtCore import QEvent, QPoint, QPointF, Qt
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from tests.helpers import qapp

from linxdiagram import app as appmod
from linxdiagram.document import Document
from linxdiagram.scene import DiagramScene

L = Qt.MouseButton.LeftButton
CTRL = Qt.KeyboardModifier.ControlModifier


class VisioEditingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = qapp()
        appmod.apply_theme(cls.app, False)
        cls.ctx = appmod.AppContext(cls.app)

    def setUp(self):
        self.w = self.ctx.new_window(Document())
        self.w.resize(1400, 900)
        self.w.hide_backstage()
        self.app.processEvents()
        self.view = self.w.view
        self.vp = self.view.viewport()
        self.sc = self.w.scene()
        self.view.set_zoom(1.0)
        self.view.centerOn(QPointF(300, 300))
        self.app.processEvents()

    def tearDown(self):
        for w in list(self.ctx.windows):
            w.doc.undo_stack.setClean()
            w.close()
        self.app.processEvents()

    def P(self, x, y):
        return self.view.mapFromScene(QPointF(x, y))

    def test_ctrl_drag_duplicates(self):
        a = self.sc.add_shape("flow.process", QPointF(200, 200))
        x0 = a.pos().x()
        self.sc.select_items([a])
        start, end = self.P(200, 200), self.P(320, 260)
        QTest.mousePress(self.vp, L, CTRL, start)
        for i in range(1, 9):
            QTest.mouseMove(self.vp, QPoint(start.x() + (end.x() - start.x()) * i // 8,
                                            start.y() + (end.y() - start.y()) * i // 8))
            self.app.processEvents()
        QTest.mouseRelease(self.vp, L, CTRL, end)
        self.app.processEvents()
        shapes = self.sc.shapes()
        self.assertEqual(len(shapes), 2)
        self.assertAlmostEqual(a.pos().x(), x0, delta=0.01)
        copy = next(s for s in shapes if s is not a)
        self.assertGreater(copy.pos().x(), 280)
        self.assertEqual(self.w.doc.undo_stack.undoText(), "Dupliquer")
        self.w.doc.undo_stack.undo()
        self.assertEqual(len(self.sc.shapes()), 1)

    def test_copy_puts_image_and_svg(self):
        a = self.sc.add_shape("flow.process", QPointF(200, 200))
        self.sc.add_shape("flow.decision", QPointF(400, 400))
        self.sc.select_items([a])
        self.w.copy()
        md = QApplication.clipboard().mimeData()
        self.assertTrue(md.hasImage())
        img = md.imageData()
        self.assertLess(img.width(), 2 * (a.w + 40))  # la seule forme sélectionnée
        self.assertIn(b"<svg", bytes(md.data("image/svg+xml")))
        self.assertTrue(a.isSelected())

    def test_paste_special_as_text(self):
        QApplication.clipboard().setText("Bonjour")
        with mock.patch("linxdiagram.mainwindow.QInputDialog.getItem",
                        return_value=("Texte non mis en forme", True)):
            self.w.paste_special()
        self.assertEqual([s.text for s in self.sc.shapes()], ["Bonjour"])

    def test_sticky_format_painter(self):
        src = self.sc.add_shape("flow.process", QPointF(200, 200))
        b = self.sc.add_shape("flow.process", QPointF(400, 200))
        c = self.sc.add_shape("flow.process", QPointF(600, 200))
        self.sc.select_items([src])
        self.sc.apply_shape_style({"fill": "#ff0000"}, "Remplissage")
        ev = QMouseEvent(QEvent.Type.MouseButtonDblClick, QPointF(5, 5), QPointF(5, 5), L, L,
                         Qt.KeyboardModifier.NoModifier)
        self.assertTrue(self.w.eventFilter(self.w._painter_btn, ev))
        for target in (b, c):
            QTest.mouseClick(self.vp, L, Qt.KeyboardModifier.NoModifier, self.P(target.pos().x(), target.pos().y()))
            self.app.processEvents()
        self.assertEqual(b.style["fill"], "#ff0000")
        self.assertEqual(c.style["fill"], "#ff0000")
        self.assertIsNotNone(self.sc.format_painter)
        QTest.keyClick(self.vp, Qt.Key.Key_Escape)
        self.assertIsNone(self.sc.format_painter)

    def test_ruler_guides_toggle(self):
        self.sc.add_guide("v", 150)
        box = next(c for c in self.w.findChildren(__import__("PyQt6.QtWidgets", fromlist=["QCheckBox"]).QCheckBox)
                   if c.text() == "Repères")
        self.assertEqual(box.isChecked(), self.w.a["ruler_guides"].isChecked())
        self.w.a["ruler_guides"].setChecked(False)
        self.assertFalse(DiagramScene.show_ruler_guides)
        self.w.a["ruler_guides"].setChecked(True)
        self.assertTrue(DiagramScene.show_ruler_guides)

    def test_arrange_windows(self):
        from PyQt6.QtCore import QRect
        from linxdiagram.mainwindow import tile_rects
        rects = tile_rects(3, QRect(0, 0, 1200, 800))
        self.assertEqual([(r.x(), r.y(), r.width()) for r in rects], [(0, 0, 600), (600, 0, 600), (0, 400, 600)])
        self.assertEqual(tile_rects(1, QRect(0, 0, 1200, 800))[0].width(), 1200)
        w2 = self.ctx.new_window(Document())
        self.w.arrange_windows()  # ne doit pas échouer ; le placement dépend du gestionnaire de fenêtres
        self.w.cascade_windows()
        self.w._fill_switch_menu()
        self.assertEqual(len(self.w.switch_menu.actions()), 2)

    def test_paragraph_bullets_indent_spacing(self):
        a = self.sc.add_shape("basic.rectangle", QPointF(200, 200))
        a.text = "Un\nDeux"
        a.layout_label()
        self.sc.select_items([a])
        self.w.a["bullets"].trigger()
        self.assertTrue(a.text_style["bullets"])
        self.assertIsNotNone(a.label.document().firstBlock().textList())
        self.w.a["indent_more"].trigger()
        self.w.a["indent_more"].trigger()
        self.assertEqual(a.text_style["indent"], 2)
        self.w._text_style({"spacing": 1.5})
        fmt = a.label.document().firstBlock().blockFormat()
        self.assertAlmostEqual(fmt.lineHeight(), 150)
        self.assertEqual(a.label.toPlainText(), "Un\nDeux")  # les puces ne s'ajoutent pas au texte
        self.w.a["bullets"].trigger()
        self.assertIsNone(a.label.document().firstBlock().textList())
        self.w.a["indent_less"].trigger()
        self.assertEqual(a.text_style["indent"], 1)

    def test_paragraphs_and_justify_survive_vsdx(self):
        import os
        import tempfile
        from linxdiagram import vsdx
        a = self.sc.add_shape("basic.rectangle", QPointF(200, 200))
        self.sc.select_items([a])
        self.w._text_style({"halign": "justify", "bullets": True, "indent": 2, "spacing": 1.5})
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "p.vsdx")
            vsdx.export_vsdx(self.w.doc, path)
            data, _w = vsdx.import_vsdx(path)
        ts = data["pages"][0]["shapes"][0]["text_style"]
        self.assertEqual(ts["halign"], "justify")
        self.assertTrue(ts["bullets"])
        self.assertEqual(ts["indent"], 2)
        self.assertAlmostEqual(ts["spacing"], 1.5)

    def test_reorder_pages_by_tab_drag_and_undo(self):
        self.w.add_page()
        self.w.add_page()
        names = [p.page_name for p in self.w.doc.pages]
        self.w.page_tabs.moveTab(0, 2)  # même signal que le glisser d'un onglet
        self.app.processEvents()
        self.assertEqual([p.page_name for p in self.w.doc.pages], names[1:] + names[:1])
        self.assertEqual([self.w.page_tabs.tabText(i) for i in range(3)], names[1:] + names[:1])
        self.w.doc.undo_stack.undo()
        self.assertEqual([p.page_name for p in self.w.doc.pages], names)

    def test_reorder_pages_dialog(self):
        from linxdiagram.dialogs import ReorderPagesDialog
        self.w.add_page()
        pages = list(self.w.doc.pages)
        dlg = ReorderPagesDialog(self.w, pages)
        dlg.list.setCurrentRow(1)
        dlg.move(-1)
        self.assertEqual(dlg.order(), [pages[1], pages[0]])


if __name__ == "__main__":
    unittest.main()
