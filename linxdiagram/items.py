"""Éléments graphiques : formes (ShapeItem) et connecteurs (ConnectorItem).

Le modèle reprend celui de la ShapeSheet Visio : une forme est positionnée par
son centre (PinX/PinY), possède une largeur, une hauteur, un angle, des
retournements, des points de connexion et un bloc de texte. Un connecteur est
une forme 1-D dont chaque extrémité est libre ou collée à une forme, soit sur
un point précis (collage statique), soit sur la forme entière (collage
dynamique : le meilleur côté est choisi automatiquement).
"""

from __future__ import annotations

import base64
import math

from PyQt6.QtCore import QBuffer, QByteArray, QIODevice, QLineF, QPointF, QRectF, Qt
from PyQt6.QtGui import (QBrush, QColor, QFont, QImageReader, QKeySequence, QLinearGradient,
                         QFontMetricsF, QPainter, QPainterPath, QPainterPathStroker, QPen, QPixmap,
                         QPolygonF, QTextBlockFormat, QTextCursor, QTextDocument, QTextListFormat,
                         QTextOption, QTransform)
from PyQt6.QtWidgets import (QApplication, QGraphicsItem, QGraphicsTextItem, QMenu,
                             QStyleOptionGraphicsItem)

from . import fields, security, stencils
from .fileformat import MAX_TEXT, clean_data_links, normalize_status_key
from .routing import axis_direction, curve_controls, route_orthogonal
from .swimlanes import HEADER as CFF_HEADER, PHASE as CFF_PHASE, TITLE as CFF_TITLE
from .units import INDENT_PX, MIN_SIZE_PX, mm_to_px

ACCENT = QColor("#2563eb")
GLUE = QColor("#16a34a")
HANDLE_PX = 8.0
ROT_OFFSET_PX = 24.0
TEXT_PAD = 3.0
PT_TO_PX = 96.0 / 72.0

GIC = QGraphicsItem.GraphicsItemChange
GIF = QGraphicsItem.GraphicsItemFlag

_DASH = {"solid": Qt.PenStyle.SolidLine, "dash": Qt.PenStyle.DashLine,
         "dot": Qt.PenStyle.DotLine, "dashdot": Qt.PenStyle.DashDotLine}
_HALIGN = {"left": Qt.AlignmentFlag.AlignLeft, "center": Qt.AlignmentFlag.AlignHCenter,
           "right": Qt.AlignmentFlag.AlignRight, "justify": Qt.AlignmentFlag.AlignJustify}
JUMP_R = 4.0
# Signe (x, y) de la poignée mobile par rapport au point d'ancrage opposé.
_HANDLE_SIGNS = [(-1, -1), (0, -1), (1, -1), (1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0)]
ROTATE_HANDLE = 8


def make_pen(color: str, width: float, dash: str) -> QPen:
    if not color:
        return QPen(Qt.PenStyle.NoPen)
    pen = QPen(QColor(color), width)
    pen.setStyle(_DASH.get(dash, Qt.PenStyle.SolidLine))
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap if dash == "solid" else Qt.PenCapStyle.FlatCap)
    return pen


def make_font(ts: dict) -> QFont:
    f = QFont(ts["font"])
    f.setPixelSize(max(1, round(ts["size"] * PT_TO_PX)))
    f.setBold(ts["bold"])
    f.setItalic(ts["italic"])
    f.setUnderline(ts["underline"])
    f.setStrikeOut(ts.get("strike", False))
    return f


def painter_scale(painter: QPainter) -> float:
    t = painter.worldTransform()
    return max(math.hypot(t.m11(), t.m12()), 1e-6)


def decode_image(data: bytes) -> QPixmap:
    """Décode une image PNG/JPEG avec plafond mémoire et taille maximale."""
    buf = QBuffer()
    buf.setData(QByteArray(data))
    buf.open(QIODevice.OpenModeFlag.ReadOnly)
    reader = QImageReader(buf)
    reader.setAllocationLimit(256)  # Mo
    if bytes(reader.format().data()).lower() not in (b"png", b"jpeg", b"jpg"):
        return QPixmap()
    size = reader.size()
    if not size.isValid() or size.width() > 12000 or size.height() > 12000:
        return QPixmap()
    image = reader.read()
    if image.isNull():
        return QPixmap()
    return QPixmap.fromImage(image)


class SafeTextDocument(QTextDocument):
    """Document texte qui refuse de charger toute ressource (fichiers, images)."""

    def loadResource(self, rtype, url):  # noqa: N802 (API Qt)
        return None


class TextLabel(QGraphicsTextItem):
    """Bloc de texte d'une forme ou d'un connecteur, en texte brut uniquement."""

    def __init__(self, owner: "TextOwner"):
        super().__init__(owner)
        self.owner = owner
        self.setDocument(SafeTextDocument(self))
        self.document().setDocumentMargin(1)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.setAcceptDrops(False)
        self.setAcceptHoverEvents(False)
        self.document().contentsChanged.connect(self._changed)

    def _changed(self) -> None:
        if self.owner.editing and not self.owner._formatting:
            self.owner.layout_label()

    def keyPressEvent(self, event):  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self.owner.finish_edit()
            return
        if event.matches(QKeySequence.StandardKey.Paste):
            self.paste_plain()
            return
        super().keyPressEvent(event)

    def paste_plain(self) -> None:
        text = security.clean_text(QApplication.clipboard().text(), MAX_TEXT)
        cursor = self.textCursor()
        cursor.insertText(text)
        self.setTextCursor(cursor)

    def focusOutEvent(self, event):  # noqa: N802
        super().focusOutEvent(event)
        if self.owner.editing and event.reason() != Qt.FocusReason.PopupFocusReason:
            self.owner.finish_edit()

    def contextMenuEvent(self, event):  # noqa: N802
        if not self.owner.editing:
            event.ignore()
            return
        menu = QMenu()
        cursor = self.textCursor()
        a_cut = menu.addAction("Couper")
        a_copy = menu.addAction("Copier")
        a_paste = menu.addAction("Coller")
        menu.addSeparator()
        a_all = menu.addAction("Tout sélectionner")
        a_cut.setEnabled(cursor.hasSelection())
        a_copy.setEnabled(cursor.hasSelection())
        chosen = menu.exec(event.screenPos())
        if chosen is a_cut or chosen is a_copy:
            QApplication.clipboard().setText(cursor.selectedText().replace(" ", "\n"))
            if chosen is a_cut:
                cursor.removeSelectedText()
                self.setTextCursor(cursor)
        elif chosen is a_paste:
            self.paste_plain()
        elif chosen is a_all:
            cursor.select(cursor.SelectionType.Document)
            self.setTextCursor(cursor)
        event.accept()


