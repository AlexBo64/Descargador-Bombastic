"""Ejecuta ffprobe sin bloquear y entrega la información del archivo."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal

from bombastic.core.binaries import Tool, locate
from bombastic.core.media_probe import ProbeError, parse_probe, probe_args
from bombastic.core.paths import AppPaths
from bombastic.core.ytdlp_runner import Launch, Launcher, OutputCollector


def tool_launcher(paths: AppPaths, tool: Tool) -> Launcher:
    """Lanzador que busca ``tool`` cada vez (puede instalarse con la app abierta)."""

    def launch(args: list[str]) -> Launch | None:
        location = locate(tool, paths)
        return (str(location.path), args) if location.path is not None else None

    return launch


class MediaProber(QObject):
    #: ``(ruta, ProbeInfo)``.
    probed = Signal(str, object)
    #: ``(ruta, motivo)``: ``missing`` (no hay ffprobe) o ``unreadable``.
    failed = Signal(str, str)

    def __init__(self, launcher: Launcher, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._launcher = launcher

    def probe(self, path: Path) -> None:
        launch = self._launcher(probe_args(str(path)))
        if launch is None:
            self.failed.emit(str(path), "missing")
            return
        collector = OutputCollector(launch, self)

        def done(code: int, output: str) -> None:
            collector.deleteLater()
            if code != 0:
                self.failed.emit(str(path), "unreadable")
                return
            try:
                self.probed.emit(str(path), parse_probe(output))
            except ProbeError:
                self.failed.emit(str(path), "unreadable")

        collector.finished.connect(done)
        collector.start()
