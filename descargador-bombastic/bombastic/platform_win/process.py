"""Control de procesos en Windows."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

log = logging.getLogger(__name__)


def kill_tree(pid: int) -> bool:
    """Mata un proceso y todos sus descendientes con ``taskkill /T /F``.

    Hace falta porque ``yt-dlp.exe`` se relanza a sí mismo como proceso hijo y además lanza
    ffmpeg: terminar solo el proceso inicial dejaría la descarga viva.

    No espera a que termine. Devuelve ``False`` si no se ha podido lanzar ``taskkill`` (o si
    no se está en Windows), para que quien llama use otro método.
    """
    if sys.platform != "win32":
        return False
    # En Windows los nombres de las variables de entorno no distinguen mayúsculas.
    system_root = os.environ.get("SYSTEMROOT", r"C:\Windows")
    taskkill = Path(system_root) / "System32" / "taskkill.exe"
    try:
        subprocess.Popen(
            [str(taskkill), "/PID", str(pid), "/T", "/F"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except OSError:
        log.exception("Could not run taskkill for PID %s", pid)
        return False
    return True
