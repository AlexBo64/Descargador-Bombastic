"""Animaciones de la interfaz: quitar tarjetas explotando, plegarlas, aparecer y destellos.

Los efectos que se aplican a un widget usan ``QGraphicsOpacityEffect`` (solo uno por widget).
La explosión no toca la tarjeta: se pinta encima una capa con una foto de la tarjeta partida en
fragmentos, mientras la tarjeta real se vuelve invisible y su hueco se cierra.
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable, Sequence

from PySide6.QtCore import (
    QEasingCurve,
    QPoint,
    QPointF,
    QPropertyAnimation,
    QRect,
    QRectF,
    QSequentialAnimationGroup,
    Qt,
    QVariantAnimation,
)
from PySide6.QtGui import QPainter, QPaintEvent, QPixmap
from PySide6.QtWidgets import QBoxLayout, QGraphicsOpacityEffect, QWidget

#: Duraciones en milisegundos.
EXPLODE_MS = 700
COLLAPSE_MS = 280
FADE_OUT_MS = 220
PULSE_MS = 380

_COLUMNS, _ROWS = 14, 4
#: Margen alrededor de la tarjeta por el que pueden volar los fragmentos.
_SPREAD = 80


class ExplodeOverlay(QWidget):
    """Capa que pinta la foto de un widget partida en fragmentos que salen despedidos."""

    def __init__(self, pixmap: QPixmap, rect: QRect, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self._pixmap = pixmap
        self._origin = QPointF(_SPREAD, _SPREAD)
        self.setGeometry(rect.adjusted(-_SPREAD, -_SPREAD, _SPREAD, _SPREAD))
        self.progress = 0.0
        ratio = pixmap.devicePixelRatio() or 1.0
        width, height = pixmap.width() / ratio, pixmap.height() / ratio
        tile_w, tile_h = width / _COLUMNS, height / _ROWS
        center = QPointF(width / 2, height / 2)
        generator = random.Random(int(width * 31 + height))
        #: Cada fragmento: (rectángulo en la tarjeta, dirección, distancia, giro, retraso).
        self.tiles: list[tuple[QRectF, QPointF, float, float, float]] = []
        for row in range(_ROWS):
            for column in range(_COLUMNS):
                tile = QRectF(column * tile_w, row * tile_h, tile_w, tile_h)
                offset = tile.center() - center
                length = math.hypot(offset.x(), offset.y()) or 1.0
                direction = QPointF(offset.x() / length, offset.y() / length)
                distance = _SPREAD * generator.uniform(0.45, 1.0) + length * 0.25
                spin = generator.uniform(-55, 55)
                # Revienta desde el centro hacia fuera.
                delay = 0.25 * (1 - min(1.0, length / max(center.x(), 1.0)))
                self.tiles.append((tile, direction, distance, spin, delay))
        self.animation = QVariantAnimation(self)
        self.animation.setStartValue(0.0)
        self.animation.setEndValue(1.0)
        self.animation.setDuration(EXPLODE_MS)
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.animation.valueChanged.connect(self._on_value)
        self.animation.finished.connect(self.deleteLater)

    def start(self) -> None:
        self.show()
        self.raise_()
        self.animation.start()

    def _on_value(self, value: float) -> None:
        self.progress = float(value)
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        ratio = self._pixmap.devicePixelRatio() or 1.0
        for tile, direction, distance, spin, delay in self.tiles:
            local = min(1.0, max(0.0, (self.progress - delay) / (1 - delay)))
            opacity = (1 - local) ** 1.4
            if opacity <= 0.01:
                continue
            painter.save()
            painter.setOpacity(opacity)
            center = self._origin + tile.center() + direction * distance * local
            painter.translate(center)
            painter.rotate(spin * local)
            scale = 1 - 0.45 * local
            painter.scale(scale, scale)
            source = QRectF(tile.x() * ratio, tile.y() * ratio, tile.width() * ratio,
                            tile.height() * ratio)  # fmt: skip
            target = QRectF(-tile.width() / 2, -tile.height() / 2, tile.width(), tile.height())
            painter.drawPixmap(target, self._pixmap, source)
            painter.restore()
        painter.end()


def _hide_contents(widget: QWidget) -> QGraphicsOpacityEffect:
    effect = QGraphicsOpacityEffect(widget)
    widget.setGraphicsEffect(effect)
    return effect


def _collapse(widget: QWidget, duration: int) -> QPropertyAnimation:
    animation = QPropertyAnimation(widget, b"maximumHeight", widget)
    animation.setDuration(duration)
    animation.setStartValue(widget.height())
    animation.setEndValue(0)
    animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
    return animation


def _animatable(widget: QWidget) -> bool:
    """Solo se anima lo que se ve: lo oculto o fuera de pantalla se quita al momento."""
    if not widget.isVisible() or widget.height() <= 0:
        return False
    return not widget.visibleRegion().isEmpty()


def explode_and_remove(widget: QWidget, on_done: Callable[[], None]) -> ExplodeOverlay | None:
    """Rompe el widget en fragmentos que se dispersan y, después, cierra su hueco."""
    if not _animatable(widget):
        on_done()
        return None
    window = widget.window()
    rect = QRect(widget.mapTo(window, QPoint(0, 0)), widget.size())
    overlay = ExplodeOverlay(widget.grab(), rect, window)
    widget.setEnabled(False)
    effect = _hide_contents(widget)
    effect.setOpacity(0.0)
    group = QSequentialAnimationGroup(widget)
    group.addPause(EXPLODE_MS // 3)
    group.addAnimation(_collapse(widget, COLLAPSE_MS))
    group.finished.connect(on_done)
    overlay.start()
    group.start()
    return overlay


def fade_out_and_remove(widget: QWidget, on_done: Callable[[], None]) -> None:
    """Desvanece y pliega el widget (para lo que se mueve a otro sitio, no se borra)."""
    if not _animatable(widget):
        on_done()
        return
    widget.setEnabled(False)
    effect = _hide_contents(widget)
    fade = QPropertyAnimation(effect, b"opacity", widget)
    fade.setDuration(FADE_OUT_MS)
    fade.setStartValue(1.0)
    fade.setEndValue(0.0)
    group = QSequentialAnimationGroup(widget)
    group.addAnimation(fade)
    group.addAnimation(_collapse(widget, COLLAPSE_MS))
    group.finished.connect(on_done)
    group.start()


def pulse(widget: QWidget) -> None:
    """Destello breve: el widget vuelve desde medio transparente (cambio de estado)."""
    if not _animatable(widget):
        return
    effect = QGraphicsOpacityEffect(widget)
    widget.setGraphicsEffect(effect)
    animation = QPropertyAnimation(effect, b"opacity", widget)
    animation.setDuration(PULSE_MS)
    animation.setStartValue(0.25)
    animation.setEndValue(1.0)
    animation.setEasingCurve(QEasingCurve.Type.OutCubic)
    animation.finished.connect(lambda: widget.setGraphicsEffect(None))  # type: ignore[arg-type]
    animation.start()


def sync_order(layout: QBoxLayout, wanted: Sequence[QWidget], first: int = 1) -> None:
    """Pone ``wanted`` en ese orden dentro de ``layout`` sin tocar los demás widgets.

    Solo se recolocan si el orden relativo ha cambiado: así una tarjeta que se está quitando
    (aún en el layout, invisible) no desplaza a las demás durante su animación.
    """
    members = set(wanted)
    current = [
        item.widget()
        for index in range(layout.count())
        if (item := layout.itemAt(index)) is not None and item.widget() in members
    ]
    if current == list(wanted):
        return
    for widget in wanted:
        layout.removeWidget(widget)
    for offset, widget in enumerate(wanted):
        layout.insertWidget(first + offset, widget)
