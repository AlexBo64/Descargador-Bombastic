"""Ejecución de yt-dlp con ``QProcess``: obtención de metadatos y descargas.

Nada de aquí bloquea el hilo de la interfaz; los resultados llegan por señales.
"""

from __future__ import annotations

import logging
import subprocess
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, Signal

from bombastic.core.binaries import Tool, locate
from bombastic.core.media_info import MediaInfoError, parse_media_info
from bombastic.core.paths import AppPaths
from bombastic.core.process_control import kill_process_tree
from bombastic.core.ytdlp_options import HelpParseError, save_catalog
from bombastic.core.ytdlp_progress import ErrorLine, FileReady, ProgressTracker, parse_line

log = logging.getLogger(__name__)

#: Programa y argumentos listos para ``QProcess``.
Launch = tuple[str, list[str]]
#: Convierte los argumentos de yt-dlp en un :data:`Launch`, o ``None`` si no hay yt-dlp.
#: Los tests lo sustituyen por un script falso.
Launcher = Callable[[list[str]], Launch | None]

# Códigos de error (la interfaz los traduce con ``downloads.error.<código>``).
ERROR_YTDLP = "ytdlp"  # yt-dlp ha explicado el fallo: el detalle es su mensaje
ERROR_EXIT_CODE = "exit_code"  # ha fallado sin mensaje: el detalle es el código de salida
ERROR_START_FAILED = "start_failed"  # no se ha podido lanzar el ejecutable
ERROR_TIMEOUT = "timeout"
ERROR_BAD_INFO = "bad_info"  # la salida de -J no es el JSON esperado
ERROR_MISSING = "ytdlp_missing"

_LOG_LINES = 400


def default_launcher(paths: AppPaths) -> Launcher:
    """Lanzador real: busca ``yt-dlp`` cada vez, por si se instala con la app abierta."""

    def launch(args: list[str]) -> Launch | None:
        location = locate(Tool.YTDLP, paths)
        if location.path is None:
            return None
        return str(location.path), args

    return launch


def describe(launch: Launch) -> str:
    """El comando como texto, solo para mostrarlo o registrarlo (nunca para ejecutarlo)."""
    program, args = launch
    return subprocess.list2cmdline([program, *args])


def _environment() -> QProcessEnvironment:
    env = QProcessEnvironment.systemEnvironment()
    # Salida en UTF-8 aunque la consola de Windows use otra codificación.
    env.insert("PYTHONIOENCODING", "utf-8")
    env.insert("PYTHONUTF8", "1")
    return env


class _LineBuffer:
    """Convierte los bytes que van llegando en líneas de texto completas."""

    def __init__(self) -> None:
        self._pending = b""

    def feed(self, data: bytes) -> list[str]:
        self._pending += data
        *complete, self._pending = self._pending.split(b"\n")
        return [self._decode(raw) for raw in complete]

    def flush(self) -> list[str]:
        rest, self._pending = self._pending, b""
        return [self._decode(rest)] if rest.strip() else []

    @staticmethod
    def _decode(raw: bytes) -> str:
        return raw.decode("utf-8", errors="replace").rstrip("\r")


def _last_error(lines: list[str]) -> str:
    for line in reversed(lines):
        event = parse_line(line)
        if isinstance(event, ErrorLine):
            return event.message
    return ""


