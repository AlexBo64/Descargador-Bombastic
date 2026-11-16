import logging
from collections.abc import Iterator
from pathlib import Path

import pytest

from bombastic.core.logging_setup import LOG_FILE_NAME, setup_logging


@pytest.fixture(autouse=True)
def restore_root_logger() -> Iterator[None]:
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    yield
    for handler in list(root.handlers):
        if handler not in handlers:
            root.removeHandler(handler)
            handler.close()
    root.setLevel(level)


def test_writes_utf8_log_file(tmp_path: Path) -> None:
    log_file = setup_logging(tmp_path / "logs", console=False)
    logging.getLogger("prueba").info("Descarga terminada: vídeo ñ 日本語")
    for handler in logging.getLogger().handlers:
        handler.flush()
    assert log_file == tmp_path / "logs" / LOG_FILE_NAME
    assert "vídeo ñ 日本語" in log_file.read_text(encoding="utf-8")


def test_setup_is_idempotent(tmp_path: Path) -> None:
    before = len(logging.getLogger().handlers)
    setup_logging(tmp_path, console=False)
    setup_logging(tmp_path, console=False)
    assert len(logging.getLogger().handlers) == before + 1
