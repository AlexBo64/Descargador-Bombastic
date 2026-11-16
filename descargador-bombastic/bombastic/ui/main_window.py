"""Ventana principal: navegación lateral y páginas."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QCloseEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from bombastic import APP_NAME, __version__
from bombastic.context import AppContext
from bombastic.core.i18n import tr
from bombastic.core.settings import MIN_WINDOW_HEIGHT, MIN_WINDOW_WIDTH, PAGES
from bombastic.ui.pages import Page, PlaceholderPage
from bombastic.ui.settings_page import SettingsPage
from bombastic.ui.theme import load_icon

#: Fase del plan en la que se implementa cada sección todavía vacía.
_PLACEHOLDER_PHASES = {"downloads": 1, "queue": 2, "editor": 4, "history": 7, "library": 6}


class MainWindow(QMainWindow):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self._ctx = ctx
        self.setObjectName("MainWindow")
        self.setMinimumSize(MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)

        # --- Barra lateral ---
        self.title_label = QLabel(APP_NAME)
        self.title_label.setObjectName("AppTitle")
        self.nav = QListWidget()
        self.nav.setObjectName("Nav")
        self.nav.setIconSize(QSize(20, 20))
        self.nav.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.version_label = QLabel()
        self.version_label.setObjectName("AppVersion")

        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(228)
        side_layout = QVBoxLayout(sidebar)
        side_layout.setContentsMargins(0, 0, 0, 0)
        side_layout.setSpacing(0)
        side_layout.addWidget(self.title_label)
        side_layout.addWidget(self.nav, 1)
        side_layout.addWidget(self.version_label)

        # --- Páginas ---
        self.stack = QStackedWidget()
        self.settings_page = SettingsPage(ctx)
        self.pages: dict[str, Page] = {}
        for key in PAGES:
            page: Page = (
                self.settings_page
                if key == "settings"
                else PlaceholderPage(key, _PLACEHOLDER_PHASES[key])
            )
            self.pages[key] = page
            self.stack.addWidget(page)
            self.nav.addItem(QListWidgetItem())

        central = QWidget()
        central.setObjectName("Central")
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(sidebar)
        layout.addWidget(self.stack, 1)
        self.setCentralWidget(central)

        # --- Atajos: Ctrl+1 … Ctrl+6 ---
        for number, key in enumerate(PAGES, start=1):
            shortcut = QShortcut(QKeySequence(f"Ctrl+{number}"), self)
            shortcut.activated.connect(lambda key=key: self.show_page(key))

        self.nav.currentRowChanged.connect(self._on_row_changed)
        self._unsubscribe = ctx.translator.subscribe(lambda _language: self.retranslate())
        ctx.theme.changed.connect(self._refresh_icons)

        self.retranslate()
        self._refresh_icons()
        self._restore_state()

    # ------------------------------------------------------------- navegación

    def current_page(self) -> str:
        return PAGES[max(0, self.nav.currentRow())]

    def show_page(self, key: str) -> None:
        if key in PAGES:
            self.nav.setCurrentRow(PAGES.index(key))

    def _on_row_changed(self, row: int) -> None:
        if 0 <= row < len(PAGES):
            self.stack.setCurrentIndex(row)
            self._ctx.settings.last_page = PAGES[row]

    # ------------------------------------------------------------ textos y tema

    def retranslate(self) -> None:
        self.setWindowTitle(tr("app.name"))
        self.version_label.setText(tr("app.version", version=__version__))
        for row, key in enumerate(PAGES):
            item = self.nav.item(row)
            name = tr(f"nav.{key}")
            item.setText(name)
            item.setToolTip(tr("nav.tooltip", name=name, number=row + 1))
        for page in self.pages.values():
            page.retranslate()

    def _refresh_icons(self) -> None:
        color = self._ctx.theme.palette["muted"]
        for row, key in enumerate(PAGES):
            self.nav.item(row).setIcon(load_icon(key, color))

    # ------------------------------------------------------- estado de ventana

    def _restore_state(self) -> None:
        settings = self._ctx.settings
        self.resize(settings.window_width, settings.window_height)
        if settings.window_maximized:
            self.setWindowState(self.windowState() | Qt.WindowState.WindowMaximized)
        self.show_page(settings.last_page)

    def closeEvent(self, event: QCloseEvent) -> None:
        settings = self._ctx.settings
        settings.window_maximized = self.isMaximized()
        if not self.isMaximized():
            settings.window_width = self.width()
            settings.window_height = self.height()
        self._ctx.save_settings()
        self._unsubscribe()
        super().closeEvent(event)
