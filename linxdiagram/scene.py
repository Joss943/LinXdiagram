"""Page de dessin : interactions à la souris, magnétisme, repères dynamiques,
connexion automatique (AutoConnect) et opérations d'édition annulables."""

from __future__ import annotations

import copy
import secrets

from PyQt6.QtCore import QLineF, QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen, QPolygonF
from PyQt6.QtWidgets import QApplication, QGraphicsScene

from . import fields, fileformat, layout, quickstyles, shapeops, stencils, swimlanes
from .commands import AddItemsCommand, RemoveItemsCommand, StateCommand, _shapes_first
from .items import ACCENT, GLUE, ConnectorItem, ShapeItem, TextLabel, make_item
from .units import GRID_PX, connector_style, connector_text_style, mm_to_px

PORT_TOL_PX = 9.0
GUIDE_TOL_PX = 7.0
AC_DIST_PX = 18.0
AC_SIZE_PX = 6.0
CANVAS_BG = QColor("#e7e9ec")
_DARK_CANVAS = False


def set_dark_canvas(dark: bool) -> None:
    """Fond autour de la page, assorti au thème de l'interface."""
    global _DARK_CANVAS
    _DARK_CANVAS = dark
    CANVAS_BG.setRgba(QColor("#2b2d31" if dark else "#e7e9ec").rgba())


def paint_canvas_backdrop(painter: QPainter, rect: QRectF) -> None:
    """Dégradé très doux derrière la feuille, inspiré des surfaces Mica de Visio 2024."""
    gradient = QLinearGradient(rect.topLeft(), rect.bottomLeft())
    gradient.setColorAt(0, CANVAS_BG.lighter(112 if _DARK_CANVAS else 105))
    gradient.setColorAt(1, CANVAS_BG.darker(106 if _DARK_CANVAS else 103))
    painter.fillRect(rect, gradient)
GRID_MINOR = QColor("#eceff3")
GRID_MAJOR = QColor("#d7dce3")
GUIDE = QColor("#d6336c")
GUIDE_RULER = QColor("#2f6fd6")  # repères tirés des règles
AC_DIRS = ((0, -1), (1, 0), (0, 1), (-1, 0))


def new_id() -> str:
    return secrets.token_hex(6)


def _simplify(pts: list, eps: float) -> list:
    """Ramer-Douglas-Peucker : moins de points pour un tracé à main levée."""
    if len(pts) < 3:
        return list(pts)
    a, b = pts[0], pts[-1]
    dx, dy = b.x() - a.x(), b.y() - a.y()
    norm = (dx * dx + dy * dy) ** 0.5
    best, idx = 0.0, 0
    for i in range(1, len(pts) - 1):
        p = pts[i]
        if norm < 1e-9:
            d = ((p.x() - a.x()) ** 2 + (p.y() - a.y()) ** 2) ** 0.5
        else:
            d = abs(dy * p.x() - dx * p.y() + b.x() * a.y() - b.y() * a.x()) / norm
        if d > best:
            best, idx = d, i
    if best <= eps:
        return [a, b]
    return _simplify(pts[:idx + 1], eps)[:-1] + _simplify(pts[idx:], eps)


