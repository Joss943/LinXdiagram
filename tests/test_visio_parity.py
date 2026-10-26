"""Fonctions de parité Visio : opérations sur les formes, pages d'arrière-plan, champs,
espacement automatique, export page web, portabilité Windows / macOS."""

import os
import sys
import tempfile
import unittest
from unittest import mock

from PyQt6.QtCore import QPointF
from PyQt6.QtGui import QColor, QImage, QPainter

from tests.helpers import qapp

from linxdiagram import app as appmod, compat, export, fields, fileformat, security, vsdx
from linxdiagram.document import Document


class VisioParityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = qapp()
        appmod.apply_theme(cls.app, False)
        cls.ctx = appmod.AppContext(cls.app)

    def setUp(self):
        self.w = self.ctx.new_window(Document())
        self.w.hide_backstage()
        self.sc = self.w.scene()
        self.doc = self.w.doc

    def tearDown(self):
        self.doc.undo_stack.setClean()
        self.w.close()
        self.app.processEvents()

    def _shape(self, type_id, x, y, text=""):
        st = self.sc.new_shape_state(type_id, QPointF(x, y))
        st["text"] = text
        self.sc.add_states([st], "Ajouter")
        return self.sc.item_by_id(st["id"])

    def _two_overlapping(self):
        a = self._shape("basic.rectangle", 200, 200, "A")
        b = self._shape("basic.ellipse", 240, 220, "B")
        self.sc.select_items([a, b])
        return a, b

    # ------------------------------------------------------------ opérations
    def test_union_replaces_shapes_and_undoes(self):
        a, b = self._two_overlapping()
        box = a.scene_box().united(b.scene_box())
        self.assertEqual(self.sc.shape_operation("union"), 1)
        shapes = self.sc.shapes()
        self.assertEqual(len(shapes), 1)
        res = shapes[0]
        self.assertEqual(res.type_id, "special.custom")
        self.assertEqual(res.text, "A")
        self.assertAlmostEqual(res.scene_box().width(), box.width(), delta=1.5)
        self.doc.undo_stack.undo()
        self.assertEqual(sorted(s.text for s in self.sc.shapes()), ["A", "B"])

    def test_intersect_subtract_fragment(self):
        a, b = self._two_overlapping()
        self.sc.shape_operation("intersect")
        inter = self.sc.shapes()[0].scene_box()
        self.assertLess(inter.width(), a.w)
        self.doc.undo_stack.undo()
        self.sc.select_items(self.sc.shapes())
        self.sc.shape_operation("subtract")
        self.assertEqual(len(self.sc.shapes()), 1)
        self.doc.undo_stack.undo()
        self.sc.select_items(self.sc.shapes())
        self.assertEqual(self.sc.shape_operation("fragment"), 3)

    def test_combine_saves_and_reloads(self):
        self._two_overlapping()
        self.sc.shape_operation("combine")
        data, _w = fileformat.validate_document(fileformat.parse_json(fileformat.dump_bytes(self.doc.to_dict())))
        path = data["pages"][0]["shapes"][0]["path"]
        self.assertGreater(sum(1 for c in path if c[0] == "M"), 1)

    def test_operation_needs_two_shapes(self):
        a = self.sc.add_shape("basic.rectangle", QPointF(100, 100))
        self.sc.select_items([a])
        self.assertEqual(self.sc.shape_operation("union"), 0)

    # ------------------------------------------------------------ espacement
    def test_auto_space(self):
        shapes = [self._shape("basic.rectangle", x, 100 + i * 7, str(i))
                  for i, x in enumerate((100, 180, 400))]
        self.sc.select_items(shapes)
        self.assertTrue(self.sc.auto_space(10))
        boxes = sorted((s.scene_box() for s in shapes), key=lambda r: r.left())
        gaps = [boxes[i + 1].left() - boxes[i].right() for i in range(2)]
        self.assertAlmostEqual(gaps[0], gaps[1], places=3)
        self.assertEqual(len({round(b.center().y(), 3) for b in boxes}), 1)

    # ------------------------------------------------------------ arrière-plans
    def test_background_page_renders_under_foreground(self):
        self.w.add_background_page()
        bg = self.doc.pages[-1]
        self.assertEqual(bg.page_kind, "background")
        self.assertIs(self.sc.background_scene(), bg)
        st = bg.new_shape_state("basic.rectangle", QPointF(60, 60), 80, 80)
        st["style"]["fill"] = "#ff0000"
        bg.add_states([st], "x")
        img = QImage(int(self.sc.page_w), int(self.sc.page_h), QImage.Format.Format_ARGB32)
        img.fill(QColor("#ffffff"))
        with export.exporting(self.sc):
            p = QPainter(img)
            self.sc.render(p, export.source_rect(self.sc, "page").translated(0, 0),
                           self.sc.page_rect())
            p.end()
        self.assertEqual(img.pixelColor(60, 60).name(), "#ff0000")
        self.assertEqual(self.doc.printable_pages(), [self.sc])
        self.doc.undo_stack.undo()  # la forme
        self.doc.undo_stack.undo()  # la page d'arrière-plan
        self.assertEqual(len(self.doc.pages), 1)
        self.assertEqual(self.sc.backpage, "")

    def test_background_rename_and_validation(self):
        self.w.add_background_page()
        bg = self.doc.pages[-1]
        before = bg.page_props()
        bg.set_page_props(dict(before, name="Fond"))
        self.assertEqual(self.sc.backpage, "Fond")
        pages = [dict(fileformat.default_page("A"), backpage="B"),
                 dict(fileformat.default_page("B"), kind="background", backpage="C"),
                 dict(fileformat.default_page("C"), kind="background", backpage="B"),
                 dict(fileformat.default_page("D"), backpage="A")]
        doc, _w = fileformat.validate_document({"format": "linxdiagram", "version": 1, "pages": pages})
        refs = {p["name"]: p["backpage"] for p in doc["pages"]}
        self.assertEqual(refs["A"], "B")
        self.assertEqual(refs["D"], "")  # A n'est pas un arrière-plan
        self.assertTrue(refs["B"] == "" or refs["C"] == "")  # boucle rompue

    def test_background_vsdx_round_trip(self):
        self.w.add_background_page()
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "bg.vsdx")
            vsdx.export_vsdx(self.doc, path)
            data, _w = vsdx.import_vsdx(path)
        kinds = [(p["name"], p.get("kind"), p.get("backpage")) for p in data["pages"]]
        self.assertEqual(kinds[1][1], "background")
        self.assertEqual(kinds[0][2], kinds[1][0])

    # ------------------------------------------------------------ champs
    def test_fields_expand_and_edit_raw(self):
        self.doc.properties["title"] = "Plan réseau"
        s = self._shape("basic.text", 100, 100, "Page {{Page}}/{{Pages}} – {{Titre}}")
        self.assertEqual(s.label.toPlainText(), "Page 1/1 – Plan réseau")
        self.w.add_page()
        self.app.processEvents()
        self.assertEqual(s.label.toPlainText(), "Page 1/2 – Plan réseau")
        s.start_edit()
        self.assertIn("{{Page}}", s.label.toPlainText())
        s.finish_edit()
        self.assertEqual(fields.expand("{{Inconnu}}", self.sc), "{{Inconnu}}")

    def test_field_on_background_uses_foreground_number(self):
        self.w.add_page()
        page2 = self.doc.pages[1]
        self.w.show_page(page2)
        self.w.add_background_page()
        bg = self.doc.pages[-1]
        page2.set_page_props(dict(page2.page_props(), backpage=bg.page_name))
        st = bg.new_shape_state("basic.text", QPointF(50, 50))
        st["text"] = "{{Page}}"
        bg.add_states([st], "x")
        item = bg.shapes()[0]
        seen = []
        orig = item.layout_label

        def spy():
            orig()
            seen.append(item.label.toPlainText())
        item.layout_label = spy
        img = QImage(100, 100, QImage.Format.Format_ARGB32)
        p = QPainter(img)
        page2._paint_background_page(p)
        p.end()
        self.assertIn("2", seen)

    # ------------------------------------------------------------ export web
    def test_export_html(self):
        self._shape("basic.rectangle", 100, 100, "Bonjour <b>")
        self.w.add_page()
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "dessin.html")
            export.export_html(self.doc.printable_pages(), path, "Titre & test")
            with open(path, encoding="utf-8") as f:
                text = f.read()
        self.assertTrue(text.startswith("<!doctype html>"))
        self.assertEqual(text.count("<svg"), 2)
        self.assertNotIn("<script", text)
        self.assertNotIn("<?xml", text)
        self.assertIn("Titre &amp; test", text)
        self.assertNotIn("Bonjour <b>", text)


