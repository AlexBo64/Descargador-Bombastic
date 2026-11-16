"""Configuración común de los tests."""

from __future__ import annotations

import os

# Debe fijarse antes de importar Qt: permite ejecutar los tests sin pantalla (CI).
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from collections.abc import Iterator
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from bombastic.context import AppContext
from bombastic.core import i18n
from bombastic.core.paths import AppPaths, resources_dir
from bombastic.core.settings import SettingsStore
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
def ctx(qapp: QApplication, paths: AppPaths, translator: i18n.Translator) -> Iterator[AppContext]:
    store = SettingsStore(paths.settings_path)
    theme = ThemeManager(qapp)
    theme.apply("dark")
    yield AppContext(paths, store.load(), store, translator, theme)
    qapp.setStyleSheet("")
