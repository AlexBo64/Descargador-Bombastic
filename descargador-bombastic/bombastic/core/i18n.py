"""Traducciones basadas en catálogos JSON (``resources/i18n/<idioma>.json``).

Cada catálogo es un objeto plano ``{"clave": "texto"}``. Los textos pueden llevar
marcadores ``{nombre}`` que se rellenan con ``tr("clave", nombre=valor)``.

Se usa JSON en lugar de los ``.ts/.qm`` de Qt porque no necesita compilación, permite
cambiar de idioma en caliente y sirve también para textos generados dinámicamente
(la ayuda de las opciones de yt-dlp).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from pathlib import Path

log = logging.getLogger(__name__)

Listener = Callable[[str], None]


class Translator:
    """Carga los catálogos y traduce claves, con idioma de respaldo."""

    def __init__(self, catalogs_dir: Path, fallback: str = "es") -> None:
        self._catalogs: dict[str, dict[str, str]] = {}
        self._listeners: list[Listener] = []
        self.fallback = fallback
        for file in sorted(catalogs_dir.glob("*.json")):
            try:
                data = json.loads(file.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                log.exception("Invalid translation catalog: %s", file)
                continue
            if isinstance(data, dict):
                self._catalogs[file.stem] = {str(k): str(v) for k, v in data.items()}
        self._language = fallback

    @property
    def language(self) -> str:
        return self._language

    def available(self) -> list[str]:
        return sorted(self._catalogs)

    def catalog(self, language: str) -> dict[str, str]:
        return dict(self._catalogs.get(language, {}))

    def set_language(self, language: str) -> None:
        """Cambia de idioma y avisa a los suscriptores. Un idioma desconocido usa el respaldo."""
        if language not in self._catalogs:
            log.warning("Unknown language %r; falling back to %r", language, self.fallback)
            language = self.fallback
        if language == self._language:
            return
        self._language = language
        for listener in list(self._listeners):
            listener(language)

    def subscribe(self, listener: Listener) -> Callable[[], None]:
        """Registra un aviso de cambio de idioma. Devuelve la función para darse de baja."""
        self._listeners.append(listener)

        def unsubscribe() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return unsubscribe

    def t(self, key: str, **params: object) -> str:
        """Traduce ``key``. Si falta en el idioma actual usa el de respaldo, y si no la clave."""
        text = self._catalogs.get(self._language, {}).get(key)
        if text is None:
            text = self._catalogs.get(self.fallback, {}).get(key)
        if text is None:
            log.debug("Missing translation key: %s", key)
            return key
        if params:
            try:
                return text.format(**params)
            except (KeyError, IndexError, ValueError):
                log.warning("Bad placeholders in translation %r", key)
        return text


_active: Translator | None = None


def install(translator: Translator) -> None:
    """Define el traductor global que usa :func:`tr`."""
    global _active
    _active = translator


def tr(key: str, **params: object) -> str:
    """Atajo global. Sin traductor instalado devuelve la clave tal cual."""
    if _active is None:
        return key
    return _active.t(key, **params)
