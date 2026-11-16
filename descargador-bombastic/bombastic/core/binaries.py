"""Localización de los ejecutables externos (yt-dlp, ffmpeg, ffprobe) y lectura de su versión.

Este módulo es puro (sin Qt). La comprobación asíncrona de versiones está en
:mod:`bombastic.core.binary_probe`.
"""

from __future__ import annotations

import re
import shutil
import sys
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from bombastic.core.paths import AppPaths


class Tool(StrEnum):
    YTDLP = "yt-dlp"
    FFMPEG = "ffmpeg"
    FFPROBE = "ffprobe"


class Source(StrEnum):
    """De dónde sale el ejecutable encontrado."""

    DATA = "data"  # carpeta bin\ de datos (actualizable)
    BUNDLED = "bundled"  # junto al ejecutable de la app
    PATH = "path"  # PATH del sistema
    MISSING = "missing"


@dataclass(frozen=True)
class BinaryLocation:
    tool: Tool
    path: Path | None
    source: Source

    @property
    def found(self) -> bool:
        return self.path is not None


@dataclass(frozen=True)
class BinaryStatus:
    """Resultado de comprobar un ejecutable: dónde está y qué versión responde."""

    location: BinaryLocation
    version: str | None = None
    error: str | None = None

    @property
    def usable(self) -> bool:
        return self.location.found and self.version is not None


def exe_name(tool: Tool, platform: str | None = None) -> str:
    platform = platform if platform is not None else sys.platform
    return f"{tool.value}.exe" if platform == "win32" else tool.value


def locate(
    tool: Tool,
    paths: AppPaths,
    search_system_path: bool = True,
    which: Callable[[str], str | None] = shutil.which,
    platform: str | None = None,
) -> BinaryLocation:
    """Busca el ejecutable por orden: carpeta de datos, carpeta de la app y PATH.

    La carpeta de datos va primero porque es la que se actualiza sin administrador.
    """
    name = exe_name(tool, platform)
    for folder, source in ((paths.bin_dir, Source.DATA), (paths.bundled_bin_dir, Source.BUNDLED)):
        candidate = folder / name
        if candidate.is_file():
            return BinaryLocation(tool, candidate, source)
    if search_system_path:
        found = which(tool.value)
        if found:
            return BinaryLocation(tool, Path(found), Source.PATH)
    return BinaryLocation(tool, None, Source.MISSING)


def locate_all(paths: AppPaths, search_system_path: bool = True) -> dict[Tool, BinaryLocation]:
    return {tool: locate(tool, paths, search_system_path) for tool in Tool}


def version_args(tool: Tool) -> list[str]:
    """Argumentos para pedir la versión."""
    return ["--version"] if tool is Tool.YTDLP else ["-version"]


_YTDLP_VERSION = re.compile(r"^\d{4}\.\d{1,2}\.\d{1,2}(?:\.\d+)?$")
_FF_VERSION = re.compile(r"^(?:ffmpeg|ffprobe) version (\S+)", re.MULTILINE)


def parse_version(tool: Tool, output: str) -> str | None:
    """Extrae la versión de la salida del ejecutable, o ``None`` si no se reconoce."""
    if tool is Tool.YTDLP:
        for line in output.splitlines():
            line = line.strip()
            if _YTDLP_VERSION.match(line):
                return line
        return None
    match = _FF_VERSION.search(output)
    return match.group(1) if match else None
