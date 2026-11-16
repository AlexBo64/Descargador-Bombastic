"""Rutas de datos de la aplicación (modo instalado y modo portable)."""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from bombastic import APP_ID

PORTABLE_FLAG = "portable.flag"


@dataclass(frozen=True)
class AppPaths:
    """Rutas que usa la app. ``data_dir`` siempre es escribible sin administrador."""

    app_dir: Path
    data_dir: Path
    portable: bool

    @property
    def bin_dir(self) -> Path:
        """Carpeta actualizable con yt-dlp, ffmpeg y ffprobe."""
        return self.data_dir / "bin"

    @property
    def bundled_bin_dir(self) -> Path:
        """Binarios que trae el instalador junto al ejecutable (solo lectura)."""
        return self.app_dir / "bin"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"

    @property
    def thumbnails_dir(self) -> Path:
        return self.cache_dir / "thumbnails"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "bombastic.sqlite3"

    @property
    def settings_path(self) -> Path:
        return self.data_dir / "settings.json"

    def ensure(self) -> None:
        """Crea las carpetas de datos si no existen."""
        for folder in (self.data_dir, self.bin_dir, self.logs_dir, self.thumbnails_dir):
            folder.mkdir(parents=True, exist_ok=True)


def get_app_dir() -> Path:
    """Carpeta del ejecutable (congelado con PyInstaller) o raíz del proyecto (desarrollo)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def resources_dir() -> Path:
    """Carpeta de recursos empaquetados (iconos, estilos, traducciones)."""
    return Path(__file__).resolve().parents[1] / "resources"


def resolve_paths(
    app_dir: Path | None = None,
    env: Mapping[str, str] | None = None,
    platform: str | None = None,
    home: Path | None = None,
) -> AppPaths:
    """Decide dónde se guardan los datos.

    - Si existe ``portable.flag`` junto al ejecutable: ``<app_dir>/data``.
    - En Windows: ``%LOCALAPPDATA%\\DescargadorBombastic``.
    - En otros sistemas (solo desarrollo y tests): ``$XDG_DATA_HOME`` o ``~/.local/share``.

    Los parámetros existen para poder testear sin tocar el entorno real.
    """
    app_dir = app_dir if app_dir is not None else get_app_dir()
    env = env if env is not None else os.environ
    platform = platform if platform is not None else sys.platform
    home = home if home is not None else Path.home()

    if (app_dir / PORTABLE_FLAG).is_file():
        return AppPaths(app_dir=app_dir, data_dir=app_dir / "data", portable=True)

    if platform == "win32":
        local = env.get("LOCALAPPDATA")
        base = Path(local) if local else home / "AppData" / "Local"
    else:
        xdg = env.get("XDG_DATA_HOME")
        base = Path(xdg) if xdg else home / ".local" / "share"
    return AppPaths(app_dir=app_dir, data_dir=base / APP_ID, portable=False)


def default_download_dir(home: Path | None = None) -> Path:
    """Carpeta de descargas del usuario (``~/Downloads`` existe en Windows 10/11)."""
    home = home if home is not None else Path.home()
    return home / "Downloads"
