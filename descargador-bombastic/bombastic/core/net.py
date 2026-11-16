"""Descargas HTTP sin bloquear (QtNetwork): textos pequeños y archivos con progreso."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from bombastic import APP_ID, __version__

log = logging.getLogger(__name__)

#: Identificador genérico (sin datos del usuario): GitHub exige un User-Agent.
USER_AGENT = f"{APP_ID}/{__version__}"
_TEXT_LIMIT = 4 * 1024 * 1024


def _request(url: str) -> QNetworkRequest:
    request = QNetworkRequest(QUrl(url))
    request.setRawHeader(b"User-Agent", USER_AGENT.encode("ascii"))
    request.setRawHeader(b"Accept", b"application/vnd.github+json, */*")
    request.setAttribute(
        QNetworkRequest.Attribute.RedirectPolicyAttribute,
        QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy,
    )
    request.setTransferTimeout(60_000)
    return request


class TextFetch(QObject):
    """Descarga un texto pequeño (JSON de GitHub, lista de sumas SHA-256…)."""

    #: ``(texto, error)``: el error está vacío si ha ido bien.
    finished = Signal(str, str)

    def __init__(self, network: QNetworkAccessManager, url: str, parent: QObject | None = None):
        super().__init__(parent)
        self._reply = network.get(_request(url))
        self._reply.finished.connect(self._done)

    def _done(self) -> None:
        reply = self._reply
        reply.deleteLater()
        if reply.error() != QNetworkReply.NetworkError.NoError:
            log.warning("GET %s failed: %s", reply.url().toString(), reply.errorString())
            self.finished.emit("", reply.errorString() or "network")
            return
        data = bytes(reply.readAll().data())[:_TEXT_LIMIT]
        self.finished.emit(data.decode("utf-8", errors="replace"), "")


class FileFetch(QObject):
    """Descarga un archivo a disco por partes, con progreso. Escribe en ``.part`` y renombra."""

    #: ``(bytes recibidos, total o -1)``.
    progress = Signal(object, object)
    #: Error vacío si ha ido bien.
    finished = Signal(str)

    def __init__(
        self,
        network: QNetworkAccessManager,
        url: str,
        target: Path,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.target = target
        self._part = target.with_name(target.name + ".part")
        target.parent.mkdir(parents=True, exist_ok=True)
        self._file = self._part.open("wb")
        self._reply = network.get(_request(url))
        self._reply.readyRead.connect(self._read)
        # downloadProgress usa enteros de 64 bits (archivos de más de 2 GB).
        self._reply.downloadProgress.connect(lambda done, total: self.progress.emit(done, total))
        self._reply.finished.connect(self._done)

    def abort(self) -> None:
        self._reply.abort()

    def _read(self) -> None:
        self._file.write(bytes(self._reply.readAll().data()))

    def _done(self) -> None:
        self._read()
        self._file.close()
        reply = self._reply
        reply.deleteLater()
        if reply.error() != QNetworkReply.NetworkError.NoError:
            self._part.unlink(missing_ok=True)
            self.finished.emit(reply.errorString() or "network")
            return
        self._part.replace(self.target)
        self.finished.emit("")
