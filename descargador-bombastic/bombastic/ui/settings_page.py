"""Página de ajustes: idioma, tema, carpeta de descargas, dependencias y registros."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QShowEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from bombastic.context import AppContext
from bombastic.core.binaries import BinaryStatus, Tool, locate_all
from bombastic.core.binary_probe import BinaryProbe
from bombastic.core.hwaccel import HwProbe
from bombastic.core.i18n import tr
from bombastic.core.media_prober import tool_launcher
from bombastic.core.settings import LANGUAGES, THEMES, is_valid_rate
from bombastic.core.ytdlp_runner import CatalogRefresher, default_launcher
from bombastic.ui.pages import Page
from bombastic.ui.updates import Updates, UpdatesBox


class SettingsPage(Page):
    #: Han cambiado las descargas simultáneas, los reintentos o el límite de velocidad.
    queue_settings_changed = Signal()

    def __init__(
        self, ctx: AppContext, updates: Updates | None = None, parent: QWidget | None = None
    ) -> None:
        super().__init__("settings", parent)
        self.updates = updates if updates is not None else Updates(ctx, parent=self)
        self._ctx = ctx
        self._probe: BinaryProbe | None = None
        self._statuses: dict[Tool, BinaryStatus] | None = None

        content = QWidget()
        column = QVBoxLayout(content)
        column.setContentsMargins(0, 0, 8, 0)
        column.setSpacing(6)

        # --- Apariencia ---
        self.appearance_box = QGroupBox()
        form = QFormLayout(self.appearance_box)
        self.language_label = QLabel()
        self.language_combo = QComboBox()
        self.language_combo.setObjectName("LanguageCombo")
        self.theme_label = QLabel()
        self.theme_combo = QComboBox()
        self.theme_combo.setObjectName("ThemeCombo")
        self.language_label.setBuddy(self.language_combo)
        self.theme_label.setBuddy(self.theme_combo)
        form.addRow(self.language_label, self.language_combo)
        form.addRow(self.theme_label, self.theme_combo)
        column.addWidget(self.appearance_box)

        # --- Descargas ---
        self.downloads_box = QGroupBox()
        form = QFormLayout(self.downloads_box)
        self.download_dir_label = QLabel()
        self.download_dir_edit = QLineEdit()
        self.download_dir_edit.setReadOnly(True)
        self.browse_button = QPushButton()
        row = QHBoxLayout()
        row.addWidget(self.download_dir_edit, 1)
        row.addWidget(self.browse_button)
        form.addRow(self.download_dir_label, row)
        settings = ctx.settings
        self.concurrent_label = QLabel()
        self.concurrent_spin = QSpinBox()
        self.concurrent_spin.setRange(1, 8)
        self.concurrent_spin.setValue(settings.max_concurrent)
        self.retries_label = QLabel()
        self.retries_spin = QSpinBox()
        self.retries_spin.setRange(0, 10)
        self.retries_spin.setValue(settings.auto_retries)
        self.edits_label = QLabel()
        self.edits_spin = QSpinBox()
        self.edits_spin.setRange(1, 4)
        self.edits_spin.setValue(settings.max_concurrent_edits)
        self.rate_label = QLabel()
        self.rate_edit = QLineEdit(settings.rate_limit)
        self.rate_edit.setMaxLength(12)
        for label, widget in (
            (self.concurrent_label, self.concurrent_spin),
            (self.retries_label, self.retries_spin),
            (self.rate_label, self.rate_edit),
            (self.edits_label, self.edits_spin),
        ):
            label.setBuddy(widget)
            form.addRow(label, widget)
        self.archive_check = QCheckBox()
        self.archive_check.setChecked(settings.use_download_archive)
        form.addRow(self.archive_check)
        column.addWidget(self.downloads_box)

        # --- Editor: aceleración por hardware ---
        self.editor_box = QGroupBox()
        editor_form = QFormLayout(self.editor_box)
        self.hw_label = QLabel()
        self.hw_combo = QComboBox()
        self.hw_combo.setObjectName("HwCombo")
        self.hw_detect_button = QPushButton()
        self.hw_status = QLabel()
        self.hw_status.setProperty("muted", True)
        self.hw_status.setWordWrap(True)
        hw_row = QHBoxLayout()
        hw_row.addWidget(self.hw_combo, 1)
        hw_row.addWidget(self.hw_detect_button)
        editor_form.addRow(self.hw_label, hw_row)
        editor_form.addRow(self.hw_status)
        column.addWidget(self.editor_box)

        # --- Actualizaciones ---
        self.updates_box = QGroupBox()
        updates_layout = QVBoxLayout(self.updates_box)
        self.updates_panel = UpdatesBox(ctx, self.updates)
        updates_layout.addWidget(self.updates_panel)

        # --- Dependencias ---
        self.dependencies_box = QGroupBox()
        deps = QVBoxLayout(self.dependencies_box)
        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setColumnStretch(2, 1)
        self._tool_status: dict[Tool, QLabel] = {}
        self._tool_path: dict[Tool, QLabel] = {}
        for index, tool in enumerate(Tool):
            name = QLabel(tool.value)
            status = QLabel()
            status.setObjectName(f"Status_{tool.name}")
            path = QLabel()
            path.setProperty("muted", True)
            path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            grid.addWidget(name, index, 0)
            grid.addWidget(status, index, 1)
            grid.addWidget(path, index, 2)
            self._tool_status[tool] = status
            self._tool_path[tool] = path
        deps.addLayout(grid)
        self.dependencies_hint = QLabel()
        self.dependencies_hint.setProperty("muted", True)
        self.dependencies_hint.setWordWrap(True)
        deps.addWidget(self.dependencies_hint)
        self.recheck_button = QPushButton()
        self.open_bin_button = QPushButton()
        self.catalog_button = QPushButton()
        self.catalog_status = QLabel()
        self.catalog_status.setProperty("muted", True)
        row = QHBoxLayout()
        row.addWidget(self.recheck_button)
        row.addWidget(self.open_bin_button)
        row.addWidget(self.catalog_button)
        row.addWidget(self.catalog_status)
        row.addStretch(1)
        deps.addLayout(row)
        column.addWidget(self.dependencies_box)
        column.addWidget(self.updates_box)

        # --- Datos y registros ---
        self.data_box = QGroupBox()
        data = QVBoxLayout(self.data_box)
        self.data_location_label = QLabel()
        self.data_location_label.setWordWrap(True)
        self.data_location_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.portable_label = QLabel()
        self.portable_label.setProperty("muted", True)
        self.portable_label.setVisible(ctx.paths.portable)
        self.open_logs_button = QPushButton()
        row = QHBoxLayout()
        row.addWidget(self.open_logs_button)
        row.addStretch(1)
        data.addWidget(self.data_location_label)
        data.addWidget(self.portable_label)
        data.addLayout(row)
        column.addWidget(self.data_box)

        # --- Atajos ---
        self.shortcuts_box = QGroupBox()
        shortcuts = QVBoxLayout(self.shortcuts_box)
        self.shortcuts_label = QLabel()
        shortcuts.addWidget(self.shortcuts_label)
        column.addWidget(self.shortcuts_box)
        column.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)
        self.body.addWidget(scroll)

        self.language_combo.currentIndexChanged.connect(self._on_language_changed)
        self.theme_combo.currentIndexChanged.connect(self._on_theme_changed)
        self.browse_button.clicked.connect(self._browse_download_dir)
        self.concurrent_spin.valueChanged.connect(self._on_queue_settings_changed)
        self.retries_spin.valueChanged.connect(self._on_queue_settings_changed)
        self.edits_spin.valueChanged.connect(self._on_queue_settings_changed)
        self.archive_check.toggled.connect(self._on_archive_toggled)
        self.rate_edit.editingFinished.connect(self._on_queue_settings_changed)
        self.recheck_button.clicked.connect(self.refresh_dependencies)
        self.catalog_button.clicked.connect(self.refresh_catalog)
        self.hw_detect_button.clicked.connect(self.detect_hw)
        self.hw_combo.currentIndexChanged.connect(self._on_hw_changed)
        self.open_bin_button.clicked.connect(lambda: self._open_folder(ctx.paths.bin_dir))
        self.open_logs_button.clicked.connect(lambda: self._open_folder(ctx.paths.logs_dir))

        self.retranslate()

    # ------------------------------------------------------------------ textos

    def retranslate(self) -> None:
        super().retranslate()
        settings = self._ctx.settings
        self.appearance_box.setTitle(tr("settings.appearance"))
        self.language_label.setText(tr("settings.language"))
        self.theme_label.setText(tr("settings.theme"))
        self._fill_combo(self.language_combo, LANGUAGES, "settings.language", settings.language)
        self._fill_combo(self.theme_combo, THEMES, "settings.theme", settings.theme)

        self.downloads_box.setTitle(tr("settings.downloads"))
        self.download_dir_label.setText(tr("settings.download_dir"))
        self.browse_button.setText(tr("settings.browse"))
        self.download_dir_edit.setText(self.download_dir())
        self.concurrent_label.setText(tr("settings.max_concurrent"))
        self.retries_label.setText(tr("settings.auto_retries"))
        self.retries_spin.setToolTip(tr("settings.auto_retries.tooltip"))
        self.rate_label.setText(tr("settings.rate_limit"))
        self.edits_label.setText(tr("settings.max_concurrent_edits"))
        self.archive_check.setText(tr("settings.download_archive"))
        self.archive_check.setToolTip(tr("settings.download_archive.tooltip"))
        self.rate_edit.setPlaceholderText(tr("settings.rate_limit.placeholder"))
        self.rate_edit.setToolTip(tr("settings.rate_limit.tooltip"))

        self.editor_box.setTitle(tr("settings.editor"))
        self.hw_label.setText(tr("settings.hw"))
        self.hw_detect_button.setText(tr("settings.hw.detect"))
        self._fill_hw()
        if not self.hw_status.text():
            self.hw_status.setText(tr("settings.hw.hint"))

        self.updates_box.setTitle(tr("settings.updates"))
        self.updates_panel.retranslate()
        self.dependencies_box.setTitle(tr("settings.dependencies"))
        self.dependencies_hint.setText(tr("settings.dependencies.hint"))
        self.recheck_button.setText(tr("settings.dependencies.recheck"))
        self.open_bin_button.setText(tr("settings.dependencies.open_bin"))
        self.catalog_button.setText(tr("settings.catalog.refresh"))
        self.catalog_button.setToolTip(tr("settings.catalog.refresh.tooltip"))
        self._render_statuses()

        self.data_box.setTitle(tr("settings.data"))
        self.data_location_label.setText(
            f"{tr('settings.data.location')}: {self._ctx.paths.data_dir}"
        )
        self.portable_label.setText(tr("settings.data.portable"))
        self.open_logs_button.setText(tr("settings.data.open_logs"))

        self.shortcuts_box.setTitle(tr("settings.shortcuts"))
        self.shortcuts_label.setText(
            "\n".join((tr("settings.shortcuts.navigation"), tr("settings.shortcuts.downloads")))
        )

    @staticmethod
    def _fill_combo(combo: QComboBox, values: tuple[str, ...], prefix: str, current: str) -> None:
        """Rellena el desplegable sin disparar ``currentIndexChanged``."""
        combo.blockSignals(True)
        combo.clear()
        for value in values:
            combo.addItem(tr(f"{prefix}.{value}"), value)
        combo.setCurrentIndex(max(0, combo.findData(current)))
        combo.blockSignals(False)

    # ------------------------------------------------------------- preferencias

    def download_dir(self) -> str:
        return self._ctx.download_dir()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        # La carpeta también se puede cambiar desde la página de descargas.
        self.download_dir_edit.setText(self.download_dir())

    def _on_language_changed(self, index: int) -> None:
        language = self.language_combo.itemData(index)
        if not isinstance(language, str) or language == self._ctx.settings.language:
            return
        self._ctx.settings.language = language
        self._ctx.save_settings()
        # El traductor avisa a la ventana principal, que retraduce todas las páginas.
        self._ctx.translator.set_language(language)

    def _on_theme_changed(self, index: int) -> None:
        theme = self.theme_combo.itemData(index)
        if not isinstance(theme, str) or theme == self._ctx.settings.theme:
            return
        self._ctx.settings.theme = theme
        self._ctx.save_settings()
        self._ctx.theme.apply(theme)

    def _on_queue_settings_changed(self) -> None:
        settings = self._ctx.settings
        rate = self.rate_edit.text().strip().upper()
        if not is_valid_rate(rate):
            # Se vuelve al último valor válido en lugar de guardar algo que yt-dlp rechazaría.
            self.rate_edit.setText(settings.rate_limit)
            rate = settings.rate_limit
        settings.max_concurrent = self.concurrent_spin.value()
        settings.auto_retries = self.retries_spin.value()
        settings.max_concurrent_edits = self.edits_spin.value()
        settings.rate_limit = rate
        self._ctx.save_settings()
        self.queue_settings_changed.emit()

    def _on_archive_toggled(self, checked: bool) -> None:
        self._ctx.settings.use_download_archive = checked
        self._ctx.save_settings()

    def _browse_download_dir(self) -> None:
        chosen = QFileDialog.getExistingDirectory(
            self, tr("settings.browse.title"), self.download_dir()
        )
        if chosen:
            self.set_download_dir(chosen)

    def set_download_dir(self, folder: str) -> None:
        self._ctx.settings.download_dir = str(Path(folder))
        self._ctx.save_settings()
        self.download_dir_edit.setText(self.download_dir())

    @staticmethod
    def _open_folder(folder: Path) -> None:
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    # ------------------------------------------------------------------- hardware

    def _fill_hw(self) -> None:
        settings = self._ctx.settings
        self.hw_combo.blockSignals(True)
        self.hw_combo.clear()
        self.hw_combo.addItem(tr("settings.hw.off"), "")
        for hw in settings.hw_available:
            self.hw_combo.addItem(tr(f"settings.hw.{hw}"), hw)
        self.hw_combo.setCurrentIndex(max(0, self.hw_combo.findData(settings.hw_encoder)))
        self.hw_combo.blockSignals(False)

    def _on_hw_changed(self) -> None:
        self._ctx.settings.hw_encoder = str(self.hw_combo.currentData() or "")
        self._ctx.save_settings()

    def detect_hw(self) -> HwProbe:
        """Busca la aceleración por hardware disponible sin bloquear la interfaz."""
        self.hw_detect_button.setEnabled(False)
        self.hw_status.setText(tr("settings.hw.detecting"))
        probe = HwProbe(tool_launcher(self._ctx.paths, Tool.FFMPEG), parent=self)

        def done(working: list[str]) -> None:
            settings = self._ctx.settings
            settings.hw_available = working
            if settings.hw_encoder not in working:
                settings.hw_encoder = ""
            self._ctx.save_settings()
            self._fill_hw()
            self.hw_detect_button.setEnabled(True)
            names = ", ".join(tr(f"settings.hw.{hw}") for hw in working)
            self.hw_status.setText(
                tr("settings.hw.found", names=names) if working else tr("settings.hw.none")
            )
            probe.deleteLater()

        probe.finished.connect(done)
        probe.start()
        return probe

    # -------------------------------------------------------------- dependencias

    def refresh_catalog(self) -> None:
        """Regenera la lista de opciones del modo avanzado con el yt-dlp instalado."""
        self.catalog_button.setEnabled(False)
        self.catalog_status.setText(tr("settings.catalog.working"))
        refresher = CatalogRefresher(
            default_launcher(self._ctx.paths), self._ctx.paths.data_dir, parent=self
        )

        def done(ok: bool) -> None:
            self.catalog_button.setEnabled(True)
            self.catalog_status.setText(
                tr("settings.catalog.done" if ok else "settings.catalog.failed")
            )
            refresher.deleteLater()

        refresher.finished.connect(done)
        refresher.start()

    def refresh_dependencies(self) -> None:
        """Busca los ejecutables y pregunta su versión sin bloquear la interfaz."""
        if self._probe is not None and self._probe.running:
            return
        self._statuses = None
        self._render_statuses()
        self.recheck_button.setEnabled(False)
        self._probe = BinaryProbe(locate_all(self._ctx.paths), parent=self)
        self._probe.finished.connect(self.show_statuses)
        self._probe.start()

    def show_statuses(self, statuses: Mapping[Tool, BinaryStatus]) -> None:
        self._statuses = dict(statuses)
        self.recheck_button.setEnabled(True)
        self._render_statuses()

    def _render_statuses(self) -> None:
        for tool in Tool:
            status = self._statuses.get(tool) if self._statuses is not None else None
            path = ""
            if status is None:
                text = tr("settings.dependencies.checking") if self._probe else "—"
            elif not status.location.found:
                text = tr("settings.dependencies.missing")
            elif status.version is None:
                text = tr("settings.dependencies.broken")
                path = str(status.location.path)
            else:
                text = tr("settings.dependencies.version", version=status.version)
                path = str(status.location.path)
            self._tool_status[tool].setText(text)
            self._tool_path[tool].setText(path)
