"""Arranque de la aplicación."""

from __future__ import annotations

import logging
import sys
from collections.abc import Sequence

from PySide6.QtCore import QLibraryInfo, QTimer, QTranslator
from PySide6.QtWidgets import QApplication

from bombastic import APP_ID, APP_NAME, __version__
from bombastic.context import AppContext
from bombastic.core import i18n
from bombastic.core.db import Database
from bombastic.core.logging_setup import install_excepthook, setup_logging
from bombastic.core.paths import resolve_paths, resources_dir
from bombastic.core.settings import SettingsStore
from bombastic.ui.main_window import MainWindow
from bombastic.ui.theme import ThemeManager

log = logging.getLogger(__name__)


class QtDialogTranslations:
    """Traduce los diálogos estándar de Qt (selector de carpetas, botones Aceptar/Cancelar)."""

    def __init__(self, app: QApplication) -> None:
        self._app = app
        self._translator: QTranslator | None = None

    def apply(self, language: str) -> None:
        if self._translator is not None:
            self._app.removeTranslator(self._translator)
            self._translator = None
        translator = QTranslator(self._app)
        folder = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
        if translator.load(f"qtbase_{language}", folder):
            self._app.installTranslator(translator)
            self._translator = translator


def main(argv: Sequence[str] | None = None) -> int:
    paths = resolve_paths()
    paths.ensure()
    setup_logging(paths.logs_dir)
    install_excepthook()
    log.info(
        "Starting %s %s (data: %s, portable: %s)",
        APP_NAME,
        __version__,
        paths.data_dir,
        paths.portable,
    )

    store = SettingsStore(paths.settings_path)
    settings = store.load()

    app = QApplication(list(argv) if argv is not None else sys.argv)
    app.setApplicationName(APP_ID)
    app.setApplicationDisplayName(APP_NAME)
    app.setApplicationVersion(__version__)

    translator = i18n.Translator(resources_dir() / "i18n")
    translator.set_language(settings.language)
    i18n.install(translator)
    qt_translations = QtDialogTranslations(app)
    qt_translations.apply(translator.language)
    translator.subscribe(qt_translations.apply)

    theme = ThemeManager(app)
    theme.apply(settings.theme)

    db = Database(paths.db_path)
    ctx = AppContext(paths, settings, store, translator, theme, db)
    window = MainWindow(ctx)
    window.show()
    # Tras mostrar la ventana, para que el arranque no espere a los ejecutables externos.
    QTimer.singleShot(0, window.settings_page.refresh_dependencies)
    QTimer.singleShot(1500, window.startup_checks)

    code = app.exec()
    db.close()
    return code


if __name__ == "__main__":
    sys.exit(main())
