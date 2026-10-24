"""Mode Présentation (Affichage > Plein écran) : une page à la fois, plein écran."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import QFrame, QGraphicsView

from .items import ShapeItem


class PresentationView(QGraphicsView):
    def __init__(self, doc, index: int = 0):
        super().__init__()
        self.doc = doc
        self.index = index
        self.setWindowTitle("Présentation")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing
                            | QPainter.RenderHint.SmoothPixmapTransform)
        self.setInteractive(False)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self._show()

    def _show(self) -> None:
        sc = self.doc.pages[self.index]
        for p in self.doc.pages:
            p.exporting = p is sc
        sc.clearSelection()
        self.setScene(sc)
        self.fitInView(sc.page_rect(), Qt.AspectRatioMode.KeepAspectRatio)

    def resizeEvent(self, e):  # noqa: N802
        super().resizeEvent(e)
        if self.scene() is not None:
            self.fitInView(self.scene().page_rect(), Qt.AspectRatioMode.KeepAspectRatio)

    def drawBackground(self, painter, rect):  # noqa: N802
        painter.fillRect(rect, QColor("#000000"))
        sc = self.scene()
        if sc is not None:
            painter.fillRect(sc.page_rect(), QColor(sc.page_bg))

    def drawForeground(self, painter, rect):  # noqa: N802
        pass

    def go(self, step: int) -> None:
        n = len(self.doc.pages)
        new = min(max(self.index + step, 0), n - 1)
        if new != self.index:
            self.index = new
            self._show()

    def keyPressEvent(self, e):  # noqa: N802
        k = e.key()
        if k in (Qt.Key.Key_Escape, Qt.Key.Key_F5):
            self.close()
        elif k in (Qt.Key.Key_Right, Qt.Key.Key_Down, Qt.Key.Key_PageDown, Qt.Key.Key_Space,
                   Qt.Key.Key_Return, Qt.Key.Key_N):
            self.go(1)
        elif k in (Qt.Key.Key_Left, Qt.Key.Key_Up, Qt.Key.Key_PageUp, Qt.Key.Key_Backspace, Qt.Key.Key_P):
            self.go(-1)
        elif k == Qt.Key.Key_Home:
            self.go(-len(self.doc.pages))
        elif k == Qt.Key.Key_End:
            self.go(len(self.doc.pages))

    def mousePressEvent(self, e):  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton:
            sp = self.mapToScene(e.position().toPoint())
            item = self.scene().top_item_at(sp) if self.scene() is not None else None
            if isinstance(item, ShapeItem) and item.link.startswith("page:"):
                name = item.link[5:]
                for i, p in enumerate(self.doc.pages):
                    if p.page_name == name:
                        self.index = i
                        self._show()
                        return
            self.go(1)
        elif e.button() == Qt.MouseButton.RightButton:
            self.go(-1)

    def closeEvent(self, e):  # noqa: N802
        for p in self.doc.pages:
            p.exporting = False
            p.update()
        super().closeEvent(e)
