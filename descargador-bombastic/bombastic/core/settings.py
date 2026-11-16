"""Preferencias del usuario, guardadas en ``settings.json``."""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

from bombastic.core.ytdlp_command import DEFAULT_MP3_QUALITY, MP3_QUALITIES, Preset

log = logging.getLogger(__name__)

LANGUAGES: tuple[str, ...] = ("es", "en")
THEMES: tuple[str, ...] = ("system", "dark", "light")
PAGES: tuple[str, ...] = ("downloads", "queue", "editor", "history", "library", "settings")

_RATE = re.compile(r"^\d+(\.\d+)?[KMG]?$", re.IGNORECASE)


def is_valid_rate(text: str) -> bool:
    """Límite de velocidad aceptado por ``--limit-rate`` (vacío = sin límite)."""
    return not text or bool(_RATE.match(text))


MIN_WINDOW_WIDTH = 900
MIN_WINDOW_HEIGHT = 600


@dataclass
class Settings:
    """Preferencias. Añadir un campo nuevo con valor por defecto no rompe archivos antiguos."""

    language: str = "es"
    theme: str = "system"
    #: Vacío significa "usar la carpeta de descargas del usuario".
    download_dir: str = ""
    window_width: int = 1180
    window_height: int = 760
    window_maximized: bool = False
    last_page: str = "downloads"
    #: Opciones del modo simple de descargas (se recuerdan entre sesiones).
    download_preset: str = Preset.BEST.value
    mp3_quality: str = DEFAULT_MP3_QUALITY
    embed_subs: bool = False
    embed_extras: bool = False
    #: Cola de descargas.
    max_concurrent: int = 3
    auto_retries: int = 2
    #: Límite global de velocidad para yt-dlp (``500K``, ``2M``…); vacío = sin límite.
    rate_limit: str = ""

    def sanitize(self) -> None:
        """Corrige valores fuera de rango (archivo editado a mano o de otra versión)."""
        defaults = Settings()
        if self.language not in LANGUAGES:
            self.language = defaults.language
        if self.theme not in THEMES:
            self.theme = defaults.theme
        if self.last_page not in PAGES:
            self.last_page = defaults.last_page
        if self.download_preset not in {preset.value for preset in Preset}:
            self.download_preset = defaults.download_preset
        if self.mp3_quality not in MP3_QUALITIES:
            self.mp3_quality = defaults.mp3_quality
        self.max_concurrent = max(1, min(self.max_concurrent, 8))
        self.auto_retries = max(0, min(self.auto_retries, 10))
        if not is_valid_rate(self.rate_limit):
            self.rate_limit = defaults.rate_limit
        self.window_width = max(MIN_WINDOW_WIDTH, min(self.window_width, 10_000))
        self.window_height = max(MIN_WINDOW_HEIGHT, min(self.window_height, 10_000))


class SettingsStore:
    """Lee y escribe las preferencias de forma tolerante y atómica."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> Settings:
        """Carga las preferencias. Nunca lanza: ante cualquier problema devuelve los valores
        por defecto (y conserva una copia del archivo dañado como ``.bak``)."""
        settings = Settings()
        if not self.path.is_file():
            return settings
        try:
            data: Any = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("settings root is not an object")
        except (OSError, ValueError) as exc:
            log.warning("Could not read settings (%s); using defaults", exc)
            self._backup_corrupt()
            return settings

        for field in fields(Settings):
            if field.name not in data:
                continue
            value = data[field.name]
            # Comparación exacta de tipo: bool es subclase de int y no deben mezclarse.
            if type(value) is type(getattr(settings, field.name)):
                setattr(settings, field.name, value)
            else:
                log.warning("Ignoring setting %r with wrong type", field.name)
        settings.sanitize()
        return settings

    def save(self, settings: Settings) -> None:
        """Escribe en un temporal y lo renombra, para no dejar el archivo a medias."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        payload = json.dumps(asdict(settings), ensure_ascii=False, indent=2)
        try:
            tmp.write_text(payload + "\n", encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError:
            log.exception("Could not save settings to %s", self.path)
            tmp.unlink(missing_ok=True)

    def _backup_corrupt(self) -> None:
        try:
            os.replace(self.path, self.path.with_name(self.path.name + ".bak"))
        except OSError:
            log.debug("Could not back up corrupt settings file", exc_info=True)