class DiagramScene(QGraphicsScene):
    selectionInfo = pyqtSignal()
    autoconnectHover = pyqtSignal(object, int, QPointF)

    def __init__(self, doc, page: dict):
        super().__init__()
        self.doc = doc
        self.page_name = page["name"]
        self.page_w = page["width"]
        self.page_h = page["height"]
        self.page_bg = page["background"]
        self.auto_size = page.get("auto_size", False)
        self.layers: list[dict] = [dict(lay) for lay in page.get("layers", [])]
        # Repères tirés des règles (comme dans Visio) ; les formes s'y aimantent.
        self.ruler_guides: list[dict] = [dict(g) for g in page.get("guides", [])]
        # Pages d'arrière-plan (comme Visio) : une page de premier plan peut afficher derrière
        # son contenu celui d'une page marquée « arrière-plan ».
        self.is_background = bool(page.get("is_background", False))
        self.backpage = page.get("backpage", "")
        self._painting_back = False
        self.selected_guide: int | None = None
        self.guide_preview: dict | None = None
        self._guide_drag: dict | None = None
        self._items: dict[str, ShapeItem | ConnectorItem] = {}
        self._conn_index: dict[str, set[str]] = {}
        self._conn_ends: dict[str, tuple[str, str]] = {}
        self.view_scale = 1.0
        self.exporting = False
        self.editing_item = None
        self.single_selected = None
        self.interactive_move = False
        self.hover_shape: ShapeItem | None = None
        self.hover_port: int | None = None
        self.hover_arrow: int | None = None
        self.guides: list[QLineF] = []
        self.glue_target = None
        self.format_painter: dict | None = None
        self._press_states: dict | None = None
        self._press_pos: dict[str, QPointF] = {}
        self._press_mouse = QPointF()
        self._mouse = QPointF()
        self._snap_key = None
        self._snap_adj = QPointF()
        self._conn_drag: dict | None = None
        self._draw: dict | None = None
        self._jump_pending = False
        self._carry: dict[str, QPointF] = {}
        self._carry_anchor: tuple[str, QPointF] | None = None
        self._sel_order: list = []  # ordre de sélection : la première forme est la « principale »
        self.selectionChanged.connect(self._on_selection_changed)
        for st in page.get("shapes", []):
            self.add_item_from_state(st)
        for st in page.get("connectors", []):
            self.add_item_from_state(st)
        # Second passage : chaque connecteur dynamique voit les côtés déjà occupés.
        self.refresh_connectors()
        self.update_scene_rect()

    # ------------------------------------------------------------------ registre
    @property
    def snap_enabled(self) -> bool:
        return self.doc.settings["snap"]

    def item_by_id(self, item_id: str):
        return self._items.get(item_id)

    def shapes(self) -> list[ShapeItem]:
        return [i for i in self._items.values() if isinstance(i, ShapeItem)]

    def connectors(self) -> list[ConnectorItem]:
        return [i for i in self._items.values() if isinstance(i, ConnectorItem)]

    def all_items(self):
        return list(self._items.values())

    def connectors_of(self, shape_id: str) -> list[ConnectorItem]:
        return [self._items[c] for c in self._conn_index.get(shape_id, ()) if c in self._items]

    def reindex_connector(self, conn: ConnectorItem) -> None:
        self._unindex(conn.id)
        ends = (conn.src.get("shape", ""), conn.dst.get("shape", ""))
        self._conn_ends[conn.id] = ends
        for sid in ends:
            if sid:
                self._conn_index.setdefault(sid, set()).add(conn.id)

    def _unindex(self, cid: str) -> None:
        for sid in self._conn_ends.pop(cid, ()):
            if sid and sid in self._conn_index:
                self._conn_index[sid].discard(cid)

    def add_item_from_state(self, st: dict):
        item = make_item(st)
        self.addItem(item)
        self._items[item.id] = item
        if item.layer and self.layers:
            lay = self.layer(item.layer)
            if lay is not None:
                item.setVisible(lay["visible"])
                item.setFlag(item.GraphicsItemFlag.ItemIsSelectable, not lay["locked"])
        if isinstance(item, ConnectorItem):
            self.reindex_connector(item)
            item.update_path()
        else:
            item.notify_connectors()
        return item

    def remove_item_by_id(self, item_id: str) -> None:
        item = self._items.pop(item_id, None)
        if item is None:
            return
        if item is self.editing_item:
            item.editing = False
            self.editing_item = None
        if item is self.hover_shape:
            self.hover_shape = None
        if isinstance(item, ConnectorItem):
            self._unindex(item_id)
        self.removeItem(item)
        if isinstance(item, ShapeItem):
            for c in self.connectors_of(item_id):
                c.update_path()

    def refresh_connectors(self) -> None:
        for c in self.connectors():
            c.update_path()

    def request_jump_refresh(self) -> None:
        """Recalcule les sauts de ligne une fois la série de modifications terminée."""
        if self._jump_pending:
            return
        self._jump_pending = True
        QTimer.singleShot(0, self._refresh_jumps)

    def _refresh_jumps(self) -> None:
        self._jump_pending = False
        for c in self.connectors():
            c.rebuild_jumps()

    def next_z(self) -> float:
        return max((i.zValue() for i in self._items.values()), default=0.0) + 1.0

    def min_z(self) -> float:
        return min((i.zValue() for i in self._items.values()), default=0.0) - 1.0

    # ------------------------------------------------------------------ page
    def page_rect(self) -> QRectF:
        return QRectF(0, 0, self.page_w, self.page_h)

    def page_props(self) -> dict:
        return {"name": self.page_name, "width": self.page_w, "height": self.page_h,
                "background": self.page_bg, "auto_size": self.auto_size,
                "layers": [dict(lay) for lay in self.layers],
                "guides": [dict(g) for g in self.ruler_guides],
                "is_background": self.is_background, "backpage": self.backpage}

    def set_page_props(self, props: dict) -> None:
        self.page_name = props["name"]
        self.page_w = props["width"]
        self.page_h = props["height"]
        self.page_bg = props["background"]
        self.auto_size = props.get("auto_size", self.auto_size)
        self.layers = [dict(lay) for lay in props.get("layers", self.layers)]
        self.ruler_guides = [dict(g) for g in props.get("guides", self.ruler_guides)]
        self.is_background = props.get("is_background", self.is_background)
        self.backpage = props.get("backpage", self.backpage)
        if self.selected_guide is not None and self.selected_guide >= len(self.ruler_guides):
            self.selected_guide = None
        self.apply_layers()
        self.update_scene_rect()
        self.update()
        self.doc.pagesChanged.emit()

    def refresh_fields(self) -> None:
        """Met à jour les champs affichés (numéro de page, date…) après un changement."""
        for it in self._items.values():
            if fields.has_fields(it.text) and not it.editing:
                it.layout_label()

    # ------------------------------------------------------------------ repères
    def guide_at(self, pos: QPointF) -> int | None:
        tol = 4.0 / max(self.view_scale, 0.05)
        best = None
        for i, g in enumerate(self.ruler_guides):
            d = abs((pos.y() if g["o"] == "h" else pos.x()) - g["pos"])
            if d <= tol and (best is None or d < best[0]):
                best = (d, i)
        return best[1] if best else None

    def _set_guides(self, guides: list[dict], text: str) -> None:
        from .commands import PageCommand
        before = self.page_props()
        after = dict(before, guides=guides)
        self.doc.undo_stack.push(PageCommand(self.doc, text, scene=self, before=before, after=after))

    def add_guide(self, orientation: str, pos: float) -> None:
        self._set_guides(self.ruler_guides + [{"o": orientation, "pos": float(pos)}], "Ajouter un repère")
        self.selected_guide = len(self.ruler_guides) - 1

    def move_guide(self, index: int, pos: float) -> None:
        guides = [dict(g) for g in self.ruler_guides]
        guides[index]["pos"] = float(pos)
        self._set_guides(guides, "Déplacer un repère")

    def remove_guide(self, index: int) -> None:
        guides = [g for i, g in enumerate(self.ruler_guides) if i != index]
        self.selected_guide = None
        self._set_guides(guides, "Supprimer un repère")

    def _paint_ruler_guides(self, painter: QPainter, rect: QRectF) -> None:
        s = self.view_scale
        area = self.sceneRect().united(rect)
        for i, g in enumerate(self.ruler_guides):
            if self._guide_drag is not None and self._guide_drag["i"] == i:
                continue
            selected = i == self.selected_guide
            pen = QPen(GUIDE_RULER, (2.0 if selected else 1.0) / s,
                       Qt.PenStyle.SolidLine if selected else Qt.PenStyle.DashLine)
            painter.setPen(pen)
            if g["o"] == "h":
                painter.drawLine(QLineF(area.left(), g["pos"], area.right(), g["pos"]))
            else:
                painter.drawLine(QLineF(g["pos"], area.top(), g["pos"], area.bottom()))
        if self.guide_preview is not None:
            painter.setPen(QPen(GUIDE_RULER, 1.5 / s))
            g = self.guide_preview
            if g["o"] == "h":
                painter.drawLine(QLineF(area.left(), g["pos"], area.right(), g["pos"]))
            else:
                painter.drawLine(QLineF(g["pos"], area.top(), g["pos"], area.bottom()))

    # ------------------------------------------------------------------ calques
    def layer(self, name: str) -> dict | None:
        for lay in self.layers:
            if lay["name"] == name:
                return lay
        return None

    def apply_layers(self) -> None:
        """Visibilité et verrouillage des objets selon leur calque."""
        for it in self._items.values():
            lay = self.layer(it.layer) if it.layer else None
            visible = lay["visible"] if lay else True
            locked = lay["locked"] if lay else False
            it.setVisible(visible)
            it.setFlag(it.GraphicsItemFlag.ItemIsSelectable, not locked)
            if isinstance(it, ShapeItem):
                it.setFlag(it.GraphicsItemFlag.ItemIsMovable, not locked and not it.locked)
            if locked and it.isSelected():
                it.setSelected(False)

    def assign_layer(self, items, name: str) -> None:
        def lay(it, st):
            st["layer"] = name
        self.modify(items, lay, f"Affecter au calque « {name} »" if name else "Retirer du calque")

    def hidden_for_print(self) -> list:
        """Objets des calques non imprimables (masqués à l'export et à l'impression)."""
        out = []
        for it in self._items.values():
            lay = self.layer(it.layer) if it.layer else None
            if lay is not None and not lay["printable"] and it.isVisible():
                out.append(it)
        return out

    def drawing_rect(self) -> QRectF:
        r = QRectF()
        for it in self._items.values():
            if isinstance(it, ShapeItem):
                rect = it.visual_scene_rect()
            else:
                rect = it.mapRectToScene(it.boundingRect())
            r = rect if r.isNull() else r.united(rect)
        return r

    def update_scene_rect(self) -> None:
        r = self.page_rect()
        d = self.drawing_rect()
        if not d.isNull():
            r = r.united(d)
        m = max(self.page_w, self.page_h) * 0.6
        self.setSceneRect(r.adjusted(-m, -m, m, m))

    def to_dict(self) -> dict:
        items = sorted(self._items.values(), key=lambda i: i.zValue())
        return {**self.page_props(),
                "shapes": [i.state() for i in items if isinstance(i, ShapeItem)],
                "connectors": [i.state() for i in items if isinstance(i, ConnectorItem)]}

    # ------------------------------------------------------------------ dessin
    def backpage_scene(self):
        """Page d'arrière-plan affectée à cette page (None si aucune)."""
        if not self.backpage or self.is_background and self.backpage == self.page_name:
            return None
        for p in self.doc.pages:
            if p is not self and p.is_background and p.page_name == self.backpage:
                return p
        return None

    def _paint_backpage(self, painter: QPainter) -> None:
        bg = self.backpage_scene()
        if bg is None or bg._painting_back or self._painting_back:
            return
        from .export import exporting  # import local : évite un cycle au chargement
        self._painting_back = True
        try:
            with exporting(bg, transparent=True):
                src = bg.page_rect()
                bg.render(painter, QRectF(0, 0, src.width(), src.height()), src)
        finally:
            self._painting_back = False

    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:  # noqa: N802
        page = self.page_rect()
        if self.exporting:
            painter.fillRect(rect, QColor(self.page_bg))
            self._paint_backpage(painter)
            return
        paint_canvas_backdrop(painter, rect)
        s = self.view_scale
        painter.fillRect(page.translated(3 / s, 3 / s), QColor(0, 0, 0, 45))
        painter.fillRect(page, QColor(self.page_bg))
        self._paint_backpage(painter)
        if self.doc.settings["grid"]:
            area = rect.intersected(page)
            if not area.isEmpty():
                step = GRID_PX
                while step * s < 7:
                    step *= 2
                minor, major = [], []
                x = int(area.left() // step) * step
                i = int(round(x / step))
                while x <= area.right():
                    if x >= page.left():
                        (major if i % 2 == 0 else minor).append(QLineF(x, area.top(), x, area.bottom()))
                    x += step
                    i += 1
                y = int(area.top() // step) * step
                i = int(round(y / step))
                while y <= area.bottom():
                    if y >= page.top():
                        (major if i % 2 == 0 else minor).append(QLineF(area.left(), y, area.right(), y))
                    y += step
                    i += 1
                painter.setPen(QPen(GRID_MINOR, 0))
                painter.drawLines(minor)
                painter.setPen(QPen(GRID_MAJOR, 0))
                painter.drawLines(major)
        painter.setPen(QPen(QColor("#b9bec6"), 0))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(page)

    def drawForeground(self, painter: QPainter, rect: QRectF) -> None:  # noqa: N802
        if self.exporting:
            return
        s = self.view_scale
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self._draw is not None and self._draw["tool"] in ("freeform", "arc"):
            painter.setPen(QPen(ACCENT, 1.5 / s))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(self._draw_path(self._draw))
        elif self._draw is not None:
            if self._draw["tool"] == "pen":
                pen = QPen(ACCENT, 2 / s)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
                painter.setPen(pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawPath(self._draw["preview"])
            elif not self._draw["rect"].isNull():
                painter.setPen(QPen(ACCENT, 1 / s, Qt.PenStyle.DashLine))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                if self._draw["tool"] == "ellipse":
                    painter.drawEllipse(self._draw["rect"])
                else:
                    painter.drawRect(self._draw["rect"])
        if self.ruler_guides or self.guide_preview is not None:
            self._paint_ruler_guides(painter, rect)
        if self.guides:
            painter.setPen(QPen(GUIDE, 1 / s, Qt.PenStyle.DashLine))
            for line in self.guides:
                painter.drawLine(line)
        hover = self.hover_shape if (self.hover_shape is not None and self.hover_shape.scene() is self) \
            else None
        tool = self.doc.tool
        target = None
        if self._conn_drag is not None:
            target = self.glue_target[0] if self.glue_target else None
        elif hover is not None and not hover.editing and self.doc.settings["ports"] \
                and tool in ("select", "connector", "line") and self._press_states is None:
            target = hover
        if target is not None:
            painter.setPen(QPen(ACCENT, 1.4 / s))
            k = 3.5 / s
            for i in range(target.port_count()):
                p, _ = target.port_scene(i)
                painter.drawLine(QPointF(p.x() - k, p.y() - k), QPointF(p.x() + k, p.y() + k))
                painter.drawLine(QPointF(p.x() - k, p.y() + k), QPointF(p.x() + k, p.y() - k))
            if self.hover_port is not None and target is hover and self._conn_drag is None:
                p, _ = target.port_scene(self.hover_port)
                painter.setBrush(QColor(37, 99, 235, 60))
                painter.drawEllipse(p, 6 / s, 6 / s)
        if self._conn_drag is not None and self.glue_target:
            shape, port = self.glue_target
            painter.setPen(QPen(GLUE, 2.5 / s))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            if port is None:
                painter.drawPolygon(shape.mapToScene(shape.box()))
            else:
                p, _ = shape.port_scene(port)
                painter.drawEllipse(p, 6 / s, 6 / s)
        if hover is not None and self._autoconnect_allowed(hover):
            for i, (pt, (dx, dy)) in enumerate(zip(self._autoconnect_points(hover), AC_DIRS)):
                active = i == self.hover_arrow
                size = (AC_SIZE_PX * (1.35 if active else 1.0)) / s
                color = QColor(ACCENT)
                color.setAlpha(255 if active else 150)
                nx, ny = -dy, dx
                tip = QPointF(pt.x() + dx * size, pt.y() + dy * size)
                b1 = QPointF(pt.x() - dx * size * 0.4 + nx * size, pt.y() - dy * size * 0.4 + ny * size)
                b2 = QPointF(pt.x() - dx * size * 0.4 - nx * size, pt.y() - dy * size * 0.4 - ny * size)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(color)
                painter.drawPolygon(QPolygonF([tip, b1, b2]))

    # ------------------------------------------------------------------ recherche d'objets
    def _owner(self, it):
        if isinstance(it, TextLabel):
            return it.parentItem()
        return it

    def shape_at(self, pos: QPointF, exclude=None) -> ShapeItem | None:
        for it in self.items(pos, Qt.ItemSelectionMode.IntersectsItemShape,
                             Qt.SortOrder.DescendingOrder):
            it = self._owner(it)
            if isinstance(it, ShapeItem) and it is not exclude:
                return it
        return None

    def port_near(self, pos: QPointF):
        """Forme et point de connexion à portée du curseur (même sur le bord exact)."""
        if not self.doc.settings["ports"]:
            return None, None
        s = self.view_scale
        tol = PORT_TOL_PX / s
        area = QRectF(pos.x() - tol, pos.y() - tol, 2 * tol, 2 * tol)
        for it in self.items(area, Qt.ItemSelectionMode.IntersectsItemShape,
                             Qt.SortOrder.DescendingOrder):
            it = self._owner(it)
            if isinstance(it, ShapeItem) and min(it.w, it.h) * s >= 30:
                port = it.port_at(pos, tol)
                if port is not None:
                    return it, port
        return None, None

    def top_item_at(self, pos: QPointF):
        for it in self.items(pos, Qt.ItemSelectionMode.IntersectsItemShape,
                             Qt.SortOrder.DescendingOrder):
            it = self._owner(it)
            if isinstance(it, (ShapeItem, ConnectorItem)):
                return it
        return None

    # ------------------------------------------------------------------ AutoConnect
    def _autoconnect_allowed(self, shape: ShapeItem) -> bool:
        return (self.doc.tool == "select" and self.doc.settings.get("autoconnect", True)
                and not shape.editing and not shape.sdef.container and self._conn_drag is None
                and self._press_states is None and self._draw is None
                and self.format_painter is None)

    def _autoconnect_points(self, shape: ShapeItem) -> list[QPointF]:
        r = shape.visual_scene_rect()
        d = AC_DIST_PX / self.view_scale
        c = r.center()
        return [QPointF(c.x(), r.top() - d), QPointF(r.right() + d, c.y()),
                QPointF(c.x(), r.bottom() + d), QPointF(r.left() - d, c.y())]

    def autoconnect_hit(self, shape: ShapeItem | None, pos: QPointF) -> int | None:
        if shape is None or not self._autoconnect_allowed(shape):
            return None
        tol = (AC_SIZE_PX + 4) / self.view_scale
        for i, p in enumerate(self._autoconnect_points(shape)):
            if QLineF(p, pos).length() <= tol:
                return i
        return None

    def autoconnect(self, shape: ShapeItem, direction: int, type_id: str | None = None) -> None:
        dx, dy = AC_DIRS[direction]
        type_id = type_id or self.doc.quick_shape or shape.type_id
        if swimlanes.is_cff(type_id):
            type_id = shape.type_id
        if type_id == shape.type_id:
            w, h = shape.w, shape.h
        else:
            sdef = stencils.get(type_id)
            w, h = mm_to_px(sdef.size_mm[0]), mm_to_px(sdef.size_mm[1])
        gap = mm_to_px(20)
        box = shape.visual_scene_rect() if dy > 0 else shape.scene_box()
        c = shape.scene_box().center()
        if dx:
            cx = box.right() + gap + w / 2 if dx > 0 else box.left() - gap - w / 2
            cy = c.y()
        else:
            cy = box.bottom() + gap + h / 2 if dy > 0 else box.top() - gap - h / 2
            cx = c.x()
        new_rect = QRectF(cx - w / 2, cy - h / 2, w, h)
        existing = None
        for other in self.shapes():
            if other is not shape and not other.sdef.container and other.scene_box().intersects(new_rect):
                existing = other
                break
        states = []
        if existing is None:
            st = self.new_shape_state(type_id, QPointF(cx, cy), w, h, snap=False)
            if type_id == shape.type_id:
                st["style"] = dict(shape.style)
                st["text_style"] = dict(shape.text_style)
                st["text"] = ""
            states.append(st)
            target_id = st["id"]
        else:
            target_id = existing.id
        states.append(self.new_connector_state(
            {"shape": shape.id, "port": -1, "x": c.x(), "y": c.y()},
            {"shape": target_id, "port": -1, "x": cx, "y": cy}))
        self.doc.undo_stack.push(AddItemsCommand(self, states, "Connexion automatique"))
        self.clearSelection()
        target = self.item_by_id(target_id)
        if target is not None:
            target.setSelected(True)
        self.hover_arrow = None
        self.update()

    # ------------------------------------------------------------------ fabriques d'états
    def new_shape_state(self, type_id: str, center: QPointF, w: float | None = None,
                        h: float | None = None, snap: bool = True) -> dict:
        sdef = stencils.get(type_id)
        style, ts = fileformat.default_shape_styles(type_id, self.doc.settings["theme"])
        w = w if w is not None else mm_to_px(sdef.size_mm[0])
        h = h if h is not None else mm_to_px(sdef.size_mm[1])
        x, y = center.x(), center.y()
        if snap and self.snap_enabled:
            x = round((x - w / 2) / GRID_PX) * GRID_PX + w / 2
            y = round((y - h / 2) / GRID_PX) * GRID_PX + h / 2
        return {"id": self._fresh_id(), "type": type_id, "x": x, "y": y, "w": w, "h": h,
                "rotation": 0.0, "flip_h": False, "flip_v": False,
                "z": self.min_z() if sdef.container else self.next_z(),
                "text": sdef.default_text, "style": style, "text_style": ts, "data": {},
                "link": "", "group": ""}

    def new_connector_state(self, src: dict, dst: dict, route: str | None = None) -> dict:
        theme = self.doc.settings["theme"]
        return {"id": self._fresh_id(), "kind": "connector", "src": dict(src), "dst": dict(dst),
                "z": self.next_z(), "text": "",
                "style": connector_style(theme, route or self.doc.settings["route"]),
                "text_style": connector_text_style(theme), "data": {}}

    def _fresh_id(self) -> str:
        while True:
            i = new_id()
            if i not in self._items:
                return i

    def add_shape(self, type_id: str, center: QPointF, text: str = "Ajouter une forme") -> ShapeItem:
        if swimlanes.is_cff(type_id):
            return self.cff_drop(type_id, center)
        st = self.new_shape_state(type_id, center)
        self.doc.undo_stack.push(AddItemsCommand(self, [st], text))
        return self.item_by_id(st["id"])

    def add_states(self, states: list[dict], text: str) -> None:
        self.doc.undo_stack.push(AddItemsCommand(self, states, text))

    # ------------------------------------------------------------------ souris
    def mousePressEvent(self, event):  # noqa: N802
        pos = event.scenePos()
        self._mouse = pos
        if self.editing_item is not None:
            if self.editing_item.label.sceneBoundingRect().contains(pos):
                super().mousePressEvent(event)
                return
            self.editing_item.finish_edit()
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        tool = self.doc.tool
        s = self.view_scale
        if self.format_painter is not None:
            item = self.top_item_at(pos)
            if item is not None:
                self.apply_format(item, self.format_painter)
            self.format_painter = None
            self.doc.formatPainterDone.emit()
            event.accept()
            return
        if tool == "select" and self.hover_shape is not None:
            d = self.autoconnect_hit(self.hover_shape, pos)
            if d is not None:
                self.autoconnect(self.hover_shape, d)
                event.accept()
                return
        if tool == "select" and self.ruler_guides:
            gi = self.guide_at(pos)
            if gi is not None and self.top_item_at(pos) is None:
                self.clearSelection()
                self.selected_guide = gi
                self._guide_drag = {"i": gi, "start": QPointF(pos)}
                self.guide_preview = dict(self.ruler_guides[gi])
                self.update()
                event.accept()
                return
        if self.selected_guide is not None:
            self.selected_guide = None
            self.update()
        for item in self.selectedItems():
            if isinstance(item, ConnectorItem):
                which = item.end_handle_at(pos)
                if which:
                    self._conn_drag = {"mode": "end", "item": item, "which": which,
                                       "before": item.state(), "start": pos}
                    event.accept()
                    return
        if tool in ("connector", "line"):
            self._begin_new_connector(pos, route="straight" if tool == "line" else None)
            event.accept()
            return
        if tool in ("rectangle", "ellipse"):
            start = self.snap_point(pos)
            self._draw = {"tool": tool, "start": start, "rect": QRectF()}
            event.accept()
            return
        if tool in ("freeform", "arc"):
            start = self.snap_point(pos) if tool == "arc" else pos
            self._draw = {"tool": tool, "start": start, "rect": QRectF(), "points": [start]}
            event.accept()
            return
        if tool == "pen":
            preview = QPainterPath(pos)
            self._draw = {"tool": "pen", "points": [QPointF(pos)], "preview": preview}
            event.accept()
            return
        if tool == "text":
            item = self.top_item_at(pos)
            if item is not None:
                self.clearSelection()
                item.setSelected(True)
                item.start_edit()
            else:
                st = self.new_shape_state("basic.text", pos)
                st["text"] = ""
                self.add_states([st], "Ajouter du texte")
                created = self.item_by_id(st["id"])
                if created is not None:
                    created.start_edit()
            event.accept()
            return
        shape, port = self.port_near(pos)
        if shape is not None and not (shape.isSelected() and shape.handle_at(pos) is not None):
            self._begin_new_connector(pos, start_shape=shape, start_port=port)
            event.accept()
            return
        self.interactive_move = True
        self._press_mouse = pos
        super().mousePressEvent(event)
        grabbed = self._owner(self.mouseGrabberItem())
        if isinstance(grabbed, ShapeItem) and grabbed.group and grabbed.isSelected():
            for other in self.shapes():
                if other.group == grabbed.group:
                    other.setSelected(True)
        self._carry, self._carry_anchor = {}, None
        if isinstance(grabbed, ShapeItem) and grabbed.sdef.cff and grabbed._drag is None:
            self._carry = self._cff_carry(grabbed)
            self._carry_anchor = (grabbed.id, QPointF(grabbed.pos()))
        elif isinstance(grabbed, ShapeItem) and grabbed.sdef.container and grabbed._drag is None:
            # Comme dans Visio : déplacer un conteneur déplace les formes qu'il contient.
            self._carry = {s.id: QPointF(s.pos()) for s in self.container_members(grabbed) if not s.isSelected()}
            self._carry_anchor = (grabbed.id, QPointF(grabbed.pos()))
        self._capture_press()

    def _capture_press(self) -> None:
        sel = [i for i in self.selectedItems() if isinstance(i, (ShapeItem, ConnectorItem))]
        ids = {i.id for i in sel} | set(self._carry)
        for i in list(ids):
            it = self._items.get(i)
            if isinstance(it, ShapeItem):
                ids.update(c.id for c in self.connectors_of(it.id))
        self._press_states = {i: self._items[i].state() for i in ids if i in self._items}
        self._press_pos = {i.id: QPointF(i.pos()) for i in sel}
        self._snap_key = None
        self._snap_adj = QPointF()

    def mouseMoveEvent(self, event):  # noqa: N802
        pos = event.scenePos()
        self._mouse = pos
        if self._guide_drag is not None:
            g = self.ruler_guides[self._guide_drag["i"]]
            p = self.snap_point(pos)
            self.guide_preview = {"o": g["o"], "pos": p.y() if g["o"] == "h" else p.x()}
            self.update()
            event.accept()
            return
        if self._conn_drag is not None:
            self._update_conn_drag(pos)
            event.accept()
            return
        if self._draw is not None and self._draw["tool"] in ("freeform", "arc"):
            pts = self._draw["points"]
            if self._draw["tool"] == "arc":
                self._draw["points"] = [pts[0], self.snap_point(pos)]
            elif (pos - pts[-1]).manhattanLength() * self.view_scale > 2:
                pts.append(pos)
            self.update()
            event.accept()
            return
        if self._draw is not None:
            if self._draw["tool"] == "pen":
                points = self._draw["points"]
                min_distance = 2.0 / max(self.view_scale, 0.1)
                if QLineF(points[-1], pos).length() >= min_distance:
                    if len(points) >= 4096:
                        reduced = points[::2]
                        if reduced[-1] != points[-1]:
                            reduced.append(points[-1])
                        points[:] = reduced
                        preview = QPainterPath(points[0])
                        for point in points[1:]:
                            preview.lineTo(point)
                        self._draw["preview"] = preview
                    points.append(QPointF(pos))
                    self._draw["preview"].lineTo(pos)
            else:
                self._draw["rect"] = QRectF(self._draw["start"], self.snap_point(pos)).normalized()
            self.update()
            event.accept()
            return
        if event.buttons() == Qt.MouseButton.NoButton:
            self._update_hover(pos)
        super().mouseMoveEvent(event)
        if self._carry and self._carry_anchor is not None:
            # Les formes d'un couloir (ou du cadre) suivent leur conteneur.
            anchor = self._items.get(self._carry_anchor[0])
            if anchor is not None:
                delta = anchor.pos() - self._carry_anchor[1]
                for cid, start in self._carry.items():
                    it = self._items.get(cid)
                    if it is not None:
                        it._applying = True
                        it.setPos(start + delta)
                        it._applying = False

    def mouseReleaseEvent(self, event):  # noqa: N802
        pos = event.scenePos()
        self._mouse = pos
        if self._guide_drag is not None:
            d, self._guide_drag = self._guide_drag, None
            preview, self.guide_preview = self.guide_preview, None
            views = self.views()
            visible = views[0].mapToScene(views[0].viewport().rect()).boundingRect() if views else None
            if visible is not None and not visible.contains(pos):
                self.remove_guide(d["i"])          # ramené sur la règle : supprimé, comme dans Visio
            elif preview is not None and (pos - d["start"]).manhattanLength() * self.view_scale > 2:
                self.move_guide(d["i"], preview["pos"])
            self.update()
            event.accept()
            return
        if self._conn_drag is not None:
            self._finish_conn_drag(pos)
            event.accept()
            return
        if self._draw is not None:
            self._finish_draw()
            event.accept()
            return
        super().mouseReleaseEvent(event)
        self.interactive_move = False
        if self.guides:
            self.guides = []
            self.update()
        if self._press_states is not None:
            for it in self.selectedItems():
                if isinstance(it, ConnectorItem):
                    it.normalize_position()
            before, after = {}, {}
            for k, v in self._press_states.items():
                item = self._items.get(k)
                if item is None:
                    continue
                now = item.state()
                if now != v:
                    before[k] = v
                    after[k] = now
            self._press_states = None
            prefer = self._carry_anchor[0] if self._carry_anchor else None
            self._carry, self._carry_anchor = {}, None
            if after:
                cff = any(isinstance(self._items.get(k), ShapeItem) and self._items[k].sdef.cff for k in after)
                if cff:
                    self.doc.undo_stack.beginMacro(self._describe(before, after))
                self.push_state(before, after, self._describe(before, after))
                if cff:
                    self.cff_layout(prefer=prefer)
                    self.doc.undo_stack.endMacro()
                self.update_scene_rect()
                self.maybe_auto_size()
        self.selection_info_changed()

    def maybe_auto_size(self) -> None:
        """« Taille automatique » : la page s'agrandit pour contenir le dessin."""
        if not self.auto_size:
            return
        r = self.drawing_rect()
        if r.isNull():
            return
        margin = mm_to_px(10)
        step = mm_to_px(10)
        w = max(self.page_w, -(-(r.right() + margin) // step) * step)
        h = max(self.page_h, -(-(r.bottom() + margin) // step) * step)
        if w > self.page_w + 0.5 or h > self.page_h + 0.5:
            from .commands import PageCommand
            before = self.page_props()
            self.doc.undo_stack.push(PageCommand(self.doc, "Taille automatique de la page", scene=self,
                                                 before=before, after=dict(before, width=w, height=h)))

    @staticmethod
    def _describe(before: dict, after: dict) -> str:
        for k, b in before.items():
            a = after[k]
            if "w" in a and (a["w"] != b["w"] or a["h"] != b["h"]):
                return "Redimensionner"
            if "rotation" in a and a["rotation"] != b["rotation"]:
                return "Faire pivoter"
        return "Déplacer"

    def _update_hover(self, pos: QPointF) -> None:
        s = self.view_scale
        shape = self.shape_at(pos)
        if shape is None and self.hover_shape is not None and self.hover_shape.scene() is self:
            zone = self.hover_shape.visual_scene_rect()
            m = (AC_DIST_PX + AC_SIZE_PX + 6) / s
            if zone.adjusted(-m, -m, m, m).contains(pos):
                shape = self.hover_shape
        near, port = self.port_near(pos)
        if near is not None and (shape is None or near is shape):
            shape = near
        else:
            port = None
        arrow = self.autoconnect_hit(shape, pos)
        if (shape, port, arrow) != (self.hover_shape, self.hover_port, self.hover_arrow):
            changed_arrow = arrow != self.hover_arrow
            self.hover_shape, self.hover_port, self.hover_arrow = shape, port, arrow
            self.update()
            if changed_arrow:
                pt = self._autoconnect_points(shape)[arrow] if arrow is not None else QPointF()
                self.autoconnectHover.emit(shape if arrow is not None else None, -1 if arrow is None else arrow, pt)

    def clear_hover(self) -> None:
        if self.hover_shape is not None:
            had_arrow = self.hover_arrow is not None
            self.hover_shape = None
            self.hover_port = self.hover_arrow = None
            self.update()
            if had_arrow:
                self.autoconnectHover.emit(None, -1, QPointF())

    def cursor_for(self, pos: QPointF) -> Qt.CursorShape:
        tool = self.doc.tool
        if self._conn_drag is not None or tool in ("connector", "line", "rectangle", "ellipse"):
            return Qt.CursorShape.CrossCursor
        if self.format_painter is not None:
            return Qt.CursorShape.PointingHandCursor
        if tool == "text":
            return Qt.CursorShape.IBeamCursor
        if self.editing_item is not None and self.editing_item.label.sceneBoundingRect().contains(pos):
            return Qt.CursorShape.IBeamCursor
        if self.hover_arrow is not None:
            return Qt.CursorShape.PointingHandCursor
        single = self.single_selected
        if isinstance(single, ShapeItem):
            h = single.handle_at(pos)
            if h is not None:
                return single.handle_cursor(h)
        if isinstance(single, ConnectorItem) and single.end_handle_at(pos):
            return Qt.CursorShape.CrossCursor
        if self.hover_port is not None:
            return Qt.CursorShape.CrossCursor
        item = self.top_item_at(pos)
        if isinstance(item, ShapeItem) or (isinstance(item, ConnectorItem)
                                           and item.flags() & item.GraphicsItemFlag.ItemIsMovable):
            return Qt.CursorShape.SizeAllCursor
        return Qt.CursorShape.ArrowCursor

    # ------------------------------------------------------------------ magnétisme
    def snap_point(self, p: QPointF) -> QPointF:
        if not self.snap_enabled:
            return p
        return QPointF(round(p.x() / GRID_PX) * GRID_PX, round(p.y() / GRID_PX) * GRID_PX)

    def adjust_move(self, item, value: QPointF) -> QPointF:
        grabber = self._owner(self.mouseGrabberItem())
        if not isinstance(grabber, ShapeItem) or grabber.id not in self._press_pos:
            return value
        delta = self._mouse - self._press_mouse
        constrain = QPointF()
        if QApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier:
            if abs(delta.x()) >= abs(delta.y()):
                constrain = QPointF(0, -delta.y())
            else:
                constrain = QPointF(-delta.x(), 0)
        intended = self._press_pos[grabber.id] + delta + constrain
        key = (round(intended.x(), 3), round(intended.y(), 3))
        if key != self._snap_key:
            self._snap_key = key
            self._snap_adj, self.guides = self._compute_snap(grabber, intended)
            self.update()
        return value + constrain + self._snap_adj

    def _compute_snap(self, g: ShapeItem, intended: QPointF):
        s = self.view_scale
        box = g.scene_box().translated(intended - g.pos())
        adj_x = adj_y = None
        hit_x = hit_y = None
        if self.doc.settings["guides"]:
            tol = GUIDE_TOL_PX / s
            bx = (box.left(), box.center().x(), box.right())
            by = (box.top(), box.center().y(), box.bottom())
            for o in self.shapes():
                if o.isSelected():
                    continue
                ob = o.scene_box()
                for vx in (ob.left(), ob.center().x(), ob.right()):
                    for x in bx:
                        d = vx - x
                        if abs(d) <= tol and (adj_x is None or abs(d) < abs(adj_x)):
                            adj_x, hit_x = d, (vx, ob)
                for vy in (ob.top(), ob.center().y(), ob.bottom()):
                    for y in by:
                        d = vy - y
                        if abs(d) <= tol and (adj_y is None or abs(d) < abs(adj_y)):
                            adj_y, hit_y = d, (vy, ob)
        if self.ruler_guides:
            tol = GUIDE_TOL_PX / s
            for gd in self.ruler_guides:
                refs = (box.left(), box.center().x(), box.right()) if gd["o"] == "v" else \
                    (box.top(), box.center().y(), box.bottom())
                for v in refs:
                    d = gd["pos"] - v
                    if abs(d) > tol:
                        continue
                    if gd["o"] == "v" and (adj_x is None or abs(d) < abs(adj_x)):
                        adj_x, hit_x = d, None
                    elif gd["o"] == "h" and (adj_y is None or abs(d) < abs(adj_y)):
                        adj_y, hit_y = d, None
        if self.snap_enabled:
            square = abs(round(g.rotation() / 90.0) * 90.0 - g.rotation()) < 0.01
            ref_x = box.left() if square else box.center().x()
            ref_y = box.top() if square else box.center().y()
            if adj_x is None:
                adj_x = round(ref_x / GRID_PX) * GRID_PX - ref_x
            if adj_y is None:
                adj_y = round(ref_y / GRID_PX) * GRID_PX - ref_y
        adj = QPointF(adj_x or 0.0, adj_y or 0.0)
        final = box.translated(adj)
        guides = []
        if hit_x is not None:
            vx, ob = hit_x
            guides.append(QLineF(vx, min(final.top(), ob.top()) - 10 / s,
                                 vx, max(final.bottom(), ob.bottom()) + 10 / s))
        if hit_y is not None:
            vy, ob = hit_y
            guides.append(QLineF(min(final.left(), ob.left()) - 10 / s, vy,
                                 max(final.right(), ob.right()) + 10 / s, vy))
        return adj, guides

    # ------------------------------------------------------------------ connecteurs à la souris
    def _begin_new_connector(self, pos: QPointF, start_shape=None, start_port=None, route=None):
        s = self.view_scale
        if start_shape is None and self.doc.tool == "connector":
            start_shape = self.shape_at(pos)
            if start_shape is not None and start_shape.sdef.cff:
                start_shape = None
            if start_shape is not None:
                start_port = start_shape.port_at(pos, PORT_TOL_PX / s)
        if start_shape is None:
            pos = self.snap_point(pos)
        src = {"shape": start_shape.id if start_shape else "",
               "port": start_port if (start_shape is not None and start_port is not None) else -1,
               "x": pos.x(), "y": pos.y()}
        dst = {"shape": "", "port": -1, "x": pos.x(), "y": pos.y()}
        temp = ConnectorItem(self.new_connector_state(src, dst, route))
        self.addItem(temp)
        temp.update_path()
        self.clearSelection()
        self._conn_drag = {"mode": "new", "item": temp, "which": "dst", "start": pos,
                           "start_shape": start_shape}

    def _update_conn_drag(self, pos: QPointF) -> None:
        d = self._conn_drag
        conn: ConnectorItem = d["item"]
        exclude = d.get("start_shape") if d["mode"] == "new" else None
        target = self.shape_at(pos, exclude=exclude)
        if isinstance(target, ShapeItem) and (target is conn or target.sdef.cff):
            target = None
        end = {"shape": "", "port": -1, "x": pos.x(), "y": pos.y()}
        port = None
        if target is not None:
            port = target.port_at(pos, PORT_TOL_PX * 1.5 / self.view_scale)
            end.update(shape=target.id, port=port if port is not None else -1)
            self.glue_target = (target, port)
        else:
            p = self.snap_point(pos)
            end.update(x=p.x(), y=p.y())
            self.glue_target = None
        if d["mode"] == "new":
            setattr(conn, d["which"], end)
            conn.update_path()
        else:
            conn.set_end(d["which"], end)
        self.update()

    def _finish_conn_drag(self, pos: QPointF) -> None:
        d = self._conn_drag
        self._conn_drag = None
        self.glue_target = None
        conn: ConnectorItem = d["item"]
        if d["mode"] == "new":
            self.removeItem(conn)
            moved = QLineF(d["start"], pos).length() * self.view_scale
            if moved < 6 and not conn.dst.get("shape"):
                if d.get("start_shape") is not None:
                    d["start_shape"].setSelected(True)
                self.update()
                return
            self.doc.undo_stack.push(AddItemsCommand(self, [conn.state()], "Ajouter un connecteur"))
        else:
            after = conn.state()
            if after != d["before"]:
                self.push_state({conn.id: d["before"]}, {conn.id: after}, "Recoller le connecteur")
        self.update()

    @staticmethod
    def _draw_path(d: dict) -> QPainterPath:
        """Tracé du Crayon, de la Forme libre ou de l'Arc dans le repère de la page."""
        pts = d["points"]
        p = QPainterPath(pts[0])
        if d["tool"] == "arc":
            if len(pts) > 1:
                a, b = pts[0], pts[-1]
                # Quart d'ellipse, comme l'outil Arc de Visio : part verticalement, arrive horizontalement.
                k = 0.5523
                p.cubicTo(QPointF(a.x(), a.y() + (b.y() - a.y()) * k),
                          QPointF(b.x() - (b.x() - a.x()) * k, b.y()), b)
            return p
        pts = _simplify(pts, 1.2)
        if len(pts) > 2:
            # Lissage : courbes passant par le milieu des segments.
            for i in range(1, len(pts) - 1):
                mid = (pts[i] + pts[i + 1]) / 2
                p.quadTo(pts[i], mid)
            p.lineTo(pts[-1])
        else:
            for pt in pts[1:]:
                p.lineTo(pt)
        if d["tool"] == "freeform":
            p.closeSubpath()
        return p

    def _finish_freehand(self, d: dict) -> None:
        path = self._draw_path(d)
        r = path.boundingRect()
        if max(r.width(), r.height()) * self.view_scale < 6:
            return
        r = r.adjusted(-0.5, -0.5, 0.5, 0.5)
        _r, cmds = shapeops.to_commands(path)
        # to_commands normalise sur le rectangle exact : on recalcule sur le rectangle élargi.
        box = path.boundingRect()
        sx = box.width() / r.width() if r.width() else 1.0
        sy = box.height() / r.height() if r.height() else 1.0
        ox, oy = (box.left() - r.left()) / r.width(), (box.top() - r.top()) / r.height()
        fixed = []
        for cmd in cmds:
            vals = cmd[1:]
            fixed.append([cmd[0]] + [round(ox + v * sx, 6) if k % 2 == 0 else round(oy + v * sy, 6)
                                     for k, v in enumerate(vals)])
        if d["tool"] != "freeform":
            fixed = [c for c in fixed if c[0] != "Z"]
        st = self.new_shape_state("special.custom", r.center(), r.width(), r.height(), snap=False)
        st["path"] = fixed
        st["text"] = ""
        if d["tool"] != "freeform":
            st["style"].update(fill="", themed=False)
            st["style"]["line"] = st["style"]["line"] or "#000000"
        names = {"freeform": "Forme libre", "arc": "Arc"}
        self.add_states([st], names[d["tool"]])

    def _finish_draw(self) -> None:
        d = self._draw
        self._draw = None
        if d["tool"] in ("freeform", "arc"):
            self.update()
            self._finish_freehand(d)
            return
        self.update()
        if d["tool"] == "pen":
            points = d["points"]
            end = self._mouse
            min_distance = 2.0 / max(self.view_scale, 0.1)
            if QLineF(points[-1], end).length() >= min_distance:
                if len(points) < 4096:
                    points.append(QPointF(end))
                else:
                    points[-1] = QPointF(end)
            if len(points) < 2:
                return
            left = min(point.x() for point in points)
            right = max(point.x() for point in points)
            top = min(point.y() for point in points)
            bottom = max(point.y() for point in points)
            if max(right - left, bottom - top) < 2.0 / max(self.view_scale, 0.1):
                return
            if right - left < 2.0:
                left -= (2.0 - (right - left)) / 2
                right = left + 2.0
            if bottom - top < 2.0:
                top -= (2.0 - (bottom - top)) / 2
                bottom = top + 2.0
            width, height = right - left, bottom - top
            commands = [["M", (points[0].x() - left) / width, (points[0].y() - top) / height]]
            commands.extend([["L", (point.x() - left) / width, (point.y() - top) / height]
                             for point in points[1:]])
            center = QPointF(left + width / 2, top + height / 2)
            st = self.new_shape_state("special.custom", center, width, height, snap=False)
            st["path"] = commands
            st["style"]["fill"] = ""
            st["text"] = ""
            self.add_states([st], "Tracer à main levée")
            return
        r = d["rect"]
        if r.width() * self.view_scale < 4 or r.height() * self.view_scale < 4:
            return
        type_id = "basic.ellipse" if d["tool"] == "ellipse" else "basic.rectangle"
        st = self.new_shape_state(type_id, r.center(), r.width(), r.height(), snap=False)
        st["text"] = ""
        self.add_states([st], "Dessiner une forme")

    # ------------------------------------------------------------------ sélection
    def _on_selection_changed(self) -> None:
        sel = self.selectedItems()
        self._sel_order = [i for i in self._sel_order if i in sel] + [i for i in sel if i not in self._sel_order]
        prev = self.single_selected
        self.single_selected = sel[0] if len(sel) == 1 else None
        for it in sel:
            it.prepareGeometryChange()
            it.update()
        if prev is not None and prev.scene() is self and prev not in sel:
            prev.prepareGeometryChange()
            prev.update()
        self.selection_info_changed()

    def selection_info_changed(self) -> None:
        self.selectionInfo.emit()

    def selected_shapes(self) -> list[ShapeItem]:
        return [i for i in self.selectedItems() if isinstance(i, ShapeItem)]

    def selected_connectors(self) -> list[ConnectorItem]:
        return [i for i in self.selectedItems() if isinstance(i, ConnectorItem)]

    def selected_all(self) -> list:
        return [i for i in self.selectedItems() if isinstance(i, (ShapeItem, ConnectorItem))]

    def select_items(self, items, clear: bool = True) -> None:
        """Sélection groupée : une seule notification au lieu d'une par objet."""
        blocked = self.blockSignals(True)
        try:
            if clear:
                self.clearSelection()
            for it in items:
                it.setSelected(True)
        finally:
            self.blockSignals(blocked)
        self._on_selection_changed()

    def select_all(self) -> None:
        self.select_items(self._items.values())

    def after_text_edit(self, item) -> None:
        """Une zone de texte laissée vide est supprimée, comme dans Visio."""
        if isinstance(item, ShapeItem) and item.type_id == "basic.text" and not item.text.strip():
            item_id = item.id

            def cleanup():
                it = self.item_by_id(item_id)
                if it is not None and not it.text.strip() and not it.editing:
                    self.delete_items([it], "Supprimer le texte vide")
            QTimer.singleShot(0, cleanup)

    def set_view_scale(self, s: float) -> None:
        if abs(s - self.view_scale) < 1e-9:
            return
        self.view_scale = s
        for it in self.selectedItems():
            it.prepareGeometryChange()
        for c in self.connectors():
            c.prepareGeometryChange()

    # ------------------------------------------------------------------ opérations annulables
    def push_state(self, before: dict, after: dict, text: str, merge_key: str | None = None) -> None:
        self.doc.undo_stack.push(StateCommand(self, before, after, text, merge_key))

    def modify(self, items, fn, text: str, merge_key: str | None = None) -> None:
        """Applique ``fn(item, état)`` à chaque objet puis enregistre l'annulation."""
        before, after = {}, {}
        for it in items:
            b = it.state()
            a = copy.deepcopy(b)
            fn(it, a)
            if a != b:
                before[it.id] = b
                after[it.id] = a
        if not after:
            return
        for st in _shapes_first(after.values()):
            self._items[st["id"]].set_state(st)
        self.refresh_connectors()
        self.apply_layers()
        self.update_scene_rect()
        self.push_state(before, after, text, merge_key)
        self.selection_info_changed()

    def delete_items(self, items, text: str = "Supprimer") -> None:
        items = [it for it in items if not getattr(it, "locked", False)]
        cff = [it for it in items if isinstance(it, ShapeItem) and it.sdef.cff]
        if cff:
            # Supprimer un couloir supprime son contenu ; supprimer le cadre, toute la structure.
            extra = []
            for it in cff:
                r = it.scene_box()
                kind, o = swimlanes.KIND_OF[it.type_id]
                for s in self.shapes():
                    if s in items or s in extra or s.locked:
                        continue
                    inside = r.contains(s.scene_box().center())
                    if kind == "lane" and not s.sdef.cff and inside:
                        extra.append(s)
                    elif kind == "frame" and (inside or swimlanes.KIND_OF.get(s.type_id, ("", ""))[1] == o):
                        extra.append(s)
            self.doc.undo_stack.beginMacro(text)
            self._delete_now(items + extra, text)
            self.cff_layout()
            self.doc.undo_stack.endMacro()
            self.selection_info_changed()
            return
        self._delete_now(items, text)

    def _delete_now(self, items, text: str) -> None:
        ids = set()
        for it in items:
            ids.add(it.id)
            if isinstance(it, ShapeItem):
                ids.update(c.id for c in self.connectors_of(it.id))
        if not ids:
            return
        states = [self._items[i].state() for i in ids if i in self._items]
        self.doc.undo_stack.push(RemoveItemsCommand(self, states, text))
        self.selection_info_changed()

    def delete_selection(self) -> None:
        self.delete_items(self.selected_all())

    def copy_selection(self) -> bytes | None:
        sel = self.selected_all()
        if not sel:
            return None
        shape_ids = {i.id for i in sel if isinstance(i, ShapeItem)}
        shapes = [i.state() for i in sorted(sel, key=lambda i: i.zValue()) if isinstance(i, ShapeItem)]
        conns = []
        for i in sorted(sel, key=lambda i: i.zValue()):
            if isinstance(i, ConnectorItem):
                st = i.state()
                for end in (st["src"], st["dst"]):
                    if end["shape"] and end["shape"] not in shape_ids:
                        end["shape"], end["port"] = "", -1
                conns.append(st)
        return fileformat.dump_clip(shapes, conns)

    def paste(self, data: bytes, offset: QPointF, text: str = "Coller") -> None:
        shapes, conns = fileformat.load_clip(data, self.doc.settings["theme"],
                                             self.doc.settings["route"])
        if not shapes and not conns:
            return
        mapping = {}
        groups = {}
        z = self.next_z()
        for st in shapes:
            mapping[st["id"]] = st["id"] = self._fresh_id()
            st["x"] += offset.x()
            st["y"] += offset.y()
            st["z"] = z
            z += 1
            if st["group"]:
                st["group"] = groups.setdefault(st["group"], new_id())
        for st in conns:
            st["id"] = self._fresh_id()
            st["z"] = z
            z += 1
            for end in (st["src"], st["dst"]):
                end["x"] += offset.x()
                end["y"] += offset.y()
                if end["shape"]:
                    end["shape"] = mapping.get(end["shape"], "")
                    if not end["shape"]:
                        end["port"] = -1
        self.doc.undo_stack.push(AddItemsCommand(self, shapes + conns, text))
        self.select_items(filter(None, (self.item_by_id(st["id"]) for st in shapes + conns)))

    def nudge(self, dx: float, dy: float) -> None:
        items = self.selected_shapes()
        free = [c for c in self.selected_connectors()
                if c.glued_shape(c.src) is None or c.glued_shape(c.dst) is None]

        def move(it, st):
            if "kind" in st:
                for end in (st["src"], st["dst"]):
                    if not end["shape"] or it.glued_shape(end) is None:
                        end["x"] += dx
                        end["y"] += dy
            else:
                st["x"] += dx
                st["y"] += dy
        self.modify(items + free, move, "Déplacer", merge_key="nudge")

    def reorder(self, mode: str) -> None:
        sel = sorted(self.selected_all(), key=lambda i: i.zValue())
        if not sel:
            return
        ordered = sorted(self._items.values(), key=lambda i: i.zValue())
        if mode == "front":
            top = self.next_z()
            zmap = {it.id: top + n for n, it in enumerate(sel)}
            text = "Mettre au premier plan"
        elif mode == "back":
            bottom = self.min_z() - len(sel)
            zmap = {it.id: bottom + n for n, it in enumerate(sel)}
            text = "Mettre à l'arrière-plan"
        else:
            ids = [i.id for i in ordered]
            selected = {i.id for i in sel}
            rng = range(len(ids) - 2, -1, -1) if mode == "forward" else range(1, len(ids))
            for k in rng:
                j = k + 1 if mode == "forward" else k - 1
                if ids[k] in selected and ids[j] not in selected:
                    ids[k], ids[j] = ids[j], ids[k]
            zmap = {i: float(n) for n, i in enumerate(ids)}
            text = "Avancer" if mode == "forward" else "Reculer"
            sel = ordered

        def set_z(it, st):
            st["z"] = zmap.get(it.id, st["z"])
        self.modify(sel, set_z, text)

    def group_selection(self) -> None:
        shapes = self.selected_shapes()
        if len(shapes) < 2:
            return
        gid = new_id()

        def grp(it, st):
            st["group"] = gid
        self.modify(shapes, grp, "Grouper")

    def ungroup_selection(self) -> None:
        def ungrp(it, st):
            st["group"] = ""
        self.modify(self.selected_shapes(), ungrp, "Dissocier")

    def align(self, mode: str) -> None:
        shapes = self.selected_shapes()
        if len(shapes) < 2:
            return
        boxes = {s.id: s.scene_box() for s in shapes}
        left = min(b.left() for b in boxes.values())
        right = max(b.right() for b in boxes.values())
        top = min(b.top() for b in boxes.values())
        bottom = max(b.bottom() for b in boxes.values())

        def al(it, st):
            b = boxes[it.id]
            dx = dy = 0.0
            if mode == "left":
                dx = left - b.left()
            elif mode == "center":
                dx = (left + right) / 2 - b.center().x()
            elif mode == "right":
                dx = right - b.right()
            elif mode == "top":
                dy = top - b.top()
            elif mode == "middle":
                dy = (top + bottom) / 2 - b.center().y()
            elif mode == "bottom":
                dy = bottom - b.bottom()
            st["x"] += dx
            st["y"] += dy
        self.modify(shapes, al, "Aligner")

    # ------------------------------------------------------------------ opérations sur les formes
    def shape_operation(self, op: str) -> bool:
        """Union, Combiner, Fragmenter, Intersecter, Soustraire (Développeur > Opérations)."""
        shapes = [s for s in self.selected_shapes() if not s.locked and not s.sdef.cff]
        if len(shapes) < 2:
            return False
        order = [s for s in self._sel_order if s in shapes] + [s for s in shapes if s not in self._sel_order]
        paths = [s.sceneTransform().map(s._outline) for s in order]
        results = shapeops.apply(op, paths)
        ref = order[0].state()
        states = []
        for path in results:
            r, cmds = shapeops.to_commands(path)
            if len(cmds) < 2 or len(cmds) > fileformat.MAX_PATH_COMMANDS or r.width() < 1 or r.height() < 1:
                continue
            st = self.new_shape_state("special.custom", r.center(), r.width(), r.height(), snap=False)
            st.update(path=cmds, style=dict(ref["style"]), text_style=dict(ref["text_style"]),
                      z=ref["z"] + len(states) * 0.001, layer=ref.get("layer", ""),
                      text=ref["text"] if op != "fragment" else "")
            states.append(st)
        if not states:
            return False
        label = shapeops.OPERATIONS[op]
        self.doc.undo_stack.beginMacro(label)
        try:
            self.delete_items(order, label)
            self.add_states(states, label)
        finally:
            self.doc.undo_stack.endMacro()
        self.select_items([self._items[st["id"]] for st in states if st["id"] in self._items])
        return True

    def auto_align_space(self, align: bool = True, space: bool = True) -> None:
        """« Aligner automatiquement et espacer » : les formes reliées presque alignées le
        deviennent, et les écarts le long des colonnes et des lignes sont égalisés."""
        shapes = [s for s in (self.selected_shapes() or self.shapes())
                  if not s.sdef.cff and not s.sdef.container and not s.locked]
        ids = {s.id: s for s in shapes}
        if len(ids) < 2:
            return
        c = {i: s.scene_box().center() for i, s in ids.items()}
        size = {i: s.scene_box() for i, s in ids.items()}
        tol = mm_to_px(20)
        parent = {"col": {i: i for i in ids}, "row": {i: i for i in ids}}

        def find(kind, i):
            while parent[kind][i] != i:
                parent[kind][i] = parent[kind][parent[kind][i]]
                i = parent[kind][i]
            return i
        for conn in self.connectors():
            a, b = conn.src.get("shape"), conn.dst.get("shape")
            if a not in ids or b not in ids or a == b:
                continue
            dx, dy = abs(c[a].x() - c[b].x()), abs(c[a].y() - c[b].y())
            kind = "col" if dx <= dy else "row"
            if min(dx, dy) < tol:
                parent[kind][find(kind, a)] = find(kind, b)
        x = {i: c[i].x() for i in ids}
        y = {i: c[i].y() for i in ids}
        for kind in ("col", "row"):
            groups: dict[str, list[str]] = {}
            for i in ids:
                groups.setdefault(find(kind, i), []).append(i)
            for members in groups.values():
                if len(members) < 2:
                    continue
                if align:
                    vals = sorted((x if kind == "col" else y)[i] for i in members)
                    med = vals[len(vals) // 2]
                    for i in members:
                        (x if kind == "col" else y)[i] = med
                if space:
                    axis = y if kind == "col" else x
                    members.sort(key=lambda i: axis[i])
                    ext = (lambda i: size[i].height()) if kind == "col" else (lambda i: size[i].width())
                    gaps = [axis[b] - ext(b) / 2 - (axis[a] + ext(a) / 2) for a, b in zip(members, members[1:])]
                    gap = max(mm_to_px(8), sum(gaps) / len(gaps))
                    pos = axis[members[0]] + ext(members[0]) / 2
                    for i in members[1:]:
                        axis[i] = pos + gap + ext(i) / 2
                        pos = axis[i] + ext(i) / 2
        labels = {(True, True): "Aligner automatiquement et espacer", (True, False): "Aligner automatiquement",
                  (False, True): "Espacement automatique"}

        def fn(it, st):
            st["x"] += x[it.id] - c[it.id].x()
            st["y"] += y[it.id] - c[it.id].y()
        self.modify(list(ids.values()), fn, labels[(align, space)])

    def distribute(self, axis: str) -> None:
        shapes = self.selected_shapes()
        if len(shapes) < 3:
            return
        boxes = {s.id: s.scene_box() for s in shapes}
        horiz = axis == "h"
        shapes.sort(key=lambda s: boxes[s.id].center().x() if horiz else boxes[s.id].center().y())
        first, last = boxes[shapes[0].id], boxes[shapes[-1].id]
        start = first.left() if horiz else first.top()
        end = last.right() if horiz else last.bottom()
        sizes = sum((boxes[s.id].width() if horiz else boxes[s.id].height()) for s in shapes)
        gap = (end - start - sizes) / (len(shapes) - 1)
        targets = {}
        cur = start
        for s in shapes:
            b = boxes[s.id]
            targets[s.id] = cur - (b.left() if horiz else b.top())
            cur += (b.width() if horiz else b.height()) + gap

        def dist(it, st):
            if horiz:
                st["x"] += targets[it.id]
            else:
                st["y"] += targets[it.id]
        self.modify(shapes, dist, "Distribuer")

    def rotate_selection(self, degrees: float) -> None:
        def rot(it, st):
            r = st["rotation"] + degrees
            while r > 180:
                r -= 360
            while r <= -180:
                r += 360
            st["rotation"] = r
        self.modify(self.selected_shapes(), rot, "Faire pivoter")

    def flip_selection(self, horizontal: bool) -> None:
        key = "flip_h" if horizontal else "flip_v"

        def flip(it, st):
            st[key] = not st[key]
        self.modify(self.selected_shapes(), flip,
                    "Retourner horizontalement" if horizontal else "Retourner verticalement")

    def apply_shape_style(self, changes: dict, text: str = "Mettre en forme",
                          merge_key: str | None = None) -> None:
        manual = any(k in changes for k in ("fill", "line"))

        def sty(it, st):
            st["style"].update(changes)
            if manual:
                st["style"]["themed"] = False
        self.modify(self.selected_shapes(), sty, text, merge_key)

    def apply_connector_style(self, changes: dict, items=None, text: str = "Mettre en forme",
                              merge_key: str | None = None) -> None:
        def sty(it, st):
            st["style"].update(changes)
            if "line" in changes:
                st["style"]["themed"] = False
        self.modify(items if items is not None else self.selected_connectors(), sty, text, merge_key)

    def apply_line_to_selection(self, changes: dict, text: str = "Mettre en forme le trait",
                                merge_key: str | None = None) -> None:
        """Trait commun aux formes et connecteurs (couleur, épaisseur, motif)."""
        def sty(it, st):
            for k, v in changes.items():
                if isinstance(it, ConnectorItem) and k == "line" and not v:
                    continue
                st["style"][k] = v
            if "line" in changes:
                st["style"]["themed"] = False
        self.modify(self.selected_all(), sty, text, merge_key)

    def apply_text_style(self, changes: dict, text: str = "Mettre en forme le texte",
                         merge_key: str | None = None) -> None:
        def sty(it, st):
            st["text_style"].update(changes)
        self.modify(self.selected_all(), sty, text, merge_key)

    def apply_format(self, item, fmt: dict) -> None:
        """Reproduire la mise en forme (pinceau)."""
        def sty(it, st):
            if isinstance(it, ShapeItem) and fmt.get("kind") == "shape":
                st["style"] = dict(fmt["style"])
            elif isinstance(it, ConnectorItem) and fmt.get("kind") == "connector":
                st["style"] = dict(fmt["style"])
            elif isinstance(it, ConnectorItem):
                st["style"]["line"] = fmt["style"].get("line") or st["style"]["line"]
                st["style"]["line_width"] = fmt["style"]["line_width"]
                st["style"]["dash"] = fmt["style"]["dash"]
            else:
                for k in ("line", "line_width", "dash"):
                    st["style"][k] = fmt["style"][k]
            st["text_style"] = dict(fmt["text_style"])
        self.modify([item], sty, "Reproduire la mise en forme")

    def set_geometry(self, shape: ShapeItem, **values) -> None:
        def geo(it, st):
            st.update({k: v for k, v in values.items() if v is not None})
        self.modify([shape], geo, "Taille et position", merge_key="geometry")

    def apply_theme(self, theme: str, variant: str = "standard") -> None:
        t = quickstyles.theme_colors(theme, variant)

        def th(it, st):
            if not st["style"].get("themed"):
                return
            if isinstance(it, ConnectorItem):
                st["style"]["line"] = t["connector"]
                st["text_style"]["color"] = t["label"]
            else:
                st["style"]["fill"] = t["fill"]
                st["style"]["line"] = t["line"]
                st["text_style"]["color"] = t["label"] if it.sdef.label_outside else t["text"]
        self.modify(self.all_items(), th, "Appliquer le thème")

    def find_text(self, query: str) -> int:
        q = query.strip().lower()
        self.clearSelection()
        n = 0
        if not q:
            return 0
        for it in self._items.values():
            hay = (it.text + " " + " ".join(f"{k} {v}" for k, v in it.data.items())).lower()
            if q in hay:
                it.setSelected(True)
                n += 1
        return n

    def relayout(self, direction: str) -> None:
        shapes = [s for s in self.shapes() if not s.sdef.container]
        if not shapes:
            return
        nodes = []
        for s in shapes:
            b = s.scene_box()
            nodes.append((s.id, b.center().x(), b.center().y(), b.width(), b.height()))
        edges = []
        for c in self.connectors():
            a, b = c.src.get("shape"), c.dst.get("shape")
            if a and b:
                edges.append((a, b))
        pos = layout.layered_layout(nodes, edges, direction, gap_major=mm_to_px(15),
                                    gap_minor=mm_to_px(10))

        def place(it, st):
            if it.id in pos:
                st["x"], st["y"] = pos[it.id]
        self.modify(shapes, place, "Redisposer la page")
        self.refresh_connectors()

    def set_route_all(self, route: str) -> None:
        self.apply_connector_style({"route": route}, items=self.connectors(),
                                   text="Style des connecteurs")

    # ------------------------------------------------------------------ fonctions Visio
    def change_shape(self, type_id: str) -> None:
        """« Modifier la forme » : remplace le type en gardant texte, style et connexions."""
        targets = [s for s in self.selected_shapes() if s.type_id != type_id and not s.locked]
        sdef = stencils.get(type_id)
        style_base, text_base = fileformat.default_shape_styles(type_id, self.doc.settings["theme"])

        def chg(it, st):
            st["type"] = type_id
            st.pop("path", None)
            st.pop("image", None)
            st.pop("text_rect", None)
            if it.style.get("themed"):
                st["style"] = dict(style_base)
            if sdef.label_outside != it.sdef.label_outside:
                st["text_style"]["color"] = text_base["color"]
                st["text_style"]["valign"] = text_base["valign"]
        self.modify(targets, chg, "Modifier la forme")

    def select_by_type(self, kind: str) -> int:
        items = []
        for it in self._items.values():
            if not it.isVisible() or not (it.flags() & it.GraphicsItemFlag.ItemIsSelectable):
                continue
            if kind == "shapes" and isinstance(it, ShapeItem) and it.type_id not in ("basic.text", "basic.title"):
                items.append(it)
            elif kind == "connectors" and isinstance(it, ConnectorItem):
                items.append(it)
            elif kind == "text" and isinstance(it, ShapeItem) and it.type_id in ("basic.text", "basic.title"):
                items.append(it)
            elif kind == "images" and isinstance(it, ShapeItem) and it.type_id == "special.image":
                items.append(it)
            elif kind.startswith("layer:") and it.layer == kind[6:]:
                items.append(it)
        self.select_items(items)
        return len(items)

    def apply_quick_style(self, changes: dict, text_color: str) -> None:
        def sty(it, st):
            if isinstance(it, ConnectorItem):
                if changes.get("line"):
                    st["style"]["line"] = changes["line"]
                st["style"]["themed"] = False
                return
            st["style"].update(changes)
            st["style"]["themed"] = False
            if not it.sdef.label_outside:
                st["text_style"]["color"] = text_color
        self.modify(self.selected_all(), sty, "Style rapide")

    def set_locked(self, items, locked: bool) -> None:
        def lk(it, st):
            if "locked" in st:
                st["locked"] = locked
        self.modify(items, lk, "Verrouiller" if locked else "Déverrouiller")

    def set_tip(self, item, tip: str) -> None:
        def tp(it, st):
            st["tip"] = tip
        self.modify([item], tp, "Info-bulle d'écran")

    def add_comment(self, item, text: str, author: str) -> None:
        import datetime
        entry = {"author": author, "date": datetime.datetime.now().strftime("%d/%m/%Y %H:%M"),
                 "text": text}

        def add(it, st):
            st["comments"] = list(st.get("comments", [])) + [entry]
        self.modify([item], add, "Nouveau commentaire")

    def delete_comment(self, item, index: int | None = None) -> None:
        def rm(it, st):
            if index is None:
                st["comments"] = []
            else:
                st["comments"] = [c for i, c in enumerate(st.get("comments", [])) if i != index]
        self.modify([item], rm, "Supprimer le commentaire")

    def commented_shapes(self) -> list[ShapeItem]:
        shapes = [s for s in self.shapes() if s.comments]
        return sorted(shapes, key=lambda s: (s.scene_box().top(), s.scene_box().left()))

    def add_border_title(self, style: str, title: str) -> None:
        """« Bordures et titres » : cadre et bandeau de titre posés à l'arrière-plan."""
        theme = quickstyles.theme_colors(self.doc.settings["theme"], "standard")
        m = mm_to_px(8)
        gid = new_id()
        states = []
        z = self.min_z() - 3

        def shape(type_id, x, y, w, h, **kw):
            nonlocal z
            st = self.new_shape_state(type_id, QPointF(x + w / 2, y + h / 2), w, h, snap=False)
            st.update(z=z, group=gid, locked=True, text=kw.pop("text", ""))
            st["style"].update(kw.pop("style", {}))
            st["style"]["themed"] = False
            st["text_style"].update(kw.pop("text_style", {}))
            states.append(st)
            z += 1
        W, H = self.page_w, self.page_h
        if style == "simple":
            shape("basic.rectangle", m, m, W - 2 * m, H - 2 * m, style={"fill": "", "line": theme["line"],
                                                                         "line_width": 1.5})
            shape("basic.title", m * 2, m * 1.6, W - 4 * m, mm_to_px(14), text=title,
                  text_style={"halign": "left", "color": theme["line"]})
        elif style == "band":
            shape("basic.rectangle", 0, 0, W, mm_to_px(22), style={"fill": theme["fill"], "line": ""})
            shape("basic.title", m, mm_to_px(4), W - 2 * m, mm_to_px(14), text=title,
                  text_style={"halign": "left", "color": "#ffffff"})
        elif style == "frame":
            shape("basic.rectangle", m, m, W - 2 * m, H - 2 * m, style={"fill": "", "line": "#404040",
                                                                         "line_width": 2.5})
            shape("basic.rectangle", W - m - mm_to_px(80), H - m - mm_to_px(22), mm_to_px(80), mm_to_px(22),
                  style={"fill": "#ffffff", "line": "#404040"})
            shape("basic.text", W - m - mm_to_px(78), H - m - mm_to_px(21), mm_to_px(76), mm_to_px(10),
                  text=title, text_style={"bold": True, "halign": "left", "color": "#000000"})
            import datetime
            shape("basic.text", W - m - mm_to_px(78), H - m - mm_to_px(11), mm_to_px(76), mm_to_px(9),
                  text=datetime.date.today().strftime("%d/%m/%Y"),
                  text_style={"halign": "left", "color": "#404040", "size": 9.0})
        else:  # moderne
            shape("basic.rectangle", 0, 0, mm_to_px(6), H, style={"fill": theme["fill"], "line": ""})
            shape("basic.title", m * 1.5, m, W - 3 * m, mm_to_px(14), text=title,
                  text_style={"halign": "left", "color": theme["line"], "size": 24.0})
            shape("basic.rectangle", m * 1.5, m + mm_to_px(15), mm_to_px(40), mm_to_px(1),
                  style={"fill": theme["fill"], "line": ""})
        self.add_states(states, "Bordures et titres")

    def check_diagram(self) -> list[tuple[str, str, list[str]]]:
        """« Vérifier le diagramme » : règles de cohérence des diagrammes de flux."""
        issues: list[tuple[str, str, list[str]]] = []
        conns = self.connectors()
        out_count: dict[str, int] = {}
        linked: set[str] = set()
        for c in conns:
            a, b = c.src.get("shape"), c.dst.get("shape")
            if a and self.item_by_id(a):
                out_count[a] = out_count.get(a, 0) + 1
                linked.add(a)
            if b and self.item_by_id(b):
                linked.add(b)
            if not (a and self.item_by_id(a)) or not (b and self.item_by_id(b)):
                issues.append(("Erreur", "Connecteur dont une extrémité n'est reliée à aucune forme.",
                               [c.id]))
        flow = [s for s in self.shapes() if s.type_id.startswith("flow.")]
        lanes = [s for s in self.shapes() if s.sdef.cff in ("lane_h", "lane_v")]
        if lanes:
            for s in flow:
                c = s.scene_box().center()
                if not any(lane.scene_box().contains(c) for lane in lanes):
                    issues.append(("Information", f"« {s.text or s.sdef.name} » n'est dans aucun couloir.",
                                   [s.id]))
        passive = {"basic.text", "basic.title", "basic.note", "basic.container", "basic.callout",
                   "flow.annotation", "uml.note", "special.image"}
        if conns:
            for s in self.shapes():
                if s.type_id not in passive and not s.sdef.container and not s.group and s.id not in linked:
                    issues.append(("Avertissement", f"Forme isolée : « {s.text or s.sdef.name} » n'est "
                                   "reliée à aucune autre forme.", [s.id]))
        for s in flow:
            if s.type_id == "flow.decision" and out_count.get(s.id, 0) < 2:
                issues.append(("Avertissement", f"La décision « {s.text or 'sans texte'} » devrait avoir "
                               "au moins deux sorties.", [s.id]))
            if s.type_id in ("flow.process", "flow.decision") and not s.text.strip():
                issues.append(("Information", f"{s.sdef.name} sans texte.", [s.id]))
        if flow and not any(s.type_id == "flow.terminator" for s in flow):
            issues.append(("Information", "Le diagramme de flux n'a pas de forme Début / Fin.", []))
        return issues

    # ------------------------------------------------------------------ couloirs (interfonctionnel)
    def cff_parts(self, orientation: str):
        frames, lanes, phases = [], [], []
        for s in self.shapes():
            kind = swimlanes.KIND_OF.get(s.type_id)
            if kind is None or kind[1] != orientation:
                continue
            (frames if kind[0] == "frame" else lanes if kind[0] == "lane" else phases).append(s)
        return frames, lanes, phases

    def has_cff(self) -> bool:
        return any(s.sdef.cff for s in self.shapes())

    @staticmethod
    def _cff_box(s: ShapeItem) -> swimlanes.Box:
        r = s.scene_box()
        return swimlanes.Box(s.id, r.left(), r.top(), r.width(), r.height())

    def _cff_carry(self, grabbed: ShapeItem) -> dict[str, QPointF]:
        kind, o = swimlanes.KIND_OF[grabbed.type_id]
        if kind == "phase":
            return {}
        r = grabbed.scene_box()
        out = {}
        for s in self.shapes():
            if s is grabbed or s.isSelected():
                continue
            if kind == "lane" and s.sdef.cff:
                continue
            if kind == "frame" and s.sdef.cff and swimlanes.KIND_OF[s.type_id][1] == o:
                out[s.id] = QPointF(s.pos())
            elif r.contains(s.scene_box().center()):
                out[s.id] = QPointF(s.pos())
        return out

    @staticmethod
    def _cff_flags(frame, phases) -> tuple[bool, bool]:
        title = frame.cff_opts.get("title", True) if frame is not None else True
        return title, not any(p.cff_opts.get("hidden", False) for p in phases)

    def cff_orientation(self) -> str | None:
        """Orientation du diagramme concerné : celle de la sélection, sinon celle de la page."""
        sel = self.single_selected
        if isinstance(sel, ShapeItem) and sel.sdef.cff:
            return sel.sdef.cff[-1]
        for o in ("h", "v"):
            if any(self.cff_parts(o)):
                return o
        return None

    def cff_option(self, key: str) -> bool:
        defaults = {"title": True, "hidden": False, "rotate": False}
        o = self.cff_orientation()
        if o is None:
            return defaults[key]
        frames, lanes, phases = self.cff_parts(o)
        targets = {"title": frames, "hidden": phases, "rotate": lanes}[key]
        return targets[0].cff_opts.get(key, defaults[key]) if targets else defaults[key]

    def cff_set_option(self, key: str, value: bool) -> None:
        """Barre de titre, séparateurs, étiquettes pivotées : comme les cases de l'onglet de Visio."""
        o = self.cff_orientation()
        if o is None:
            return
        frames, lanes, phases = self.cff_parts(o)
        targets = {"title": frames, "hidden": phases, "rotate": lanes}[key]
        if not targets:
            return
        labels = {"title": "Barre de titre", "hidden": "Séparateurs", "rotate": "Faire pivoter les étiquettes"}

        def fn(_it, st):
            st["cff"] = {**st.get("cff", {}), key: value}
        self.doc.undo_stack.beginMacro(labels[key])
        try:
            self.modify(targets, fn, labels[key])
            self.cff_layout(labels[key])
        finally:
            self.doc.undo_stack.endMacro()

    def cff_set_orientation(self, new: str) -> bool:
        """Change l'orientation du diagramme : couloirs, phases et formes sont transposés."""
        old = "v" if new == "h" else "h"
        frames, lanes, phases = self.cff_parts(old)
        if not lanes or any(self.cff_parts(new)):
            return False
        frame = frames[0] if frames else None
        title, _sep = self._cff_flags(frame, phases)
        t = swimlanes.TITLE if (frame is not None and title) else 0.0
        fbox = self._cff_box(frame) if frame else None
        lane_boxes = [self._cff_box(lane) for lane in lanes]
        ox, oy = swimlanes.origin(old, fbox, lane_boxes, title)
        areas = [fbox] if fbox else lane_boxes
        members = [s for s in self.shapes() if not s.sdef.cff
                   and any(b.contains(s.scene_box().center().x(), s.scene_box().center().y()) for b in areas)]

        def fn(it, st):
            if it.sdef.cff:
                kind = swimlanes.KIND_OF[it.type_id][0]
                st["type"] = {"frame": swimlanes.FRAME, "lane": swimlanes.LANE, "phase": swimlanes.PHASE_T}[kind][new]
                if kind == "frame":
                    w, h = st["h"] - t, st["w"] + t
                    st.update(x=fbox.left + w / 2, y=fbox.top + h / 2, w=w, h=h)
                    return
                st["w"], st["h"] = st["h"], st["w"]
            st["x"], st["y"] = swimlanes.transpose(ox, oy, st["x"], st["y"])
        self.doc.undo_stack.beginMacro("Orientation du diagramme")
        try:
            self.modify(frames + lanes + phases + members, fn, "Orientation du diagramme")
            self.cff_layout("Orientation du diagramme")
        finally:
            self.doc.undo_stack.endMacro()
        return True

    def cff_apply_style(self, preset: dict) -> None:
        """Styles du diagramme interfonctionnel (galerie de l'onglet)."""
        o = self.cff_orientation()
        if o is None:
            return
        frames, lanes, phases = self.cff_parts(o)

        def fn(it, st):
            role = "title" if it.sdef.cff.startswith("frame") else "lane"
            st["style"].update(fill=preset[role + "_fill"], line=preset["line"], themed=False)
            st["text_style"]["color"] = preset[role + "_text"]
        self.modify(frames + lanes + phases, fn, "Style interfonctionnel")

    # ------------------------------------------------------------------ conteneurs (Visio)
    @staticmethod
    def is_plain_container(s) -> bool:
        return isinstance(s, ShapeItem) and s.sdef.container and not s.sdef.cff

    def container_members(self, c: ShapeItem) -> list[ShapeItem]:
        """Formes posées dans le conteneur (centre à l'intérieur, au-dessus de lui)."""
        box = c.scene_box()
        return [s for s in self.shapes() if s is not c and not s.sdef.cff and s.zValue() > c.zValue()
                and box.contains(s.scene_box().center())]

    def containers_of(self, s: ShapeItem) -> list[ShapeItem]:
        c = s.scene_box().center()
        return [o for o in self.shapes() if self.is_plain_container(o) and o is not s
                and o.zValue() < s.zValue() and o.scene_box().contains(c)]

    def container_fit(self, c: ShapeItem, margin_mm: float = 6.0) -> bool:
        """« Ajuster au contenu » : le conteneur entoure exactement ses formes."""
        members = self.container_members(c)
        if not members:
            return False
        r = members[0].scene_box()
        for m in members[1:]:
            r = r.united(m.scene_box())
        m = mm_to_px(margin_mm)
        f = c.text_rect_norm()[3] if c.sdef.text_rect[1] == 0 else 0.0
        h = (r.height() + 2 * m) / max(0.2, 1.0 - f)
        w = r.width() + 2 * m
        top = r.top() - m - f * h
        self.modify([c], lambda _i, st: st.update(x=r.left() - m + w / 2, y=top + h / 2, w=w, h=h, rotation=0.0),
                    "Ajuster au contenu")
        return True

    def container_disband(self, c: ShapeItem) -> None:
        """« Désassembler le conteneur » : supprime le cadre, garde les formes."""
        self.delete_items([c], "Désassembler le conteneur")

    def container_select_contents(self, c: ShapeItem) -> None:
        self.select_items(self.container_members(c))

    def wrap_in_container(self, type_id: str, style: dict | None = None, text_style: dict | None = None):
        """Insertion > Conteneur avec une sélection : le conteneur entoure les formes choisies."""
        shapes = [s for s in self.selected_shapes() if not s.sdef.cff]
        if not shapes:
            return None
        r = shapes[0].scene_box()
        for s in shapes[1:]:
            r = r.united(s.scene_box())
        m = mm_to_px(6)
        sdef = stencils.get(type_id)
        f = sdef.text_rect[3]
        h = (r.height() + 2 * m) / (1.0 - f)
        w = r.width() + 2 * m
        st = self.new_shape_state(type_id, QPointF(r.left() - m + w / 2, r.top() - m - f * h + h / 2), w, h,
                                  snap=False)
        st["z"] = min(s.zValue() for s in shapes) - 1.0
        if style:
            st["style"].update(style, themed=False)
        if text_style:
            st["text_style"].update(text_style)
        self.add_states([st], "Insérer un conteneur")
        item = self.item_by_id(st["id"])
        self.select_items([item])
        return item

    def cff_memberships(self) -> dict[str, list[str]]:
        """Appartenance aux cadres, couloirs et phases, pour l'export Visio."""
        out: dict[str, list[str]] = {}
        others = [self._cff_box(s) for s in self.shapes() if not s.sdef.cff]
        for o in ("h", "v"):
            frames, lanes, phases = self.cff_parts(o)
            if not lanes and not frames:
                continue
            m = swimlanes.memberships(self._cff_box(frames[0]) if frames else None,
                                      [self._cff_box(x) for x in lanes], [self._cff_box(x) for x in phases],
                                      others)
            for k, v in m.items():
                out.setdefault(k, []).extend(c for c in v if c not in out.get(k, []))
        for c in self.shapes():
            if self.is_plain_container(c):
                for s in self.container_members(c):
                    if c.id not in out.setdefault(s.id, []):
                        out[s.id].append(c.id)
        return out

    def cff_layout(self, text: str = "Disposer les couloirs", prefer: str | None = None) -> None:
        """Remet les couloirs bout à bout, aligne phases et cadre, et déplace le contenu."""
        geo: dict[str, tuple] = {}
        deltas: dict[str, tuple[float, float]] = {}
        zmap: dict[str, float] = {}
        for o in ("h", "v"):
            frames, lanes, phases = self.cff_parts(o)
            if not lanes and not frames:
                continue
            frame = frames[0] if frames else None
            lane_boxes = [self._cff_box(lane) for lane in lanes]
            title, separators = self._cff_flags(frame, phases)
            g = swimlanes.layout(o, self._cff_box(frame) if frame else None, lane_boxes,
                                 [self._cff_box(p) for p in phases], title, separators)
            geo.update(g)
            for b in lane_boxes:
                if b.id in g:
                    deltas[b.id] = (g[b.id][0] - b.left, g[b.id][1] - b.top)
            for s in self.shapes():
                if s.sdef.cff:
                    continue
                c = s.scene_box().center()
                lane_id = swimlanes.member_lane(lane_boxes, c.x(), c.y(), prefer)
                if lane_id is not None and deltas.get(lane_id, (0, 0)) != (0, 0):
                    deltas[s.id] = deltas[lane_id]
            if frame is not None:
                zmap[frame.id] = swimlanes.Z_FRAME
            key = (lambda b: b.cy) if o == "h" else (lambda b: b.cx)
            for i, b in enumerate(sorted(lane_boxes, key=key)):
                zmap[b.id] = swimlanes.Z_LANE + i
            for i, p in enumerate(phases):
                zmap[p.id] = swimlanes.Z_PHASE + i
        if not geo and not deltas:
            return
        targets = [self._items[i] for i in set(geo) | set(deltas) | set(zmap) if i in self._items]

        def fn(it, st):
            if it.id in geo:
                left, top, w, h = geo[it.id]
                st.update(x=left + w / 2, y=top + h / 2, w=w, h=h, rotation=0.0, flip_h=False, flip_v=False)
            elif it.id in deltas:
                dx, dy = deltas[it.id]
                st["x"] += dx
                st["y"] += dy
            if it.id in zmap:
                st["z"] = zmap[it.id]
        self.modify(targets, fn, text)

    def cff_structure_states(self, orientation: str, center: QPointF, n_lanes: int = 3,
                             title: str = "Titre du diagramme", lane_names=None) -> list[dict]:
        length = swimlanes.DEFAULT_LENGTH if orientation == "h" else mm_to_px(140)
        size = swimlanes.DEFAULT_LANE if orientation == "h" else mm_to_px(55)
        if orientation == "h":
            left, top = center.x() - length / 2, center.y() - (n_lanes * size + swimlanes.TITLE) / 2
        else:
            left, top = center.x() - n_lanes * size / 2, center.y() - (length + swimlanes.TITLE) / 2
        left, top = max(left, mm_to_px(10)), max(top, mm_to_px(10))
        states = []
        lane_i = 0
        for role, type_id, b in swimlanes.new_structure(orientation, left, top, n_lanes, length, size):
            st = self.new_shape_state(type_id, QPointF(b.cx, b.cy), b.w, b.h, snap=False)
            if role == "frame":
                st["text"], st["z"] = title, swimlanes.Z_FRAME
            else:
                names = lane_names or []
                st["text"] = names[lane_i] if lane_i < len(names) else "Fonction"
                st["z"] = swimlanes.Z_LANE + lane_i
                lane_i += 1
            states.append(st)
        return states

    def cff_drop(self, type_id: str, pos: QPointF):
        """Dépôt d'une forme du gabarit interfonctionnel : crée ou complète la structure."""
        kind, o = swimlanes.KIND_OF[type_id]
        frames, lanes, phases = self.cff_parts(o)
        labels = {"frame": "Diagramme interfonctionnel", "lane": "Insérer un couloir",
                  "phase": "Insérer un séparateur"}
        self.doc.undo_stack.beginMacro(labels[kind])
        new_id_ = None
        try:
            if not lanes:
                states = self.cff_structure_states(o, pos, 3 if kind != "lane" else 1)
                self.add_states(states, labels["frame"])
                new_id_ = states[-1]["id"]
                frames, lanes, phases = self.cff_parts(o)
            if kind == "lane" and new_id_ is None:
                ref = self._cff_box(lanes[0])
                if o == "h":
                    st = self.new_shape_state(type_id, QPointF(ref.cx, pos.y()), ref.w, swimlanes.DEFAULT_LANE,
                                              snap=False)
                else:
                    st = self.new_shape_state(type_id, QPointF(pos.x(), ref.cy), swimlanes.DEFAULT_LANE, ref.h,
                                              snap=False)
                self._cff_inherit(st, lanes)
                self.add_states([st], labels["lane"])
                new_id_ = st["id"]
            elif kind == "phase":
                ref = self._cff_box(lanes[0])
                size = swimlanes.DEFAULT_PHASE
                host = next((p for p in phases if p.scene_box().contains(pos)), None)
                if host is not None:
                    # Comme Visio : le séparateur coupe la phase où on le dépose, sans rallonger.
                    hb = self._cff_box(host)
                    start, end = (hb.left, hb.left + hb.w) if o == "h" else (hb.top, hb.top + hb.h)
                    cut = min(max((pos.x() if o == "h" else pos.y()), start + swimlanes.MIN_PHASE),
                              end - swimlanes.MIN_PHASE)
                    if cut > start:
                        size = end - cut

                        def shrink(_it, hst, keep=cut - start):
                            if o == "h":
                                hst.update(x=start + keep / 2, w=keep)
                            else:
                                hst.update(y=start + keep / 2, h=keep)
                        self.modify([host], shrink, labels["phase"])
                        pos = QPointF(cut + size / 2, pos.y()) if o == "h" else QPointF(pos.x(), cut + size / 2)
                if o == "h":
                    st = self.new_shape_state(type_id, QPointF(pos.x(), ref.cy), size, ref.h, snap=False)
                else:
                    st = self.new_shape_state(type_id, QPointF(ref.cx, pos.y()), ref.w, size, snap=False)
                self._cff_inherit(st, phases or [])
                self.add_states([st], labels["phase"])
                new_id_ = st["id"]
            elif kind == "frame" and new_id_ is None:
                new_id_ = frames[0].id if frames else None
            self.cff_layout()
        finally:
            self.doc.undo_stack.endMacro()
        item = self.item_by_id(new_id_) if new_id_ else None
        if item is not None:
            self.select_items([item])
        return item

    @staticmethod
    def _cff_inherit(st: dict, like: list) -> None:
        if like:
            ref = like[-1]
            st["style"] = dict(ref.style)
            st["text_style"] = dict(ref.text_style)
            if ref.cff_opts:
                st["cff"] = dict(ref.cff_opts)

    def cff_insert_lane(self, before: bool = False) -> None:
        sel = self.single_selected
        if isinstance(sel, ShapeItem) and sel.sdef.cff in ("lane_h", "lane_v"):
            o = sel.sdef.cff[-1]
            b = sel.scene_box()
            if o == "h":
                pos = QPointF(b.center().x(), b.top() - 1 if before else b.bottom() + 1)
            else:
                pos = QPointF(b.left() - 1 if before else b.right() + 1, b.center().y())
            self.cff_drop(swimlanes.LANE[o], pos)
            return
        o = "v" if self.cff_parts("v")[1] and not self.cff_parts("h")[1] else "h"
        frames, lanes, _p = self.cff_parts(o)
        if lanes:
            last = max(lanes, key=lambda s: s.scene_box().bottom() if o == "h" else s.scene_box().right())
            b = last.scene_box()
            pos = QPointF(b.center().x(), b.bottom() + 1) if o == "h" else QPointF(b.right() + 1, b.center().y())
        else:
            pos = self.page_rect().center()
        self.cff_drop(swimlanes.LANE[o], pos)

    def cff_insert_phase(self) -> None:
        o = "v" if self.cff_parts("v")[1] and not self.cff_parts("h")[1] else "h"
        _f, lanes, phases = self.cff_parts(o)
        if phases:
            last = max(phases, key=lambda s: s.scene_box().center().x() if o == "h" else s.scene_box().center().y())
            b = last.scene_box()
            pos = QPointF(b.center().x() + 1, b.center().y()) if o == "h" else QPointF(b.center().x(),
                                                                                      b.center().y() + 1)
        elif lanes:
            b = self._cff_box(lanes[0])
            pos = QPointF(b.left + swimlanes.HEADER + 1, b.cy) if o == "h" else QPointF(b.cx, b.top + swimlanes.HEADER + 1)
        else:
            pos = self.page_rect().center()
        self.cff_drop(swimlanes.PHASE_T[o], pos)
