"""Temas claro y oscuro, cambiables en caliente, con la opción de seguir al sistema."""

from __future__ import annotations

import re
from functools import cache

from PySide6.QtCore import QByteArray, QObject, Qt, Signal
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication

from bombastic.core.paths import resources_dir

PALETTES: dict[str, dict[str, str]] = {
    "dark": {
        "bg": "#16171b",
        "sidebar": "#1b1c21",
        "surface": "#202127",
        "surface_alt": "#292b33",
        "input": "#1a1b20",
        "border": "#34363f",
        "hover": "#2b2d36",
        "text": "#e8e9ed",
        "muted": "#9a9daa",
        "accent": "#8a7bf5",
        "accent_soft": "#2f2b57",
        "accent_text": "#dcd7ff",
    },
    "light": {
        "bg": "#f5f6f8",
        "sidebar": "#eceef2",
        "surface": "#ffffff",
        "surface_alt": "#f3f4f7",
        "input": "#ffffff",
        "border": "#d8dbe2",
        "hover": "#e3e5eb",
        "text": "#1d1f25",
        "muted": "#666a77",
        "accent": "#5b4be0",
        "accent_soft": "#e3dfff",
        "accent_text": "#3a2bb8",
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
    palette = PALETTES[theme]
    return _TOKEN.sub(lambda match: palette[match.group(1)], _template())


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


class ThemeManager(QObject):
    """Aplica el tema a toda la aplicación y avisa cuando cambia."""

    #: Emite el tema efectivo: ``"dark"`` o ``"light"``.
    changed = Signal(str)

    def __init__(self, app: QApplication) -> None:
        super().__init__(app)
        self._app = app
        self._mode = "system"
        self._effective = ""
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
