"""Gestor de los enlaces añadidos: obtiene sus metadatos y los descarga de uno en uno.

En esta fase la lista vive solo en memoria y hay una única descarga a la vez; lo que se pide
mientras tanto espera su turno. La cola persistente y las descargas simultáneas son de la
Fase 2.
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field, replace
from enum import StrEnum
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from bombastic.core.media_info import MediaInfo
from bombastic.core.ytdlp_command import DownloadOptions, build_download_args, build_info_args
from bombastic.core.ytdlp_progress import ProgressSnapshot
from bombastic.core.ytdlp_runner import (
    ERROR_MISSING,
    DownloadJob,
    DownloadResult,
    InfoFetcher,
    Launcher,
)

log = logging.getLogger(__name__)

#: Consultas de metadatos simultáneas (son ligeras, pero no conviene lanzar cien a la vez).
MAX_INFO_FETCHES = 3


class ItemState(StrEnum):
    FETCHING = "fetching"  # obteniendo metadatos
    INFO_ERROR = "info_error"  # no se han podido obtener
    READY = "ready"  # listo para descargar
    QUEUED = "queued"  # esperando a que termine otra descarga
    DOWNLOADING = "downloading"
    PROCESSING = "processing"  # ffmpeg uniendo, convirtiendo o incrustando
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


#: Estados desde los que se puede pedir (o volver a pedir) la descarga.
STARTABLE = frozenset({ItemState.READY, ItemState.COMPLETED, ItemState.FAILED, ItemState.CANCELLED})
ACTIVE = frozenset({ItemState.DOWNLOADING, ItemState.PROCESSING})


@dataclass
class DownloadItem:
    item_id: int
    url: str
    state: ItemState = ItemState.FETCHING
    info: MediaInfo | None = None
    error_code: str = ""
    error_detail: str = ""
    options: DownloadOptions | None = None
    snapshot: ProgressSnapshot | None = None
    files: list[Path] = field(default_factory=list)
    #: Comando de la última descarga, como texto.
    command: str = ""


class DownloadManager(QObject):
    item_added = Signal(int)
    item_changed = Signal(int)
    item_removed = Signal(int)

    def __init__(self, launcher: Launcher, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._launcher = launcher
        self._items: dict[int, DownloadItem] = {}
        self._next_id = 1
        self._info_pending: deque[int] = deque()
        self._fetchers: dict[int, InfoFetcher] = {}
        self._queue: deque[int] = deque()
        self._active_id: int | None = None
        self._job: DownloadJob | None = None

    # ------------------------------------------------------------------ consulta

    def items(self) -> list[DownloadItem]:
        return list(self._items.values())

    def item(self, item_id: int) -> DownloadItem | None:
        return self._items.get(item_id)

    @property
    def busy(self) -> bool:
        """Hay una descarga en curso o esperando."""
        return self._active_id is not None or bool(self._queue)

    # ------------------------------------------------------------------- enlaces

    def add_urls(self, urls: list[str]) -> list[int]:
        """Añade los enlaces que no estén ya en la lista. Devuelve los ids creados."""
        known = {item.url for item in self._items.values()}
        created: list[int] = []
        for url in urls:
            if url in known:
                continue
            known.add(url)
            item = DownloadItem(self._next_id, url)
            self._next_id += 1
            self._items[item.item_id] = item
            created.append(item.item_id)
            self.item_added.emit(item.item_id)
            self._info_pending.append(item.item_id)
        self._pump_info()
        return created

    def retry_info(self, item_id: int) -> None:
        item = self._items.get(item_id)
        if item is None or item.state is not ItemState.INFO_ERROR:
            return
        item.state = ItemState.FETCHING
        item.error_code = item.error_detail = ""
        self._info_pending.append(item_id)
        self.item_changed.emit(item_id)
        self._pump_info()

    def remove(self, item_id: int) -> None:
        """Quita un enlace de la lista, cancelando lo que tuviera en marcha."""
        item = self._items.pop(item_id, None)
        if item is None:
            return
        if item_id in self._info_pending:
            self._info_pending.remove(item_id)
        fetcher = self._fetchers.pop(item_id, None)
        if fetcher is not None:
            fetcher.cancel()
            fetcher.deleteLater()
        if item_id in self._queue:
            self._queue.remove(item_id)
        if item_id == self._active_id and self._job is not None:
            # El resultado llegará por la señal y liberará el turno.
            self._job.cancel()
        self.item_removed.emit(item_id)
        self._pump_info()

    # ----------------------------------------------------------------- metadatos

    def _pump_info(self) -> None:
        while self._info_pending and len(self._fetchers) < MAX_INFO_FETCHES:
            item_id = self._info_pending.popleft()
            item = self._items.get(item_id)
            if item is None:
                continue
            launch = self._launcher(build_info_args(item.url))
            if launch is None:
                self._info_failed(item_id, ERROR_MISSING, "")
                continue
            fetcher = InfoFetcher(launch, item.url, parent=self)
            self._fetchers[item_id] = fetcher
            fetcher.succeeded.connect(lambda info, i=item_id: self._info_ready(i, info))
            fetcher.failed.connect(
                lambda code, detail, i=item_id: self._info_failed(i, code, detail)
            )
            fetcher.start()

    def _release_fetcher(self, item_id: int) -> None:
        fetcher = self._fetchers.pop(item_id, None)
        if fetcher is not None:
            fetcher.deleteLater()

    def _info_ready(self, item_id: int, info: MediaInfo) -> None:
        self._release_fetcher(item_id)
        item = self._items.get(item_id)
        if item is not None:
            item.info = info
            item.state = ItemState.READY
            self.item_changed.emit(item_id)
        self._pump_info()

    def _info_failed(self, item_id: int, code: str, detail: str) -> None:
        self._release_fetcher(item_id)
        item = self._items.get(item_id)
        if item is not None:
            item.state = ItemState.INFO_ERROR
            item.error_code = code
            item.error_detail = detail
            self.item_changed.emit(item_id)
        self._pump_info()

    # ----------------------------------------------------------------- descargas

    def start(self, item_id: int, options: DownloadOptions) -> bool:
        """Pide la descarga de un enlace con las opciones dadas.

        Empieza al momento si no hay otra en curso; si la hay, espera su turno.
        Devuelve ``False`` si el enlace no está en un estado descargable.
        """
        item = self._items.get(item_id)
        if item is None or item.state not in STARTABLE:
            return False
        is_playlist = item.info.is_playlist if item.info is not None else False
        item.options = replace(options, playlist=is_playlist)
        item.state = ItemState.QUEUED
        item.error_code = item.error_detail = ""
        item.snapshot = None
        item.files = []
        self._queue.append(item_id)
        self.item_changed.emit(item_id)
        self._pump_downloads()
        return True

    def cancel(self, item_id: int) -> None:
        item = self._items.get(item_id)
        if item is None:
            return
        if item.state is ItemState.QUEUED:
            self._queue.remove(item_id)
            item.state = ItemState.CANCELLED
            self.item_changed.emit(item_id)
        elif item_id == self._active_id and self._job is not None:
            self._job.cancel()

    def shutdown(self) -> None:
        """Detiene todo lo que esté en marcha. Se llama al cerrar la aplicación."""
        self._info_pending.clear()
        self._queue.clear()
        for fetcher in self._fetchers.values():
            fetcher.cancel()
        self._fetchers.clear()
        if self._job is not None:
            self._job.cancel()

    def _pump_downloads(self) -> None:
        while self._active_id is None and self._queue:
            item_id = self._queue.popleft()
            item = self._items.get(item_id)
            if item is None or item.options is None:
                continue
            launch = self._launcher(build_download_args(item.url, item.options))
            if launch is None:
                item.state = ItemState.FAILED
                item.error_code = ERROR_MISSING
                self.item_changed.emit(item_id)
                continue
            job = DownloadJob(launch, parent=self)
            self._job = job
            self._active_id = item_id
            item.command = job.command
            item.state = ItemState.DOWNLOADING
            job.progress.connect(lambda snapshot, i=item_id: self._on_progress(i, snapshot))
            job.finished.connect(lambda result, i=item_id: self._on_finished(i, result))
            self.item_changed.emit(item_id)
            job.start()

    def _on_progress(self, item_id: int, snapshot: ProgressSnapshot) -> None:
        item = self._items.get(item_id)
        if item is None or item_id != self._active_id:
            return
        item.snapshot = snapshot
        item.state = (
            ItemState.PROCESSING if snapshot.phase == "processing" else ItemState.DOWNLOADING
        )
        self.item_changed.emit(item_id)

    def _on_finished(self, item_id: int, result: DownloadResult) -> None:
        if item_id == self._active_id:
            if self._job is not None:
                self._job.deleteLater()
            self._job = None
            self._active_id = None
        item = self._items.get(item_id)
        if item is not None:
            item.files = list(result.files)
            item.error_code = result.error_code
            item.error_detail = result.error_detail
            item.state = {
                "completed": ItemState.COMPLETED,
                "cancelled": ItemState.CANCELLED,
            }.get(result.status, ItemState.FAILED)
            self.item_changed.emit(item_id)
        self._pump_downloads()
