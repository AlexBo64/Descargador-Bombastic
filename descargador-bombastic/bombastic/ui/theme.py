"""Temas claro y oscuro, cambiables en caliente, con la opción de seguir al sistema.

Estilo "aurora + cristal": un fondo con degradado y manchas de color difuminadas
(:class:`AuroraBackground`), paneles translúcidos encima y degradados en lo destacado. Qt no
puede difuminar lo que hay detrás de un widget, así que el cristal se consigue con
transparencias sobre ese fondo ya difuminado.
"""

from __future__ import annotations

import re
from functools import cache

from PySide6.QtCore import (
    QByteArray,
    QEasingCurve,
    QEvent,
    QObject,
    QPointF,
    QPropertyAnimation,
    Qt,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QIcon,
    QLinearGradient,
    QPainter,
    QPaintEvent,
    QPixmap,
    QRadialGradient,
)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractScrollArea,
    QAbstractSpinBox,
    QApplication,
    QComboBox,
    QGraphicsOpacityEffect,
    QListWidget,
    QMenu,
    QSlider,
    QTabBar,
    QWidget,
)

from bombastic.core.paths import resources_dir

#: Los tokens con ``rgba`` solo se usan en el QSS; los que lee el código (``accent``,
#: ``muted``, ``bg_*``, ``blob_*``) son colores ``#rrggbb``.
PALETTES: dict[str, dict[str, str]] = {
    "dark": {
        # Fondo aurora
        "bg": "#0d0e1a",
        "bg_top": "#0c0d1c",
        "bg_bottom": "#141030",
        "blob_1": "#6d4dff",
        "blob_2": "#00b8d9",
        "blob_3": "#d946ef",
        # Cristal
        "glass": "rgba(255, 255, 255, 0.045)",
        "glass_strong": "rgba(255, 255, 255, 0.075)",
        "glass_hover": "rgba(255, 255, 255, 0.10)",
        "glass_border": "rgba(255, 255, 255, 0.10)",
        "glass_edge": "rgba(255, 255, 255, 0.16)",
        "sidebar": "rgba(10, 10, 24, 0.55)",
        "input": "rgba(0, 0, 0, 0.28)",
        "popup": "#1a1a2e",
        # Texto
        "text": "#eceefa",
        "muted": "#9ea3c0",
        # Acento y degradado
        "accent": "#8b6cff",
        "accent_2": "#22c3ee",
        "accent_hover": "#a18aff",
        "accent_hover_2": "#4dd4f3",
        "accent_soft": "rgba(139, 108, 255, 0.22)",
        "accent_text": "#d9d0ff",
        "on_accent": "#ffffff",
        "danger": "#ff7b8a",
        "danger_soft": "rgba(255, 123, 138, 0.12)",
        "scroll": "rgba(255, 255, 255, 0.16)",
    },
    "light": {
        "bg": "#f3f2ff",
        "bg_top": "#f5f3ff",
        "bg_bottom": "#e8f4ff",
        "blob_1": "#a78bfa",
        "blob_2": "#67e8f9",
        "blob_3": "#f9a8d4",
        "glass": "rgba(255, 255, 255, 0.62)",
        "glass_strong": "rgba(255, 255, 255, 0.80)",
        "glass_hover": "rgba(255, 255, 255, 0.92)",
        "glass_border": "rgba(91, 75, 224, 0.13)",
        "glass_edge": "rgba(255, 255, 255, 0.95)",
        "sidebar": "rgba(255, 255, 255, 0.50)",
        "input": "rgba(255, 255, 255, 0.85)",
        "popup": "#ffffff",
        "text": "#1b1d2e",
        "muted": "#5f6480",
        "accent": "#6246ea",
        "accent_2": "#0ea5e9",
        "accent_hover": "#7259f0",
        "accent_hover_2": "#38b6f0",
        "accent_soft": "rgba(98, 70, 234, 0.13)",
        "accent_text": "#4a2fd0",
        "on_accent": "#ffffff",
        "danger": "#d0284a",
        "danger_soft": "rgba(208, 40, 74, 0.08)",
        "scroll": "rgba(27, 29, 46, 0.18)",
    },
}

_TOKEN = re.compile(r"\{\{(\w+)\}\}")


def resolve_theme(mode: str, system_is_dark: bool) -> str:
    """Convierte la preferencia (``system``/``dark``/``light``) en el tema efectivo."""
    if mode in PALETTES:
        return mode
    return "dark" if system_is_dark else "light"


@cache
def _template() -> str:
    return (resources_dir() / "styles" / "app.qss").read_text(encoding="utf-8")


def build_stylesheet(theme: str) -> str:
    """Devuelve el QSS con los colores del tema. Un marcador desconocido lanza ``KeyError``."""
    values = {**PALETTES[theme], "res": resources_dir().as_posix()}
    return _TOKEN.sub(lambda match: values[match.group(1)], _template())


def load_icon(name: str, color: str, size: int = 20) -> QIcon:
    """Carga un SVG de ``resources/icons`` tiñendo ``currentColor`` con ``color``."""
    svg = (resources_dir() / "icons" / f"{name}.svg").read_text(encoding="utf-8")
    renderer = QSvgRenderer(QByteArray(svg.replace("currentColor", color).encode("utf-8")))
    # Se renderiza a 3x para que se vea nítido con escalado DPI alto.
    pixmap = QPixmap(size * 3, size * 3)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    return QIcon(pixmap)


