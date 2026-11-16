"""Gestor de descargas: metadatos de los enlaces, cola persistente y descargas simultáneas.

Los enlaces recién añadidos viven en memoria (estados de :data:`STAGING`). Al pedir su
descarga pasan a la cola, que se guarda en SQLite si se da una base de datos: al volver a abrir
la app, lo que estaba en marcha o esperando se recupera en pausa.
"""

from __future__ import annotations

import json
import logging
from collections import deque
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal

from bombastic.core.db import Database, now_iso
from bombastic.core.download_models import (
    ACTIVE,
    CANCELLABLE,
    FINISHED,
    PAUSABLE,
    QUEUE_STATES,
    STAGING,
    STARTABLE,
    DownloadItem,
    ItemState,
)
from bombastic.core.errors import classify_error
from bombastic.core.media_info import MediaInfo, info_from_dict, info_to_dict
from bombastic.core.ytdlp_command import (
    DownloadOptions,
    build_download_args,
    build_info_args,
    options_from_dict,
    options_to_dict,
)
from bombastic.core.ytdlp_progress import ProgressSnapshot
from bombastic.core.ytdlp_runner import (
    ERROR_MISSING,
    ERROR_YTDLP,
    DownloadJob,
    DownloadResult,
    InfoFetcher,
    Launcher,
)

__all__ = [
    "ACTIVE",
    "CANCELLABLE",
    "FINISHED",
    "PAUSABLE",
    "QUEUE_STATES",
    "STAGING",
    "STARTABLE",
    "DownloadItem",
    "DownloadManager",
    "ItemState",
]

log = logging.getLogger(__name__)

#: Consultas de metadatos simultáneas (son ligeras, pero no conviene lanzar cien a la vez).
MAX_INFO_FETCHES = 3
MIN_CONCURRENT, MAX_CONCURRENT = 1, 8
#: Líneas del log que se guardan con cada elemento.
_SAVED_LOG_LINES = 200
_SHUTDOWN_WAIT_MS = 3000