class TextOwner(QGraphicsItem):
    """Comportement commun : édition du texte en place, annulable."""

    def __init__(self):
        super().__init__()
        self.id = ""
        self.text = ""
        self.text_style: dict = {}
        self.editing = False
        self._edit_before: dict | None = None
        self._applying = False
        self._formatting = False  # mise en forme des paragraphes en cours (évite la récursion)
        self.label = TextLabel(self)

    def state(self) -> dict:  # pragma: no cover - surchargé
        raise NotImplementedError

    def layout_label(self) -> None:  # pragma: no cover - surchargé
        raise NotImplementedError

    def _apply_label_format(self) -> None:
        ts = self.text_style
        lab = self.label
        shown = self.display_text()
        if not self.editing and lab.toPlainText() != shown:
            lab.setPlainText(shown)
        lab.setFont(make_font(ts))
        lab.setDefaultTextColor(QColor(ts["color"]))
        doc = lab.document()
        opt = doc.defaultTextOption()
        opt.setAlignment(_HALIGN[ts["halign"]])
        opt.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        doc.setDefaultTextOption(opt)
        self._apply_paragraphs(doc, ts)

    def _apply_paragraphs(self, doc, ts: dict) -> None:
        """Puces, retrait et interligne (Accueil > Paragraphe de Visio) sur tous les paragraphes."""
        bullets = bool(ts.get("bullets"))
        indent = int(ts.get("indent", 0)) * INDENT_PX
        spacing = float(ts.get("spacing", 1.0))
        first = doc.firstBlock()
        fmt0 = first.blockFormat()
        same_spacing = (abs(fmt0.lineHeight() - spacing * 100) < 0.01 if abs(spacing - 1.0) > 1e-6
                        else fmt0.lineHeightType() == 0)
        if ((first.textList() is not None) == bullets and abs(fmt0.leftMargin() - indent) < 0.01
                and same_spacing):
            return
        self._formatting = True
        try:
            cur = QTextCursor(doc)
            cur.beginEditBlock()
            cur.select(QTextCursor.SelectionType.Document)
            bf = QTextBlockFormat()
            bf.setLeftMargin(indent)
            if abs(spacing - 1.0) > 1e-6:
                bf.setLineHeight(spacing * 100, QTextBlockFormat.LineHeightTypes.ProportionalHeight.value)
            cur.setBlockFormat(bf)
            if bullets:
                lf = QTextListFormat()
                lf.setStyle(QTextListFormat.Style.ListDisc)
                lf.setIndent(1)
                cur.createList(lf)
            cur.endEditBlock()
        finally:
            self._formatting = False

    def display_text(self) -> str:
        """Texte affiché : les champs ({{page}}, {{date}}…) sont remplacés par leur valeur."""
        return fields.resolve(self.text, self.scene()) if fields.has_fields(self.text) else self.text

    def start_edit(self, select_all: bool = True) -> None:
        sc = self.scene()
        if self.editing or sc is None:
            return
        if self.label.toPlainText() != self.text:
            self.label.setPlainText(self.text)  # en édition, les codes de champ sont visibles
        if sc.editing_item is not None and sc.editing_item is not self:
            sc.editing_item.finish_edit()
        self._edit_before = self.state()
        self.editing = True
        sc.editing_item = self
        self.label.setTextInteractionFlags(Qt.TextInteractionFlag.TextEditorInteraction)
        self.label.setAcceptedMouseButtons(Qt.MouseButton.LeftButton | Qt.MouseButton.RightButton)
        self.label.setFocus(Qt.FocusReason.OtherFocusReason)
        cursor = self.label.textCursor()
        if select_all:
            cursor.select(cursor.SelectionType.Document)
        else:
            cursor.movePosition(cursor.MoveOperation.End)
        self.label.setTextCursor(cursor)
        self.layout_label()
        self.update()

    def finish_edit(self) -> None:
        if not self.editing:
            return
        self.editing = False
        self.text = security.clean_text(self.label.toPlainText(), MAX_TEXT)
        self.label.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self.label.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        cursor = self.label.textCursor()
        cursor.clearSelection()
        self.label.setTextCursor(cursor)
        self.label.clearFocus()
        self.layout_label()
        self.update()
        sc = self.scene()
        before, self._edit_before = self._edit_before, None
        if sc is not None:
            if sc.editing_item is self:
                sc.editing_item = None
            if before is not None and before.get("text") != self.text:
                sc.push_state({self.id: before}, {self.id: self.state()}, "Modifier le texte")
            sc.after_text_edit(self)


# =========================================================================== formes

