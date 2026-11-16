"""Modelo de datos de las descargas (sin Qt)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from bombastic.core.media_info import MediaInfo
from bombastic.core.ytdlp_command import DownloadOptions
from bombastic.core.ytdlp_progress import ProgressSnapshot


class ItemState(StrEnum):
    FETCHING = "fetching"  # obteniendo metadatos
    INFO_ERROR = "info_error"  # no se han podido obtener
    READY = "ready"  # listo para descargar (aún en la página de Descargas)
    QUEUED = "queued"  # en la cola, esperando turno
    DOWNLOADING = "downloading"
    PROCESSING = "processing"  # ffmpeg uniendo, convirtiendo o incrustando
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


#: Estados de la página de Descargas (antes de pedir la descarga).
STAGING = frozenset({ItemState.FETCHING, ItemState.INFO_ERROR, ItemState.READY})
#: Estados que se ven en la Cola.
QUEUE_STATES = frozenset(set(ItemState) - STAGING)
ACTIVE = frozenset({ItemState.DOWNLOADING, ItemState.PROCESSING})
FINISHED = frozenset({ItemState.COMPLETED, ItemState.FAILED, ItemState.CANCELLED})
#: Estados desde los que se puede pedir (o volver a pedir) la descarga.
STARTABLE = frozenset({ItemState.READY, ItemState.COMPLETED, ItemState.FAILED, ItemState.CANCELLED})
PAUSABLE = frozenset({ItemState.QUEUED, *ACTIVE})
CANCELLABLE = frozenset({ItemState.QUEUED, ItemState.PAUSED, *ACTIVE})


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
    #: Orden en la cola (menor = antes).
    position: float = 0.0
    #: Reintentos automáticos hechos en la descarga actual.
    attempts: int = 0
    #: Elementos elegidos de una lista (``--playlist-items``); vacío = todos.
    playlist_items: str = ""
    #: Últimas líneas de la salida de yt-dlp de la última descarga.
    log: list[str] = field(default_factory=list)
    created_at: str = ""

    @property
    def title(self) -> str:
        return self.info.title if self.info is not None else self.url
