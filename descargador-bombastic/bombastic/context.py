"""Objetos compartidos por toda la aplicación."""

from __future__ import annotations

from dataclasses import dataclass

from bombastic.core.db import Database
from bombastic.core.i18n import Translator
from bombastic.core.paths import AppPaths, default_download_dir
from bombastic.core.settings import Settings, SettingsStore
from bombastic.ui.theme import ThemeManager


@dataclass
class AppContext:
    paths: AppPaths
    settings: Settings
    store: SettingsStore
    translator: Translator
    theme: ThemeManager
    #: Base de datos (``None`` en los tests que no la necesitan).
    db: Database | None = None

    def save_settings(self) -> None:
        self.store.save(self.settings)

    def download_dir(self) -> str:
        """Carpeta de destino elegida o, si no hay ninguna, la de descargas del usuario."""
        return self.settings.download_dir or str(default_download_dir())
