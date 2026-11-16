"""Instancia única con ``QLocalServer``/``QLocalSocket``.

Si la app ya está abierta, la nueva instancia manda sus argumentos a la existente (por ejemplo,
desde el menú contextual con varios archivos) y se cierra sin abrir otra ventana.
"""

from __future__ import annotations

import getpass
import hashlib
import json
import logging

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from bombastic import APP_ID

log = logging.getLogger(__name__)

_TIMEOUT_MS = 1500


def server_name(suffix: str = "") -> str:
    """Nombre por usuario (y por carpeta de datos, para que la portable no choque)."""
    try:
        user = getpass.getuser()
    except (OSError, KeyError):
        user = "user"
    digest = hashlib.sha1(f"{user}|{suffix}".encode()).hexdigest()[:12]
    return f"{APP_ID}-{digest}"


def send_to_running(name: str, args: list[str]) -> bool:
    """Manda ``args`` a la instancia abierta. ``False`` si no hay ninguna."""
    socket = QLocalSocket()
    socket.connectToServer(name)
    if not socket.waitForConnected(_TIMEOUT_MS):
        return False
    socket.write(json.dumps(args).encode("utf-8") + b"\n")
    socket.flush()
    socket.waitForBytesWritten(_TIMEOUT_MS)
    socket.disconnectFromServer()
    return True


class InstanceServer(QObject):
    """Escucha a las instancias nuevas. Emite sus argumentos."""

    message_received = Signal(list)

    def __init__(self, name: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._server = QLocalServer(self)
        # Solo el mismo usuario puede conectarse.
        self._server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self._server.newConnection.connect(self._on_connection)
        if not self._server.listen(name):
            # Quedó un socket de una ejecución que se cerró mal: se limpia y se reintenta.
            QLocalServer.removeServer(name)
            if not self._server.listen(name):
                log.warning("Single instance server unavailable: %s", self._server.errorString())

    @property
    def listening(self) -> bool:
        return self._server.isListening()

    def _on_connection(self) -> None:
        while (socket := self._server.nextPendingConnection()) is not None:
            buffer = bytearray()

            def read(sock: QLocalSocket = socket, data: bytearray = buffer) -> None:
                data.extend(bytes(sock.readAll().data()))
                if data.endswith(b"\n"):
                    self._deliver(bytes(data))
                    data.clear()

            socket.readyRead.connect(read)
            socket.disconnected.connect(socket.deleteLater)
            # Los datos pueden haber llegado ya antes de conectar readyRead.
            if socket.bytesAvailable():
                read()

    def _deliver(self, raw: bytes) -> None:
        try:
            args = json.loads(raw.decode("utf-8"))
        except ValueError:
            return
        if isinstance(args, list) and all(isinstance(a, str) for a in args):
            self.message_received.emit(args)
