"""Asistente del primer arranque y ventana "Acerca de"."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
    QWizard,
    QWizardPage,
)

from bombastic import APP_NAME, __version__
from bombastic.context import AppContext
from bombastic.core.binaries import Tool, locate
from bombastic.core.i18n import tr
from bombastic.core.paths import get_app_dir
from bombastic.core.settings import LANGUAGES, THEMES


class FirstRunWizard(QWizard):
    """Idioma, tema, carpeta de descargas, dependencias y menú contextual."""

    def __init__(self, ctx: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ctx = ctx
        self.setWindowTitle(tr("wizard.title", name=APP_NAME))
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        settings = ctx.settings

        # 1. Idioma y tema (se aplican al momento).
        look = QWizardPage()
        look.setTitle(tr("wizard.look.title"))
        self.language = QComboBox()
        for language in LANGUAGES:
            self.language.addItem(tr(f"settings.language.{language}"), language)
        self.language.setCurrentIndex(max(0, self.language.findData(settings.language)))
        self.theme = QComboBox()
        for theme in THEMES:
            self.theme.addItem(tr(f"settings.theme.{theme}"), theme)
        self.theme.setCurrentIndex(max(0, self.theme.findData(settings.theme)))
        form = QFormLayout(look)
        form.addRow(tr("settings.language"), self.language)
        form.addRow(tr("settings.theme"), self.theme)
        self.language.currentIndexChanged.connect(self._apply_look)
        self.theme.currentIndexChanged.connect(self._apply_look)

        # 2. Carpeta de descargas.
        folder_page = QWizardPage()
        folder_page.setTitle(tr("wizard.folder.title"))
        self.folder = QLineEdit(ctx.download_dir())
        browse = QPushButton(tr("settings.browse"))
        browse.clicked.connect(self._browse)
        row = QHBoxLayout()
        row.addWidget(self.folder, 1)
        row.addWidget(browse)
        folder_layout = QVBoxLayout(folder_page)
        folder_layout.addWidget(QLabel(tr("wizard.folder.text")))
        folder_layout.addLayout(row)

        # 3. Dependencias y menú contextual.
        final = QWizardPage()
        final.setTitle(tr("wizard.deps.page"))
        self.deps_label = QLabel()
        self.deps_label.setWordWrap(True)
        self.context_menu = QCheckBox(tr("settings.context_menu.add"))
        self.context_note = QLabel()
        self.context_note.setWordWrap(True)
        self.context_note.setProperty("muted", True)
        if ctx.paths.portable:
            self.context_menu.setEnabled(False)
            self.context_note.setText(tr("settings.context_menu.portable"))
        else:
            self.context_note.setText(tr("settings.context_menu.hint"))
        final_layout = QVBoxLayout(final)
        final_layout.addWidget(self.deps_label)
        final_layout.addWidget(self.context_menu)
        final_layout.addWidget(self.context_note)
        final_layout.addStretch(1)

        for page in (look, folder_page, final):
            self.addPage(page)
        self.refresh_dependencies()

    def _apply_look(self) -> None:
        settings = self._ctx.settings
        settings.language = str(self.language.currentData())
        settings.theme = str(self.theme.currentData())
        self._ctx.save_settings()
        self._ctx.translator.set_language(settings.language)
        self._ctx.theme.apply(settings.theme)

    def _browse(self) -> None:
        title = tr("settings.browse.title")
        chosen = QFileDialog.getExistingDirectory(self, title, self.folder.text())
        if chosen:
            self.folder.setText(chosen)

    def missing(self) -> list[Tool]:
        return [t for t in (Tool.YTDLP, Tool.FFMPEG) if not locate(t, self._ctx.paths).found]

    def refresh_dependencies(self) -> None:
        missing = self.missing()
        if missing:
            names = ", ".join(t.value for t in missing)
            self.deps_label.setText(tr("wizard.deps.missing", names=names))
        else:
            self.deps_label.setText(tr("wizard.deps.ok"))

    def accept(self) -> None:
        settings = self._ctx.settings
        if self.folder.text().strip():
            settings.download_dir = str(Path(self.folder.text().strip()))
        settings.first_run_done = True
        self._ctx.save_settings()
        super().accept()

    @property
    def wants_context_menu(self) -> bool:
        return self.context_menu.isEnabled() and self.context_menu.isChecked()


class AboutDialog(QDialog):
    """Versión de la app, de yt-dlp y de ffmpeg, licencias y aviso legal."""

    def __init__(self, versions: dict[str, str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("about.title", name=APP_NAME))
        title = QLabel(f"<b>{APP_NAME}</b> {__version__}")
        title.setTextFormat(Qt.TextFormat.RichText)
        missing = tr("settings.dependencies.missing")
        lines = [
            tr("about.component", name=name, version=version or missing)
            for name, version in versions.items()
        ]
        self.versions = QLabel("\n".join(lines))
        self.versions.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        notice = QLabel(tr("about.notice"))
        notice.setWordWrap(True)
        licenses = QPushButton(tr("about.licenses"))
        licenses.clicked.connect(self.open_licenses)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addWidget(self.versions)
        layout.addWidget(notice)
        layout.addWidget(licenses, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(buttons)

    @staticmethod
    def licenses_path() -> Path:
        return get_app_dir() / "THIRD_PARTY_LICENSES.txt"

    def open_licenses(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.licenses_path())))