class ShapeItem(TextOwner):
    kind = "shape"

    def __init__(self, state: dict):
        super().__init__()
        self.id = state["id"]
        self.type_id = state["type"]
        self.sdef = stencils.get(self.type_id)
        self.w = self.h = 10.0
        self.flip_h = self.flip_v = False
        self.style: dict = {}
        self.data: dict = {}
        self.data_links: list[dict] = []
        self.data_graphic: dict = {}
        self.link = ""
        self.group = ""
        self.image_b64 = ""
        self.custom: list = []
        self.text_rect_override: list | None = None
        self.custom_ports: list | None = None  # points de connexion ajoutés ou retirés par l'utilisateur
        self.cff_opts: dict = {}  # options interfonctionnelles : title, hidden, rotate
        self.locked = False
        self.tip = ""
        self.comments: list = []
        self.layer = ""
        self._pixmap: QPixmap | None = None
        self._outline = QPainterPath()
        self._detail: QPainterPath | None = None
        self._drag: dict | None = None
        self.setFlags(GIF.ItemIsSelectable | GIF.ItemIsMovable | GIF.ItemSendsGeometryChanges)
        self.set_state(state)

    # ------------------------------------------------------------ état
    def state(self) -> dict:
        d = {"id": self.id, "type": self.type_id, "x": self.pos().x(), "y": self.pos().y(),
             "w": self.w, "h": self.h, "rotation": self.rotation(), "flip_h": self.flip_h,
             "flip_v": self.flip_v, "z": self.zValue(), "text": self.text,
             "style": dict(self.style), "text_style": dict(self.text_style),
             "data": dict(self.data), "link": self.link, "group": self.group,
             "locked": self.locked, "tip": self.tip, "comments": [dict(c) for c in self.comments],
             "layer": self.layer}
        if self.data_links:
            d["data_links"] = [dict(link, fields=list(link.get("fields", [])),
                                    field_map=dict(link.get("field_map", {})))
                                for link in self.data_links]
        if self.data_graphic:
            d["data_graphic"] = dict(self.data_graphic)
        if self.type_id == "special.image":
            d["image"] = self.image_b64
        if self.type_id == "special.custom":
            d["path"] = [list(c) for c in self.custom]
        if self.text_rect_override:
            d["text_rect"] = list(self.text_rect_override)
        if self.custom_ports is not None:
            d["ports"] = [list(p) for p in self.custom_ports]
        if self.cff_opts:
            d["cff"] = dict(self.cff_opts)
        return d

    def set_state(self, st: dict) -> None:
        self.prepareGeometryChange()
        if st.get("type", self.type_id) != self.type_id:  # « Modifier la forme »
            self.type_id = st["type"]
            self.sdef = stencils.get(self.type_id)
            self.image_b64 = ""
            self._pixmap = None
        self.w = max(MIN_SIZE_PX, st["w"])
        self.h = max(MIN_SIZE_PX, st["h"])
        self.flip_h, self.flip_v = st["flip_h"], st["flip_v"]
        self.style = dict(st["style"])
        self.text_style = dict(st["text_style"])
        self.text = st["text"]
        self.data = dict(st.get("data", {}))
        self.data_links = clean_data_links(st.get("data_links"), st.get("data_link"))
        self.data_graphic = dict(st.get("data_graphic", {}))
        self.link = st.get("link", "")
        self.group = st.get("group", "")
        if self.type_id == "special.image" and st.get("image", "") != self.image_b64:
            self.image_b64 = st.get("image", "")
            self._pixmap = None
        if self.type_id == "special.custom":
            self.custom = [list(c) for c in st.get("path", [])]
        self.text_rect_override = list(st["text_rect"]) if st.get("text_rect") else None
        self.custom_ports = [tuple(p) for p in st["ports"]] if st.get("ports") is not None else None
        self.locked = bool(st.get("locked", False))
        self.tip = st.get("tip", "")
        self.comments = [dict(c) for c in st.get("comments", [])]
        self.layer = st.get("layer", "")
        self.cff_opts = dict(st.get("cff", {})) if self.sdef.cff else {}
        self.setToolTip(security.tooltip_html(self.tip))
        self.setFlag(GIF.ItemIsMovable, not self.locked)
        self._applying = True
        self.setPos(st["x"], st["y"])
        self.setRotation(st["rotation"])
        self.setZValue(st["z"])
        self._applying = False
        self.rebuild()

    # ------------------------------------------------------------ géométrie
    def box(self) -> QRectF:
        return QRectF(-self.w / 2, -self.h / 2, self.w, self.h)

    def cff_header_rect(self) -> QRectF:
        """Bandeau d'un élément interfonctionnel : en-tête de couloir, barre de titre, phase."""
        b = self.box()
        kind = self.sdef.cff
        if self.cff_band_hidden():
            return QRectF(b.left(), b.top(), 0.0, 0.0)
        if kind == "lane_h":
            return QRectF(b.left(), b.top(), min(CFF_HEADER, b.width() * 0.4), b.height())
        if kind == "lane_v":
            return QRectF(b.left(), b.top(), b.width(), min(CFF_HEADER, b.height() * 0.4))
        if kind in ("frame_h", "frame_v"):
            return QRectF(b.left(), b.top(), b.width(), min(CFF_TITLE, b.height() * 0.5))
        if kind == "phase_h":
            return QRectF(b.left(), b.top(), b.width(), min(CFF_PHASE, b.height() * 0.5))
        return QRectF(b.left(), b.top(), min(CFF_PHASE, b.width() * 0.5), b.height())

    def cff_band_hidden(self) -> bool:
        """Barre de titre masquée (cadre) ou séparateurs masqués (phase)."""
        kind = self.sdef.cff
        if kind.startswith("frame"):
            return not self.cff_opts.get("title", True)
        return kind.startswith("phase") and bool(self.cff_opts.get("hidden", False))

    def vertical_text(self) -> bool:
        vertical = self.sdef.cff in ("lane_h", "phase_v")
        if self.sdef.cff.startswith("lane") and self.cff_opts.get("rotate", False):
            return not vertical  # « Faire pivoter les étiquettes des couloirs »
        return vertical

    def text_rect_norm(self) -> tuple[float, float, float, float]:
        if self.sdef.cff:
            r = self.cff_header_rect()
            return ((r.left() + self.w / 2) / self.w, (r.top() + self.h / 2) / self.h,
                    r.width() / self.w, r.height() / self.h)
        return tuple(self.text_rect_override or self.sdef.text_rect)

    def text_rect(self) -> QRectF:
        if self.sdef.cff:
            return self.cff_header_rect()
        tx, ty, tw, th = self.text_rect_norm()
        return QRectF(-self.w / 2 + tx * self.w, -self.h / 2 + ty * self.h, tw * self.w, th * self.h)

    def scene_box(self) -> QRectF:
        return self.mapRectToScene(self.box())

    def visual_scene_rect(self) -> QRectF:
        r = self.box()
        if self.sdef.label_outside and self.text:
            r = r.united(self.label.mapRectToParent(self.label.boundingRect()))
        data_rect = self.data_graphic_rect()
        if not data_rect.isNull():
            r = r.united(data_rect)
            r = r.united(self.data_graphic_rect(1.0))
        return self.mapRectToScene(r)

    def data_graphic_text(self) -> str:
        field = self.data_graphic.get("field", "")
        value = self.data.get(field, "") if field else ""
        if not isinstance(value, str) or not value.strip():
            return ""
        if self.data_graphic.get("display") == "label_value":
            return f"{field} · {value}"
        return value

    def data_graphic_rect(self, scale: float | None = None) -> QRectF:
        text = self.data_graphic_text()
        if not text:
            return QRectF()
        s = max(scale or self._scale(), 1e-6)
        font = QFont("Arial")
        font.setPixelSize(max(1, round(11.0 / s)))
        metrics = QFontMetricsF(font)
        max_width = 240.0 / s
        width = min(max_width, max(52.0 / s, metrics.horizontalAdvance(text) + 16.0 / s))
        height = 22.0 / s
        b = self.box()
        return QRectF(b.right() - width, b.bottom() + 5.0 / s, width, height)

    def data_graphic_palette(self) -> tuple[str, str, str]:
        if self.data_graphic.get("display") == "status":
            value = normalize_status_key(self.data.get(self.data_graphic.get("field", ""), ""))
            key = value
            for rule in self.data_graphic.get("status_colors", []):
                if normalize_status_key(rule.get("value", "")) == key:
                    color = QColor(rule.get("color", "#f3f4f6"))
                    fill = color.name()
                    ink = "#27313d" if color.lightness() >= 145 else "#ffffff"
                    border = color.darker(125).name() if color.lightness() >= 45 else color.lighter(170).name()
                    return fill, ink, border
            if value in {"done", "complete", "completed", "termine", "terminee", "success",
                         "succeeded", "ok", "valide", "validee", "vert", "green"}:
                return "#e7f4e4", "#237a3b", "#9fcf9b"
            if value in {"blocked", "bloque", "late", "retard", "error", "failed", "echec",
                         "critical", "critique", "urgent", "rouge", "red"}:
                return "#fde7e9", "#a4262c", "#e8a3a6"
            if value in {"in progress", "en cours", "pending", "en attente", "attention", "orange",
                         "amber", "yellow", "jaune"}:
                return "#fff4ce", "#8a4b00", "#e5c66a"
            return "#f3f4f6", "#374151", "#d1d5db"
        return "#eff6ff", "#1e3a5f", "#bfdbfe"

    def export_paths(self) -> tuple[QPainterPath, QPainterPath | None]:
        """Géométrie non retournée dans le repère (0..w, 0..h), y vers le bas."""
        w, h = self.w, self.h
        if self.type_id == "special.custom" and self.custom:
            return stencils.custom_path(self.custom, w, h), None
        if self.sdef.roundable and self.style.get("rounding", 0) > 0:
            return stencils.rect_builder(w, h, mm_to_px(self.style["rounding"]))
        return self.sdef.builder(w, h)

    def rebuild(self) -> None:
        self.prepareGeometryChange()
        w, h = self.w, self.h
        outline, detail = self.export_paths()
        m = QTransform.fromTranslate(-w / 2, -h / 2) * QTransform.fromScale(
            -1.0 if self.flip_h else 1.0, -1.0 if self.flip_v else 1.0)
        self._outline = m.map(outline)
        self._detail = m.map(detail) if detail is not None else None
        self.layout_label()
        self.update()
        self.notify_connectors()

    def layout_label(self) -> None:
        self._apply_label_format()
        lab = self.label
        r = self.text_rect().adjusted(TEXT_PAD, TEXT_PAD, -TEXT_PAD, -TEXT_PAD)
        lab.setVisible(not (self.sdef.cff and self.cff_band_hidden()))
        if self.vertical_text():
            # Étiquette de couloir écrite de bas en haut, comme dans Visio.
            lab.setRotation(-90)
            lab.setTextWidth(max(r.height(), 8.0))
            dh = lab.document().size().height()
            lab.setPos(r.center().x() - dh / 2, r.bottom())
            return
        lab.setRotation(0)
        lab.setTextWidth(max(r.width(), 8.0))
        dh = lab.document().size().height()
        valign = self.text_style["valign"]
        if valign == "top":
            y = r.top()
        elif valign == "bottom":
            y = r.bottom() - dh
        else:
            y = r.center().y() - dh / 2
        lab.setPos(r.left(), y)

    def _scale(self) -> float:
        sc = self.scene()
        return sc.view_scale if sc is not None else 1.0

    def _is_single_selected(self) -> bool:
        sc = self.scene()
        return sc is not None and sc.single_selected is self

    def boundingRect(self) -> QRectF:  # noqa: N802
        r = self._outline.boundingRect().united(self.box())
        m = self.style.get("line_width", 1.0) / 2 + 2
        if self.style.get("shadow"):
            m += 6
        if self.style.get("glow"):
            m += self.style.get("glow_size", 8.0) * PT_TO_PX * 1.7
        if self.comments:
            m += 20
        r = r.adjusted(-m, -m, m, m)
        data_rect = self.data_graphic_rect()
        if not data_rect.isNull():
            r = r.united(data_rect)
            r = r.united(self.data_graphic_rect(1.0))
        if self.isSelected():
            s = self._scale()
            hs = HANDLE_PX / s
            r = r.adjusted(-hs, -hs - ROT_OFFSET_PX / s, hs, hs)
        return r

    def shape(self) -> QPainterPath:
        if self.sdef.cff:
            # Seuls le bandeau et le bord sont cliquables : l'intérieur d'un couloir laisse
            # passer les clics (sélection par zone, formes posées dessus).
            p = QPainterPath()
            p.setFillRule(Qt.FillRule.WindingFill)
            p.addRect(self.cff_header_rect())
            b = self.box()
            k = 4.0 / self._scale()
            if self.sdef.cff.startswith("phase") and self.cff_band_hidden() and not self.isSelected():
                return QPainterPath()
            if not self.sdef.cff.startswith("phase"):
                for r in (QRectF(b.left() - k, b.top() - k, b.width() + 2 * k, 2 * k),
                          QRectF(b.left() - k, b.bottom() - k, b.width() + 2 * k, 2 * k),
                          QRectF(b.left() - k, b.top(), 2 * k, b.height()),
                          QRectF(b.right() - k, b.top(), 2 * k, b.height())):
                    p.addRect(r)
            if self.isSelected() and self._is_single_selected():
                hs = HANDLE_PX / self._scale() * 1.6
                for pt in self.handle_points()[:8]:
                    p.addRect(QRectF(pt.x() - hs / 2, pt.y() - hs / 2, hs, hs))
            return p
        p = QPainterPath(self._outline)
        p.setFillRule(Qt.FillRule.WindingFill)
        if not self.sdef.outline_visible or not self.style.get("fill"):
            p.addRect(self.box())
        if self.sdef.label_outside and self.text:
            p.addRect(self.label.mapRectToParent(self.label.boundingRect()))
        if self.isSelected() and self._is_single_selected():
            s = self._scale()
            hs = HANDLE_PX / s * 1.6
            for pt in self.handle_points():
                p.addRect(QRectF(pt.x() - hs / 2, pt.y() - hs / 2, hs, hs))
        return p

    def handle_points(self) -> list[QPointF]:
        b = self.box()
        l, t, r, bt = b.left(), b.top(), b.right(), b.bottom()
        cx, cy = b.center().x(), b.center().y()
        pts = [QPointF(l, t), QPointF(cx, t), QPointF(r, t), QPointF(r, cy), QPointF(r, bt),
               QPointF(cx, bt), QPointF(l, bt), QPointF(l, cy)]
        pts.append(QPointF(cx, t - ROT_OFFSET_PX / self._scale()))
        return pts

    def handle_at(self, scene_pos: QPointF) -> int | None:
        if not self._is_single_selected() or self.locked:
            return None
        local = self.mapFromScene(scene_pos)
        tol = HANDLE_PX / self._scale() * 0.9
        pts = self.handle_points()
        for i in ([] if self.sdef.cff else [ROTATE_HANDLE]) + list(range(8)):
            if abs(pts[i].x() - local.x()) <= tol and abs(pts[i].y() - local.y()) <= tol:
                if i in (1, 5) and self.w * self._scale() < 3 * HANDLE_PX:
                    continue
                if i in (3, 7) and self.h * self._scale() < 3 * HANDLE_PX:
                    continue
                return i
        return None

    def handle_cursor(self, index: int) -> Qt.CursorShape:
        if index == ROTATE_HANDLE:
            return Qt.CursorShape.CrossCursor
        cursors = [Qt.CursorShape.SizeFDiagCursor, Qt.CursorShape.SizeVerCursor,
                   Qt.CursorShape.SizeBDiagCursor, Qt.CursorShape.SizeHorCursor]
        step = round(self.rotation() / 45.0)
        return cursors[(index + step) % 4]

    # ------------------------------------------------------------ points de connexion
    @property
    def ports(self) -> tuple:
        """Points de connexion (coordonnées normalisées) : ceux du gabarit ou ceux de la forme."""
        return tuple(self.custom_ports) if self.custom_ports is not None else self.sdef.ports

    def port_count(self) -> int:
        return len(self.ports)

    def local_norm(self, scene_pos: QPointF) -> tuple[float, float]:
        """Position normalisée (0..1 sur la boîte, avant retournement) d'un point de la scène."""
        p = self.mapFromScene(scene_pos)
        x, y = p.x(), p.y()
        if self.flip_h:
            x = -x
        if self.flip_v:
            y = -y
        return (x + self.w / 2) / self.w, (y + self.h / 2) / self.h

    def _port_local(self, i: int) -> tuple[QPointF, tuple[float, float]]:
        nx, ny = self.ports[i]
        x = -self.w / 2 + nx * self.w
        y = -self.h / 2 + ny * self.h
        if nx <= 0.001:
            d = (-1.0, 0.0)
        elif nx >= 0.999:
            d = (1.0, 0.0)
        elif ny <= 0.001:
            d = (0.0, -1.0)
        elif ny >= 0.999:
            d = (0.0, 1.0)
        else:
            d = axis_direction(x, y)
        if self.flip_h:
            x, d = -x, (-d[0], d[1])
        if self.flip_v:
            y, d = -y, (d[0], -d[1])
        return QPointF(x, y), d

    def port_scene(self, i: int) -> tuple[QPointF, tuple[float, float]]:
        p, d = self._port_local(i)
        t = QTransform().rotate(self.rotation())
        dx, dy = t.map(d[0], d[1])
        return self.mapToScene(p), axis_direction(dx, dy)

    def _is_side_port(self, i: int) -> bool:
        nx, ny = self.ports[i]
        on_x = nx <= 0.001 or nx >= 0.999
        on_y = ny <= 0.001 or ny >= 0.999
        return on_x != on_y

    def best_port(self, ref: QPointF, exclude=None) -> tuple[QPointF, tuple[float, float]]:
        """Collage dynamique : côté le plus proche, en évitant les côtés déjà occupés."""
        candidates = [i for i in range(self.port_count()) if self._is_side_port(i)]
        if not candidates:
            candidates = list(range(self.port_count()))
        used: list[QPointF] = []
        sc = self.scene()
        if sc is not None:
            for c in sc.connectors_of(self.id):
                if c is exclude:
                    continue
                for end in (c.src, c.dst):
                    if end.get("shape") == self.id:
                        used.append(QPointF(end["x"], end["y"]))
        best = None
        for i in candidates:
            p, d = self.port_scene(i)
            dist = QLineF(p, ref).length()
            dist += 80.0 * sum(1 for u in used if QLineF(u, p).length() < 1.5)
            if best is None or dist < best[0]:
                best = (dist, p, d)
        if best is None:
            return self.scenePos(), None
        return best[1], best[2]

    def port_at(self, scene_pos: QPointF, tol: float) -> int | None:
        best = None
        for i in range(self.port_count()):
            p, _ = self.port_scene(i)
            dist = QLineF(p, scene_pos).length()
            if dist <= tol and (best is None or dist < best[0]):
                best = (dist, i)
        return best[1] if best else None

    def notify_connectors(self) -> None:
        sc = self.scene()
        if sc is not None:
            for c in sc.connectors_of(self.id):
                c.update_path()

    # ------------------------------------------------------------ dessin
    def _brush(self) -> QBrush:
        fill = self.style.get("fill")
        if not fill:
            return QBrush(Qt.BrushStyle.NoBrush)
        color = QColor(fill)
        color.setAlphaF(max(0.0, 1.0 - self.style.get("transparency", 0) / 100.0))
        if self.style.get("gradient"):
            g = QLinearGradient(0, -self.h / 2, 0, self.h / 2)
            top = color.lighter(145)
            top.setAlphaF(color.alphaF())
            g.setColorAt(0, top)
            g.setColorAt(1, color)
            return QBrush(g)
        return QBrush(color)

    def pixmap(self) -> QPixmap:
        if self._pixmap is None:
            self._pixmap = QPixmap()
            if self.image_b64:
                try:
                    self._pixmap = decode_image(base64.b64decode(self.image_b64))
                except ValueError:
                    pass
        return self._pixmap

    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem, widget=None) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        st = self.style
        pen = make_pen(st["line"], st["line_width"], st["dash"])
        if st.get("glow") and self.sdef.outline_visible:
            glow = QColor(st["glow"])
            size = st.get("glow_size", 8.0) * PT_TO_PX
            for i in range(4, 0, -1):
                glow.setAlpha(int(140 / (i + 1)))
                gpen = QPen(glow, size * i / 2.5)
                gpen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
                painter.strokePath(self._outline, gpen)
        if st.get("shadow") and self.sdef.outline_visible:
            painter.fillPath(self._outline.translated(4, 4), QColor(0, 0, 0, 60))
        if self.type_id == "special.image":
            pm = self.pixmap()
            if pm.isNull():
                painter.fillRect(self.box(), QColor("#f0f0f0"))
                painter.setPen(QPen(QColor("#999999"), 1, Qt.PenStyle.DashLine))
                painter.drawRect(self.box())
                painter.drawText(self.box(), Qt.AlignmentFlag.AlignCenter, "Image")
            else:
                painter.save()
                painter.scale(-1 if self.flip_h else 1, -1 if self.flip_v else 1)
                painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
                painter.drawPixmap(self.box(), pm, QRectF(pm.rect()))
                painter.restore()
            if st["line"]:
                painter.setPen(pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRect(self.box())
        elif self.sdef.cff:
            self._paint_cff(painter, pen)
        elif self.sdef.outline_visible:
            painter.setBrush(self._brush())
            painter.setPen(pen)
            painter.drawPath(self._outline)
        if self._detail is not None:
            detail_pen = pen if st["line"] else QPen(QColor("#404040"), 1)
            painter.setPen(detail_pen)
            if self.sdef.detail_fill and st["line"]:
                painter.setBrush(QColor(st["line"]))
            else:
                painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(self._detail)
        sc = self.scene()
        exporting = sc is not None and sc.exporting
        if self.data_graphic_text() and not getattr(widget, "is_overview", False):
            self._paint_data_graphic(painter, exporting)
        if self.link and not exporting:
            self._paint_link_badge(painter)
        if self.comments and not exporting:
            self._paint_comment_badge(painter)
        if self.isSelected() and not exporting and not getattr(widget, "is_overview", False):
            self._paint_selection(painter)

    def _paint_data_graphic(self, painter: QPainter, exporting: bool) -> None:
        text = self.data_graphic_text()
        if not text:
            return
        # Les exports suivent l'échelle du dessin ; à l'écran, la pastille garde une taille lisible.
        s = 1.0 if exporting else painter_scale(painter)
        rect = self.data_graphic_rect(s)
        if rect.isNull():
            return
        fill, ink, border = self.data_graphic_palette()
        font = QFont("Arial")
        font.setPixelSize(max(1, round(11.0 / s)))
        painter.save()
        painter.setFont(font)
        painter.setPen(QPen(QColor(border), 0.8 / s))
        painter.setBrush(QColor(fill))
        painter.drawRoundedRect(rect, 5.0 / s, 5.0 / s)
        pad = 8.0 / s
        text_rect = rect.adjusted(pad, 0, -pad, 0)
        metrics = QFontMetricsF(font)
        shown = metrics.elidedText(text, Qt.TextElideMode.ElideRight, max(1.0, text_rect.width()))
        painter.setPen(QColor(ink))
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, shown)
        painter.restore()

    def _paint_link_badge(self, painter: QPainter) -> None:
        s = painter_scale(painter)
        r = 5.0 / s
        c = QPointF(self.w / 2 - r * 0.2, -self.h / 2 + r * 0.2)
        painter.setPen(QPen(ACCENT, 1.2 / s))
        painter.setBrush(QColor("#ffffff"))
        painter.drawEllipse(c, r, r)
        painter.drawLine(QPointF(c.x() - r * 0.45, c.y() + r * 0.45),
                         QPointF(c.x() + r * 0.45, c.y() - r * 0.45))

    def _paint_cff(self, painter: QPainter, pen: QPen) -> None:
        b = self.box()
        hdr = self.cff_header_rect()
        kind = self.sdef.cff
        if kind.startswith("phase") and self.cff_band_hidden():
            return
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._brush())
        painter.drawRect(hdr)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        if kind.startswith("phase"):
            painter.drawRect(hdr)
            if kind == "phase_h":
                painter.drawLine(QPointF(b.right(), hdr.bottom()), QPointF(b.right(), b.bottom()))
            else:
                painter.drawLine(QPointF(hdr.right(), b.bottom()), QPointF(b.right(), b.bottom()))
        else:
            painter.drawRect(b)
            painter.drawRect(hdr)

    def _paint_comment_badge(self, painter: QPainter) -> None:
        s = painter_scale(painter)
        w, h = 12.0 / s, 9.0 / s
        x, y = self.w / 2 + 3 / s, -self.h / 2 - h - 3 / s
        painter.setPen(QPen(QColor("#b8860b"), 1 / s))
        painter.setBrush(QColor("#ffd966"))
        painter.drawRect(QRectF(x, y, w, h))
        painter.drawPolygon(QPolygonF([QPointF(x + 2 / s, y + h), QPointF(x + 2 / s, y + h + 3 / s),
                                       QPointF(x + 5 / s, y + h)]))

    def _paint_selection(self, painter: QPainter) -> None:
        s = painter_scale(painter)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        pen = QPen(ACCENT, 1.0 / s, Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.drawRect(self.box())
        if self.locked:
            painter.setPen(QPen(QColor("#a19f9d"), 1.0 / s))
            painter.setBrush(QColor("#ffffff"))
            k = 6 / s
            for pt in self.handle_points()[:8:2]:
                painter.drawLine(QPointF(pt.x() - k / 2, pt.y() - k / 2), QPointF(pt.x() + k / 2, pt.y() + k / 2))
                painter.drawLine(QPointF(pt.x() - k / 2, pt.y() + k / 2), QPointF(pt.x() + k / 2, pt.y() - k / 2))
            return
        if not self._is_single_selected() or self.editing:
            return
        hs = HANDLE_PX / s
        pts = self.handle_points()
        painter.setPen(QPen(QColor("#5f6368"), 1.0 / s))
        painter.setBrush(QColor("#ffffff"))
        for i, pt in enumerate(pts[:8]):
            if i in (1, 5) and self.w * s < 3 * HANDLE_PX:
                continue
            if i in (3, 7) and self.h * s < 3 * HANDLE_PX:
                continue
            painter.drawRect(QRectF(pt.x() - hs / 2, pt.y() - hs / 2, hs, hs))
        if self.sdef.cff:
            return
        rot = pts[ROTATE_HANDLE]
        painter.setPen(QPen(ACCENT, 1.2 / s))
        painter.setBrush(QColor("#ffffff"))
        painter.drawEllipse(rot, hs * 0.65, hs * 0.65)
        arc = QRectF(rot.x() - hs * 0.35, rot.y() - hs * 0.35, hs * 0.7, hs * 0.7)
        painter.drawArc(arc, 30 * 16, 260 * 16)

    # ------------------------------------------------------------ interactions
    def itemChange(self, change, value):  # noqa: N802
        if change == GIC.ItemPositionChange and not self._applying:
            sc = self.scene()
            if sc is not None and sc.interactive_move:
                return sc.adjust_move(self, value)
        elif change in (GIC.ItemPositionHasChanged, GIC.ItemRotationHasChanged,
                        GIC.ItemTransformHasChanged):
            self.notify_connectors()
        elif change == GIC.ItemSelectedChange:
            self.prepareGeometryChange()
        elif change == GIC.ItemSelectedHasChanged:
            if not self.isSelected() and self.editing:
                self.finish_edit()
        return super().itemChange(change, value)

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and not self.editing:
            h = self.handle_at(event.scenePos())
            if h is not None:
                self._begin_handle_drag(h)
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):  # noqa: N802
        if self._drag is not None:
            if self._drag["mode"] == "rotate":
                self._do_rotate(event.scenePos(), event.modifiers())
            else:
                self._do_resize(event.scenePos(), event.modifiers())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):  # noqa: N802
        if self._drag is not None:
            self._drag = None
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.start_edit(select_all=False)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def _begin_handle_drag(self, index: int) -> None:
        if index == ROTATE_HANDLE:
            self._drag = {"mode": "rotate"}
            return
        opposite = self.handle_points()[(index + 4) % 8]
        self._drag = {"mode": "resize", "handle": index, "anchor": self.mapToScene(opposite),
                      "rot": self.rotation(), "w0": self.w, "h0": self.h}

    def _do_rotate(self, pos: QPointF, mods) -> None:
        c = self.scenePos()
        ang = math.degrees(math.atan2(pos.y() - c.y(), pos.x() - c.x())) + 90.0
        if mods & Qt.KeyboardModifier.ShiftModifier:
            ang = round(ang / 15.0) * 15.0
        elif abs(ang - round(ang / 90.0) * 90.0) < 4.0:
            ang = round(ang / 90.0) * 90.0
        while ang > 180:
            ang -= 360
        while ang <= -180:
            ang += 360
        self.setRotation(ang)

    def _do_resize(self, pos: QPointF, mods) -> None:
        d = self._drag
        sx, sy = _HANDLE_SIGNS[d["handle"]]
        anchor: QPointF = d["anchor"]
        rot = math.radians(d["rot"])
        cos, sin = math.cos(rot), math.sin(rot)
        sc = self.scene()
        snap = sc is not None and sc.snap_enabled and abs(math.sin(rot * 2)) < 1e-6
        if snap and sc.snap_to_grid:
            g = sc.grid_px
            pos = QPointF(round(pos.x() / g) * g if sx else pos.x(),
                          round(pos.y() / g) * g if sy else pos.y())
        vx, vy = pos.x() - anchor.x(), pos.y() - anchor.y()
        lx = vx * cos + vy * sin
        ly = -vx * sin + vy * cos
        nw = max(MIN_SIZE_PX, lx * sx) if sx else d["w0"]
        nh = max(MIN_SIZE_PX, ly * sy) if sy else d["h0"]
        if mods & Qt.KeyboardModifier.ShiftModifier and sx and sy and d["h0"] > 0:
            ratio = d["w0"] / d["h0"]
            if nw / nh > ratio:
                nh = nw / ratio
            else:
                nw = nh * ratio
        cx_l, cy_l = sx * nw / 2, sy * nh / 2
        center = QPointF(anchor.x() + cx_l * cos - cy_l * sin, anchor.y() + cx_l * sin + cy_l * cos)
        self.w, self.h = nw, nh
        self._applying = True
        self.setPos(center)
        self._applying = False
        self.rebuild()


# =========================================================================== connecteurs

class ConnectorItem(TextOwner):
    kind = "connector"

    def __init__(self, state: dict):
        super().__init__()
        self.id = state["id"]
        self.src: dict = {}
        self.dst: dict = {}
        self.style: dict = {}
        self.data: dict = {}
        self._path = QPainterPath()
        self._arrows: list[tuple[str, QPolygonF | QRectF]] = []
        self._ends = (QPointF(), QPointF())
        self._label_rect = QRectF()
        self._last_pos = QPointF(0, 0)
        self._pts: list[QPointF] = []
        self._curved = False
        self.layer = ""
        self.setFlags(GIF.ItemIsSelectable | GIF.ItemSendsGeometryChanges)
        self.set_state(state)

    def state(self) -> dict:
        return {"id": self.id, "kind": "connector", "src": dict(self.src), "dst": dict(self.dst),
                "z": self.zValue(), "text": self.text, "style": dict(self.style),
                "text_style": dict(self.text_style), "data": dict(self.data), "layer": self.layer}

    def set_state(self, st: dict) -> None:
        self.src = dict(st["src"])
        self.dst = dict(st["dst"])
        self.style = dict(st["style"])
        self.text_style = dict(st["text_style"])
        self.text = st["text"]
        self.data = dict(st.get("data", {}))
        self.layer = st.get("layer", "")
        self._applying = True
        self.setPos(0, 0)
        self._last_pos = QPointF(0, 0)
        self.setZValue(st["z"])
        self._applying = False
        sc = self.scene()
        if sc is not None:
            sc.reindex_connector(self)
        self.update_path()

    def set_end(self, which: str, end: dict) -> None:
        setattr(self, which, dict(end))
        sc = self.scene()
        if sc is not None:
            sc.reindex_connector(self)
        self.update_path()

    def glued_shape(self, end: dict) -> ShapeItem | None:
        sc = self.scene()
        if sc is None or not end.get("shape"):
            return None
        item = sc.item_by_id(end["shape"])
        return item if isinstance(item, ShapeItem) else None

    def _update_movable(self) -> None:
        free = self.glued_shape(self.src) is None or self.glued_shape(self.dst) is None
        self.setFlag(GIF.ItemIsMovable, free)

    def _reference(self, end: dict) -> QPointF:
        shape = self.glued_shape(end)
        if shape is not None:
            return shape.scene_box().center()
        return QPointF(end["x"], end["y"])

    def _resolve(self, end: dict, ref: QPointF):
        shape = self.glued_shape(end)
        if shape is None:
            return QPointF(end["x"], end["y"]), None, None
        if 0 <= end.get("port", -1) < shape.port_count():
            p, d = shape.port_scene(end["port"])
        else:
            p, d = shape.best_port(ref, exclude=self)
        end["x"], end["y"] = p.x(), p.y()
        r = shape.scene_box()
        return p, d, (r.left(), r.top(), r.right(), r.bottom())

    def path_scene(self) -> QPainterPath:
        return self._path.translated(self.pos())

    def end_points(self) -> tuple[QPointF, QPointF]:
        """Extrémités actuelles, en coordonnées de scène."""
        o = self.pos()
        return self._ends[0] + o, self._ends[1] + o

    def update_path(self) -> None:
        self.prepareGeometryChange()
        self._update_movable()
        p1, d1, r1 = self._resolve(self.src, self._reference(self.dst))
        p2, d2, r2 = self._resolve(self.dst, self._reference(self.src))
        o = self.pos()
        route = self.style["route"]
        path = QPainterPath()
        if route == "curved":
            c1, c2 = curve_controls((p1.x(), p1.y()), d1, (p2.x(), p2.y()), d2)
            pts = [p1, QPointF(*c1), QPointF(*c2), p2]
            start_dir = (pts[1], p1) if QLineF(pts[1], p1).length() > 0.5 else (p2, p1)
            end_dir = (pts[2], p2) if QLineF(pts[2], p2).length() > 0.5 else (p1, p2)
        else:
            if route == "orthogonal":
                raw = route_orthogonal((p1.x(), p1.y()), d1, (p2.x(), p2.y()), d2, r1, r2)
                pts = [QPointF(x, y) for x, y in raw]
            else:
                pts = [p1, p2]
            if len(pts) < 2:
                pts = [p1, p2]
            start_dir = (pts[1], pts[0])
            end_dir = (pts[-2], pts[-1])
        pts = [p - o for p in pts]
        start_dir = (start_dir[0] - o, start_dir[1] - o)
        end_dir = (end_dir[0] - o, end_dir[1] - o)
        self._arrows = []
        width = self.style["line_width"]
        a_start = self._arrow(self.style["arrow_start"], *start_dir, width)
        a_end = self._arrow(self.style["arrow_end"], *end_dir, width)
        # On raccourcit le trait sous les flèches pleines pour une pointe nette.
        if a_start is not None and self.style["arrow_start"] != "open":
            pts[0] = self._retract(pts[0], pts[1] if route != "curved" else pts[1], a_start[2])
        if a_end is not None and self.style["arrow_end"] != "open":
            pts[-1] = self._retract(pts[-1], pts[-2], a_end[2])
        self._pts = pts
        self._curved = route == "curved"
        for a in (a_start, a_end):
            if a is not None:
                self._arrows.append((a[0], a[1]))
        self._ends = (p1 - o, p2 - o)
        self._build_path()
        self.layout_label()
        self.update()
        sc = self.scene()
        if sc is not None:
            sc.request_jump_refresh()

    # ------------------------------------------------------------ sauts de ligne
    def vertical_segments(self) -> list[tuple[float, float, float]]:
        o = self.pos()
        out = []
        if self._curved:
            return out
        for a, b in zip(self._pts, self._pts[1:]):
            if abs(a.x() - b.x()) < 0.5 and abs(a.y() - b.y()) > 1:
                out.append((a.x() + o.x(), a.y() + o.y(), b.y() + o.y()))
        return out

    def _jumps(self) -> dict[int, list[float]]:
        sc = self.scene()
        if sc is None or self._curved or not sc.doc.settings.get("line_jumps", True):
            return {}
        vsegs = []
        for c in sc.connectors():
            if c is not self and c.zValue() < self.zValue() and c.isVisible():
                vsegs.extend(c.vertical_segments())
        if not vsegs:
            return {}
        o = self.pos()
        res = {}
        for i, (a, b) in enumerate(zip(self._pts, self._pts[1:])):
            if abs(a.y() - b.y()) > 0.5 or abs(a.x() - b.x()) < 4 * JUMP_R:
                continue
            y = a.y() + o.y()
            lo, hi = sorted((a.x() + o.x(), b.x() + o.x()))
            xs = sorted({round(x, 2) for x, y1, y2 in vsegs
                         if lo + JUMP_R * 1.6 < x < hi - JUMP_R * 1.6
                         and min(y1, y2) + 1 < y < max(y1, y2) - 1})
            if xs:
                res[i] = [x - o.x() for x in (xs if b.x() > a.x() else reversed(xs))]
        return res

    def _build_path(self) -> None:
        pts = self._pts
        path = QPainterPath()
        if not pts:
            self._path = path
            return
        if self._curved:
            path.moveTo(pts[0])
            path.cubicTo(pts[1], pts[2], pts[3])
        else:
            jumps = self._jumps()
            path.moveTo(pts[0])
            for i, p in enumerate(pts[1:]):
                a = pts[i]
                for xc in jumps.get(i, ()):
                    y = a.y()
                    if p.x() > a.x():
                        path.lineTo(xc - JUMP_R, y)
                        path.arcTo(QRectF(xc - JUMP_R, y - JUMP_R, 2 * JUMP_R, 2 * JUMP_R), 180, -180)
                    else:
                        path.lineTo(xc + JUMP_R, y)
                        path.arcTo(QRectF(xc - JUMP_R, y - JUMP_R, 2 * JUMP_R, 2 * JUMP_R), 0, 180)
                path.lineTo(p)
        self._path = path

    def rebuild_jumps(self) -> None:
        before = self._path
        self._build_path()
        if self._path != before:
            self.prepareGeometryChange()
            self.update()

    @staticmethod
    def _retract(tip: QPointF, towards: QPointF, dist: float) -> QPointF:
        line = QLineF(tip, towards)
        length = line.length()
        if length < 1e-6:
            return tip
        d = min(dist, length * 0.9)
        return line.pointAt(d / length)

    @staticmethod
    def _arrow(kind: str, base: QPointF, tip: QPointF, width: float):
        if kind == "none":
            return None
        line = QLineF(base, tip)
        length = line.length()
        if length < 1e-6:
            return None
        ux, uy = (tip.x() - base.x()) / length, (tip.y() - base.y()) / length
        nx, ny = -uy, ux
        size = 7.0 + 2.2 * width
        hw = size * 0.42
        b = QPointF(tip.x() - ux * size, tip.y() - uy * size)
        if kind in ("triangle", "open"):
            poly = QPolygonF([QPointF(b.x() + nx * hw, b.y() + ny * hw), tip,
                              QPointF(b.x() - nx * hw, b.y() - ny * hw)])
            return kind, poly, size * 0.85
        if kind == "diamond":
            m = QPointF(tip.x() - ux * size * 0.5, tip.y() - uy * size * 0.5)
            poly = QPolygonF([tip, QPointF(m.x() + nx * hw * 0.8, m.y() + ny * hw * 0.8), b,
                              QPointF(m.x() - nx * hw * 0.8, m.y() - ny * hw * 0.8)])
            return kind, poly, size
        r = size * 0.38
        c = QPointF(tip.x() - ux * r, tip.y() - uy * r)
        return kind, QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r), 2 * r

    def layout_label(self) -> None:
        self._apply_label_format()
        lab = self.label
        lab.setTextWidth(-1)
        ideal = lab.document().idealWidth()
        if ideal > 220:
            lab.setTextWidth(220)
        size = lab.document().size()
        if self._path.length() > 1e-6:
            mid = self._path.pointAtPercent(0.5)
        else:  # connecteur de longueur nulle : pointAtPercent renverrait l'origine
            mid = (self._ends[0] + self._ends[1]) / 2
        lab.setPos(mid.x() - size.width() / 2, mid.y() - size.height() / 2)
        self._label_rect = QRectF(lab.pos(), size) if (self.text or self.editing) else QRectF()

    def _scale(self) -> float:
        sc = self.scene()
        return sc.view_scale if sc is not None else 1.0

    def boundingRect(self) -> QRectF:  # noqa: N802
        r = self._path.boundingRect()
        for _, geo in self._arrows:
            r = r.united(geo.boundingRect())
        if not self._label_rect.isNull():
            r = r.united(self._label_rect)
        m = self.style.get("line_width", 1.0) + 4
        if self.isSelected():
            m += HANDLE_PX / self._scale()
        return r.adjusted(-m, -m, m, m)

    def shape(self) -> QPainterPath:
        stroker = QPainterPathStroker()
        stroker.setWidth(max(self.style["line_width"] + 2, 10.0 / self._scale()))
        p = stroker.createStroke(self._path)
        p.setFillRule(Qt.FillRule.WindingFill)
        if not self._label_rect.isNull():
            p.addRect(self._label_rect)
        if self.isSelected():
            hs = HANDLE_PX / self._scale() * 1.6
            for e in self._ends:
                p.addRect(QRectF(e.x() - hs / 2, e.y() - hs / 2, hs, hs))
        return p

    def end_handle_at(self, scene_pos: QPointF) -> str | None:
        if not self.isSelected():
            return None
        tol = HANDLE_PX / self._scale()
        a, b = self.end_points()
        if QLineF(b, scene_pos).length() <= tol:
            return "dst"
        if QLineF(a, scene_pos).length() <= tol:
            return "src"
        return None

    def paint(self, painter: QPainter, option, widget=None) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        st = self.style
        color = QColor(st["line"])
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(make_pen(st["line"], st["line_width"], st["dash"]))
        painter.drawPath(self._path)
        solid = QPen(color, st["line_width"])
        solid.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
        for kind, geo in self._arrows:
            painter.setPen(solid)
            if kind == "open":
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawPolyline(geo)
            elif kind == "circle":
                painter.setBrush(color)
                painter.drawEllipse(geo)
            else:
                painter.setBrush(color)
                painter.drawPolygon(geo)
        sc = self.scene()
        if not self._label_rect.isNull():
            bg = QColor(sc.page_bg if sc is not None else "#ffffff")
            painter.fillRect(self._label_rect, bg)
        exporting = sc is not None and sc.exporting
        if self.isSelected() and not exporting and not getattr(widget, "is_overview", False):
            s = painter_scale(painter)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(ACCENT, 1.0 / s, Qt.PenStyle.DashLine))
            painter.drawPath(self._path)
            hs = HANDLE_PX / s
            for end, pt in ((self.src, self._ends[0]), (self.dst, self._ends[1])):
                glued = self.glued_shape(end) is not None
                painter.setPen(QPen(QColor("#3c4043"), 1.0 / s))
                painter.setBrush(GLUE if glued else QColor("#ffffff"))
                painter.drawRect(QRectF(pt.x() - hs / 2, pt.y() - hs / 2, hs, hs))

    def itemChange(self, change, value):  # noqa: N802
        if change == GIC.ItemPositionHasChanged and not self._applying:
            pos = self.pos()
            delta = pos - self._last_pos
            self._last_pos = QPointF(pos)
            for end in (self.src, self.dst):
                if self.glued_shape(end) is None:
                    end["x"] += delta.x()
                    end["y"] += delta.y()
            self.update_path()
        elif change == GIC.ItemSelectedChange:
            self.prepareGeometryChange()
        elif change == GIC.ItemSelectedHasChanged:
            if not self.isSelected() and self.editing:
                self.finish_edit()
        return super().itemChange(change, value)

    def normalize_position(self) -> None:
        """Ramène pos() à l'origine après un déplacement (extrémités absolues)."""
        if self.pos().isNull():
            return
        self._applying = True
        self.setPos(0, 0)
        self._last_pos = QPointF(0, 0)
        self._applying = False
        self.update_path()

    def mouseDoubleClickEvent(self, event):  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.start_edit(select_all=False)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


def make_item(state: dict) -> ShapeItem | ConnectorItem:
    if state.get("kind") == "connector":
        return ConnectorItem(state)
    return ShapeItem(state)
