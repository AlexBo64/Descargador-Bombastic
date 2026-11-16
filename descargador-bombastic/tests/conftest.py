"""Configuración común de los tests."""

from __future__ import annotations

import os

# Debe fijarse antes de importar Qt: permite ejecutar los tests sin pantalla (CI).
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication

from bombastic.context import AppContext
from bombastic.core import i18n
from bombastic.core.download_manager import DownloadManager
from bombastic.core.paths import AppPaths, resources_dir
from bombastic.core.settings import SettingsStore
from bombastic.core.ytdlp_runner import Launch, Launcher
from bombastic.ui.theme import ThemeManager


@pytest.fixture
def paths(tmp_path: Path) -> AppPaths:
    app_paths = AppPaths(app_dir=tmp_path / "app", data_dir=tmp_path / "datos ñ", portable=False)
    app_paths.ensure()
    return app_paths


@pytest.fixture
def translator() -> Iterator[i18n.Translator]:
    translator = i18n.Translator(resources_dir() / "i18n")
    i18n.install(translator)
    yield translator
    i18n.install(i18n.Translator(resources_dir() / "i18n"))


@pytest.fixture
def fake_launcher() -> Launcher:
    """Lanza ``tests/fake_ytdlp.py`` con el intérprete actual en vez del yt-dlp real."""
    script = str(Path(__file__).with_name("fake_ytdlp.py"))

    def launch(args: list[str]) -> Launch | None:
        return sys.executable, [script, *args]

    return launch


@pytest.fixture
def ctx(qapp: QApplication, paths: AppPaths, translator: i18n.Translator) -> Iterator[AppContext]:
    store = SettingsStore(paths.settings_path)
    theme = ThemeManager(qapp)
    theme.apply("dark")
    yield AppContext(paths, store.load(), store, translator, theme)
    qapp.setStyleSheet("")


@pytest.fixture(autouse=True)
def _dispose_managers(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Cierra y borra con Qt los gestores sin padre creados en cada test.

    Si se dejara que el recolector de Python los destruyera (en cualquier momento de un test
    posterior), Qt podría abortar. En la app el gestor cuelga de una página y vive toda la sesión.
    """
    created: list[DownloadManager] = []
    original = DownloadManager.__init__

    def init(self: DownloadManager, *args: Any, **kwargs: Any) -> None:
        original(self, *args, **kwargs)
        if self.parent() is None:
            created.append(self)

    monkeypatch.setattr(DownloadManager, "__init__", init)
    yield
    for manager in created:
        manager.shutdown()
        manager.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
