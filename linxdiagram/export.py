"""Exports PNG / JPEG / SVG / PDF et impression."""

from __future__ import annotations

import contextlib
import math

from PyQt6.QtCore import QMarginsF, QRectF, QSize, QSizeF, Qt
from PyQt6.QtGui import QColor, QImage, QPageLayout, QPageSize, QPainter, QPdfWriter
from PyQt6.QtSvg import QSvgGenerator

from . import APP_NAME, __version__
from .security import SecurityError, atomic_target
from .units import PX_PER_MM

MAX_IMAGE_SIDE = 16000
MAX_IMAGE_PIXELS = 160_000_000


@contextlib.contextmanager
def exporting(scene, transparent: bool = False):
    """Masque sélection, poignées et grille le temps du rendu."""
    if scene.editing_item is not None:
        scene.editing_item.finish_edit()
    selected = scene.selected_all()
    hover = scene.hover_shape
    blocked = scene.blockSignals(True)
    scene.hover_shape = None
    scene.clearSelection()
    scene.exporting = True
    old_bg = scene.page_bg
    if transparent:
        scene.page_bg = "#00000000"
    hidden = scene.hidden_for_print() if hasattr(scene, "hidden_for_print") else []
    for it in hidden:
        it.setVisible(False)
    try:
        yield
    finally:
        for it in hidden:
            it.setVisible(True)
        scene.exporting = False
        scene.page_bg = old_bg
        scene.hover_shape = hover
        for it in selected:
            it.setSelected(True)
        scene.blockSignals(blocked)


def source_rect(scene, mode: str) -> QRectF:
    if mode == "drawing":
        r = scene.drawing_rect()
        if not r.isNull():
            return r.adjusted(-10, -10, 10, 10)
    if mode == "selection":
        r = QRectF()
        for it in scene.selected_all():
            rr = it.visual_scene_rect() if hasattr(it, "visual_scene_rect") else \
                it.mapRectToScene(it.boundingRect())
            r = rr if r.isNull() else r.united(rr)
        if not r.isNull():
            return r.adjusted(-10, -10, 10, 10)
    return scene.page_rect()


def _render(scene, painter: QPainter, target: QRectF, source: QRectF) -> None:
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    scene.render(painter, target, source, Qt.AspectRatioMode.KeepAspectRatio)


def export_image(scene, path: str, mode: str = "page", dpi: int = 150,
                 transparent: bool = False) -> None:
    src = source_rect(scene, mode)
    scale = dpi / 96.0
    w, h = math.ceil(src.width() * scale), math.ceil(src.height() * scale)
    if w > MAX_IMAGE_SIDE or h > MAX_IMAGE_SIDE or w * h > MAX_IMAGE_PIXELS:
        raise SecurityError("Image trop grande : réduisez la résolution ou la zone exportée.")
    fmt = "JPEG" if path.lower().endswith((".jpg", ".jpeg")) else "PNG"
    if fmt == "JPEG":
        transparent = False
    img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    img.setDotsPerMeterX(round(dpi / 0.0254))
    img.setDotsPerMeterY(round(dpi / 0.0254))
    img.fill(QColor(0, 0, 0, 0) if transparent else QColor(scene.page_bg))
    with exporting(scene, transparent):
        p = QPainter(img)
        _render(scene, p, QRectF(0, 0, w, h), src)
        p.end()
    with atomic_target(path) as tmp:
        if not img.save(tmp, fmt, 92):
            raise SecurityError("Échec de l'écriture de l'image.")


def export_svg(scene, path: str, mode: str = "page") -> None:
    src = source_rect(scene, mode)
    with atomic_target(path) as tmp:
        gen = QSvgGenerator()
        gen.setFileName(tmp)
        gen.setSize(QSize(math.ceil(src.width()), math.ceil(src.height())))
        gen.setViewBox(QRectF(0, 0, src.width(), src.height()))
        gen.setResolution(96)
        gen.setTitle(scene.page_name)
        gen.setDescription(f"Créé avec {APP_NAME} {__version__}")
        with exporting(scene):
            p = QPainter(gen)
            _render(scene, p, QRectF(0, 0, src.width(), src.height()), src)
            p.end()


def _page_layout(scene) -> QPageLayout:
    size = QPageSize(QSizeF(scene.page_w / PX_PER_MM, scene.page_h / PX_PER_MM),
                     QPageSize.Unit.Millimeter, scene.page_name,
                     QPageSize.SizeMatchPolicy.ExactMatch)
    return QPageLayout(size, QPageLayout.Orientation.Portrait, QMarginsF(0, 0, 0, 0))


def export_pdf(pages, path: str, title: str = "") -> None:
    with atomic_target(path) as tmp:
        writer = QPdfWriter(tmp)
        writer.setCreator(f"{APP_NAME} {__version__}")
        writer.setTitle(title)
        writer.setResolution(300)
        painter = None
        for i, scene in enumerate(pages):
            writer.setPageLayout(_page_layout(scene))
            if i == 0:
                painter = QPainter(writer)
            else:
                writer.newPage()
            target = QRectF(0, 0, writer.width(), writer.height())
            with exporting(scene):
                _render(scene, painter, target, scene.page_rect())
        if painter is not None:
            painter.end()


def print_pages(printer, pages) -> None:
    """Imprime chaque page à l'échelle de la feuille (orientation automatique)."""
    painter = None
    for i, scene in enumerate(pages):
        landscape = scene.page_w > scene.page_h
        printer.setPageOrientation(QPageLayout.Orientation.Landscape if landscape
                                   else QPageLayout.Orientation.Portrait)
        if i == 0:
            painter = QPainter(printer)
            if not painter.isActive():
                return
        else:
            printer.newPage()
        target = QRectF(printer.pageRect(printer.Unit.DevicePixel))
        target.moveTo(0, 0)
        with exporting(scene):
            _render(scene, painter, target, scene.page_rect())
    if painter is not None:
        painter.end()
