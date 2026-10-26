"""Zone de dessin : vue zoomable, règles graduées, vue « Panoramique et zoom »."""

from __future__ import annotations

import math
import os

from PyQt6.QtCore import QPoint, QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPen, QTransform
from PyQt6.QtWidgets import QFrame, QGraphicsView, QGridLayout, QWidget

from .items import ConnectorItem, ShapeItem
from .scene import paint_canvas_backdrop
from .units import PX_PER_MM

STENCIL_MIME = "application/x-linxdiagram-stencil"
MIN_ZOOM, MAX_ZOOM = 0.1, 8.0


class DiagramView(QGraphicsView):
    zoomChanged = pyqtSignal(float)
    viewChanged = pyqtSignal()
    mouseScenePos = pyqtSignal(QPointF)
    contextMenuRequested = pyqtSignal(QPoint)
    favoriteDropped = pyqtSignal(int, QPointF)
    imageDropped = pyqtSignal(str, QPointF)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing
                            | QPainter.RenderHint.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setRubberBandSelectionMode(Qt.ItemSelectionMode.ContainsItemShape)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        # SmartViewportUpdate redraws only the changed areas for ordinary edits, then
        # falls back to a larger redraw when many regions change at once. This keeps
        # large diagrams responsive without leaving stale grid or guide pixels behind.
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.SmartViewportUpdate)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setAcceptDrops(True)
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._zoom = 1.0
        self._pan_origin: QPoint | None = None
        self._space = False
        self._view_states: dict[int, tuple[float, QPointF]] = {}

    # ------------------------------------------------------------------ pages
    def show_scene(self, scene) -> None:
        old = self.scene()
        if old is scene:
            return
        if old is not None:
            self._view_states[id(old)] = (self._zoom, self.mapToScene(self.viewport().rect().center()))
            old.clear_hover()
        self.setScene(scene)
        state = self._view_states.get(id(scene))
        if state is None:
            self.fit_page()
        else:
            self.set_zoom(state[0])
            self.centerOn(state[1])
        self.viewChanged.emit()

    def forget_scene(self, scene) -> None:
        self._view_states.pop(id(scene), None)

    # ------------------------------------------------------------------ zoom
    @property
    def zoom(self) -> float:
        return self._zoom

    def set_zoom(self, z: float, anchor_view: QPoint | None = None) -> None:
        z = min(max(z, MIN_ZOOM), MAX_ZOOM)
        if anchor_view is not None:
            before = self.mapToScene(anchor_view)
        else:
            center = self.mapToScene(self.viewport().rect().center())
        self._zoom = z
        self.setTransform(QTransform.fromScale(z, z))
        if anchor_view is not None:
            after = self.mapToScene(anchor_view)
            delta = after - before
            c = self.mapToScene(self.viewport().rect().center()) - delta
            self.centerOn(c)
        else:
            self.centerOn(center)
        sc = self.scene()
        if sc is not None:
            sc.set_view_scale(z)
        self.zoomChanged.emit(z)
        self.viewChanged.emit()

    def zoom_by(self, factor: float, anchor_view: QPoint | None = None) -> None:
        self.set_zoom(self._zoom * factor, anchor_view)

    def fit_rect(self, rect: QRectF, margin: float = 24) -> None:
        if rect.isNull() or self.viewport().width() < 10:
            return
        vw = max(self.viewport().width() - 2 * margin, 50)
        vh = max(self.viewport().height() - 2 * margin, 50)
        z = min(vw / rect.width(), vh / rect.height())
        self.set_zoom(z)
        self.centerOn(rect.center())
        self.viewChanged.emit()

    def fit_page(self) -> None:
        sc = self.scene()
        if sc is not None:
            self.fit_rect(sc.page_rect())

    def fit_width(self) -> None:
        sc = self.scene()
        if sc is None:
            return
        r = sc.page_rect()
        z = (self.viewport().width() - 48) / r.width()
        self.set_zoom(z)
        self.centerOn(QPointF(r.center().x(), self.mapToScene(self.viewport().rect().center()).y()))

    # ------------------------------------------------------------------ événements
    def wheelEvent(self, event):  # noqa: N802
        mods = event.modifiers()
        delta = event.angleDelta().y() or event.angleDelta().x()
        if mods & Qt.KeyboardModifier.ControlModifier:
            steps = delta / 120.0
            self.zoom_by(1.15 ** steps, event.position().toPoint())
            event.accept()
            return
        if mods & Qt.KeyboardModifier.ShiftModifier:
            bar = self.horizontalScrollBar()
            bar.setValue(bar.value() - delta)
            event.accept()
            return
        super().wheelEvent(event)

    def scrollContentsBy(self, dx, dy):  # noqa: N802
        super().scrollContentsBy(dx, dy)
        self.viewChanged.emit()

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        self.viewChanged.emit()

    def _start_pan(self, pos: QPoint) -> None:
        self._pan_origin = pos
        self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.MouseButton.MiddleButton or (
                event.button() == Qt.MouseButton.LeftButton and self._space):
            self._start_pan(event.position().toPoint())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):  # noqa: N802
        pos = event.position().toPoint()
        if self._pan_origin is not None:
            d = pos - self._pan_origin
            self._pan_origin = pos
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - d.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - d.y())
            event.accept()
            return
        super().mouseMoveEvent(event)
        sc = self.scene()
        sp = self.mapToScene(pos)
        self.mouseScenePos.emit(sp)
        if sc is not None and not (event.buttons() & Qt.MouseButton.LeftButton and
                                   self.dragMode() == QGraphicsView.DragMode.RubberBandDrag and
                                   sc.mouseGrabberItem() is None and sc._conn_drag is None):
            cursor = Qt.CursorShape.OpenHandCursor if self._space else sc.cursor_for(sp)
            self.viewport().setCursor(cursor)

    def mouseReleaseEvent(self, event):  # noqa: N802
        if self._pan_origin is not None:
            self._pan_origin = None
            self.viewport().setCursor(Qt.CursorShape.OpenHandCursor if self._space
                                      else Qt.CursorShape.ArrowCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event):  # noqa: N802
        sc = self.scene()
        if sc is not None and sc._conn_drag is None:
            sc.clear_hover()
        super().leaveEvent(event)

    def keyPressEvent(self, event):  # noqa: N802
        sc = self.scene()
        if sc is None:
            return super().keyPressEvent(event)
        if sc.editing_item is not None:
            return super().keyPressEvent(event)
        key = event.key()
        mods = event.modifiers()
        if key == Qt.Key.Key_Space and not event.isAutoRepeat():
            self._space = True
            self.viewport().setCursor(Qt.CursorShape.OpenHandCursor)
            return
        if key in (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Up, Qt.Key.Key_Down):
            step = 1.0 if mods & Qt.KeyboardModifier.ShiftModifier else sc.grid_px
            dx = {Qt.Key.Key_Left: -step, Qt.Key.Key_Right: step}.get(key, 0.0)
            dy = {Qt.Key.Key_Up: -step, Qt.Key.Key_Down: step}.get(key, 0.0)
            sc.nudge(dx, dy)
            return
        if key == Qt.Key.Key_Escape:
            if sc.format_painter is not None:
                sc.format_painter = None
                sc.doc.formatPainterDone.emit()
            elif sc.doc.tool != "select":
                sc.doc.set_tool("select")
            else:
                sc.clearSelection()
            return
        single = sc.single_selected
        if key in (Qt.Key.Key_F2, Qt.Key.Key_Return, Qt.Key.Key_Enter) and single is not None:
            single.start_edit(select_all=key != Qt.Key.Key_F2)
            return
        text = event.text()
        if single is not None and isinstance(single, (ShapeItem, ConnectorItem)) and text and \
                text.isprintable() and not (mods & (Qt.KeyboardModifier.ControlModifier |
                                                    Qt.KeyboardModifier.AltModifier |
                                                    Qt.KeyboardModifier.MetaModifier)):
            # Comme dans Visio : taper au clavier remplace le texte de la forme sélectionnée.
            single.start_edit(select_all=True)
            cursor = single.label.textCursor()
            cursor.insertText(text)
            single.label.setTextCursor(cursor)
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):  # noqa: N802
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            self._space = False
            self.viewport().setCursor(Qt.CursorShape.ArrowCursor)
            return
        super().keyReleaseEvent(event)

    def focusOutEvent(self, event):  # noqa: N802
        self._space = False
        super().focusOutEvent(event)

    def contextMenuEvent(self, event):  # noqa: N802
        sc = self.scene()
        if sc is None:
            return
        sp = self.mapToScene(event.pos())
        if sc.editing_item is not None and sc.editing_item.label.sceneBoundingRect().contains(sp):
            super().contextMenuEvent(event)
            return
        item = sc.top_item_at(sp)
        if item is not None and not item.isSelected():
            sc.select_items([item])
        elif item is None:
            sc.clearSelection()
        self.contextMenuRequested.emit(event.globalPos())

    # ------------------------------------------------------------------ glisser-déposer
    def _accepts(self, mime) -> bool:
        if mime.hasFormat(STENCIL_MIME):
            return True
        if mime.hasUrls():
            return any(u.isLocalFile() and u.toLocalFile().lower().endswith((".png", ".jpg", ".jpeg"))
                       for u in mime.urls())
        return False

    def dragEnterEvent(self, event):  # noqa: N802
        if self._accepts(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):  # noqa: N802
        if self._accepts(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):  # noqa: N802
        sc = self.scene()
        mime = event.mimeData()
        pos = self.mapToScene(event.position().toPoint())
        if sc is None:
            return
        if mime.hasFormat(STENCIL_MIME):
            type_id = bytes(mime.data(STENCIL_MIME)).decode("ascii", "ignore")
            from . import favorites, stencils
            fav = favorites.Favorites.index_of(type_id)
            if fav is not None:
                self.favoriteDropped.emit(fav, pos)
                self.setFocus()
            elif type_id in stencils.SHAPES:
                sc.add_shape(type_id, pos)
                self.setFocus()
            event.acceptProposedAction()
            return
        for u in mime.urls():
            if u.isLocalFile():
                path = u.toLocalFile()
                if os.path.splitext(path)[1].lower() in (".png", ".jpg", ".jpeg"):
                    self.imageDropped.emit(path, pos)
                    break
        event.acceptProposedAction()


