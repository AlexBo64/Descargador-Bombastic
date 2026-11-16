"""Comprobación asíncrona de las versiones de yt-dlp, ffmpeg y ffprobe con ``QProcess``.

No bloquea el hilo de la interfaz: lanza los procesos en paralelo y emite ``finished``
con un ``dict[Tool, BinaryStatus]`` cuando todos han respondido o han agotado el tiempo.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QTimer, Signal

from bombastic.core.binaries import (
    BinaryLocation,
    BinaryStatus,
    Tool,
    parse_version,
    version_args,
)

log = logging.getLogger(__name__)

#: Dado un ejecutable devuelve (programa, argumentos). Se sustituye en los tests.
CommandFactory = Callable[[Tool, Path], tuple[str, list[str]]]


def _default_command(tool: Tool, path: Path) -> tuple[str, list[str]]:
    return str(path), version_args(tool)


class BinaryProbe(QObject):
    """Pregunta la versión a cada ejecutable encontrado."""

    finished = Signal(object)

    def __init__(
        self,
        locations: Mapping[Tool, BinaryLocation],
        parent: QObject | None = None,
        timeout_ms: int = 10_000,
        command_factory: CommandFactory = _default_command,
    ) -> None:
        super().__init__(parent)
        self._locations = dict(locations)
        self._timeout_ms = timeout_ms
        self._command_factory = command_factory
        self._results: dict[Tool, BinaryStatus] = {}
        self._processes: dict[Tool, QProcess] = {}
        self._running = False

    @property
    def running(self) -> bool:
        return self._running

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._results.clear()
        for tool, location in self._locations.items():
            if location.path is None:
                self._results[tool] = BinaryStatus(location)
                continue
            self._launch(tool, location.path)
        # Si no había nada que lanzar, se emite igualmente (de forma asíncrona).
        QTimer.singleShot(0, self._maybe_finish)

    def _launch(self, tool: Tool, path: Path) -> None:
        program, args = self._command_factory(tool, path)
        process = QProcess(self)
        process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        process.finished.connect(lambda *_: self._on_finished(tool))
        process.errorOccurred.connect(lambda error: self._on_error(tool, error))
        self._processes[tool] = process
        log.debug("Probing %s: %s %s", tool.value, program, args)
        process.start(program, args)
        QTimer.singleShot(self._timeout_ms, self, lambda: self._on_timeout(tool))

    def _on_finished(self, tool: Tool) -> None:
        process = self._processes.get(tool)
        if process is None or tool in self._results:
            return
        output = bytes(process.readAll().data()).decode("utf-8", errors="replace")
        version = parse_version(tool, output)
        error = None if version else "unrecognized version output"
        self._record(tool, version, error)

    def _on_error(self, tool: Tool, error: QProcess.ProcessError) -> None:
        if tool in self._results:
            return
        self._record(tool, None, error.name)

    def _on_timeout(self, tool: Tool) -> None:
        if tool in self._results:
            return
        self._record(tool, None, "timeout")
        process = self._processes.get(tool)
        if process is not None:
            process.kill()

    def _record(self, tool: Tool, version: str | None, error: str | None) -> None:
        self._results[tool] = BinaryStatus(self._locations[tool], version, error)
        if error:
            log.warning("%s did not report a version: %s", tool.value, error)
        else:
            log.info("%s version %s (%s)", tool.value, version, self._locations[tool].path)
        self._maybe_finish()

    def _maybe_finish(self) -> None:
        if not self._running or len(self._results) < len(self._locations):
            return
        self._running = False
        for process in self._processes.values():
            process.deleteLater()
        self._processes.clear()
        self.finished.emit(dict(self._results))
