"""Fonctions Visio ajoutées : opérations sur les formes, alignement automatique,
Forme libre / Arc, gabarits blocs, entité-relation et chronologie."""

import os
import tempfile
import unittest

from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtTest import QTest

from tests.helpers import qapp

from linxdiagram import app as appmod, fileformat, stencils, templates, vsdx
from linxdiagram.document import Document

L = Qt.MouseButton.LeftButton
NOMOD = Qt.KeyboardModifier.NoModifier


def _overlapping(sc):
    a = sc.add_shape("basic.rectangle", QPointF(300, 300))
    b = sc.add_shape("basic.circle", QPointF(340, 310))
    a.setSelected(True)
    b.setSelected(True)
    return a, b


class ShapeOperationsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = qapp()

    def test_each_operation_and_undo(self):
        expected = {"union": 1, "combine": 1, "fragment": 3, "intersect": 1, "subtract": 1}
        for op, count in expected.items():
            doc = Document()
            sc = doc.pages[0]
            a, b = _overlapping(sc)
            area_a = a.scene_box().width() * a.scene_box().height()
            self.assertTrue(sc.shape_operation(op), op)
            shapes = sc.shapes()
            self.assertEqual(len(shapes), count, op)
            self.assertTrue(all(s.type_id == "special.custom" and s.custom for s in shapes))
            box = shapes[0].scene_box()
            if op == "subtract":      # le rectangle (sélectionné en premier) moins le cercle
                self.assertLess(box.width() * box.height(), area_a)
            doc.undo_stack.undo()
            self.assertEqual(sorted(s.type_id for s in sc.shapes()), ["basic.circle", "basic.rectangle"])

    def test_result_survives_save_and_vsdx(self):
        doc = Document()
        sc = doc.pages[0]
        _overlapping(sc)
        sc.shape_operation("union")
        data, _w = fileformat.validate_document({"format": fileformat.FORMAT, "version": fileformat.VERSION,
                                                 **doc.to_dict()})
        self.assertEqual(data["pages"][0]["shapes"][0]["type"], "special.custom")
        self.assertGreater(len(data["pages"][0]["shapes"][0]["path"]), 4)
        path = os.path.join(tempfile.mkdtemp(), "union.vsdx")
        vsdx.export_vsdx(doc, path)
        back, _w = vsdx.import_vsdx(path)
        self.assertEqual(back["pages"][0]["shapes"][0]["type"], "special.custom")

    def test_needs_two_shapes(self):
        doc = Document()
        sc = doc.pages[0]
        sc.add_shape("basic.rectangle", QPointF(100, 100)).setSelected(True)
        self.assertFalse(sc.shape_operation("union"))


class AutoAlignTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = qapp()

    def test_connected_shapes_are_aligned_and_evenly_spaced(self):
        doc = Document()
        sc = doc.pages[0]
        shapes = [sc.add_shape("flow.process", QPointF(x, y)) for x, y in ((200, 200), (214, 330), (193, 560))]
        for a, b in zip(shapes, shapes[1:]):
            sc.add_states([sc.new_connector_state({"shape": a.id, "port": -1, "x": 0, "y": 0},
                                                  {"shape": b.id, "port": -1, "x": 0, "y": 0})], "c")
        sc.clearSelection()
        offset = shapes[1].scene_box().center().x() - shapes[0].scene_box().center().x()
        sc.auto_align_space()
        xs = {round(s.scene_box().center().x(), 3) for s in shapes}
        self.assertEqual(len(xs), 1)
        boxes = sorted((s.scene_box() for s in shapes), key=lambda r: r.top())
        gaps = [b.top() - a.bottom() for a, b in zip(boxes, boxes[1:])]
        self.assertAlmostEqual(gaps[0], gaps[1], places=3)
        doc.undo_stack.undo()
        self.assertAlmostEqual(shapes[1].scene_box().center().x() - shapes[0].scene_box().center().x(), offset)


class FreehandToolsTest(unittest.TestCase):
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

    def stroke(self, points):
        pts = [self.view.mapFromScene(QPointF(x, y)) for x, y in points]
        QTest.mousePress(self.vp, L, NOMOD, pts[0])
        for p in pts[1:]:
            QTest.mouseMove(self.vp, p)
            self.app.processEvents()
        QTest.mouseRelease(self.vp, L, NOMOD, pts[-1])
        self.app.processEvents()

    def test_pencil_freeform_and_arc(self):
        wave = [(200 + i * 6, 300 + (12 if i % 2 else -12)) for i in range(20)]
        for tool, closed, filled in (("freeform", True, True), ("arc", False, False)):
            self.w.a[f"tool_{tool}"].trigger()
            self.assertEqual(self.w.doc.tool, tool)
            before = len(self.sc.shapes())
            self.stroke(wave if tool != "arc" else [(200, 400), (240, 430), (300, 460)])
            self.assertEqual(len(self.sc.shapes()), before + 1, tool)
            s = max(self.sc.shapes(), key=lambda it: it.zValue())
            self.assertEqual(s.type_id, "special.custom")
            self.assertEqual(any(c[0] == "Z" for c in s.custom), closed, tool)
            self.assertEqual(bool(s.style["fill"]), filled, tool)
            self.assertTrue(all(-10 <= v <= 10 for c in s.custom for v in c[1:]))
        self.w.a["tool_select"].trigger()


class NewStencilsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = qapp()

    def test_categories_and_templates(self):
        for cat in (stencils.BPMN, stencils.BLOCK, stencils.DB, stencils.TIMELINE):
            self.assertIn(cat, stencils.CATEGORIES)
            self.assertGreaterEqual(len(stencils.by_category(cat)), 4, cat)
        keys = [k for k, _t in templates.TEMPLATES]
        for key, cat in (("block_diagram", stencils.BLOCK), ("erd_chen", stencils.DB),
                         ("database_model", stencils.DB), ("timeline", stencils.TIMELINE)):
            self.assertIn(key, keys)
            self.assertEqual(templates.category_for(key), cat)
            Document(templates.build(key))
            templates.thumbnail(key)

    def test_new_shapes_roundtrip_vsdx(self):
        doc = Document()
        sc = doc.pages[0]
        types = [d.type_id for c in (stencils.BLOCK, stencils.DB, stencils.TIMELINE)
                 for d in stencils.by_category(c)]
        for i, t in enumerate(types):
            sc.add_shape(t, QPointF(80 + (i % 6) * 120, 80 + (i // 6) * 110))
        path = os.path.join(tempfile.mkdtemp(), "formes.vsdx")
        vsdx.export_vsdx(doc, path)
        back, _w = vsdx.import_vsdx(path)
        self.assertEqual(sorted(s["type"] for s in back["pages"][0]["shapes"]), sorted(types))


if __name__ == "__main__":
    unittest.main()
