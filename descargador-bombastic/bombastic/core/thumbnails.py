"""Descarga y caché en disco de las miniaturas.

Usa QtNetwork (sin widgets) para no bloquear la interfaz. La interfaz recibe la ruta del
archivo y es ella quien lo convierte en imagen.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from urllib.parse import urlsplit

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

log = logging.getLogger(__name__)

_MAX_BYTES = 5 * 1024 * 1024
_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".gif")


def cache_path(cache_dir: Path, url: str) -> Path:
    """Archivo de caché que corresponde a una URL de miniatura."""
    suffix = Path(urlsplit(url).path).suffix.lower()
    if suffix not in _EXTENSIONS:
        suffix = ".img"
    return cache_dir / (hashlib.sha1(url.encode("utf-8")).hexdigest() + suffix)


class ThumbnailLoader(QObject):
    #: Emite ``(url, ruta del archivo)`` cuando la miniatura está en disco.
    loaded = Signal(str, str)

    def __init__(self, cache_dir: Path, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._cache_dir = cache_dir
        self._network = QNetworkAccessManager(self)
        self._pending: set[str] = set()

    def request(self, url: str) -> None:
        """Pide una miniatura. ``loaded`` se emite siempre de forma asíncrona."""
        if not url or url in self._pending:
            return
        target = cache_path(self._cache_dir, url)
        if target.is_file():
            QTimer.singleShot(0, self, lambda: self.loaded.emit(url, str(target)))
            return
        self._pending.add(url)
        request = QNetworkRequest(QUrl(url))
        request.setTransferTimeout(20_000)
        reply = self._network.get(request)
        reply.finished.connect(lambda: self._on_finished(url, target, reply))

    def _on_finished(self, url: str, target: Path, reply: QNetworkReply) -> None:
        self._pending.discard(url)
        reply.deleteLater()
        if reply.error() != QNetworkReply.NetworkError.NoError:
            log.info("Could not download thumbnail %s: %s", url, reply.errorString())
            return
        data = bytes(reply.readAll().data())
        if not data or len(data) > _MAX_BYTES:
            return
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_name(target.name + ".tmp")
            tmp.write_bytes(data)
            tmp.replace(target)
        except OSError:
            log.exception("Could not store thumbnail %s", target)
            return
        self.loaded.emit(url, str(target))
