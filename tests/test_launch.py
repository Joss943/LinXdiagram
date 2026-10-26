"""Lancement réel de l'application et adaptation aux petits écrans (bugs vus sur un portable 1366×768)."""

import os
import subprocess
import sys
import tempfile
import unittest

from tests.helpers import qapp

from linxdiagram import app as appmod
from linxdiagram.document import Document

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class LaunchTest(unittest.TestCase):
    def test_launcher_starts_without_error(self):
        """Le lanceur du menu démarre sur l'écran d'accueil sans exception (plantage « KeyError: 0 »)."""
        home = tempfile.mkdtemp()
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen", HOME=home, XDG_CONFIG_HOME=home,
                   XDG_STATE_HOME=home, XDG_DATA_HOME=home, XDG_CACHE_HOME=home)
        code = ("import sys; sys.path.insert(0, %r)\n"
                "from PyQt6.QtCore import QTimer\n"
                "from PyQt6.QtWidgets import QApplication\n"
                "_exec = QApplication.exec\n"
                "def run(*_a):\n"
                "    QTimer.singleShot(1500, QApplication.quit)\n"
                "    return _exec()\n"
                "QApplication.exec = run\n"
                "from linxdiagram import app\n"
                "sys.exit(app.main(['linxdiagram']))\n" % ROOT)
        r = subprocess.run([sys.executable, "-I", "-c", code], env=env, capture_output=True, text=True,
                           timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("Traceback", r.stderr)


def _widest(window) -> str:
    """Diagnostic : les widgets qui imposent la plus grande largeur minimale."""
    from PyQt6.QtWidgets import QWidget
    rows = sorted(((max(c.minimumSizeHint().width(), c.minimumWidth()), type(c).__name__, c.objectName())
                   for c in window.findChildren(QWidget) if c.isVisibleTo(window)), reverse=True)
    return "; ".join(f"{name}#{obj}={w}" for w, name, obj in rows[:12])


class SmallScreenTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = qapp()
        appmod.apply_theme(cls.app, False)
        cls.ctx = appmod.AppContext(cls.app)

    def test_window_fits_a_laptop_screen(self):
        w = self.ctx.new_window(Document())
        self.assertLessEqual(w.minimumSizeHint().width(), 1000, _widest(w))
        w.resize(1366, 740)
        w.show()
        self.app.processEvents()
        self.assertLessEqual(w.width(), 1366)
        page = w.ribbon.pages["Accueil"]
        used = sum(g.width() for g in page.groups())
        self.assertLessEqual(used, page.width())
        w.resize(900, 700)
        self.app.processEvents()
        self.assertTrue(any(g.collapsed for g in page.groups()))     # groupes repliés comme Office
        g = next(g for g in page.groups() if g.collapsed)
        g._lend_content()
        self.assertTrue(g.inner.isVisible() or g.inner.parent() is g._holder)
        g._take_back_content()
        self.assertFalse(g.inner.isVisible())
        w.doc.undo_stack.setClean()
        w.close()
