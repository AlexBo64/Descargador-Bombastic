"""Página de descargas (modo simple): pegar enlaces, elegir formato y descargar."""

from __future__ import annotations

from dataclasses import replace
from functools import partial
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QGuiApplication, QKeySequence, QShortcut, QShowEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
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
from bombastic.core.chain import CHAIN_KINDS, ChainAction, chain_suggestions
from bombastic.core.download_manager import STAGING, DownloadManager, ItemState
from bombastic.core.history import PROFILE_FIELDS, Profile, ProfileStore
from bombastic.core.i18n import tr
from bombastic.core.paths import resources_dir
from bombastic.core.recipes import RecipeStore
from bombastic.core.thumbnails import ThumbnailLoader
from bombastic.core.urls import extract_urls
from bombastic.core.ytdlp_command import (
    AUDIO_PRESETS,
    MP3_QUALITIES,
    VIDEO_PRESETS,
    DownloadOptions,
    Preset,
    build_download_args,
    cookie_args,
    is_audio,
)
from bombastic.core.ytdlp_options import (
    ExtraArgsError,
    YtdlpOption,
    build_advanced_args,
    find_conflicts,
    load_catalog,
    load_help_translations,
    split_extra_args,
    visible_options,
)
from bombastic.core.ytdlp_runner import Launcher, default_launcher, describe
from bombastic.ui.advanced_dialog import AdvancedDialog
from bombastic.ui.download_card import DownloadCard, output_folder
from bombastic.ui.effects import explode_and_remove, fade_out_and_remove
from bombastic.ui.formats_dialog import FormatsDialog
from bombastic.ui.pages import Page
from bombastic.ui.theme import fade_in

#: Rápido para descargas pequeñas, sin saturar si fallan muchas por la red.
_RETRY_DELAY_MS = 5000
#: Enlace de ejemplo para la vista previa del comando.
_PREVIEW_URL = "https://www.youtube.com/watch?v=…"


class SuggestionComboBox(QComboBox):
    """Desplegable editable con sugerencias; sin sugerencias no abre una lista vacía."""

    def showPopup(self) -> None:
        if self.count():
            super().showPopup()


