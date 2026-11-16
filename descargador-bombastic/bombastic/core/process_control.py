"""Terminación de procesos externos junto con sus procesos hijo."""

from __future__ import annotations

from PySide6.QtCore import QProcess, QTimer

from bombastic.platform_win.process import kill_tree

#: Si el árbol no ha muerto en este tiempo, se mata el proceso directamente.
_FALLBACK_MS = 3000


def kill_process_tree(process: QProcess) -> None:
    """Mata ``process`` y sus descendientes sin bloquear. No hace nada si ya ha terminado."""
    if process.state() == QProcess.ProcessState.NotRunning:
        return
    pid = process.processId()
    if pid and kill_tree(pid):
        # Temporizador hijo del proceso: si el proceso se borra antes, el temporizador muere
        # con él (un singleShot con función de Python podía dispararse sobre un objeto borrado).
        timer = QTimer(process)
        timer.setSingleShot(True)
        timer.timeout.connect(process.kill)
        timer.start(_FALLBACK_MS)
        return
    process.kill()
