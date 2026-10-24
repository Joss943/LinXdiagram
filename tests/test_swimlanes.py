"""Diagrammes de flux interfonctionnels (couloirs)."""

import os
import tempfile
import unittest

from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtTest import QTest

from tests.helpers import qapp

from linxdiagram import app as appmod, datavis, swimlanes, templates, vsdx
from linxdiagram.document import Document
from linxdiagram.units import mm_to_px


class LayoutTest(unittest.TestCase):
    def test_lanes_are_stacked_and_phases_fill_length(self):
        B = swimlanes.Box
        frame = B("f", 0, 0, 500, 300)
        lanes = [B("b", 0, 200, 400, 80), B("a", 0, 40, 500, 60)]
        phases = [B("p2", 300, 0, 80, 50), B("p1", 100, 0, 120, 50)]
        g = swimlanes.layout("h", frame, lanes, phases)
        title, band = swimlanes.TITLE, swimlanes.PHASE
        self.assertEqual(g["a"][1], title + band)             # « a » est au-dessus (ordre par position)
        self.assertEqual(g["b"][1], title + band + 60)        # « b » collé sous « a »
        self.assertEqual(g["a"][2], g["b"][2])                 # même longueur pour tous les couloirs
        self.assertEqual(g["p1"][0], swimlanes.HEADER)        # première phase après les en-têtes
        self.assertAlmostEqual(g["p2"][0] + g["p2"][2], g["a"][2])  # la dernière va jusqu'au bout
        self.assertEqual(g["f"][3], title + band + 140)       # le cadre englobe tout

    def test_vertical_and_minimums(self):
        B = swimlanes.Box
        g = swimlanes.layout("v", None, [B("x", 50, 10, 5, 200), B("y", 10, 10, 60, 300)], [])
        self.assertLess(g["y"][0], g["x"][0])
        self.assertGreaterEqual(g["x"][2], swimlanes.MIN_LANE)
        self.assertEqual(g["x"][3], g["y"][3])


class SwimlaneSceneTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = qapp()
        appmod.apply_theme(cls.app, False)
        cls.ctx = appmod.AppContext(cls.app)

    def setUp(self):
        self.doc = Document()
        self.sc = self.doc.pages[0]

    def lanes(self):
        _f, lanes, _p = self.sc.cff_parts("h")
        return sorted(lanes, key=lambda s: s.scene_box().top())

    def test_drop_frame_creates_structure(self):
        self.sc.add_shape("cff.frame_h", QPointF(400, 300))
        frames, lanes, phases = self.sc.cff_parts("h")
        self.assertEqual((len(frames), len(lanes), len(phases)), (1, 3, 0))
        lanes = self.lanes()
        for a, b in zip(lanes, lanes[1:]):
            self.assertAlmostEqual(a.scene_box().bottom(), b.scene_box().top(), places=3)
        self.assertEqual(lanes[0].text, "Fonction")
        self.assertEqual(lanes[0].label.rotation(), -90)
        self.doc.undo_stack.undo()
        self.assertFalse(self.sc.has_cff())

    def test_insert_lane_in_middle_moves_lower_lanes_and_content(self):
        self.sc.add_shape("cff.frame_h", QPointF(400, 300))
        l0, l1, l2 = self.lanes()
        task = self.sc.add_shape("flow.process", l2.scene_box().center())
        y_before = task.pos().y()
        self.sc.select_items([l0])
        self.sc.cff_insert_lane()
        lanes = self.lanes()
        self.assertEqual(len(lanes), 4)
        self.assertIs(lanes[0], l0)
        self.assertNotIn(lanes[1], (l0, l1, l2))
        self.assertGreater(task.pos().y(), y_before + mm_to_px(20))
        self.assertTrue(lanes[3].scene_box().contains(task.scene_box().center()))
        self.doc.undo_stack.undo()
        self.assertEqual(len(self.lanes()), 3)
        self.assertAlmostEqual(task.pos().y(), y_before)

    def test_delete_lane_deletes_content_and_closes_gap(self):
        self.sc.add_shape("cff.frame_h", QPointF(400, 300))
        l0, l1, l2 = self.lanes()
        inside = self.sc.add_shape("flow.process", l1.scene_box().center())
        below = self.sc.add_shape("flow.decision", l2.scene_box().center())
        top_l1 = l1.scene_box().top()
        self.sc.delete_items([l1])
        self.assertIsNone(self.sc.item_by_id(inside.id))
        self.assertAlmostEqual(l2.scene_box().top(), top_l1, places=3)
        self.assertTrue(l2.scene_box().contains(below.scene_box().center()))
        self.doc.undo_stack.undo()
        self.assertIsNotNone(self.sc.item_by_id(inside.id))
        self.assertEqual(len(self.lanes()), 3)

    def test_phases(self):
        self.sc.add_shape("cff.frame_h", QPointF(400, 300))
        self.sc.cff_insert_phase()
        self.sc.cff_insert_phase()
        _f, lanes, phases = self.sc.cff_parts("h")
        self.assertEqual(len(phases), 2)
        frame = self.sc.cff_parts("h")[0][0]
        right = max(p.scene_box().right() for p in phases)
        self.assertAlmostEqual(right, frame.scene_box().right(), places=3)
        self.assertAlmostEqual(lanes[0].scene_box().top() - frame.scene_box().top(),
                               swimlanes.TITLE + swimlanes.PHASE, places=3)

    def test_vertical_structure(self):
        self.sc.add_shape("cff.frame_v", QPointF(400, 400))
        _f, lanes, _p = self.sc.cff_parts("v")
        self.assertEqual(len(lanes), 3)
        xs = sorted(lane.scene_box().left() for lane in lanes)
        self.assertLess(xs[0], xs[1])
        self.assertEqual(lanes[0].label.rotation(), 0)

    def test_lane_interior_lets_clicks_through(self):
        self.sc.add_shape("cff.frame_h", QPointF(400, 300))
        lane = self.lanes()[1]
        b = lane.scene_box()
        self.assertIsNone(self.sc.shape_at(QPointF(b.center().x(), b.center().y())))
        self.assertIs(self.sc.shape_at(QPointF(b.left() + 5, b.center().y())), lane)

    def test_drag_lane_carries_content_and_reorders(self):
        w = self.ctx.new_window(self.doc)
        w.resize(1400, 900)
        w.hide_backstage()
        self.app.processEvents()
        sc = w.scene()
        sc.add_shape("cff.frame_h", QPointF(500, 300))
        l0, l1, l2 = self.lanes()
        task = sc.add_shape("flow.process", l0.scene_box().center())
        sc.clearSelection()
        view, vp = w.view, w.view.viewport()
        view.set_zoom(1.0)
        view.centerOn(QPointF(500, 300))
        self.app.processEvents()
        hdr = l0.mapToScene(l0.cff_header_rect().center())
        a = view.mapFromScene(hdr)
        b = view.mapFromScene(QPointF(hdr.x(), l2.scene_box().bottom() - 5))
        QTest.mousePress(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, a)
        for i in range(1, 9):
            QTest.mouseMove(vp, QPoint(a.x() + (b.x() - a.x()) * i // 8, a.y() + (b.y() - a.y()) * i // 8))
            self.app.processEvents()
        QTest.mouseRelease(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, b)
        self.app.processEvents()
        lanes = self.lanes()
        self.assertIs(lanes[-1], l0, "le couloir glissé passe en dernier")
        self.assertTrue(l0.scene_box().contains(task.scene_box().center()), "son contenu le suit")
        for x, y in zip(lanes, lanes[1:]):
            self.assertAlmostEqual(x.scene_box().bottom(), y.scene_box().top(), places=3)
        self.doc.undo_stack.undo()
        self.assertIs(self.lanes()[0], l0)
        self.doc.undo_stack.setClean()
        w.close()

    def test_contextual_tab(self):
        w = self.ctx.new_window(Document(templates.build("cff")))
        self.app.processEvents()
        self.assertFalse(w.ribbon.tab_buttons["Diagramme de flux interfonctionnel"].isHidden())
        w.doc.undo_stack.setClean()
        w.close()
        w2 = self.ctx.new_window(Document(templates.build("flow")))
        self.assertTrue(w2.ribbon.tab_buttons["Diagramme de flux interfonctionnel"].isHidden())
        w2.close()

    def test_template_and_vsdx_roundtrip(self):
        doc = Document(templates.build("cff"))
        frames, lanes, _p = doc.pages[0].cff_parts("h")
        self.assertEqual((len(frames), len(lanes)), (1, 3))
        path = os.path.join(tempfile.mkdtemp(), "cff.vsdx")
        vsdx.export_vsdx(doc, path)
        data, _w = vsdx.import_vsdx(path)
        types = sorted(s["type"] for s in data["pages"][0]["shapes"])
        self.assertEqual(types.count("cff.lane_h"), 3)
        self.assertIn("cff.frame_h", types)
        import zipfile
        with zipfile.ZipFile(path) as z:
            self.assertIn(b'N="TxtAngle"', z.read("visio/pages/page1.xml"))

    def test_data_visualizer_cross_functional(self):
        csv = ("ID;Description;Type;Suivant;Fonction\n1;Commande;Début;2;Client\n2;Vérifier;Processus;3;Ventes\n"
               "3;En stock ?;Décision;4;Ventes\n4;Expédier;Processus;5;Logistique\n5;Reçu;Fin;;Client\n")
        h, rows = datavis.parse_csv(csv.encode())
        page = datavis.build_page("flow", h, rows, "Commande", "office")
        lanes = [s for s in page["shapes"] if s["type"] == "cff.lane_h"]
        self.assertEqual([l["text"] for l in lanes], ["Client", "Ventes", "Logistique"])
        doc = Document({"settings": {}, "properties": {}, "pages": [page]})
        sc = doc.pages[0]
        boxes = {lane.text: lane.scene_box() for lane in sc.cff_parts("h")[1]}
        for s in sc.shapes():
            if s.type_id.startswith("flow."):
                lane_name = {"Commande": "Client", "Reçu": "Client", "Vérifier": "Ventes", "En stock ?": "Ventes",
                             "Expédier": "Logistique"}[s.text]
                self.assertTrue(boxes[lane_name].contains(s.scene_box().center()), s.text)
        xs = {s.text: s.pos().x() for s in sc.shapes() if s.type_id.startswith("flow.")}
        self.assertLess(xs["Commande"], xs["Vérifier"])
        self.assertLess(xs["Vérifier"], xs["Expédier"])


if __name__ == "__main__":
    unittest.main()


class SwimlaneOptionsTest(unittest.TestCase):
    """Onglet interfonctionnel : orientation, barre de titre, séparateurs, styles, export Visio."""

    @classmethod
    def setUpClass(cls):
        cls.app = qapp()
        appmod.apply_theme(cls.app, False)
        cls.ctx = appmod.AppContext(cls.app)

    def setUp(self):
        self.doc = Document()
        self.sc = self.doc.pages[0]
        self.sc.add_shape("cff.frame_h", QPointF(500, 400))
        self.lanes = sorted(self.sc.cff_parts("h")[1], key=lambda s: s.scene_box().top())
        b = self.lanes[1].scene_box()
        self.step = self.sc.add_shape("flow.process", QPointF(b.left() + 150, b.center().y()))

    def test_switch_orientation_keeps_shapes_in_their_lane(self):
        second = self.lanes[1].id
        self.assertTrue(self.sc.cff_set_orientation("v"))
        frames, lanes, _p = self.sc.cff_parts("v")
        self.assertEqual((len(frames), len(lanes)), (1, 3))
        self.assertFalse(any(self.sc.cff_parts("h")))
        cols = sorted(lanes, key=lambda s: s.scene_box().left())
        self.assertEqual(cols[1].id, second)                      # même ordre, en colonnes
        self.assertTrue(cols[1].scene_box().contains(self.step.scene_box().center()))
        self.assertTrue(frames[0].scene_box().contains(cols[2].scene_box()))
        self.assertTrue(cols[0].vertical_text() is False)
        self.doc.undo_stack.undo()
        self.assertEqual(len(self.sc.cff_parts("h")[1]), 3)
        self.assertTrue(self.lanes[1].scene_box().contains(self.step.scene_box().center()))

    def test_hide_title_bar_and_separators(self):
        top = self.lanes[0].scene_box().top()
        self.sc.cff_set_option("title", False)
        self.assertAlmostEqual(self.lanes[0].scene_box().top(), top - swimlanes.TITLE, places=3)
        self.assertTrue(self.lanes[1].scene_box().contains(self.step.scene_box().center()))
        self.assertFalse(self.sc.cff_option("title"))
        self.sc.cff_insert_phase()
        phase = self.sc.cff_parts("h")[2][0]
        with_band = self.lanes[0].scene_box().top()
        self.sc.cff_set_option("hidden", True)
        self.assertAlmostEqual(self.lanes[0].scene_box().top(), with_band - swimlanes.PHASE, places=3)
        self.sc.clearSelection()
        self.assertTrue(phase.shape().isEmpty())               # masqué : plus cliquable
        self.sc.cff_insert_phase()                                 # le nouveau séparateur reste masqué
        self.assertTrue(all(p.cff_opts.get("hidden") for p in self.sc.cff_parts("h")[2]))
        data = self.doc.to_dict()
        doc2 = Document(data)
        frame2 = doc2.pages[0].cff_parts("h")[0][0]
        self.assertFalse(frame2.cff_opts["title"])

    def test_new_separator_splits_phase_without_lengthening(self):
        width = self.lanes[0].scene_box().width()
        for _ in range(3):
            self.sc.cff_insert_phase()
        phases = sorted(self.sc.cff_parts("h")[2], key=lambda p: p.scene_box().left())
        self.assertEqual(len(phases), 3)
        self.assertAlmostEqual(self.lanes[0].scene_box().width(), width, places=3)
        for a, b in zip(phases, phases[1:]):
            self.assertAlmostEqual(a.scene_box().right(), b.scene_box().left(), places=3)
        self.assertAlmostEqual(phases[-1].scene_box().right(), self.lanes[0].scene_box().right(), places=3)

    def test_rotate_labels_and_styles(self):
        self.assertTrue(self.lanes[0].vertical_text())
        self.sc.cff_set_option("rotate", True)
        self.assertFalse(self.lanes[0].vertical_text())
        self.sc.cff_insert_lane()
        newest = max(self.sc.cff_parts("h")[1], key=lambda s: s.scene_box().top())
        self.assertTrue(newest.cff_opts.get("rotate"))
        preset = swimlanes.STYLES[1]
        self.sc.cff_apply_style(preset)
        frame = self.sc.cff_parts("h")[0][0]
        self.assertEqual(frame.style["fill"], preset["title_fill"])
        self.assertEqual(frame.text_style["color"], preset["title_text"])
        self.assertEqual(self.lanes[2].style["fill"], preset["lane_fill"])

    def test_vsdx_container_relationships(self):
        path = os.path.join(tempfile.mkdtemp(), "rel.vsdx")
        vsdx.export_vsdx(self.doc, path)
        import re
        import zipfile
        with zipfile.ZipFile(path) as z:
            xml = z.read("visio/pages/page1.xml").decode()
        self.assertEqual(xml.count('N="msvStructureType"'), 4)    # cadre + 3 couloirs
        rels = re.findall(r'N="Relationships" V="0" F="([^"]+)"', xml)
        self.assertTrue(any(r.startswith("SUM(DEPENDSON(4,Sheet.") and r.count("Sheet.") == 2 for r in rels), rels)
        self.assertTrue(any("DEPENDSON(1," in r and "DEPENDSON(4," in r for r in rels), rels)  # couloir
        data, _w = vsdx.import_vsdx(path)
        self.assertEqual(sum(s["type"] == "cff.lane_h" for s in data["pages"][0]["shapes"]), 3)

    def test_ribbon_reflects_options(self):
        w = self.ctx.new_window(Document(templates.build("cff")))
        self.app.processEvents()
        self.assertTrue(w.a["cff_dir_h"].isChecked())
        self.assertTrue(w.a["cff_title"].isChecked())
        w._cff_checks["cff_title"].setChecked(False)
        self.assertFalse(w.scene().cff_option("title"))
        w._cff_orientation("v")
        self.app.processEvents()
        self.assertTrue(w.a["cff_dir_v"].isChecked())
        self.assertFalse(w._cff_checks["cff_title"].isChecked())
        w.doc.undo_stack.setClean()
        w.close()