class DownloadManager(QObject):
    item_added = Signal(int)
    item_changed = Signal(int)
    item_removed = Signal(int)

    def __init__(
        self,
        launcher: Launcher,
        parent: QObject | None = None,
        db: Database | None = None,
        max_concurrent: int = 3,
    ) -> None:
        super().__init__(parent)
        self._launcher = launcher
        self._db = db
        self._items: dict[int, DownloadItem] = {}
        self._next_id = 1
        self._info_pending: deque[int] = deque()
        self._fetchers: dict[int, InfoFetcher] = {}
        self._jobs: dict[int, DownloadJob] = {}
        #: Descargas que se están deteniendo para quedar en pausa (no canceladas).
        self._pausing: set[int] = set()
        #: Reintentos automáticos esperando su momento.
        self._cooling: set[int] = set()
        self._max_concurrent = max_concurrent
        #: La app se está cerrando: no se lanza nada nuevo.
        self._closing = False
        #: Reintentos automáticos ante errores de red pasajeros.
        self.max_retries = 2
        self.retry_delay_ms = 5000
        #: Límite global de velocidad (``--limit-rate``); se aplica al lanzar cada descarga.
        self.rate_limit = ""
        if db is not None:
            row = db.query("SELECT MAX(id) AS top FROM downloads")[0]
            self._next_id = int(row["top"] or 0) + 1

    # ------------------------------------------------------------------ consulta

    def items(self) -> list[DownloadItem]:
        return list(self._items.values())

    def item(self, item_id: int) -> DownloadItem | None:
        return self._items.get(item_id)

    def queue_items(self) -> list[DownloadItem]:
        """Elementos de la cola, en orden."""
        queued = [item for item in self._items.values() if item.state in QUEUE_STATES]
        return sorted(queued, key=lambda item: item.position)

    @property
    def busy(self) -> bool:
        """Hay alguna descarga en curso o esperando turno."""
        return any(item.state in ACTIVE or item.state is ItemState.QUEUED for item in self.items())

    @property
    def max_concurrent(self) -> int:
        return self._max_concurrent

    @max_concurrent.setter
    def max_concurrent(self, value: int) -> None:
        self._max_concurrent = max(MIN_CONCURRENT, min(MAX_CONCURRENT, value))
        self._pump_downloads()

    # ------------------------------------------------------------- persistencia

    def restore(self) -> None:
        """Carga la cola guardada. Lo que estaba en marcha o esperando queda en pausa."""
        if self._db is None:
            return
        for row in self._db.query("SELECT * FROM downloads ORDER BY position"):
            try:
                state = ItemState(row["state"])
            except ValueError:
                state = ItemState.FAILED
            if state in ACTIVE or state is ItemState.QUEUED or state in STAGING:
                state = ItemState.PAUSED
            item = DownloadItem(
                item_id=int(row["id"]),
                url=row["url"],
                state=state,
                info=info_from_dict(_load_json(row["info"]), row["url"]),
                error_code=row["error_code"],
                error_detail=row["error_detail"],
                options=options_from_dict(_load_json(row["options"])),
                files=_load_files(row["files"]),
                command=row["command"],
                position=float(row["position"]),
                attempts=int(row["attempts"]),
                log=row["log"].splitlines(),
                created_at=row["created_at"],
            )
            if item.options is None:
                item.state = ItemState.FAILED
            self._items[item.item_id] = item
            self._next_id = max(self._next_id, item.item_id + 1)
            self.item_added.emit(item.item_id)

    def _save(self, item: DownloadItem) -> None:
        if self._db is None or item.state in STAGING:
            return
        self._db.execute(
            """
            INSERT INTO downloads (id, url, position, state, info, options, files, error_code,
                error_detail, command, log, attempts, created_at, updated_at)
            VALUES (:id, :url, :position, :state, :info, :options, :files, :error_code,
                :error_detail, :command, :log, :attempts, :created_at, :updated_at)
            ON CONFLICT(id) DO UPDATE SET position = excluded.position, state = excluded.state,
                info = excluded.info, options = excluded.options, files = excluded.files,
                error_code = excluded.error_code, error_detail = excluded.error_detail,
                command = excluded.command, log = excluded.log, attempts = excluded.attempts,
                updated_at = excluded.updated_at
            """,
            {
                "id": item.item_id,
                "url": item.url,
                "position": item.position,
                "state": item.state.value,
                "info": json.dumps(info_to_dict(item.info)) if item.info is not None else None,
                "options": (
                    json.dumps(options_to_dict(item.options)) if item.options is not None else None
                ),
                "files": json.dumps([str(f) for f in item.files]),
                "error_code": item.error_code,
                "error_detail": item.error_detail,
                "command": item.command,
                "log": "\n".join(item.log[-_SAVED_LOG_LINES:]),
                "attempts": item.attempts,
                "created_at": item.created_at or now_iso(),
                "updated_at": now_iso(),
            },
        )

    def _changed(self, item: DownloadItem) -> None:
        """Guarda el elemento y avisa a la interfaz."""
        self._save(item)
        self.item_changed.emit(item.item_id)

    # ------------------------------------------------------------------- enlaces

    def add_urls(self, urls: list[str]) -> list[int]:
        """Añade los enlaces que no estén ya en la página de descargas. Devuelve los ids."""
        known = {item.url for item in self._items.values() if item.state in STAGING}
        created: list[int] = []
        for url in urls:
            if url in known:
                continue
            known.add(url)
            item = DownloadItem(self._next_id, url, created_at=now_iso())
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
        """Quita un elemento, cancelando lo que tuviera en marcha."""
        item = self._items.pop(item_id, None)
        if item is None:
            return
        if item_id in self._info_pending:
            self._info_pending.remove(item_id)
        fetcher = self._fetchers.pop(item_id, None)
        if fetcher is not None:
            fetcher.dispose()
        self._cooling.discard(item_id)
        job = self._jobs.get(item_id)
        if job is not None:
            # El resultado llegará por la señal y liberará el turno.
            job.cancel()
        if self._db is not None:
            self._db.execute("DELETE FROM downloads WHERE id = ?", (item_id,))
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

    # ------------------------------------------------------------- cola: acciones

    def start(self, item_id: int, options: DownloadOptions) -> bool:
        """Mete un enlace en la cola con las opciones dadas (o lo vuelve a meter).

        Devuelve ``False`` si el elemento no está en un estado descargable.
        """
        item = self._items.get(item_id)
        if item is None or item.state not in STARTABLE:
            return False
        is_playlist = item.info.is_playlist if item.info is not None else False
        item.options = replace(options, playlist=is_playlist)
        if item.state is ItemState.READY:
            item.position = self._last_position() + 1
        self._enqueue(item)
        return True

    def retry(self, item_id: int) -> bool:
        """Vuelve a descargar con las mismas opciones."""
        item = self._items.get(item_id)
        if item is None or item.options is None or item.state not in FINISHED:
            return False
        self._enqueue(item)
        return True

    def pause(self, item_id: int) -> None:
        """Detiene la descarga conservando los ``.part`` para reanudar después."""
        item = self._items.get(item_id)
        if item is None or item.state not in PAUSABLE:
            return
        job = self._jobs.get(item_id)
        if job is not None:
            self._pausing.add(item_id)
            job.cancel()
            return
        self._cooling.discard(item_id)
        item.state = ItemState.PAUSED
        self._changed(item)

    def resume(self, item_id: int) -> None:
        item = self._items.get(item_id)
        if item is None or item.state is not ItemState.PAUSED:
            return
        item.state = ItemState.QUEUED
        self._changed(item)
        self._pump_downloads()

    def cancel(self, item_id: int) -> None:
        item = self._items.get(item_id)
        if item is None or item.state not in CANCELLABLE:
            return
        job = self._jobs.get(item_id)
        if job is not None:
            self._pausing.discard(item_id)
            job.cancel()
            return
        self._cooling.discard(item_id)
        item.state = ItemState.CANCELLED
        self._changed(item)

    def pause_all(self) -> None:
        for item in self.queue_items():
            self.pause(item.item_id)

    def resume_all(self) -> None:
        for item in self.queue_items():
            if item.state is ItemState.PAUSED:
                item.state = ItemState.QUEUED
                self._changed(item)
        self._pump_downloads()

    def move(self, item_id: int, offset: int) -> None:
        """Mueve un elemento de la cola ``offset`` puestos (negativo = hacia arriba)."""
        queue = self.queue_items()
        index = next((i for i, item in enumerate(queue) if item.item_id == item_id), None)
        if index is None:
            return
        target = max(0, min(len(queue) - 1, index + offset))
        if target == index:
            return
        moved = queue.pop(index)
        queue.insert(target, moved)
        self.reorder([item.item_id for item in queue])

    def reorder(self, ids: list[int]) -> None:
        """Fija el orden de la cola (los ids que falten conservan su sitio al final)."""
        known = [self._items[i] for i in ids if i in self._items]
        rest = [item for item in self.queue_items() if item not in known]
        for position, item in enumerate([*known, *rest], start=1):
            if item.position != position:
                item.position = float(position)
                self._changed(item)

    def shutdown(self) -> None:
        """Detiene todo al cerrar la app. Lo que estaba en marcha queda en pausa."""
        self._closing = True
        self._info_pending.clear()
        fetchers = list(self._fetchers.values())
        for fetcher in fetchers:
            fetcher.cancel()
        self._fetchers.clear()
        self._cooling.clear()
        jobs = list(self._jobs.items())
        for item_id, job in jobs:
            self._pausing.add(item_id)
            job.cancel()
        # Se espera a que mueran los procesos: si el gestor se destruyera con uno vivo, su
        # señal de fin llegaría a un objeto a medio borrar. La muerte del árbol es rápida.
        for fetcher in fetchers:
            fetcher.wait(_SHUTDOWN_WAIT_MS)
        for _item_id, job in jobs:
            job.wait(_SHUTDOWN_WAIT_MS)
        for item in self.queue_items():
            if item.state is ItemState.QUEUED:
                item.state = ItemState.PAUSED
                self._changed(item)

    # ------------------------------------------------------------ cola: turnos

    def _last_position(self) -> float:
        return max((item.position for item in self.queue_items()), default=0.0)

    def _enqueue(self, item: DownloadItem) -> None:
        item.state = ItemState.QUEUED
        item.error_code = item.error_detail = ""
        item.snapshot = None
        item.files = []
        item.attempts = 0
        self._changed(item)
        self._pump_downloads()

    def _pump_downloads(self) -> None:
        if self._closing:
            return
        for item in self.queue_items():
            if len(self._jobs) >= self._max_concurrent:
                return
            if item.state is not ItemState.QUEUED or item.item_id in self._cooling:
                continue
            self._launch(item)

    def _launch(self, item: DownloadItem) -> None:
        assert item.options is not None
        options = replace(item.options, rate_limit=self.rate_limit)
        launch = self._launcher(build_download_args(item.url, options))
        if launch is None:
            item.state = ItemState.FAILED
            item.error_code = ERROR_MISSING
            self._changed(item)
            return
        job = DownloadJob(launch, parent=self)
        self._jobs[item.item_id] = job
        item.command = job.command
        item.state = ItemState.DOWNLOADING
        job.progress.connect(lambda snapshot, i=item.item_id: self._on_progress(i, snapshot))
        job.finished.connect(lambda result, i=item.item_id: self._on_finished(i, result))
        self._changed(item)
        job.start()

    def _on_progress(self, item_id: int, snapshot: ProgressSnapshot) -> None:
        item = self._items.get(item_id)
        if item is None or item_id not in self._jobs:
            return
        item.snapshot = snapshot
        state = ItemState.PROCESSING if snapshot.phase == "processing" else ItemState.DOWNLOADING
        if state is not item.state:
            item.state = state
            self._changed(item)
        else:
            # El progreso no se guarda: solo cambia lo que se ve.
            self.item_changed.emit(item_id)

    def _on_finished(self, item_id: int, result: DownloadResult) -> None:
        job = self._jobs.pop(item_id, None)
        if job is not None:
            item_log = list(job.log_lines)
            job.deleteLater()
        else:
            item_log = []
        pausing = item_id in self._pausing
        self._pausing.discard(item_id)
        item = self._items.get(item_id)
        if item is not None:
            item.files = list(result.files)
            item.log = item_log
            item.error_code = result.error_code
            item.error_detail = result.error_detail
            if result.status == "completed":
                item.state = ItemState.COMPLETED
            elif result.status == "cancelled":
                item.state = ItemState.PAUSED if pausing else ItemState.CANCELLED
            else:
                self._handle_failure(item)
            self._changed(item)
        self._pump_downloads()

    def _handle_failure(self, item: DownloadItem) -> None:
        """Traduce el error y, si es de red, programa un reintento automático."""
        item.state = ItemState.FAILED
        if item.error_code != ERROR_YTDLP:
            return
        error = classify_error(item.error_detail, item.log[-30:])
        if error.key != "unknown":
            item.error_code = error.key
        if error.retryable and item.attempts < self.max_retries:
            item.attempts += 1
            item.state = ItemState.QUEUED
            item_id = item.item_id
            self._cooling.add(item_id)
            log.info("Retrying %s (attempt %s) after %s", item.url, item.attempts, error.key)

            def release() -> None:
                if item_id in self._cooling:
                    self._cooling.discard(item_id)
                    self._pump_downloads()

            QTimer.singleShot(self.retry_delay_ms * item.attempts, self, release)


def _load_files(raw: str | None) -> list[Path]:
    files = _load_json(raw)
    if not isinstance(files, list):
        return []
    return [Path(f) for f in files if isinstance(f, str)]


def _load_json(raw: str | None) -> object:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None
