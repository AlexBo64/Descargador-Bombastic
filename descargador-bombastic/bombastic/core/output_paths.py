"""Nombres de salida seguros y comprobación de espacio libre."""

from __future__ import annotations

import shutil
from pathlib import Path

#: Sufijo por defecto de los archivos editados (nunca se sobrescribe el original).
EDIT_SUFFIX = "_editado"


def safe_output(source: Path, extension: str, suffix: str = EDIT_SUFFIX) -> Path:
    """``vídeo.mkv`` → ``vídeo_editado.mp4``; si existe, ``vídeo_editado (1).mp4``…"""
    extension = extension.lstrip(".")
    base = f"{source.stem}{suffix}"
    candidate = source.with_name(f"{base}.{extension}")
    counter = 1
    while candidate.exists() or candidate == source:
        candidate = source.with_name(f"{base} ({counter}).{extension}")
        counter += 1
    return candidate


def free_space(folder: Path) -> int | None:
    """Bytes libres en el disco de ``folder``; ``None`` si no se puede saber."""
    probe = folder
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    try:
        return shutil.disk_usage(probe).free
    except OSError:
        return None


def enough_space(folder: Path, needed: int) -> bool:
    """Hay sitio para ``needed`` bytes con un margen del 10 % (o no se sabe)."""
    free = free_space(folder)
    return free is None or free >= needed * 1.1
