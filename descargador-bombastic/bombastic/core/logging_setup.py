"""Logs rotativos en la carpeta de datos."""

from __future__ import annotations

import logging
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path
from types import TracebackType

LOG_FILE_NAME = "bombastic.log"
_OWNED_FLAG = "_bombastic_owned"
_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


def setup_logging(logs_dir: Path, level: int = logging.INFO, console: bool = True) -> Path:
    """Configura el logger raíz: archivo rotativo (5 x 1 MB, UTF-8) y, opcionalmente, consola.

    Es idempotente: llamarla otra vez sustituye los handlers anteriores en vez de duplicarlos.
    Devuelve la ruta del archivo de log.
    """
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = logs_dir / LOG_FILE_NAME
    root = logging.getLogger()

    for handler in list(root.handlers):
        if getattr(handler, _OWNED_FLAG, False):
            root.removeHandler(handler)
            handler.close()

    formatter = logging.Formatter(_FORMAT)
    handlers: list[logging.Handler] = [
        RotatingFileHandler(log_file, maxBytes=1_000_000, backupCount=5, encoding="utf-8")
    ]
    # En el ejecutable sin consola de Windows sys.stderr es None.
    if console and sys.stderr is not None:
        handlers.append(logging.StreamHandler(sys.stderr))
    for handler in handlers:
        handler.setFormatter(formatter)
        setattr(handler, _OWNED_FLAG, True)
        root.addHandler(handler)

    root.setLevel(level)
    return log_file


def install_excepthook() -> None:
    """Registra en el log cualquier excepción no capturada (hilo principal y secundarios)."""
    log = logging.getLogger("bombastic.crash")

    def hook(
        exc_type: type[BaseException],
        exc: BaseException,
        tb: TracebackType | None,
    ) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        log.critical("Uncaught exception", exc_info=(exc_type, exc, tb))

    def thread_hook(args: threading.ExceptHookArgs) -> None:
        if args.exc_value is not None:
            hook(args.exc_type, args.exc_value, args.exc_traceback)

    sys.excepthook = hook
    threading.excepthook = thread_hook
