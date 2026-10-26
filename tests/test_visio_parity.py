"""Export page web et portabilité Windows / macOS."""

import os
import sys
import tempfile
import unittest
from unittest import mock

from PyQt6.QtCore import QPointF

from tests.helpers import qapp

from linxdiagram import app as appmod, compat, export, fileformat, security, spellcheck
from linxdiagram.document import Document


class WebExportTest(unittest.TestCase):
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

    # ------------------------------------------------------------ export web
    def test_export_html(self):
        self._shape("basic.rectangle", 100, 100, "Bonjour <b>")
        self.w.add_page()
        self.assertTrue(self.w.a["export_html"].isEnabled())
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "dessin.html")
            export.export_html(self.doc.pages, path, "Titre & test")
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

    def test_spellcheck_dirs_per_platform(self):
        with mock.patch.object(compat, "IS_WINDOWS", True), mock.patch.object(compat, "IS_MACOS", False):
            self.assertFalse(any(d.startswith("/usr/share") for d in spellcheck.dict_dirs()))
        with mock.patch.object(compat, "IS_WINDOWS", False), mock.patch.object(compat, "IS_MACOS", True):
            self.assertIn("/opt/homebrew/share/hunspell", spellcheck.dict_dirs())
            self.assertIn("dictionnaires", spellcheck.install_hint())

    def test_encryption_round_trip(self):
        if not security.encryption_available():
            self.skipTest("aucune bibliothèque de chiffrement")
        blob = security.encrypt_payload(b"secret", "mot de passe")
        env = fileformat.parse_json(blob)
        self.assertEqual(security.decrypt_payload(env, "mot de passe"), b"secret")


if __name__ == "__main__":
    unittest.main()
