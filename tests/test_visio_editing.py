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

    def test_connection_point_tool(self):
        a = self.sc.add_shape("basic.rectangle", QPointF(200, 200))
        b = self.sc.add_shape("basic.rectangle", QPointF(420, 200))
        n = a.port_count()
        self.w.doc.set_tool("port")
        target = QPointF(a.pos().x() + a.w / 4, a.pos().y() - a.h / 4)  # loin des points existants
        QTest.mouseClick(self.vp, L, CTRL, self.P(target.x(), target.y()))
        self.assertEqual(a.port_count(), n + 1)
        p, _ = a.port_scene(n)
        self.assertLess((p - target).manhattanLength(), 1.0)
        # un connecteur collé au nouveau point, puis suppression du point
        st = self.sc.new_connector_state({"shape": a.id, "port": n, "x": 0, "y": 0},
                                         {"shape": b.id, "port": -1, "x": 0, "y": 0})
        self.sc.add_states([st], "c")
        conn = self.sc.item_by_id(st["id"])
        self.sc.select_items([a])
        self.sc.selected_port = (a.id, n)
        self.w.delete()
        self.assertEqual(a.port_count(), n)
        self.assertEqual(conn.src["port"], -1)
        self.assertEqual(conn.src["shape"], a.id)
        self.w.doc.undo_stack.undo()
        self.assertEqual(a.port_count(), n + 1)
        self.assertEqual(conn.src["port"], n)

    def test_connection_points_survive_save_and_vsdx(self):
        import os
        import tempfile
        from linxdiagram import fileformat, vsdx
        a = self.sc.add_shape("basic.rectangle", QPointF(200, 200))
        self.sc.add_port(a, QPointF(a.pos().x(), a.pos().y()))
        ports = [list(p) for p in a.ports]
        data, _w = fileformat.validate_document(fileformat.parse_json(fileformat.dump_bytes(self.w.doc.to_dict())))
        self.assertEqual(len(data["pages"][0]["shapes"][0]["ports"]), len(ports))
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "ports.vsdx")
            vsdx.export_vsdx(self.w.doc, path)
            imported, _w = vsdx.import_vsdx(path)
        got = imported["pages"][0]["shapes"][0]["ports"]
        self.assertEqual(len(got), len(ports))
        self.assertAlmostEqual(got[-1][0], 0.5, places=3)

    def test_text_block_tool_moves_text(self):
        a = self.sc.add_shape("basic.rectangle", QPointF(200, 200))
        self.sc.select_items([a])
        self.w.doc.set_tool("textblock")
        r0 = a.text_rect()
        start = a.mapToScene(r0.center())
        QTest.mousePress(self.vp, L, Qt.KeyboardModifier.NoModifier, self.P(start.x(), start.y()))
        for i in range(1, 6):
            QTest.mouseMove(self.vp, self.P(start.x() + 8 * i, start.y() + 4 * i))
            self.app.processEvents()
        QTest.mouseRelease(self.vp, L, Qt.KeyboardModifier.NoModifier, self.P(start.x() + 40, start.y() + 20))
        r1 = a.text_rect()
        self.assertAlmostEqual(r1.center().x() - r0.center().x(), 40, delta=2)
        self.assertAlmostEqual(r1.width(), r0.width(), delta=0.5)
        self.assertEqual(self.w.doc.undo_stack.undoText(), "Modifier le bloc de texte")
        self.w.doc.undo_stack.undo()
        self.assertAlmostEqual(a.text_rect().center().x(), r0.center().x(), delta=0.5)

    def test_grid_spacing_and_snap_glue_settings(self):
        from linxdiagram.dialogs import RulerGridDialog, SnapGlueDialog
        dlg = RulerGridDialog(self.w, self.w.doc.settings)
        dlg.preset.setCurrentIndex(2)  # Grossier, 10 mm
        self.w._change_doc_settings(dlg.values(), "Règle et grille")
        self.assertAlmostEqual(self.sc.snap_point(QPointF(31, 31)).x() % self.sc.grid_px, 0, places=3)
        self.assertAlmostEqual(self.sc.grid_px, 10 * 96 / 25.4, places=3)
        dlg = SnapGlueDialog(self.w, self.w.doc.settings)
        dlg.boxes["glue"].setChecked(False)
        dlg.strength.setValue(15)
        self.w._change_doc_settings(dlg.values(), "Accrocher et coller")
        self.assertFalse(self.w.doc.settings["glue"])
        self.assertEqual(self.sc.snap_tol_px, 15)
        a = self.sc.add_shape("basic.rectangle", QPointF(200, 200))
        self.sc._begin_new_connector(QPointF(50, 50))
        self.sc._update_conn_drag(a.pos())
        self.assertIsNone(self.sc.glue_target)  # collage désactivé
        self.sc._finish_conn_drag(a.pos())
        self.w.doc.undo_stack.undo()
        self.w.doc.undo_stack.undo()

    def test_page_breaks_and_tiled_printing(self):
        from PyQt6.QtGui import QPageLayout
        from linxdiagram import export
        from linxdiagram.units import PAGE_SIZES, PX_PER_MM
        a4w, a4h = (v * PX_PER_MM for v in PAGE_SIZES["A4"])
        self.assertEqual(len(export.page_tiles(self.sc, "A4")), 1)  # page A4 : une seule feuille
        before = self.sc.page_props()
        self.sc.set_page_props(dict(before, width=a4w * 1.5, height=a4h * 1.2))
        tiles = export.page_tiles(self.sc, "A4")
        self.assertEqual(len(tiles), 4)
        self.w.a["page_breaks"].setChecked(True)
        self.assertTrue(self.w.doc.settings["page_breaks"])
        self.sc.add_shape("basic.rectangle", QPointF(a4w * 1.2, a4h * 1.1))

        import os
        import re
        import tempfile
        from PyQt6.QtPrintSupport import QPrinter
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "mosaique.pdf")
            printer = QPrinter(QPrinter.PrinterMode.HighResolution)
            printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
            printer.setOutputFileName(path)
            export.print_pages(printer, [self.sc], tile=True, paper="A4")
            with open(path, "rb") as f:
                pdf = f.read()
        self.assertEqual(len(re.findall(rb"/Type\s*/Page[^s]", pdf)), 4)
        self.assertIsNotNone(QPageLayout)

    def test_print_page_options(self):
        self.w.show_backstage("home")
        self.w.backstage.select("print")
        self.app.processEvents()
        bs = self.w.backstage
        bs.scale_mode.setCurrentIndex(1)
        bs.paper.setCurrentIndex(bs.paper.findData("A3"))
        self.assertTrue(self.w.doc.settings["print_tile"])
        self.assertEqual(self.w.doc.settings["paper"], "A3")
        self.w.hide_backstage()


if __name__ == "__main__":
    unittest.main()
