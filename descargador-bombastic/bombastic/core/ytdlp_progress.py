"""Plantillas de progreso de yt-dlp y parser tolerante de su salida.

yt-dlp se lanza con ``--newline`` y dos plantillas con prefijo propio, así que cada avance
llega como una línea ``BMBPROG {json}`` (descarga) o ``BMBPP {json}`` (post-procesado).
La ruta del archivo final llega como ``BMBFILE "ruta"``.

Los campos sin valor salen como ``NA`` sin comillas incluso con la conversión ``j`` (comprobado
con yt-dlp 2026.08.19), lo que no es JSON válido: el parser los convierte en ``null``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROGRESS_PREFIX = "BMBPROG "
POSTPROCESS_PREFIX = "BMBPP "
FILE_PREFIX = "BMBFILE "

DOWNLOAD_TEMPLATE = (
    "download:" + PROGRESS_PREFIX + '{"status":%(progress.status)j,'
    '"d":%(progress.downloaded_bytes)j,'
    '"t":%(progress.total_bytes)j,'
    '"te":%(progress.total_bytes_estimate)j,'
    '"s":%(progress.speed)j,'
    '"e":%(progress.eta)j,'
    '"i":%(info.playlist_index)j,'
    '"n":%(info.n_entries)j,'
    '"fi":%(progress.fragment_index)j,'
    '"fc":%(progress.fragment_count)j}'
)
POSTPROCESS_TEMPLATE = (
    "postprocess:" + POSTPROCESS_PREFIX + '{"status":%(progress.status)j,'
    '"pp":%(progress.postprocessor)j}'
)
FILE_TEMPLATE = "after_move:" + FILE_PREFIX + "%(filepath)j"

#: ``NA`` como valor suelto (tras ``:``) y no dentro de una cadena.
_BARE_NA = re.compile(r"(?<=:)\s*NA(?=\s*[,}])")
_FORMATS = re.compile(r"^\[info\] .+?: Downloading \d+ format\(s\): (\S+)")
_ITEM = re.compile(r"^\[download\] Downloading item (\d+) of (\d+)")
_ERROR = re.compile(r"^ERROR:\s*(.+)$")


@dataclass(frozen=True)
class DownloadProgress:
    """Avance de la descarga de un archivo (un vídeo suele ser dos: imagen y sonido)."""

    status: str
    downloaded: float | None = None
    total: float | None = None
    speed: float | None = None
    eta: float | None = None
    item_index: int | None = None
    item_count: int | None = None
    fragment_index: int | None = None
    fragment_count: int | None = None

    @property
    def fraction(self) -> float | None:
        """Parte descargada de este archivo (0-1), o ``None`` si no se puede saber."""
        if self.downloaded is not None and self.total:
            return max(0.0, min(1.0, self.downloaded / self.total))
        if self.fragment_index is not None and self.fragment_count:
            return max(0.0, min(1.0, self.fragment_index / self.fragment_count))
        return None


@dataclass(frozen=True)
class PostprocessProgress:
    status: str
    postprocessor: str


@dataclass(frozen=True)
class FileReady:
    """yt-dlp ha dejado un archivo terminado en su ubicación final."""

    path: Path


@dataclass(frozen=True)
class FormatsSelected:
    """Cuántos archivos se van a descargar para el elemento actual (``137+140`` son dos)."""

    parts: int


@dataclass(frozen=True)
class PlaylistItem:
    index: int
    count: int


@dataclass(frozen=True)
class ErrorLine:
    message: str


Event = (
    DownloadProgress | PostprocessProgress | FileReady | FormatsSelected | PlaylistItem | ErrorLine
)


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _integer(value: Any) -> int | None:
    number = _number(value)
    return int(number) if number is not None else None


def _load_object(payload: str) -> dict[str, Any] | None:
    try:
        data = json.loads(_BARE_NA.sub("null", payload))
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def parse_line(line: str) -> Event | None:
    """Interpreta una línea de la salida de yt-dlp. Devuelve ``None`` si no interesa.

    Nunca lanza: una línea que no se entiende se ignora.
    """
    line = line.strip()
    if line.startswith(PROGRESS_PREFIX):
        data = _load_object(line[len(PROGRESS_PREFIX) :])
        if data is None:
            return None
        total = _number(data.get("t"))
        if total is None:
            total = _number(data.get("te"))
        status = data.get("status")
        return DownloadProgress(
            status=status if isinstance(status, str) else "downloading",
            downloaded=_number(data.get("d")),
            total=total,
            speed=_number(data.get("s")),
            eta=_number(data.get("e")),
            item_index=_integer(data.get("i")),
            item_count=_integer(data.get("n")),
            fragment_index=_integer(data.get("fi")),
            fragment_count=_integer(data.get("fc")),
        )
    if line.startswith(POSTPROCESS_PREFIX):
        data = _load_object(line[len(POSTPROCESS_PREFIX) :])
        if data is None:
            return None
        status = data.get("status")
        name = data.get("pp")
        return PostprocessProgress(
            status=status if isinstance(status, str) else "",
            postprocessor=name if isinstance(name, str) else "",
        )
    if line.startswith(FILE_PREFIX):
        try:
            path = json.loads(line[len(FILE_PREFIX) :])
        except ValueError:
            return None
        return FileReady(Path(path)) if isinstance(path, str) and path else None
    match = _FORMATS.match(line)
    if match:
        return FormatsSelected(parts=match.group(1).count("+") + 1)
    match = _ITEM.match(line)
    if match:
        return PlaylistItem(index=int(match.group(1)), count=int(match.group(2)))
    match = _ERROR.match(line)
    if match:
        return ErrorLine(match.group(1).strip())
    return None


@dataclass(frozen=True)
class ProgressSnapshot:
    """Estado global de una descarga, listo para pintar."""

    #: ``"downloading"`` o ``"processing"`` (ffmpeg uniendo, convirtiendo, incrustando…).
    phase: str = "downloading"
    #: Avance global 0-1 (todos los archivos y elementos), o ``None`` si no se conoce.
    fraction: float | None = None
    downloaded: float | None = None
    total: float | None = None
    speed: float | None = None
    eta: float | None = None
    item_index: int | None = None
    item_count: int | None = None
    postprocessor: str = ""


class ProgressTracker:
    """Combina los eventos en un avance global que nunca retrocede.

    Un vídeo se descarga normalmente en dos archivos (imagen y sonido) y cada uno va de 0 a
    100 %. Aquí se reparte la barra entre los archivos del elemento y, en una lista de
    reproducción, entre sus elementos.
    """

    def __init__(self) -> None:
        self._parts = 1
        self._parts_done = 0
        self._item_index: int | None = None
        self._item_count: int | None = None
        self._fraction: float | None = None
        self._last = ProgressSnapshot()

    @property
    def snapshot(self) -> ProgressSnapshot:
        return self._last

    def feed(self, event: Event) -> ProgressSnapshot | None:
        """Procesa un evento. Devuelve el nuevo estado si ha cambiado algo visible."""
        if isinstance(event, FormatsSelected):
            self._parts = max(1, event.parts)
            self._parts_done = 0
            return None
        if isinstance(event, PlaylistItem):
            self._set_item(event.index, event.count)
            return self._emit("downloading", None)
        if isinstance(event, DownloadProgress):
            if event.item_index is not None and event.item_count:
                self._set_item(event.item_index, event.item_count)
            return self._emit("downloading", event)
        if isinstance(event, PostprocessProgress):
            if event.status != "started" or event.postprocessor == "MoveFiles":
                return None
            self._last = ProgressSnapshot(
                phase="processing",
                fraction=self._fraction,
                item_index=self._item_index,
                item_count=self._item_count,
                postprocessor=event.postprocessor,
            )
            return self._last
        return None

    def _set_item(self, index: int, count: int) -> None:
        if index != self._item_index:
            self._parts = 1
            self._parts_done = 0
        self._item_index = index
        self._item_count = count

    def _emit(self, phase: str, event: DownloadProgress | None) -> ProgressSnapshot:
        part_fraction = 0.0
        known = True
        if event is not None:
            if event.status == "finished":
                self._parts_done += 1
            else:
                fraction = event.fraction
                known = fraction is not None
                part_fraction = fraction or 0.0
        item_fraction = min(1.0, (self._parts_done + part_fraction) / self._parts)
        if self._item_index is not None and self._item_count:
            overall = (max(0, self._item_index - 1) + item_fraction) / self._item_count
        else:
            overall = item_fraction
        overall = max(0.0, min(1.0, overall))
        if known or self._fraction is not None:
            self._fraction = max(self._fraction or 0.0, overall)
        self._last = ProgressSnapshot(
            phase=phase,
            fraction=self._fraction,
            downloaded=event.downloaded if event else None,
            total=event.total if event else None,
            speed=event.speed if event else None,
            eta=event.eta if event else None,
            item_index=self._item_index,
            item_count=self._item_count,
        )
        return self._last
