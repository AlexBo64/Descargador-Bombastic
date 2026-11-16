"""Ventana principal: navegación lateral y páginas."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, QUrl
from PySide6.QtGui import (
    QCloseEvent,
    QDesktopServices,
    QDragEnterEvent,
    QDropEvent,
    QKeySequence,
    QShortcut,
)
from PySide6.QtWidgets import (
    QApplication,
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
from bombastic.core.chain import ChainAction, ChainRunner
from bombastic.core.cli import AppCommand, parse_command
from bombastic.core.download_manager import ItemState
from bombastic.core.edit_manager import EditManager, EditState
from bombastic.core.history import HistoryRecorder, HistoryStore, ProfileStore
from bombastic.core.i18n import tr
from bombastic.core.media_prober import MediaProber, tool_launcher
from bombastic.core.recipes import RecipeStore
from bombastic.core.settings import MIN_WINDOW_HEIGHT, MIN_WINDOW_WIDTH, PAGES
from bombastic.core.updater import should_check
from bombastic.platform_win.context_menu import MEDIA_EXTENSIONS
from bombastic.platform_win.tray import Tray
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

        # --- Integración con Windows ---
        self.setAcceptDrops(True)
        self._quitting = False
        self._tray_hint_shown = False
        self._edit_states: dict[int, EditState] = {}
        self.app_icon = load_icon("app", ctx.theme.palette["accent"], 64)
        self.setWindowIcon(self.app_icon)
        self.tray: Tray | None = None
        if Tray.available():
            self.tray = Tray(self.app_icon, self)
            self.tray.show_requested.connect(self.bring_to_front)
            self.tray.pause_all_requested.connect(self._pause_all)
            self.tray.resume_all_requested.connect(self._resume_all)
            self.tray.open_folder_requested.connect(
                lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(ctx.download_dir()))
            )
            self.tray.quit_requested.connect(self.quit_app)
            self.tray.show()
        self.history_recorder.recorded.connect(self._notify_download)
        self.edit_manager.task_changed.connect(self._on_edit_changed)
        downloads.item_changed.connect(lambda _id: self._refresh_tray_progress())

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
        if getattr(self, "tray", None) is not None:
            self.tray.retranslate()  # type: ignore[union-attr]

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
        if self._ctx.settings.minimize_to_tray and self.tray is not None and not self._quitting:
            # Al cerrar, a la bandeja: las colas siguen.
            event.ignore()
            self.hide()
            if not self._tray_hint_shown:
                self._tray_hint_shown = True
                self.tray.notify(tr("app.name"), tr("tray.still_running"))
            return
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
        if self.tray is not None:
            self.tray.icon.hide()
        super().closeEvent(event)

    # ---------------------------------------------------- integración con Windows

    def quit_app(self) -> None:
        self._quitting = True
        if self.close():
            QApplication.quit()
        else:
            self._quitting = False

    def bring_to_front(self) -> None:
        if self.isMinimized() or not self.isVisible():
            self.showNormal()
        self.raise_()
        self.activateWindow()

    def _pause_all(self) -> None:
        self.downloads_page.manager.pause_all()
        for task in self.edit_manager.tasks():
            self.edit_manager.pause(task.task_id)

    def _resume_all(self) -> None:
        self.downloads_page.manager.resume_all()
        for task in self.edit_manager.tasks():
            if task.state is EditState.PAUSED:
                self.edit_manager.resume(task.task_id)

    def handle_args(self, args: list[str]) -> None:
        """Argumentos de la línea de comandos o de otra instancia."""
        self.bring_to_front()
        self.handle_command(parse_command(args))

    def handle_command(self, command: AppCommand) -> None:
        if command.download:
            self.show_page("downloads")
            self.downloads_page.add_text("\n".join(command.download))
        if command.edit:
            self._open_in_editor(command.edit)
        if command.action and command.action_files:
            self.run_action(command.action, command.action_files)

    def run_action(self, action: str, files: list[Path]) -> None:
        """Acciones del menú contextual: a la cola de edición, o al editor si piden datos."""
        mapping = {
            "convert_mp4": ChainAction("convert", "mp4"),
            "extract_mp3": ChainAction("extract_audio", "mp3"),
        }
        if action == "compress":
            self._open_in_editor(files[:1])
            self.editor_page.tools.setCurrentIndex(4)
            return
        chain = mapping.get(action)
        if chain is None and action.startswith("recipe:"):
            chain = ChainAction("recipe", action.removeprefix("recipe:"))
        if chain is None:
            return
        self.chain.queue_files(chain, files)
        self.show_page("queue")
        self.queue_page.tabs.setCurrentIndex(1)

    def _open_in_editor(self, files: list[Path]) -> None:
        existing = [f for f in files if f.is_file()]
        if not existing:
            return
        self.show_page("editor")
        self.editor_page.open_file(existing[0])
        for extra in existing[1:]:
            self.editor_page.concat_form.add_path(extra)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        mime = event.mimeData()
        if mime.hasUrls() or mime.hasText():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        """Enlaces y listas .txt a Descargas; archivos de vídeo o audio al Editor."""
        mime = event.mimeData()
        links: list[str] = []
        media: list[Path] = []
        for url in mime.urls():
            if url.isLocalFile():
                path = Path(url.toLocalFile())
                if path.suffix.lower() == ".txt":
                    try:
                        links.append(path.read_text(encoding="utf-8", errors="replace"))
                    except OSError:
                        continue
                elif path.suffix.lower() in MEDIA_EXTENSIONS:
                    media.append(path)
            elif url.scheme() in ("http", "https"):
                links.append(url.toString())
        if not mime.urls() and mime.hasText():
            links.append(mime.text())
        if links:
            self.show_page("downloads")
            self.downloads_page.add_text("\n".join(links))
        if media:
            self._open_in_editor(media)
        event.acceptProposedAction()

    def _notify(self, title: str, message: str, path: Path | None = None) -> None:
        if self.tray is None or not self._ctx.settings.notifications:
            return

        def open_result() -> None:
            if path is not None and path.exists():
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
            else:
                self.bring_to_front()

        self.tray.notify(title, message, open_result)

    def _notify_download(self, entry_id: int) -> None:
        entry = self.history.get(entry_id)
        if entry is None:
            return
        if entry.result == "completed":
            self._notify(
                tr("notify.download_done"), entry.title, entry.files[0] if entry.files else None
            )
        else:
            self._notify(tr("notify.download_failed"), entry.title)

    def _on_edit_changed(self, task_id: int) -> None:
        task = self.edit_manager.task(task_id)
        if task is None:
            return
        previous = self._edit_states.get(task_id)
        self._edit_states[task_id] = task.state
        if task.state != previous and task.state is EditState.COMPLETED:
            self._notify(tr("notify.edit_done"), task.plan.output.name, task.plan.output)
        elif task.state != previous and task.state is EditState.FAILED:
            self._notify(tr("notify.edit_failed"), task.title)
        self._refresh_tray_progress()

    def _refresh_tray_progress(self) -> None:
        if self.tray is None:
            return
        items = self.downloads_page.manager.queue_items()
        active = [i for i in items if i.state in (ItemState.DOWNLOADING, ItemState.PROCESSING)]
        fractions = [i.snapshot.fraction for i in active if i.snapshot and i.snapshot.fraction]
        edits = sum(t.state is EditState.RUNNING for t in self.edit_manager.tasks())
        parts: list[str] = []
        if active:
            mean = round(sum(fractions) / len(fractions) * 100) if fractions else 0
            parts.append(tr("tray.progress.downloads", count=len(active), percent=mean))
        if edits:
            parts.append(tr("tray.progress.edits", count=edits))
        self.tray.set_progress(" · ".join(parts))

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
