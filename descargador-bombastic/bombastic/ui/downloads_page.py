"""Página de descargas (modo simple): pegar enlaces, elegir formato y descargar."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QKeySequence, QShortcut, QShowEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from bombastic.context import AppContext
from bombastic.core.binaries import Tool, locate
from bombastic.core.download_manager import STAGING, DownloadManager, ItemState
from bombastic.core.i18n import tr
from bombastic.core.thumbnails import ThumbnailLoader
from bombastic.core.urls import extract_urls
from bombastic.core.ytdlp_command import (
    AUDIO_PRESETS,
    MP3_QUALITIES,
    VIDEO_PRESETS,
    DownloadOptions,
    Preset,
)
from bombastic.core.ytdlp_runner import Launcher, default_launcher
from bombastic.ui.download_card import DownloadCard, output_folder
from bombastic.ui.pages import Page

#: Rápido para descargas pequeñas, sin saturar si fallan muchas por la red.
_RETRY_DELAY_MS = 5000


class DownloadsPage(Page):
    def __init__(
        self,
        ctx: AppContext,
        launcher: Launcher | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__("downloads", parent)
        self._ctx = ctx
        self.manager = DownloadManager(launcher or default_launcher(ctx.paths), self, db=ctx.db)
        self.manager.retry_delay_ms = _RETRY_DELAY_MS
        self.apply_queue_settings()
        self.thumbnails = ThumbnailLoader(ctx.paths.thumbnails_dir, self)
        self.cards: dict[int, DownloadCard] = {}
        #: Clave del aviso que se muestra bajo el campo de enlaces (vacía si no hay ninguno).
        self._feedback_key = ""

        # --- Enlaces ---
        self.url_input = QPlainTextEdit()
        self.url_input.setObjectName("UrlInput")
        self.url_input.setFixedHeight(74)
        self.url_input.setTabChangesFocus(True)
        self.add_button = QPushButton()
        self.add_button.setProperty("primary", True)
        input_row = QHBoxLayout()
        input_row.setSpacing(10)
        input_row.addWidget(self.url_input, 1)
        input_row.addWidget(self.add_button, 0, Qt.AlignmentFlag.AlignTop)
        self.feedback_label = QLabel()
        self.feedback_label.setProperty("muted", True)
        self.feedback_label.setVisible(False)

        # --- Opciones ---
        self.options_box = QGroupBox()
        grid = QGridLayout(self.options_box)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)
        self.preset_label = QLabel()
        self.preset_combo = QComboBox()
        self.preset_combo.setObjectName("PresetCombo")
        self.quality_label = QLabel()
        self.quality_combo = QComboBox()
        self.quality_combo.setObjectName("QualityCombo")
        self.subs_check = QCheckBox()
        self.extras_check = QCheckBox()
        self.folder_label = QLabel()
        self.folder_edit = QLineEdit()
        self.folder_edit.setReadOnly(True)
        self.browse_button = QPushButton()
        self.open_folder_button = QPushButton()
        self.preset_label.setBuddy(self.preset_combo)
        self.quality_label.setBuddy(self.quality_combo)

        format_row = QHBoxLayout()
        format_row.setSpacing(10)
        format_row.addWidget(self.preset_combo)
        format_row.addWidget(self.quality_label)
        format_row.addWidget(self.quality_combo)
        format_row.addSpacing(8)
        format_row.addWidget(self.subs_check)
        format_row.addWidget(self.extras_check)
        format_row.addStretch(1)
        folder_row = QHBoxLayout()
        folder_row.setSpacing(10)
        folder_row.addWidget(self.folder_edit, 1)
        folder_row.addWidget(self.browse_button)
        folder_row.addWidget(self.open_folder_button)
        grid.addWidget(self.preset_label, 0, 0)
        grid.addLayout(format_row, 0, 1)
        grid.addWidget(self.folder_label, 1, 0)
        grid.addLayout(folder_row, 1, 1)
        grid.setColumnStretch(1, 1)

        self.warning_label = QLabel()
        self.warning_label.setObjectName("Warning")
        self.warning_label.setWordWrap(True)
        self.warning_label.setVisible(False)

        # --- Lista de enlaces ---
        self.download_all_button = QPushButton()
        self.download_all_button.setProperty("primary", True)
        self.clear_button = QPushButton()
        actions = QHBoxLayout()
        actions.setSpacing(10)
        actions.addStretch(1)
        actions.addWidget(self.clear_button)
        actions.addWidget(self.download_all_button)

        self.empty_label = QLabel()
        self.empty_label.setObjectName("Placeholder")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setWordWrap(True)

        cards_host = QWidget()
        self._cards_layout = QVBoxLayout(cards_host)
        self._cards_layout.setContentsMargins(0, 0, 8, 0)
        self._cards_layout.setSpacing(10)
        self._cards_layout.addWidget(self.empty_label)
        self._cards_layout.addStretch(1)
        self.cards_scroll = QScrollArea()
        self.cards_scroll.setWidgetResizable(True)
        self.cards_scroll.setWidget(cards_host)

        self.body.addLayout(input_row)
        self.body.addWidget(self.feedback_label)
        self.body.addWidget(self.options_box)
        self.body.addWidget(self.warning_label)
        self.body.addLayout(actions)
        self.body.addWidget(self.cards_scroll, 1)

        # --- Conexiones ---
        self.add_button.clicked.connect(self.add_from_input)
        for sequence in ("Ctrl+Return", "Ctrl+Enter"):
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(self.add_from_input)
        self.url_input.textChanged.connect(lambda: self._set_feedback(""))
        self.preset_combo.currentIndexChanged.connect(self._on_options_changed)
        self.quality_combo.currentIndexChanged.connect(self._on_options_changed)
        self.subs_check.toggled.connect(self._on_options_changed)
        self.extras_check.toggled.connect(self._on_options_changed)
        self.browse_button.clicked.connect(self._browse_folder)
        self.open_folder_button.clicked.connect(lambda: self._open_folder(Path(ctx.download_dir())))
        self.download_all_button.clicked.connect(self.download_all)
        self.clear_button.clicked.connect(self.clear_finished)
        self.manager.item_added.connect(self._on_item_added)
        self.manager.item_changed.connect(self._on_item_changed)
        self.manager.item_removed.connect(self._on_item_removed)
        self.thumbnails.loaded.connect(self._on_thumbnail_loaded)

        self.subs_check.setChecked(ctx.settings.embed_subs)
        self.extras_check.setChecked(ctx.settings.embed_extras)
        self.retranslate()
        self._refresh_actions()

    # ------------------------------------------------------------------ textos

    def retranslate(self) -> None:
        super().retranslate()
        settings = self._ctx.settings
        self.url_input.setPlaceholderText(tr("downloads.input.placeholder"))
        self.add_button.setText(tr("downloads.add"))
        self.add_button.setToolTip(tr("downloads.add.tooltip"))
        self._set_feedback(self._feedback_key)

        self.options_box.setTitle(tr("downloads.options"))
        self.preset_label.setText(tr("downloads.format"))
        self.quality_label.setText(tr("downloads.mp3_quality"))
        self._fill_combo(
            self.preset_combo,
            [preset.value for preset in (*VIDEO_PRESETS, *AUDIO_PRESETS)],
            "downloads.preset",
            settings.download_preset,
        )
        self._fill_combo(
            self.quality_combo, list(MP3_QUALITIES), "downloads.mp3_quality", settings.mp3_quality
        )
        self.subs_check.setText(tr("downloads.embed_subs"))
        self.subs_check.setToolTip(tr("downloads.embed_subs.tooltip"))
        self.extras_check.setText(tr("downloads.embed_extras"))
        self.extras_check.setToolTip(tr("downloads.embed_extras.tooltip"))
        self.folder_label.setText(tr("downloads.folder"))
        self._show_folder()
        self.browse_button.setText(tr("settings.browse"))
        self.open_folder_button.setText(tr("downloads.open_folder"))

        self.download_all_button.setText(tr("downloads.download_all"))
        self.clear_button.setText(tr("downloads.clear_finished"))
        self.empty_label.setText(tr("downloads.list.empty"))
        for card in self.cards.values():
            card.retranslate()
        self._sync_option_controls()
        self.refresh_warnings()

    @staticmethod
    def _fill_combo(combo: QComboBox, values: list[str], prefix: str, current: str) -> None:
        """Rellena el desplegable sin disparar ``currentIndexChanged``."""
        combo.blockSignals(True)
        combo.clear()
        for value in values:
            combo.addItem(tr(f"{prefix}.{value}"), value)
        combo.setCurrentIndex(max(0, combo.findData(current)))
        combo.blockSignals(False)

    def _set_feedback(self, key: str) -> None:
        self._feedback_key = key
        self.feedback_label.setText(tr(key) if key else "")
        self.feedback_label.setVisible(bool(key))

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        # La carpeta y los ejecutables pueden haber cambiado desde Ajustes.
        self._show_folder()
        self.refresh_warnings()

    def refresh_warnings(self) -> None:
        """Avisa si faltan yt-dlp o ffmpeg."""
        paths = self._ctx.paths
        if not locate(Tool.YTDLP, paths).found:
            key = "downloads.warning.no_ytdlp"
        elif not locate(Tool.FFMPEG, paths).found:
            key = "downloads.warning.no_ffmpeg"
        else:
            key = ""
        self.warning_label.setText(tr(key) if key else "")
        self.warning_label.setVisible(bool(key))

    # ---------------------------------------------------------------- opciones

    def current_preset(self) -> Preset:
        value = self.preset_combo.currentData()
        try:
            return Preset(value)
        except ValueError:
            return Preset.BEST

    def current_options(self) -> DownloadOptions:
        """Opciones elegidas ahora mismo; se aplican a las descargas que se pidan a continuación."""
        ffmpeg = locate(Tool.FFMPEG, self._ctx.paths)
        quality = self.quality_combo.currentData()
        return DownloadOptions(
            output_dir=Path(self._ctx.download_dir()),
            preset=self.current_preset(),
            mp3_quality=quality if isinstance(quality, str) else MP3_QUALITIES[1],
            embed_subs=self.subs_check.isChecked(),
            embed_extras=self.extras_check.isChecked(),
            ffmpeg_dir=ffmpeg.path.parent if ffmpeg.path is not None else None,
        )

    def _sync_option_controls(self) -> None:
        preset = self.current_preset()
        is_mp3 = preset is Preset.MP3
        self.quality_label.setVisible(is_mp3)
        self.quality_combo.setVisible(is_mp3)
        # Los subtítulos solo tienen sentido con vídeo.
        self.subs_check.setEnabled(preset in VIDEO_PRESETS)

    def _on_options_changed(self) -> None:
        settings = self._ctx.settings
        settings.download_preset = self.current_preset().value
        quality = self.quality_combo.currentData()
        if isinstance(quality, str):
            settings.mp3_quality = quality
        settings.embed_subs = self.subs_check.isChecked()
        settings.embed_extras = self.extras_check.isChecked()
        self._ctx.save_settings()
        self._sync_option_controls()

    def _browse_folder(self) -> None:
        chosen = QFileDialog.getExistingDirectory(
            self, tr("settings.browse.title"), self._ctx.download_dir()
        )
        if chosen:
            self.set_download_dir(chosen)

    def _show_folder(self) -> None:
        self.folder_edit.setText(self._ctx.download_dir())
        # Que se vea el principio de la ruta, no el final.
        self.folder_edit.setCursorPosition(0)

    def set_download_dir(self, folder: str) -> None:
        self._ctx.settings.download_dir = str(Path(folder))
        self._ctx.save_settings()
        self._show_folder()

    @staticmethod
    def _open_folder(folder: Path) -> None:
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError:
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    # ----------------------------------------------------------------- enlaces

    def add_from_input(self) -> None:
        """Añade a la lista los enlaces escritos o pegados en el campo."""
        self.add_text(self.url_input.toPlainText())

    def add_text(self, text: str) -> list[int]:
        urls = extract_urls(text)
        if not urls:
            self._set_feedback("downloads.add.none")
            return []
        created = self.manager.add_urls(urls)
        self.url_input.clear()
        self._set_feedback("" if created else "downloads.add.duplicates")
        return created

    def download_all(self) -> None:
        """Pide la descarga de todo lo que está listo, con las opciones actuales."""
        options = self.current_options()
        for item in self.manager.items():
            if item.state is ItemState.READY:
                self.manager.start(item.item_id, options)

    def clear_finished(self) -> None:
        """Quita los enlaces cuya información no se ha podido obtener."""
        for item in self.manager.items():
            if item.state is ItemState.INFO_ERROR:
                self.manager.remove(item.item_id)

    def apply_queue_settings(self) -> None:
        """Aplica al gestor los ajustes de la cola (simultáneas, reintentos y velocidad)."""
        settings = self._ctx.settings
        self.manager.max_concurrent = settings.max_concurrent
        self.manager.max_retries = settings.auto_retries
        self.manager.rate_limit = settings.rate_limit

    def shutdown(self) -> None:
        self.manager.shutdown()

    def has_active_downloads(self) -> bool:
        return self.manager.busy

    # ---------------------------------------------------------------- tarjetas

    def _on_item_added(self, item_id: int) -> None:
        item = self.manager.item(item_id)
        if item is None or item.state not in STAGING:
            return
        card = DownloadCard(item)
        card.download_requested.connect(self._start)
        card.retry_info_requested.connect(self.manager.retry_info)
        card.cancel_requested.connect(self.manager.cancel)
        card.remove_requested.connect(self.manager.remove)
        card.open_folder_requested.connect(self._open_item_folder)
        self.cards[item_id] = card
        # Antes del hueco elástico del final.
        self._cards_layout.insertWidget(self._cards_layout.count() - 1, card)
        self._refresh_actions()

    def _on_item_changed(self, item_id: int) -> None:
        card = self.cards.get(item_id)
        item = self.manager.item(item_id)
        if card is None or item is None:
            return
        if item.state not in STAGING:
            # Ha pasado a la cola: su tarjeta ya se ve en la página Cola.
            self._on_item_removed(item_id)
            self._set_feedback("downloads.sent_to_queue")
            return
        card.refresh()
        if item.info is not None and item.info.thumbnail_url and not card.has_thumbnail():
            self.thumbnails.request(item.info.thumbnail_url)
        self._refresh_actions()

    def _on_item_removed(self, item_id: int) -> None:
        card = self.cards.pop(item_id, None)
        if card is not None:
            self._cards_layout.removeWidget(card)
            card.deleteLater()
        self._refresh_actions()

    def _on_thumbnail_loaded(self, url: str, path: str) -> None:
        for card in self.cards.values():
            info = card.item.info
            if info is not None and info.thumbnail_url == url and not card.has_thumbnail():
                card.set_thumbnail(path)

    def _start(self, item_id: int) -> None:
        self.manager.start(item_id, self.current_options())

    def _open_item_folder(self, item_id: int) -> None:
        item = self.manager.item(item_id)
        folder = output_folder(item) if item is not None else None
        self._open_folder(folder if folder is not None else Path(self._ctx.download_dir()))

    def _refresh_actions(self) -> None:
        items = [item for item in self.manager.items() if item.state in STAGING]
        self.empty_label.setVisible(not items)
        self.download_all_button.setEnabled(any(i.state is ItemState.READY for i in items))
        self.clear_button.setEnabled(any(i.state is ItemState.INFO_ERROR for i in items))
        self.clear_button.setVisible(bool(items))
        self.download_all_button.setVisible(bool(items))
