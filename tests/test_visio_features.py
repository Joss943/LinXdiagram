"""Fonctions Visio ajoutées : styles rapides, modifier la forme, calques, verrouillage,
commentaires, vérification, bordures, données CSV, sous-processus, sauts de ligne…"""

import os
import tempfile
import unittest

from PyQt6.QtCore import QPointF

from tests.helpers import qapp

from linxdiagram import app as appmod, datavis, quickstyles, templates, vsdx
from linxdiagram.document import Document
from linxdiagram.presentation import PresentationView


class VisioFeaturesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = qapp()
        appmod.apply_theme(cls.app, False)
        cls.ctx = appmod.AppContext(cls.app)

    def setUp(self):
        self.w = self.ctx.new_window(Document(templates.build("sample")))
        self.w.hide_backstage()
        self.sc = self.w.scene()
        self.doc = self.w.doc

    def tearDown(self):
        self.doc.undo_stack.setClean()
        self.w.close()
        self.app.processEvents()

    def test_ribbon_is_like_visio(self):
        tabs = [t for t, b in self.w.ribbon.tab_buttons.items() if not b.isHidden()]
        self.assertEqual(tabs, ["Accueil", "Insertion", "Création", "Données", "Processus", "Révision",
                                "Affichage", "Développeur", "Aide"])
        if not self.w.native_frame:  # barre de titre native par défaut sous macOS
            self.assertIsNotNone(self.w.titlebar)

    def test_quick_style_and_undo(self):
        s = self.sc.item_by_id("s2")
        self.sc.select_items([s])
        self.w._apply_quick_style((0, quickstyles.ACCENTS[1]))
        self.assertEqual(s.style["fill"], "#ffffff")
        self.assertEqual(s.style["line"], quickstyles.ACCENTS[1])
        self.doc.undo_stack.undo()
        self.assertEqual(s.style["fill"], "#5b9bd5")

    def test_change_shape_keeps_text_and_connections(self):
        s = self.sc.item_by_id("s2")
        n_conn = len(self.sc.connectors_of("s2"))
        self.sc.select_items([s])
        self.sc.change_shape("flow.decision")
        self.assertEqual(s.type_id, "flow.decision")
        self.assertEqual(s.text, "Vérifier le stock")
        self.assertEqual(len(self.sc.connectors_of("s2")), n_conn)
        self.doc.undo_stack.undo()
        self.assertEqual(s.type_id, "flow.process")

    def test_select_by_type(self):
        self.assertEqual(self.sc.select_by_type("connectors"), 8)
        self.assertEqual(self.sc.select_by_type("text"), 1)

    def test_layers_hide_and_lock(self):
        s = self.sc.item_by_id("s7")
        before = self.sc.page_props()
        from linxdiagram.commands import PageCommand
        self.doc.undo_stack.push(PageCommand(self.doc, "c", scene=self.sc, before=before, after=dict(
            before, layers=[{"name": "Logistique", "visible": True, "locked": True, "printable": False}])))
        self.sc.assign_layer([s], "Logistique")
        self.assertTrue(s.isVisible())
        self.assertFalse(s.flags() & s.GraphicsItemFlag.ItemIsSelectable)
        self.assertIn(s, self.sc.hidden_for_print())
        before = self.sc.page_props()
        self.doc.undo_stack.push(PageCommand(self.doc, "c", scene=self.sc, before=before, after=dict(
            before, layers=[{"name": "Logistique", "visible": False, "locked": False, "printable": True}])))
        self.assertFalse(s.isVisible())

    def test_locked_shape_cannot_be_deleted_or_moved(self):
        s = self.sc.item_by_id("s4")
        self.sc.set_locked([s], True)
        self.sc.select_items([s])
        self.sc.delete_selection()
        self.assertIsNotNone(self.sc.item_by_id("s4"))
        self.assertFalse(s.flags() & s.GraphicsItemFlag.ItemIsMovable)
        self.assertIsNone(s.handle_at(s.scenePos()))

    def test_comments(self):
        s = self.sc.item_by_id("s3")
        self.sc.add_comment(s, "À valider avec la logistique", "Camille")
        self.assertEqual(s.comments[0]["text"], "À valider avec la logistique")
        self.assertEqual(self.sc.commented_shapes(), [s])
        self.sc.delete_comment(s, 0)
        self.assertEqual(s.comments, [])

    def test_check_diagram(self):
        issues = self.sc.check_diagram()
        self.assertFalse(any(k == "Erreur" for k, _t, _i in issues))
        free = self.sc.new_connector_state({"shape": "", "port": -1, "x": 0, "y": 0},
                                           {"shape": "s1", "port": -1, "x": 0, "y": 0})
        self.sc.add_states([free], "c")
        self.sc.add_shape("flow.process", QPointF(600, 900))
        issues = self.sc.check_diagram()
        kinds = [k for k, _t, _i in issues]
        self.assertIn("Erreur", kinds)
        self.assertIn("Avertissement", kinds)

    def test_borders_and_titles(self):
        n = len(self.sc.shapes())
        self.sc.add_border_title("band", "Mon titre")
        added = [s for s in self.sc.shapes() if s.text == "Mon titre"]
        self.assertEqual(len(added), 1)
        self.assertTrue(added[0].locked)
        self.assertGreater(len(self.sc.shapes()), n)

    def test_data_visualizer_org_and_flow(self):
        csv_org = "ID;Nom;Fonction;Responsable\n1;Alice;PDG;\n2;Bob;Ventes;1\n3;Chloé;Achats;1\n4;Dan;Vendeur;2\n"
        h, rows = datavis.parse_csv(csv_org.encode())
        page = datavis.build_page("org", h, rows, "Org", "office")
        self.assertEqual(len(page["shapes"]), 4)
        self.assertEqual(len(page["connectors"]), 3)
        top = next(s for s in page["shapes"] if s["text"].startswith("Alice"))
        dan = next(s for s in page["shapes"] if s["text"].startswith("Dan"))
        self.assertLess(top["y"], dan["y"])
        csv_flow = "ID,Description,Type,Suivant\nA,Début,Début,B\nB,Saisir,Processus,C\nC,OK ?,Décision,B;D\nD,Fin,Fin,\n"
        h, rows = datavis.parse_csv(csv_flow.encode())
        page = datavis.build_page("flow", h, rows, "Flux", "office")
        types = {s["text"]: s["type"] for s in page["shapes"]}
        self.assertEqual(types["OK ?"], "flow.decision")
        self.assertEqual(len(page["connectors"]), 4)
        with self.assertRaises(datavis.DataError):
            datavis.build_page("org", ["Foo"], [["x"]], "X", "office")

    def test_subprocess(self):
        a, b = self.sc.item_by_id("s4"), self.sc.item_by_id("s7")
        self.sc.select_items([a, b])
        self.w.create_subprocess()
        self.assertEqual(len(self.doc.pages), 2)
        sub = [s for s in self.sc.shapes() if s.type_id == "flow.subprocess"]
        self.assertEqual(len(sub), 1)
        self.assertTrue(sub[0].link.startswith("page:"))
        self.assertIsNone(self.sc.item_by_id("s4"))
        self.assertEqual(len(self.doc.pages[1].shapes()), 2)
        for _ in range(6):
            self.doc.undo_stack.undo()
        self.assertEqual(len(self.doc.pages), 1)
        self.assertIsNotNone(self.sc.item_by_id("s4"))

    def test_line_jumps(self):
        doc = Document()
        sc = doc.pages[0]
        a = sc.add_shape("basic.rectangle", QPointF(100, 300))
        b = sc.add_shape("basic.rectangle", QPointF(600, 300))
        c = sc.add_shape("basic.rectangle", QPointF(350, 100))
        d = sc.add_shape("basic.rectangle", QPointF(350, 500))
        vert = sc.new_connector_state({"shape": c.id, "port": 2, "x": 0, "y": 0},
                                      {"shape": d.id, "port": 0, "x": 0, "y": 0})
        sc.add_states([vert], "v")
        hor = sc.new_connector_state({"shape": a.id, "port": 1, "x": 0, "y": 0},
                                     {"shape": b.id, "port": 3, "x": 0, "y": 0})
        sc.add_states([hor], "h")
        sc._refresh_jumps()
        h = sc.item_by_id(hor["id"])
        self.assertGreater(h._path.elementCount(), 3, "un saut de ligne doit être dessiné")
        doc.settings["line_jumps"] = False
        sc._refresh_jumps()
        self.assertEqual(h._path.elementCount(), 2)

    def test_auto_size(self):
        sc = self.sc
        before = sc.page_props()
        from linxdiagram.commands import PageCommand
        self.doc.undo_stack.push(PageCommand(self.doc, "a", scene=sc, before=before,
                                             after=dict(before, auto_size=True)))
        sc.add_shape("basic.rectangle", QPointF(sc.page_w + 300, 200))
        w0 = sc.page_w
        sc.maybe_auto_size()
        self.assertGreater(sc.page_w, w0)

    def test_vsdx_keeps_layers_locks_tips(self):
        s = self.sc.item_by_id("s2")
        self.sc.set_locked([s], True)
        self.sc.set_tip(s, "Contrôle du stock")
        from linxdiagram.commands import PageCommand
        before = self.sc.page_props()
        self.doc.undo_stack.push(PageCommand(self.doc, "c", scene=self.sc, before=before, after=dict(
            before, layers=[{"name": "Flux", "visible": True, "locked": False, "printable": True}])))
        self.sc.assign_layer([s], "Flux")
        path = os.path.join(tempfile.mkdtemp(), "t.vsdx")
        vsdx.export_vsdx(self.doc, path)
        data, _w = vsdx.import_vsdx(path)
        page = data["pages"][0]
        imported = next(x for x in page["shapes"] if x["text"] == "Vérifier le stock")
        self.assertTrue(imported["locked"])
        self.assertEqual(imported["tip"], "Contrôle du stock")
        self.assertEqual(imported["layer"], "Flux")
        self.assertEqual(page["layers"][0]["name"], "Flux")

    def test_presentation_navigation(self):
        self.w.add_page()
        view = PresentationView(self.doc, 0)
        view.go(1)
        self.assertEqual(view.index, 1)
        view.go(5)
        self.assertEqual(view.index, 1)
        self.assertTrue(self.doc.pages[1].exporting)
        view.close()
        self.app.processEvents()
        self.assertFalse(any(p.exporting for p in self.doc.pages))

    def test_command_search_runs_actions(self):
        box = self.w.search_box
        self.assertIn("Grouper", box._entries)
        self.sc.select_items([self.sc.item_by_id("s4"), self.sc.item_by_id("s7")])
        box._run("grouper")
        self.assertTrue(self.sc.item_by_id("s4").group)
        n = len(self.sc.shapes())
        box._run("Insérer la forme : Décision")
        self.assertEqual(len(self.sc.shapes()), n + 1)

    def test_find_replace(self):
        from linxdiagram.dialogs import FindReplaceDialog
        dlg = FindReplaceDialog(self.w, self.w, replace=True)
        dlg.find.setText("commande")
        dlg.repl.setText("demande")
        dlg._replace_all()
        texts = [s.text for s in self.sc.shapes()]
        self.assertIn("demande reçue", texts)
        self.doc.undo_stack.undo()
        self.assertIn("Commande reçue", [s.text for s in self.sc.shapes()])


if __name__ == "__main__":
    unittest.main()