class DownloadsPage(Page):
    #: Se ha guardado un perfil desde esta página.
    profiles_changed = Signal()

    def __init__(
        self,
        ctx: AppContext,
        launcher: Launcher | None = None,
        profiles: ProfileStore | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__("downloads", parent)
        self._ctx = ctx
        self.manager = DownloadManager(launcher or default_launcher(ctx.paths), self, db=ctx.db)
        self.manager.retry_delay_ms = _RETRY_DELAY_MS
        self.apply_queue_settings()
        self.thumbnails = ThumbnailLoader(ctx.paths.thumbnails_dir, self)
        self.cards: dict[int, DownloadCard] = {}
        #: Formato elegido a mano para cada enlace (``-f``).
        self.format_specs: dict[int, str] = {}
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
        self.advanced_button = QPushButton()
        self.advanced_status = QLabel()
        self.advanced_status.setProperty("muted", True)
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
        advanced_row = QHBoxLayout()
        advanced_row.setSpacing(10)
        advanced_row.addWidget(self.advanced_button)
        advanced_row.addWidget(self.advanced_status, 1)
        grid.addLayout(advanced_row, 2, 1)

        # --- Acción encadenada y perfil ---
        self.profiles = profiles if profiles is not None else ProfileStore(ctx.db)
        self.recipes = RecipeStore(ctx.db)
        self.chain_label = QLabel()
        self.chain_combo = QComboBox()
        self.chain_combo.setObjectName("ChainCombo")
        # Desplegable con los valores típicos de cada acción, en el que también se puede escribir.
        self.chain_value = SuggestionComboBox()
        self.chain_value.setObjectName("ChainValue")
        self.chain_value.setEditable(True)
        self.chain_value.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.chain_value.setMinimumWidth(170)
        self.chain_value.setMaximumWidth(260)
        self.chain_delete = QCheckBox()
        chain_row = QHBoxLayout()
        chain_row.setSpacing(10)
        chain_row.addWidget(self.chain_combo)
        chain_row.addWidget(self.chain_value)
        chain_row.addWidget(self.chain_delete)
        chain_row.addStretch(1)
        grid.addWidget(self.chain_label, 3, 0)
        grid.addLayout(chain_row, 3, 1)
        self.profile_label = QLabel()
        self.profile_combo = QComboBox()
        self.profile_combo.setObjectName("ProfileCombo")
        self.save_profile_button = QPushButton()
        profile_row = QHBoxLayout()
        profile_row.setSpacing(10)
        profile_row.addWidget(self.profile_combo, 1)
        profile_row.addWidget(self.save_profile_button)
        grid.addWidget(self.profile_label, 4, 0)
        grid.addLayout(profile_row, 4, 1)
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
        # Ctrl+V fuera del campo de texto: pegar los enlaces del portapapeles y añadirlos.
        paste = QShortcut(QKeySequence.StandardKey.Paste, self)
        paste.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        paste.activated.connect(self.paste_and_add)
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
        self.advanced_button.clicked.connect(self.open_advanced)
        self.download_all_button.clicked.connect(self.download_all)
        self.clear_button.clicked.connect(self.clear_finished)
        self.manager.item_added.connect(self._on_item_added)
        self.manager.item_changed.connect(self._on_item_changed)
        self.manager.item_removed.connect(self._on_item_removed)
        self.thumbnails.loaded.connect(self._on_thumbnail_loaded)

        self.chain_combo.currentIndexChanged.connect(self._on_chain_kind_changed)
        self.chain_value.activated.connect(lambda _index: self._on_chain_changed())
        line_edit = self.chain_value.lineEdit()
        assert line_edit is not None
        line_edit.editingFinished.connect(self._on_chain_changed)
        self.chain_delete.toggled.connect(self._on_chain_changed)
        self.profile_combo.activated.connect(self._on_profile_chosen)
        self.save_profile_button.clicked.connect(self._ask_profile_name)
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
        self.advanced_button.setText(tr("downloads.advanced"))
        self._show_advanced_status()
        self.chain_label.setText(tr("downloads.chain"))
        self.chain_delete.setText(tr("downloads.chain.delete_original"))
        self.profile_label.setText(tr("downloads.profile"))
        self.save_profile_button.setText(tr("downloads.profile.save"))
        self.refresh_profiles()
        self._show_chain()

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
        extra_args, _valid = self.extra_args()
        return DownloadOptions(
            output_dir=Path(self._ctx.download_dir()),
            preset=self.current_preset(),
            mp3_quality=quality if isinstance(quality, str) else MP3_QUALITIES[1],
            embed_subs=self.subs_check.isChecked(),
            embed_extras=self.extras_check.isChecked(),
            ffmpeg_dir=ffmpeg.path.parent if ffmpeg.path is not None else None,
            extra_args=tuple(extra_args),
            chain=self._ctx.settings.chain_action,
            profile=self._ctx.settings.active_profile,
        )

    # ------------------------------------------------------------ modo avanzado

    def catalog(self) -> list[YtdlpOption]:
        """Opciones de yt-dlp (se relee cada vez: puede haberse regenerado)."""
        _version, options = load_catalog(self._ctx.paths.data_dir, resources_dir())
        return visible_options(options)

    def extra_args(self) -> tuple[list[str], bool]:
        """Cookies + modo avanzado + argumentos libres. ``False`` si los libres no son válidos."""
        settings = self._ctx.settings
        args = cookie_args(
            settings.cookies_mode,
            settings.cookies_browser,
            settings.cookies_profile,
            settings.cookies_file,
        )
        if settings.advanced_options:
            args += build_advanced_args(self.catalog(), settings.advanced_options)
        if settings.use_download_archive:
            # Lo gestiona la app: un archivo por usuario en la carpeta de datos.
            args += ["--download-archive", str(self._ctx.paths.data_dir / "download-archive.txt")]
        try:
            args += split_extra_args(settings.extra_args)
        except ExtraArgsError:
            return args, False
        return args, True

    # ------------------------------------------------------ encadenado y perfiles

    def _show_chain(self) -> None:
        action = ChainAction.from_json(self._ctx.settings.chain_action)
        self.chain_combo.blockSignals(True)
        self.chain_combo.clear()
        for kind in CHAIN_KINDS:
            self.chain_combo.addItem(tr(f"downloads.chain.{kind}"), kind)
        self.chain_combo.setCurrentIndex(max(0, self.chain_combo.findData(action.kind)))
        self.chain_combo.blockSignals(False)
        self.chain_delete.blockSignals(True)
        self.chain_delete.setChecked(action.delete_original)
        self.chain_delete.blockSignals(False)
        self._sync_chain_controls(action.value)

    def _sync_chain_controls(self, value: str) -> None:
        """Rellena el desplegable de valor con las opciones de la acción y pone ``value``."""
        kind = str(self.chain_combo.currentData() or "none")
        active = kind != "none"
        self.chain_value.setVisible(active)
        self.chain_delete.setVisible(active)
        self.chain_value.blockSignals(True)
        self.chain_value.clear()
        options = chain_suggestions(kind, self.recipes)
        self.chain_value.addItems(options)
        self.chain_value.setEditText(value)
        # Sin opciones (recortar, o no hay recetas) no hay flecha: es solo una caja de texto.
        if self.chain_value.property("noOptions") != (not options):
            self.chain_value.setProperty("noOptions", not options)
            style = self.chain_value.style()
            style.unpolish(self.chain_value)
            style.polish(self.chain_value)
        line_edit = self.chain_value.lineEdit()
        if line_edit is not None:
            placeholder = tr(f"downloads.chain.{kind}.placeholder") if active else ""
            line_edit.setPlaceholderText(placeholder)
        self.chain_value.blockSignals(False)

    def chain_has_options(self) -> bool:
        return self.chain_value.count() > 0

    def _on_chain_kind_changed(self) -> None:
        """Al cambiar de acción se propone su primer valor típico."""
        kind = str(self.chain_combo.currentData() or "none")
        options = chain_suggestions(kind, self.recipes)
        self._sync_chain_controls(options[0] if options else "")
        self._on_chain_changed()

    def _on_chain_changed(self) -> None:
        kind = str(self.chain_combo.currentData() or "none")
        value = self.chain_value.currentText().strip()
        action = ChainAction(kind, value, self.chain_delete.isChecked())
        self._ctx.settings.chain_action = action.to_json()
        self._ctx.save_settings()

    def refresh_profiles(self) -> None:
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        self.profile_combo.addItem(tr("downloads.profile.none"), "")
        for profile in self.profiles.all():
            star = " ★" if profile.is_default else ""
            self.profile_combo.addItem(profile.name + star, profile.name)
        index = self.profile_combo.findData(self._ctx.settings.active_profile)
        self.profile_combo.setCurrentIndex(max(0, index))
        self.profile_combo.blockSignals(False)

    def _on_profile_chosen(self, index: int) -> None:
        name = str(self.profile_combo.itemData(index) or "")
        profile = self.profiles.by_name(name) if name else None
        if profile is None:
            self._ctx.settings.active_profile = ""
            self._ctx.save_settings()
            return
        self.apply_profile(profile)

    def apply_profile(self, profile: Profile) -> None:
        """Copia las opciones del perfil a los ajustes y a los controles de la página."""
        settings = self._ctx.settings
        for key, value in profile.values.items():
            if key in PROFILE_FIELDS and type(value) is type(getattr(settings, key)):
                setattr(settings, key, value)
        settings.active_profile = profile.name
        settings.sanitize()
        self._ctx.save_settings()
        self.subs_check.blockSignals(True)
        self.extras_check.blockSignals(True)
        self.subs_check.setChecked(settings.embed_subs)
        self.extras_check.setChecked(settings.embed_extras)
        self.subs_check.blockSignals(False)
        self.extras_check.blockSignals(False)
        self.retranslate()
        self._set_feedback("")
        self.feedback_label.setText(tr("downloads.profile.applied", name=profile.name))
        self.feedback_label.setVisible(True)

    def save_profile(self, name: str) -> Profile:
        """Guarda las opciones actuales como perfil (o actualiza el que tiene ese nombre)."""
        settings = self._ctx.settings
        values = {key: getattr(settings, key) for key in PROFILE_FIELDS}
        existing = self.profiles.by_name(name)
        profile = Profile(name, values)
        if existing is not None:
            profile.profile_id, profile.is_default = existing.profile_id, existing.is_default
        self.profiles.save(profile)
        settings.active_profile = profile.name
        self._ctx.save_settings()
        self.refresh_profiles()
        self.profiles_changed.emit()
        return profile

    def _ask_profile_name(self) -> None:
        name, ok = QInputDialog.getText(
            self,
            tr("downloads.profile.save"),
            tr("expert.save.name"),
            text=self._ctx.settings.active_profile,
        )
        if ok and name.strip():
            self.save_profile(name.strip())

    def command_preview(self) -> tuple[str, list[str]]:
        """Comando final de ejemplo y conflictos detectados, para el diálogo avanzado."""
        options = self.current_options()
        command = describe(("yt-dlp", build_download_args(_PREVIEW_URL, options)))
        conflicts = find_conflicts(
            list(options.extra_args),
            is_audio(options.preset),
            locate(Tool.FFMPEG, self._ctx.paths).found,
        )
        return command, conflicts

    def open_advanced(self) -> AdvancedDialog:
        dialog = AdvancedDialog(
            self._ctx,
            self.catalog(),
            self.command_preview,
            load_help_translations(resources_dir()),
            parent=self,
        )
        dialog.finished.connect(lambda _result: self._show_advanced_status())
        dialog.open()
        return dialog

    def _show_advanced_status(self) -> None:
        settings = self._ctx.settings
        count = len(settings.advanced_options) + bool(settings.extra_args)
        parts: list[str] = []
        if count:
            parts.append(tr("downloads.advanced.active", count=count))
        if settings.cookies_mode != "off":
            parts.append(tr("downloads.advanced.cookies"))
        self.advanced_status.setText(" · ".join(parts))

    def choose_format(self, item_id: int) -> FormatsDialog | None:
        item = self.manager.item(item_id)
        if item is None or item.info is None or not item.info.formats:
            return None
        dialog = FormatsDialog(item.info.formats, parent=self)

        def accepted() -> None:
            self.format_specs[item_id] = dialog.spec()
            self._set_feedback("")
            self.feedback_label.setText(tr("downloads.format_chosen", spec=dialog.spec()))
            self.feedback_label.setVisible(True)

        dialog.accepted.connect(accepted)
        dialog.open()
        return dialog

    def _options_for(self, item_id: int, options: DownloadOptions) -> DownloadOptions:
        return replace(options, format_spec=self.format_specs.pop(item_id, ""))

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

    def paste_and_add(self) -> list[int]:
        """Añade los enlaces del portapapeles (``Ctrl+V`` con el foco fuera del campo)."""
        if self.url_input.hasFocus():
            self.url_input.paste()
            return []
        return self.add_text(QGuiApplication.clipboard().text())

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
                self.manager.start(item.item_id, self._options_for(item.item_id, options))

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
        card.formats_requested.connect(self.choose_format)
        self.cards[item_id] = card
        # Antes del hueco elástico del final.
        self._cards_layout.insertWidget(self._cards_layout.count() - 1, card)
        if card.isVisible():
            fade_in(card)
        self._refresh_actions()

    def _on_item_changed(self, item_id: int) -> None:
        card = self.cards.get(item_id)
        item = self.manager.item(item_id)
        if card is None or item is None:
            return
        if item.state not in STAGING:
            # Ha pasado a la cola: su tarjeta ya se ve en la página Cola.
            self._on_item_removed(item_id, moved=True)
            self._set_feedback("downloads.sent_to_queue")
            return
        card.refresh()
        if item.info is not None and item.info.thumbnail_url and not card.has_thumbnail():
            self.thumbnails.request(item.info.thumbnail_url)
        self._refresh_actions()

    def _on_item_removed(self, item_id: int, moved: bool = False) -> None:
        """Quita la tarjeta: explotando si se borra, plegándose si pasa a la Cola."""
        card = self.cards.pop(item_id, None)
        if card is not None:
            remove = fade_out_and_remove if moved else explode_and_remove
            remove(card, partial(self._discard, card))
        self._refresh_actions()

    def _discard(self, card: DownloadCard) -> None:
        self._cards_layout.removeWidget(card)
        card.deleteLater()

    def _on_thumbnail_loaded(self, url: str, path: str) -> None:
        for card in self.cards.values():
            info = card.item.info
            if info is not None and info.thumbnail_url == url and not card.has_thumbnail():
                card.set_thumbnail(path)

    def _start(self, item_id: int) -> None:
        self.manager.start(item_id, self._options_for(item_id, self.current_options()))

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
