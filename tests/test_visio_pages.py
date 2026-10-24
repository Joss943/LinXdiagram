"""Repères tirés des règles, pages d'arrière-plan, champs et orthographe."""

import datetime
import os
import tempfile
import unittest

from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QColor, QImage, QPainter
from PyQt6.QtTest import QTest

from tests.helpers import qapp

from linxdiagram import app as appmod, export, fields, fileformat, spellcheck, vsdx
from linxdiagram.document import Document

L = Qt.MouseButton.LeftButton
NOMOD = Qt.KeyboardModifier.NoModifier


def _roundtrip(doc):
    data, _w = fileformat.validate_document({"format": fileformat.FORMAT, "version": fileformat.VERSION,
                                             **doc.to_dict()})
    return Document(data)


class GuidesTest(unittest.TestCase):
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
        self.view, self.sc = self.w.view, self.w.scene()
        self.vp = self.view.viewport()
        self.view.set_zoom(1.0)
        self.view.centerOn(QPointF(300, 300))
        self.app.processEvents()

    def tearDown(self):
        self.w.doc.undo_stack.setClean()
        self.w.close()

    def test_drag_guide_from_ruler_snap_move_and_delete(self):
        from linxdiagram.canvas import Ruler
        vruler = [r for r in self.w.findChildren(Ruler) if not r.horizontal][0]
        target = self.view.mapFromScene(QPointF(250, 300))
        start = QPoint(vruler.width() // 2, vruler.mapFromGlobal(self.vp.mapToGlobal(target)).y())
        QTest.mousePress(vruler, L, NOMOD, start)
        QTest.mouseMove(vruler, vruler.mapFromGlobal(self.vp.mapToGlobal(target)))
        self.app.processEvents()
        QTest.mouseRelease(vruler, L, NOMOD, vruler.mapFromGlobal(self.vp.mapToGlobal(target)))
        self.app.processEvents()
        self.assertEqual(len(self.sc.ruler_guides), 1)
        g = self.sc.ruler_guides[0]
        self.assertEqual(g["o"], "v")
        self.assertAlmostEqual(g["pos"], 250, delta=8)
        # Une forme déposée près du repère s'y aimante quand on la déplace.
        s = self.sc.add_shape("basic.rectangle", QPointF(150, 450))
        c = self.view.mapFromScene(s.scene_box().center())
        dest = self.view.mapFromScene(QPointF(g["pos"] + 4, 450))
        QTest.mousePress(self.vp, L, NOMOD, c)
        for i in range(1, 9):
            QTest.mouseMove(self.vp, QPoint(c.x() + (dest.x() - c.x()) * i // 8, c.y()))
            self.app.processEvents()
        QTest.mouseRelease(self.vp, L, NOMOD, dest)
        self.app.processEvents()
        box = s.scene_box()
        self.assertTrue(min(abs(v - g["pos"]) for v in (box.left(), box.center().x(), box.right())) < 0.01)
        # Déplacer le repère, puis le sélectionner et le supprimer.
        self.sc.move_guide(0, 300)
        self.assertEqual(self.sc.ruler_guides[0]["pos"], 300)
        self.w.doc.undo_stack.undo()
        self.assertAlmostEqual(self.sc.ruler_guides[0]["pos"], g["pos"])
        self.sc.selected_guide = 0
        self.sc.clearSelection()
        self.w.delete()
        self.assertEqual(self.sc.ruler_guides, [])
        self.w.doc.undo_stack.undo()
        self.assertEqual(len(_roundtrip(self.w.doc).pages[0].ruler_guides), 1)


class BackgroundPageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = qapp()
        appmod.apply_theme(cls.app, False)
        cls.ctx = appmod.AppContext(cls.app)

    def test_background_page_is_drawn_behind_and_survives_files(self):
        w = self.ctx.new_window()
        w.hide_backstage()
        fg = w.scene()
        w.add_background_page()
        bg = w.scene()
        self.assertTrue(bg.is_background)
        self.assertEqual(fg.backpage, bg.page_name)
        mark = bg.add_shape("basic.rectangle", QPointF(100, 100))
        bg.modify([mark], lambda _i, st: st["style"].update(fill="#ff0000", themed=False), "rouge")
        img = QImage(int(fg.page_w), int(fg.page_h), QImage.Format.Format_ARGB32)
        img.fill(QColor("#ffffff"))
        p = QPainter(img)
        with export.exporting(fg):
            fg.render(p, fg.page_rect(), fg.page_rect())
        p.end()
        self.assertEqual(img.pixelColor(100, 100).name(), "#ff0000")
        back = _roundtrip(w.doc)
        self.assertEqual(back.pages[0].backpage, back.pages[1].page_name)
        self.assertTrue(back.pages[1].is_background)
        path = os.path.join(tempfile.mkdtemp(), "fond.vsdx")
        vsdx.export_vsdx(w.doc, path)
        data, _w = vsdx.import_vsdx(path)
        self.assertTrue(data["pages"][1]["is_background"])
        self.assertEqual(data["pages"][0]["backpage"], data["pages"][1]["name"])
        w.doc.undo_stack.setClean()
        w.close()


class FieldsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = qapp()

    def test_fields_resolve_and_update(self):
        doc = Document()
        sc = doc.pages[0]
        s = sc.add_shape("basic.text", QPointF(100, 100))
        sc.modify([s], lambda _i, st: st.update(text="Page {{page}} sur {{pages}} — {{nom_page}}"), "t")
        self.assertEqual(s.label.toPlainText(), f"Page 1 sur 1 — {sc.page_name}")
        from linxdiagram.commands import PageCommand
        doc.undo_stack.push(PageCommand(doc, "p", add=doc.make_page(), index=1))
        sc.refresh_fields()
        self.assertEqual(s.label.toPlainText(), f"Page 1 sur 2 — {sc.page_name}")
        s.start_edit()
        self.assertIn("{{page}}", s.label.toPlainText())
        s.finish_edit()
        now = datetime.datetime(2026, 10, 24, 9, 5)
        self.assertEqual(fields.resolve("{{date}} {{heure}} {{date_longue}}", sc, now),
                         "24/10/2026 09:05 samedi 24 octobre 2026")
        self.assertEqual(fields.resolve("{{inconnu}}", sc), "{{inconnu}}")


@unittest.skipUnless(spellcheck.SpellChecker().available, "aucun dictionnaire Hunspell installé")
class SpellTest(unittest.TestCase):
    def test_errors_and_personal_dictionary(self):
        path = os.path.join(tempfile.mkdtemp(), "dico.txt")
        s = spellcheck.SpellChecker(path)
        errs = s.errors("La commande est envoyée {{page}} au cliennt rapidement, SNCF.")
        self.assertEqual([e[2] for e in errs], ["cliennt"])
        self.assertIn("client", s.suggest("cliennt"))
        s.add_to_dictionary("cliennt")
        self.assertEqual(spellcheck.SpellChecker(path).errors("cliennt"), [])


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(spellcheck.SpellChecker().available, "aucun dictionnaire Hunspell installé")
class SpellDialogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = qapp()
        appmod.apply_theme(cls.app, False)
        cls.ctx = appmod.AppContext(cls.app)

    def test_change_and_change_all(self):
        from unittest import mock
        from linxdiagram.dialogs import SpellDialog
        w = self.ctx.new_window()
        w.hide_backstage()
        sc = w.scene()
        a = sc.add_shape("flow.process", QPointF(100, 100))
        b = sc.add_shape("flow.process", QPointF(100, 300))
        sc.modify([a], lambda _i, st: st.update(text="Apeler le cliennt"), "t")
        sc.modify([b], lambda _i, st: st.update(text="Rappeler le cliennt"), "t")
        checker = spellcheck.SpellChecker(os.path.join(tempfile.mkdtemp(), "d.txt"))
        dlg = SpellDialog(w, checker, [(sc, a), (sc, b)])
        with mock.patch("PyQt6.QtWidgets.QMessageBox.information"):
            self.assertTrue(dlg.start())
            self.assertEqual(dlg.current[4], "Apeler")
            dlg.replacement.setText("Appeler")
            dlg._change()
            self.assertEqual(dlg.current[4], "cliennt")
            dlg.replacement.setText("client")
            dlg._change_all()
        self.assertEqual(a.text, "Appeler le client")
        self.assertEqual(b.text, "Rappeler le client")
        w.doc.undo_stack.undo()
        self.assertEqual(b.text, "Rappeler le cliennt")
        w.doc.undo_stack.setClean()
        w.close()