class PortabilityTest(unittest.TestCase):
    def setUp(self):
        self._env = mock.patch.dict(os.environ)
        self._env.start()
        os.environ.pop("LINXDIAGRAM_HOME", None)
        self.addCleanup(self._env.stop)

    def test_dirs_per_platform(self):
        with mock.patch.object(compat, "IS_WINDOWS", True), mock.patch.object(compat, "IS_MACOS", False), \
                mock.patch.dict(os.environ, {"LOCALAPPDATA": os.path.abspath("C")}):
            self.assertTrue(compat.data_dir().endswith(os.path.join("C", "LinXdiagram")))
            self.assertIn("Logs", compat.state_dir())
        with mock.patch.object(compat, "IS_WINDOWS", False), mock.patch.object(compat, "IS_MACOS", True):
            self.assertIn(os.path.join("Library", "Application Support"), compat.data_dir())
            self.assertIn(os.path.join("Library", "Logs"), compat.state_dir())

    def test_pid_alive(self):
        self.assertTrue(compat.pid_alive(os.getpid()))
        self.assertFalse(compat.pid_alive(0))
        os.environ["LINXDIAGRAM_HOME"] = os.path.abspath("portable")
        self.assertEqual(compat.data_dir(), os.path.join(os.path.abspath("portable"), "data"))

    def test_libcrypto_candidates_never_use_macos_system_lib(self):
        with mock.patch.object(sys, "platform", "darwin"):
            cands = security._libcrypto_candidates()
        self.assertNotIn("/usr/lib/libcrypto.dylib", cands)
        with mock.patch.object(sys, "platform", "win32"):
            self.assertTrue(any(c.endswith(".dll") for c in security._libcrypto_candidates()))

    def test_encryption_round_trip(self):
        if not security.encryption_available():
            self.skipTest("aucune bibliothèque de chiffrement")
        blob = security.encrypt_payload(b"secret", "mot de passe")
        env = fileformat.parse_json(blob)
        self.assertEqual(security.decrypt_payload(env, "mot de passe"), b"secret")


if __name__ == "__main__":
    unittest.main()