class Ruler(QWidget):
    """Règle graduée en millimètres, alignée sur la page (comme dans Visio)."""

    SIZE = 20

    def __init__(self, view: DiagramView, horizontal: bool):
        super().__init__()
        self.view = view
        self.horizontal = horizontal
        self.marker: float | None = None
        if horizontal:
            self.setFixedHeight(self.SIZE)
        else:
            self.setFixedWidth(self.SIZE)
        view.viewChanged.connect(self.update)
        view.mouseScenePos.connect(self._mouse)

    def _mouse(self, p: QPointF) -> None:
        self.marker = p.x() if self.horizontal else p.y()
        self.update()

    # Comme dans Visio : faire glisser depuis une règle crée un repère sur la page.
    def _scene_point(self, global_pos) -> tuple[QPointF, bool]:
        vp = self.view.viewport()
        local = vp.mapFromGlobal(global_pos)
        return self.view.mapToScene(local), vp.rect().contains(local)

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self.view.scene() is not None:
            self._dragging = True
            self.setCursor(Qt.CursorShape.SplitVCursor if self.horizontal else Qt.CursorShape.SplitHCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):  # noqa: N802
        sc = self.view.scene()
        if getattr(self, "_dragging", False) and sc is not None:
            p, inside = self._scene_point(event.globalPosition().toPoint())
            p = sc.snap_point(p)
            sc.guide_preview = {"o": "h", "pos": p.y()} if self.horizontal else {"o": "v", "pos": p.x()}
            if not inside:
                sc.guide_preview = None
            sc.update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):  # noqa: N802
        sc = self.view.scene()
        if getattr(self, "_dragging", False) and sc is not None:
            self._dragging = False
            self.unsetCursor()
            preview, sc.guide_preview = sc.guide_preview, None
            if preview is not None:
                sc.add_guide(preview["o"], preview["pos"])
            sc.update()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        pal = self.palette()
        p.fillRect(self.rect(), pal.window())
        sc = self.view.scene()
        if sc is None:
            return
        z = self.view.zoom
        page = sc.page_rect()
        origin = self.view.mapFromScene(page.topLeft())
        length = self.width() if self.horizontal else self.height()
        o = origin.x() if self.horizontal else origin.y()
        page_len = (page.width() if self.horizontal else page.height()) * z
        # fond blanc sur l'étendue de la page
        if self.horizontal:
            p.fillRect(QRectF(o, 0, page_len, self.SIZE), pal.base())
        else:
            p.fillRect(QRectF(0, o, self.SIZE, page_len), pal.base())
        px_per_mm = PX_PER_MM * z
        step_mm = 1
        for candidate in (1, 2, 5, 10, 20, 50, 100, 200, 500, 1000):
            if candidate * px_per_mm >= 6:
                step_mm = candidate
                break
        label_every = step_mm * (10 if step_mm in (1, 10, 100) else 5 if step_mm in (2, 20, 200) else 2)
        while label_every * px_per_mm < 40:
            label_every *= 2
        first = math.floor(-o / px_per_mm / step_mm) * step_mm
        last = math.ceil((length - o) / px_per_mm)
        font = QFont(self.font())
        font.setPixelSize(9)
        p.setFont(font)
        ink = pal.windowText().color()
        p.setPen(QPen(ink, 1))
        mm = first
        while mm <= last:
            pos = o + mm * px_per_mm
            major = mm % label_every == 0
            mid = not major and mm % (label_every / 2) == 0
            size = self.SIZE * (0.7 if major else 0.45 if mid else 0.25)
            if self.horizontal:
                p.drawLine(QPointF(pos, self.SIZE), QPointF(pos, self.SIZE - size))
                if major:
                    p.drawText(QPointF(pos + 2, 9), f"{mm:g}")
            else:
                p.drawLine(QPointF(self.SIZE, pos), QPointF(self.SIZE - size, pos))
                if major:
                    p.save()
                    p.translate(9, pos + 2)
                    p.rotate(90)
                    p.drawText(QPointF(0, 0), f"{mm:g}")
                    p.restore()
            mm += step_mm
        if self.marker is not None:
            mp = self.view.mapFromScene(QPointF(self.marker, self.marker))
            v = mp.x() if self.horizontal else mp.y()
            p.setPen(QPen(QColor("#2563eb"), 1, Qt.PenStyle.DashLine))
            if self.horizontal:
                p.drawLine(QPointF(v, 0), QPointF(v, self.SIZE))
            else:
                p.drawLine(QPointF(0, v), QPointF(self.SIZE, v))
        p.setPen(QPen(pal.mid().color(), 1))
        if self.horizontal:
            p.drawLine(0, self.SIZE - 1, self.width(), self.SIZE - 1)
        else:
            p.drawLine(self.SIZE - 1, 0, self.SIZE - 1, self.height())


