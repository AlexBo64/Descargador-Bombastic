"""Detección de la aceleración por hardware: ``ffmpeg -encoders`` y una prueba real de cada una.

Que un codificador aparezca en la lista no significa que funcione (depende de la GPU y de sus
controladores), por eso se prueba codificando medio segundo sintético.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from bombastic.core.ffmpeg_tools import hw_test_args, listed_hw, parse_encoders
from bombastic.core.ytdlp_runner import Launcher, OutputCollector


class HwProbe(QObject):
    #: Lista de aceleraciones que funcionan (``nvenc``, ``qsv``, ``amf``).
    finished = Signal(list)

    def __init__(self, launcher: Launcher, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._launcher = launcher
        self._pending: list[str] = []
        self._working: list[str] = []

    def start(self) -> None:
        self._run(["-hide_banner", "-encoders"], self._on_encoders)

    def _run(self, args: list[str], slot: object) -> None:
        launch = self._launcher(args)
        if launch is None:
            self.finished.emit([])
            return
        collector = OutputCollector(launch, self)
        collector.finished.connect(slot)
        collector.finished.connect(collector.deleteLater)
        collector.start()

    def _on_encoders(self, code: int, output: str) -> None:
        self._pending = listed_hw(parse_encoders(output)) if code == 0 else []
        self._next()

    def _next(self) -> None:
        if not self._pending:
            self.finished.emit(list(self._working))
            return
        hw = self._pending.pop(0)

        def tested(code: int, _output: str) -> None:
            if code == 0:
                self._working.append(hw)
            self._next()

        self._run(hw_test_args(hw), tested)
