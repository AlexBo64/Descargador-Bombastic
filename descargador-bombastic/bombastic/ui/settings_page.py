"""Página de ajustes: idioma, tema, carpeta de descargas, dependencias y registros."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
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
    QVBoxLayout,
    QWidget,
)

from bombastic.context import AppContext
from bombastic.core.binaries import BinaryStatus, Tool, locate_all
from bombastic.core.binary_probe import BinaryProbe
from bombastic.core.i18n import tr
from bombastic.core.paths import default_download_dir
from bombastic.core.settings import LANGUAGES, THEMES
from bombastic.ui.pages import Page


class SettingsPage(Page):
    def __init__(self, ctx: AppContext, parent: QWidget | None = None) -> None:
        super().__init__("settings", parent)
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
        column.addWidget(self.downloads_box)

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
        row = QHBoxLayout()
        row.addWidget(self.recheck_button)
        row.addWidget(self.open_bin_button)
        row.addStretch(1)
        deps.addLayout(row)
        column.addWidget(self.dependencies_box)

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
        self.recheck_button.clicked.connect(self.refresh_dependencies)
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

        self.dependencies_box.setTitle(tr("settings.dependencies"))
        self.dependencies_hint.setText(tr("settings.dependencies.hint"))
        self.recheck_button.setText(tr("settings.dependencies.recheck"))
        self.open_bin_button.setText(tr("settings.dependencies.open_bin"))
        self._render_statuses()

        self.data_box.setTitle(tr("settings.data"))
        self.data_location_label.setText(
            f"{tr('settings.data.location')}: {self._ctx.paths.data_dir}"
        )
        self.portable_label.setText(tr("settings.data.portable"))
        self.open_logs_button.setText(tr("settings.data.open_logs"))

        self.shortcuts_box.setTitle(tr("settings.shortcuts"))
        self.shortcuts_label.setText(tr("settings.shortcuts.navigation"))

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
        return self._ctx.settings.download_dir or str(default_download_dir())

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

    # -------------------------------------------------------------- dependencias

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
