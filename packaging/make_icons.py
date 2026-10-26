"""Produit les icônes Windows (.ico) et macOS (.iconset → .icns) à partir du SVG.

    python packaging/make_icons.py build/icons

Sous macOS, convertir ensuite : iconutil -c icns build/icons/LinXdiagram.iconset
"""

import os
import sys

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QGuiApplication, QImage, QPainter
from PyQt6.QtSvg import QSvgRenderer

HERE = os.path.dirname(os.path.abspath(__file__))
SVG = os.path.join(HERE, "io.github.joss943.LinXdiagram.svg")


def render(size: int) -> QImage:
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    QSvgRenderer(SVG).render(p, QRectF(0, 0, size, size))
    p.end()
    return img


def main(out: str) -> int:
    os.makedirs(out, exist_ok=True)
    render(256).save(os.path.join(out, "LinXdiagram.ico"), "ICO")
    render(512).save(os.path.join(out, "LinXdiagram.png"), "PNG")
    iconset = os.path.join(out, "LinXdiagram.iconset")
    os.makedirs(iconset, exist_ok=True)
    for size in (16, 32, 128, 256, 512):
        render(size).save(os.path.join(iconset, f"icon_{size}x{size}.png"), "PNG")
        render(size * 2).save(os.path.join(iconset, f"icon_{size}x{size}@2x.png"), "PNG")
    return 0


if __name__ == "__main__":
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    _app = QGuiApplication(sys.argv[:1])
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "build/icons"))
