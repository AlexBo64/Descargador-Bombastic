"""Genera ``bombastic/resources/icons/app.ico`` (multi-resolución) a partir de ``app.svg``.

Uso: ``python build/make_icon.py``. Cada tamaño va como PNG dentro del ICO (lo admite Windows
desde Vista), así no hace falta ninguna dependencia aparte de PySide6.
"""

from __future__ import annotations

import os
import struct
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

ROOT = Path(__file__).resolve().parents[1]
ICONS = ROOT / "bombastic" / "resources" / "icons"
SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)
#: Color de acento del tema claro (el icono no cambia con el tema).
ACCENT = "#5b4be0"


def render_png(svg: str, size: int) -> bytes:
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter)
    painter.end()
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(buffer.data().data())


def build_ico(images: list[tuple[int, bytes]]) -> bytes:
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries, blobs = b"", b""
    for size, png in images:
        side = 0 if size >= 256 else size  # 0 significa 256 en el formato ICO
        entries += struct.pack("<BBBBHHII", side, side, 0, 0, 1, 32, len(png), offset)
        blobs += png
        offset += len(png)
    return header + entries + blobs


def main() -> int:
    QGuiApplication.instance() or QGuiApplication(sys.argv)
    svg = (ICONS / "app.svg").read_text(encoding="utf-8").replace("currentColor", ACCENT)
    data = build_ico([(size, render_png(svg, size)) for size in SIZES])
    target = ICONS / "app.ico"
    target.write_bytes(data)
    print(f"{target} ({len(data)} bytes, {len(SIZES)} tamaños)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
