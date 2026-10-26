"""Mise en forme des connecteurs : épaisseur, tirets et flèches, comme dans Visio."""

import unittest
from unittest import mock

from PyQt6.QtCore import QPointF
from PyQt6.QtWidgets import QMenu

from tests.helpers import qapp

from linxdiagram import app as appmod
from linxdiagram.document import Document
from linxdiagram.widgets import ColorButton


class ConnectorFormatTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = qapp()
        appmod.apply_theme(cls.app, False)
        cls.ctx = appmod.AppContext(cls.app)

    def setUp(self):
        self.w = self.ctx.new_window(Document())
        self.w.hide_backstage()
        self.sc = self.w.scene()
        a = self.sc.add_shape("flow.process", QPointF(200, 200))
        b = self.sc.add_shape("flow.process", QPointF(420, 200))
        st = self.sc.new_connector_state({"shape": a.id, "port": -1, "x": 0, "y": 0},
                                         {"shape": b.id, "port": -1, "x": 0, "y": 0})
        self.sc.add_states([st], "Connecter")
        self.conn = self.sc.item_by_id(st["id"])
        self.sc.select_items([self.conn])

    def tearDown(self):
        self.w.doc.undo_stack.setClean()
        self.w.close()
        self.app.processEvents()

    def test_weight_from_menu_and_undo(self):
        before = self.conn.style["line_width"]
        weights = self.w._weight_menu()
        act = next(a for a in weights.actions() if a.text() == "3 pt")
        act.trigger()
        self.assertAlmostEqual(self.conn.style["line_width"], 4.0)
        self.w._check_current_weight(weights)
        self.assertTrue(act.isChecked())
        self.w.doc.undo_stack.undo()
        self.assertAlmostEqual(self.conn.style["line_width"], before)

    def test_custom_weight(self):
        with mock.patch("linxdiagram.mainwindow.QInputDialog.getDouble", return_value=(7.5, True)):
            self.w.custom_line_weight()
        self.assertAlmostEqual(self.conn.style["line_width"], 10.0)

    def test_mini_toolbar_line_menu_has_weight_and_arrows(self):
        menu = QMenu()
        widget = self.w._mini_toolbar(menu).defaultWidget()
        line = next(b for b in widget.findChildren(ColorButton) if "Trait" in b.toolTip() or b.text() == "Trait")
        titles = [a.text() for a in line.menu().actions() if a.menu() is not None]
        self.assertIn("Épaisseur", titles)
        self.assertIn("Flèches", titles)


if __name__ == "__main__":
    unittest.main()