class InfoFetcher(QObject):
    """Obtiene los metadatos de un enlace con ``yt-dlp -J``."""

    #: Emite un :class:`~bombastic.core.media_info.MediaInfo`.
    succeeded = Signal(object)
    #: Emite ``(código, detalle)``.
    failed = Signal(str, str)

    def __init__(
        self,
        launch: Launch,
        url: str,
        parent: QObject | None = None,
        timeout_ms: int = 120_000,
    ) -> None:
        super().__init__(parent)
        self._launch = launch
        self._url = url
        self._done = False
        self._stdout = b""
        self._stderr = b""
        self._process = QProcess(self)
        self._process.setProcessEnvironment(_environment())
        self._process.readyReadStandardOutput.connect(self._read_stdout)
        self._process.readyReadStandardError.connect(self._read_stderr)
        self._process.finished.connect(self._on_finished)
        self._process.errorOccurred.connect(self._on_error)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(timeout_ms)
        self._timer.timeout.connect(self._on_timeout)

    def start(self) -> None:
        log.info("Fetching info: %s", describe(self._launch))
        self._timer.start()
        self._process.start(*self._launch)

    def wait(self, msecs: int) -> None:
        """Espera a que el proceso termine (solo al cerrar la app, tras ``cancel``)."""
        if self._process.state() != QProcess.ProcessState.NotRunning:
            self._process.waitForFinished(msecs)

    def cancel(self) -> None:
        """Abandona la consulta sin emitir ninguna señal."""
        self._done = True
        self._timer.stop()
        kill_process_tree(self._process)

    def dispose(self) -> None:
        """Cancela y se borra cuando el proceso haya muerto.

        Borrar un ``QProcess`` con el proceso vivo (``taskkill`` es asíncrono) hace que Qt
        aborte más tarde, así que el borrado espera a la señal de fin.
        """
        self.cancel()
        if self._process.state() == QProcess.ProcessState.NotRunning:
            self.deleteLater()
        else:
            self._process.finished.connect(self.deleteLater)

    def _read_stdout(self) -> None:
        self._stdout += bytes(self._process.readAllStandardOutput().data())

    def _read_stderr(self) -> None:
        self._stderr += bytes(self._process.readAllStandardError().data())

    def _fail(self, code: str, detail: str = "") -> None:
        if self._done:
            return
        self._done = True
        self._timer.stop()
        log.warning("Info for %s failed: %s %s", self._url, code, detail)
        self.failed.emit(code, detail)

    def _on_timeout(self) -> None:
        self._fail(ERROR_TIMEOUT)
        kill_process_tree(self._process)

    def _on_error(self, error: QProcess.ProcessError) -> None:
        if error == QProcess.ProcessError.FailedToStart:
            self._fail(ERROR_START_FAILED, self._launch[0])

    def _on_finished(self, exit_code: int, _status: QProcess.ExitStatus) -> None:
        if self._done:
            return
        self._read_stdout()
        self._read_stderr()
        if exit_code != 0:
            detail = _last_error(self._stderr.decode("utf-8", errors="replace").splitlines())
            if detail:
                self._fail(ERROR_YTDLP, detail)
            else:
                self._fail(ERROR_EXIT_CODE, str(exit_code))
            return
        try:
            info = parse_media_info(self._stdout.decode("utf-8", errors="replace"), self._url)
        except MediaInfoError as exc:
            self._fail(ERROR_BAD_INFO, str(exc))
            return
        self._done = True
        self._timer.stop()
        self.succeeded.emit(info)