class AuroraBackground(QWidget):
    """Fondo de la ventana: degradado vertical y tres manchas de color muy difuminadas."""

    #: Posición (fracción del ancho y alto), radio (fracción del lado mayor) y opacidad.
    BLOBS: tuple[tuple[str, float, float, float, int], ...] = (
        ("blob_1", 0.18, 0.05, 0.55, 95),
        ("blob_2", 0.95, 0.30, 0.45, 70),
        ("blob_3", 0.55, 1.05, 0.50, 60),
    )

    def __init__(self, palette: dict[str, str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._palette = palette
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)

    def set_palette(self, palette: dict[str, str]) -> None:
        self._palette = palette
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect()
        base = QLinearGradient(0, 0, rect.width() * 0.3, rect.height())
        base.setColorAt(0, QColor(self._palette["bg_top"]))
        base.setColorAt(1, QColor(self._palette["bg_bottom"]))
        painter.fillRect(rect, base)
        side = max(rect.width(), rect.height())
        for key, fx, fy, fr, alpha in self.BLOBS:
            center = QPointF(rect.width() * fx, rect.height() * fy)
            glow = QRadialGradient(center, side * fr)
            color = QColor(self._palette[key])
            color.setAlpha(alpha)
            glow.setColorAt(0, color)
            # Varias paradas para que el borde se funda sin anillo visible.
            for stop, factor in ((0.35, 0.55), (0.65, 0.18)):
                faded = QColor(color)
                faded.setAlpha(round(alpha * factor))
                glow.setColorAt(stop, faded)
            color.setAlpha(0)
            glow.setColorAt(1, color)
            painter.fillRect(rect, glow)
        painter.end()


#: Controles en los que el puntero pasa a ser una mano.
_CLICKABLE = (QAbstractButton, QComboBox, QTabBar, QSlider, QMenu)


#: Controles cuyo valor cambia con la rueda del ratón.
_WHEEL_GUARDED = (QAbstractSpinBox, QComboBox)


class InteractionFilter(QObject):
    """Comportamiento común de los controles, para toda la app.

    - Cursor de mano en todo lo pulsable (QSS no puede cambiar el cursor).
    - Spinbox y desplegables solo cambian con la rueda si se han pinchado antes: si no, al
      hacer scroll por una página con el puntero encima se cambiaba el valor sin querer.
      La rueda pasa entonces al área de scroll que los contiene.
    """

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if not isinstance(watched, QWidget):
            return False
        if event.type() == QEvent.Type.Polish:
            if isinstance(watched, _WHEEL_GUARDED):
                # Sin esto, la rueda les daría el foco a ellos mismos.
                watched.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            if isinstance(watched, _CLICKABLE):
                if not watched.testAttribute(Qt.WidgetAttribute.WA_SetCursor):
                    watched.setCursor(Qt.CursorShape.PointingHandCursor)
            elif isinstance(watched, QListWidget) and watched.objectName() == "Nav":
                watched.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
        elif (
            event.type() == QEvent.Type.Wheel
            and isinstance(watched, _WHEEL_GUARDED)
            and not watched.hasFocus()
        ):
            area = _scroll_area_of(watched)
            if area is not None:
                QApplication.sendEvent(area.viewport(), event)
            return True
        return False


def _scroll_area_of(widget: QWidget) -> QAbstractScrollArea | None:
    parent = widget.parentWidget()
    while parent is not None:
        if isinstance(parent, QAbstractScrollArea):
            return parent
        parent = parent.parentWidget()
    return None


def fade_in(widget: QWidget, duration: int = 180) -> QPropertyAnimation:
    """Hace aparecer un widget con un fundido; al terminar quita el efecto (cuesta pintar)."""
    effect = QGraphicsOpacityEffect(widget)
    widget.setGraphicsEffect(effect)
    animation = QPropertyAnimation(effect, b"opacity", widget)
    animation.setDuration(duration)
    animation.setStartValue(0.0)
    animation.setEndValue(1.0)
    animation.setEasingCurve(QEasingCurve.Type.OutCubic)
    animation.finished.connect(lambda: widget.setGraphicsEffect(None))  # type: ignore[arg-type]
    animation.start()
    return animation


class ThemeManager(QObject):
    """Aplica el tema a toda la aplicación y avisa cuando cambia."""

    #: Emite el tema efectivo: ``"dark"`` o ``"light"``.
    changed = Signal(str)

    def __init__(self, app: QApplication) -> None:
        super().__init__(app)
        self._app = app
        self._mode = "system"
        self._effective = ""
        # Un solo filtro por aplicación aunque se creen varios gestores (los tests lo hacen).
        existing = app.findChild(InteractionFilter)
        if existing is None:
            existing = InteractionFilter(app)
            app.installEventFilter(existing)
        self.interaction_filter = existing
        app.styleHints().colorSchemeChanged.connect(self._on_system_changed)

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def effective(self) -> str:
        return self._effective

    @property
    def palette(self) -> dict[str, str]:
        return PALETTES[self._effective or "light"]

    def system_is_dark(self) -> bool:
        return self._app.styleHints().colorScheme() == Qt.ColorScheme.Dark

    def apply(self, mode: str) -> None:
        self._mode = mode
        effective = resolve_theme(mode, self.system_is_dark())
        if effective == self._effective:
            return
        self._effective = effective
        self._app.setStyleSheet(build_stylesheet(effective))
        self.changed.emit(effective)

    def _on_system_changed(self, _scheme: Qt.ColorScheme) -> None:
        if self._mode == "system":
            self.apply("system")
