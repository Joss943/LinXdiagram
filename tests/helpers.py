from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QApplication

_app = None


def qapp() -> QApplication:
    global _app
    _app = QApplication.instance() or QApplication(["tests"])
    from linxdiagram import app as appmod
    appmod._pick_default_font()
    return _app


def hover(widget, pos) -> None:
    """Survol sans bouton enfoncé. QTest.mouseMove passe dans ce cas par QCursor.setPos, qui
    n'émet aucun événement avec la plateforme « offscreen » de Windows et de macOS."""
    local = QPointF(pos)
    ev = QMouseEvent(QMouseEvent.Type.MouseMove, local, QPointF(widget.mapToGlobal(pos)),
                     Qt.MouseButton.NoButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(widget, ev)
    QApplication.processEvents()