class OutputCollector(QObject):
    """Ejecuta un comando corto y entrega su salida estándar completa."""

    #: Emite ``(código de salida, salida)``; código -1 si no se ha podido lanzar.
    finished = Signal(int, str)

    def __init__(self, launch: Launch, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._launch = launch
        self._stdout = b""
        self._done = False
        self._process = QProcess(self)
        self._process.setProcessEnvironment(_environment())
        self._process.readyReadStandardOutput.connect(self._read)
        self._process.finished.connect(self._on_finished)
        self._process.errorOccurred.connect(self._on_error)

    def start(self) -> None:
        self._process.start(*self._launch)

    def _read(self) -> None:
        self._stdout += bytes(self._process.readAllStandardOutput().data())

    def _emit(self, code: int) -> None:
        if not self._done:
            self._done = True
            self.finished.emit(code, self._stdout.decode("utf-8", errors="replace"))

    def _on_error(self, error: QProcess.ProcessError) -> None:
        if error == QProcess.ProcessError.FailedToStart:
            self._emit(-1)

    def _on_finished(self, exit_code: int, _status: QProcess.ExitStatus) -> None:
        self._read()
        self._emit(exit_code)


class CatalogRefresher(QObject):
    """Regenera el catálogo de opciones con ``yt-dlp --version`` y ``--help``."""

    #: ``True`` si se ha guardado un catálogo nuevo.
    finished = Signal(bool)

    def __init__(self, launcher: Launcher, data_dir: Path, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._launcher = launcher
        self._data_dir = data_dir
        self._version = ""

    def start(self) -> None:
        self._run(["--version"], self._on_version)

    def _run(self, args: list[str], slot: Callable[[int, str], None]) -> None:
        launch = self._launcher(args)
        if launch is None:
            self.finished.emit(False)
            return
        collector = OutputCollector(launch, self)
        collector.finished.connect(slot)
        collector.finished.connect(collector.deleteLater)
        collector.start()

    def _on_version(self, code: int, output: str) -> None:
        if code != 0:
            self.finished.emit(False)
            return
        self._version = output.strip()
        self._run(["--help"], self._on_help)

    def _on_help(self, code: int, output: str) -> None:
        if code != 0:
            self.finished.emit(False)
            return
        try:
            save_catalog(self._data_dir, output, self._version)
        except (HelpParseError, OSError):
            log.exception("Could not regenerate the yt-dlp option catalog")
            self.finished.emit(False)
            return
        log.info("Regenerated yt-dlp option catalog for %s", self._version)
        self.finished.emit(True)


@dataclass(frozen=True)
class DownloadResult:
    #: ``"completed"``, ``"failed"`` o ``"cancelled"``.
    status: str
    files: tuple[Path, ...] = ()
    error_code: str = ""
    error_detail: str = ""


class DownloadJob(QObject):
    """Una descarga de yt-dlp con progreso."""

    #: Emite un :class:`~bombastic.core.ytdlp_progress.ProgressSnapshot`.
    progress = Signal(object)
    #: Emite un :class:`DownloadResult`. Se emite exactamente una vez.
    finished = Signal(object)

    def __init__(self, launch: Launch, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._launch = launch
        self._done = False
        self._cancelled = False
        self._tracker = ProgressTracker()
        self._files: list[Path] = []
        self._error = ""
        self._stdout = _LineBuffer()
        self._stderr = _LineBuffer()
        #: Últimas líneas de la salida, para diagnosticar fallos.
        self.log_lines: deque[str] = deque(maxlen=_LOG_LINES)
        self._process = QProcess(self)
        self._process.setProcessEnvironment(_environment())
        self._process.readyReadStandardOutput.connect(self._read_stdout)
        self._process.readyReadStandardError.connect(self._read_stderr)
        self._process.finished.connect(self._on_finished)
        self._process.errorOccurred.connect(self._on_error)

    @property
    def command(self) -> str:
        return describe(self._launch)

    @property
    def running(self) -> bool:
        return self._process.state() != QProcess.ProcessState.NotRunning

    def start(self) -> None:
        log.info("Starting download: %s", self.command)
        self._process.start(*self._launch)

    def wait(self, msecs: int) -> None:
        """Espera a que el proceso termine (solo al cerrar la app, tras ``cancel``)."""
        if self.running:
            self._process.waitForFinished(msecs)

    def cancel(self) -> None:
        """Detiene la descarga. ``finished`` se emite con estado ``cancelled``.

        Los archivos ``.part`` se conservan: yt-dlp los aprovecha al volver a descargar.
        """
        if self._done or self._cancelled:
            return
        self._cancelled = True
        if self.running:
            kill_process_tree(self._process)
        else:
            self._finish(DownloadResult("cancelled", tuple(self._files)))

    def _read_stdout(self) -> None:
        data = bytes(self._process.readAllStandardOutput().data())
        self._handle_lines(self._stdout.feed(data))

    def _read_stderr(self) -> None:
        data = bytes(self._process.readAllStandardError().data())
        self._handle_lines(self._stderr.feed(data))

    def _handle_lines(self, lines: list[str]) -> None:
        for line in lines:
            event = parse_line(line)
            if event is None:
                if line.strip():
                    self.log_lines.append(line)
                continue
            if isinstance(event, FileReady):
                self._files.append(event.path)
                self.log_lines.append(line)
                continue
            if isinstance(event, ErrorLine):
                self._error = event.message
                self.log_lines.append(line)
                continue
            snapshot = self._tracker.feed(event)
            if snapshot is not None and not self._cancelled:
                self.progress.emit(snapshot)

    def _finish(self, result: DownloadResult) -> None:
        if self._done:
            return
        self._done = True
        if result.status == "failed":
            log.warning(
                "Download failed (%s %s). Last output:\n%s",
                result.error_code,
                result.error_detail,
                "\n".join(list(self.log_lines)[-15:]),
            )
        else:
            log.info("Download %s: %s", result.status, [str(file) for file in result.files])
        self.finished.emit(result)

    def _on_error(self, error: QProcess.ProcessError) -> None:
        if error == QProcess.ProcessError.FailedToStart:
            self._finish(
                DownloadResult(
                    "cancelled" if self._cancelled else "failed",
                    error_code=ERROR_START_FAILED,
                    error_detail=self._launch[0],
                )
            )

    def _on_finished(self, exit_code: int, status: QProcess.ExitStatus) -> None:
        self._read_stdout()
        self._read_stderr()
        self._handle_lines(self._stdout.flush() + self._stderr.flush())
        files = tuple(self._files)
        if self._cancelled:
            self._finish(DownloadResult("cancelled", files))
        elif exit_code == 0 and status == QProcess.ExitStatus.NormalExit:
            self._finish(DownloadResult("completed", files))
        elif self._error:
            self._finish(DownloadResult("failed", files, ERROR_YTDLP, self._error))
        else:
            self._finish(DownloadResult("failed", files, ERROR_EXIT_CODE, str(exit_code)))