class CanvasArea(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.view = DiagramView()
        self.hruler = Ruler(self.view, True)
        self.vruler = Ruler(self.view, False)
        corner = QWidget()
        corner.setFixedSize(Ruler.SIZE, Ruler.SIZE)
        lay = QGridLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(corner, 0, 0)
        lay.addWidget(self.hruler, 0, 1)
        lay.addWidget(self.vruler, 1, 0)
        lay.addWidget(self.view, 1, 1)
        self._corner = corner

    def set_rulers_visible(self, on: bool) -> None:
        for w in (self.hruler, self.vruler, self._corner):
            w.setVisible(on)


class _OverviewViewport(QWidget):
    is_overview = True


class OverviewView(QGraphicsView):
    """Panneau « Panoramique et zoom » : vue d'ensemble cliquable."""

    def __init__(self, main: DiagramView):
        super().__init__()
        self.main = main
        self.setViewport(_OverviewViewport())
        self.setRenderHints(QPainter.RenderHint.Antialiasing)
        self.setInteractive(False)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setMinimumHeight(140)
        main.viewChanged.connect(self._sync)

    def _sync(self) -> None:
        sc = self.main.scene()
        if sc is not self.scene():
            self.setScene(sc)
        if sc is not None:
            r = sc.page_rect().united(sc.drawing_rect() if sc.all_items() else sc.page_rect())
            self.fitInView(r.adjusted(-20, -20, 20, 20), Qt.AspectRatioMode.KeepAspectRatio)
        self.viewport().update()

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        self._sync()

    def drawBackground(self, painter, rect):  # noqa: N802
        sc = self.scene()
        paint_canvas_backdrop(painter, rect)
        if sc is not None:
            painter.fillRect(sc.page_rect(), QColor(sc.page_bg))

    def drawForeground(self, painter, rect):  # noqa: N802
        visible = self.main.mapToScene(self.main.viewport().rect()).boundingRect()
        s = self.transform().m11() or 1
        painter.setPen(QPen(QColor("#dc2626"), 2 / s))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(visible)

    def _center_main(self, pos) -> None:
        self.main.centerOn(self.mapToScene(pos))

    def mousePressEvent(self, event):  # noqa: N802
        self._center_main(event.position().toPoint())

    def mouseMoveEvent(self, event):  # noqa: N802
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._center_main(event.position().toPoint())

    def wheelEvent(self, event):  # noqa: N802
        event.ignore()

