"""Ventana principal: navegación lateral y páginas."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QCloseEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from bombastic import APP_NAME, __version__
from bombastic.context import AppContext
from bombastic.core.binaries import Tool
from bombastic.core.chain import ChainRunner
from bombastic.core.edit_manager import EditManager
from bombastic.core.history import HistoryRecorder, HistoryStore, ProfileStore
from bombastic.core.i18n import tr
from bombastic.core.media_prober import MediaProber, tool_launcher
from bombastic.core.recipes import RecipeStore
from bombastic.core.settings import MIN_WINDOW_HEIGHT, MIN_WINDOW_WIDTH, PAGES
from bombastic.core.updater import should_check
from bombastic.ui.downloads_page import DownloadsPage
from bombastic.ui.editor_page import EditorPage
from bombastic.ui.history_page import HistoryPage
from bombastic.ui.library_page import LibraryPage
from bombastic.ui.pages import Page, PlaceholderPage
from bombastic.ui.queue_page import QueuePage
from bombastic.ui.settings_page import SettingsPage
from bombastic.ui.theme import load_icon
from bombastic.ui.updates import DependencyWizard, UpdateBar

#: Fase del plan en la que se implementa cada sección todavía vacía.
_PLACEHOLDER_PHASES: dict[str, int] = {}


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
        self.profiles = ProfileStore(ctx.db)
        self.downloads_page = DownloadsPage(ctx, profiles=self.profiles)
        self.edit_manager = EditManager(
            tool_launcher(ctx.paths, Tool.FFMPEG),
            self,
            db=ctx.db,
            max_concurrent=ctx.settings.max_concurrent_edits,
        )
        self.recipes = RecipeStore(ctx.db)
        self.editor_page = EditorPage(ctx, self.edit_manager, recipes=self.recipes)
        self.library_page = LibraryPage(self.recipes, self.profiles)
        self.library_page.profiles_view.apply_requested.connect(self._apply_profile)
        self.library_page.profiles_view.changed.connect(self.downloads_page.refresh_profiles)
        self.downloads_page.profiles_changed.connect(self.library_page.profiles_view.refresh)
        self.history = HistoryStore(ctx.db)
        self.history_page = HistoryPage(self.history)
        downloads = self.downloads_page.manager
        self.history_recorder = HistoryRecorder(downloads, self.history, self)
        self.history_recorder.recorded.connect(lambda _id: self.history_page.refresh())
        self.history_page.redownload_requested.connect(
            lambda entry: downloads.requeue(entry.url, entry.options)
        )
        self.history_page.edit_requested.connect(self._edit_file)
        self.chain = ChainRunner(
            downloads,
            self.edit_manager,
            MediaProber(tool_launcher(ctx.paths, Tool.FFPROBE), self),
            self.recipes,
            self,
        )
        self.edit_manager.task_completed.connect(self._link_chained_edit)
        self.library_page.recipes_view.open_requested.connect(self._open_recipe)
        self.library_page.recipes_view.changed.connect(self.editor_page.expert_form.refresh_recipes)
        self.queue_page = QueuePage(
            self.downloads_page.manager, self.downloads_page.thumbnails, self.edit_manager
        )
        self.settings_page = SettingsPage(ctx)
        self.settings_page.queue_settings_changed.connect(self._apply_queue_settings)
        ready: dict[str, Page] = {
            "downloads": self.downloads_page,
            "queue": self.queue_page,
            "editor": self.editor_page,
            "library": self.library_page,
            "history": self.history_page,
            "settings": self.settings_page,
        }
        self.pages: dict[str, Page] = {}
        for key in PAGES:
            page = ready[key] if key in ready else PlaceholderPage(key, _PLACEHOLDER_PHASES[key])
            self.pages[key] = page
            self.stack.addWidget(page)
            self.nav.addItem(QListWidgetItem())

        central = QWidget()
        central.setObjectName("Central")
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(sidebar)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        self.update_bar = UpdateBar(self.settings_page.updates)
        content_layout.addWidget(self.update_bar)
        content_layout.addWidget(self.stack, 1)
        layout.addWidget(content, 1)
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
        default = self.profiles.default()
        if default is not None and not ctx.settings.active_profile:
            self.downloads_page.apply_profile(default)
        # Con las páginas ya conectadas, para que la cola guardada aparezca en ellas.
        self.downloads_page.manager.restore()
        self.edit_manager.restore()

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
        busy = self.downloads_page.has_active_downloads() or self.edit_manager.busy
        if busy and not self._confirm_exit():
            event.ignore()
            return
        self.downloads_page.shutdown()
        self.edit_manager.shutdown()
        self.editor_page.shutdown()
        settings = self._ctx.settings
        settings.window_maximized = self.isMaximized()
        if not self.isMaximized():
            settings.window_width = self.width()
            settings.window_height = self.height()
        self._ctx.save_settings()
        self._unsubscribe()
        super().closeEvent(event)

    def startup_checks(self) -> None:
        """Tras mostrar la ventana: dependencias que faltan y comprobación de actualizaciones."""
        if DependencyWizard.missing(self._ctx):
            wizard = DependencyWizard(self._ctx, self.settings_page.updates, self)
            wizard.open()
        settings = self._ctx.settings
        if should_check(settings.last_update_check, settings.update_check_hours):
            self.settings_page.updates.check()

    def _apply_profile(self, profile_id: int) -> None:
        profile = self.profiles.get(profile_id)
        if profile is not None:
            self.downloads_page.apply_profile(profile)
            self.show_page("downloads")

    def _edit_file(self, path: str) -> None:
        self.show_page("editor")
        self.editor_page.open_file(Path(path))

    def _link_chained_edit(self, task_id: int) -> None:
        """Apunta en el historial el resultado de la edición encadenada a una descarga."""
        item_id = self.chain.task_download.get(task_id)
        entry_id = self.history_recorder.entry_for.get(item_id) if item_id else None
        task = self.edit_manager.task(task_id)
        if entry_id is not None and task is not None:
            self.history.set_edit_output(entry_id, task.plan.output)
            self.history_page.refresh()

    def _open_recipe(self, recipe_id: int) -> None:
        self.show_page("editor")
        self.editor_page.open_recipe(recipe_id)

    def _apply_queue_settings(self) -> None:
        self.downloads_page.apply_queue_settings()
        self.edit_manager.max_concurrent = self._ctx.settings.max_concurrent_edits

    def _confirm_exit(self) -> bool:
        """Pregunta antes de cerrar con una descarga a medias."""
        answer = QMessageBox.question(
            self,
            tr("downloads.confirm_exit.title"),
            tr("downloads.confirm_exit.text"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes
