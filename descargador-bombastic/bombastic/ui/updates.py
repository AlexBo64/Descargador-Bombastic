"""Actualizaciones en la interfaz: bloque de Ajustes, barra de aviso y asistente."""

from __future__ import annotations

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtNetwork import QNetworkAccessManager
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from bombastic import __version__
from bombastic.context import AppContext
from bombastic.core.binaries import Tool, locate
from bombastic.core.db import now_iso
from bombastic.core.i18n import tr
from bombastic.core.media_prober import tool_launcher
from bombastic.core.updater import (
    GITHUB_API,
    UPDATE_CHANNELS,
    FfmpegUpdate,
    ReleaseCheck,
    YtdlpUpdate,
    YtdlpVersionCheck,
    is_newer,
)
from bombastic.core.ytdlp_runner import default_launcher


class Updates(QObject):
    """Lanza las comprobaciones y actualizaciones con los ajustes y rutas de la app."""

    #: Clave de estado para mostrar (``updates.status.*``).
    status = Signal(str)
    progress = Signal(object, object)
    #: ``(ok, clave del mensaje)`` al terminar una operación.
    finished = Signal(bool, str)
    #: Hay algo nuevo: ``(qué: ytdlp/app, versión, enlace)``.
    available = Signal(str, str, str)

    def __init__(self, ctx: AppContext, api: str = GITHUB_API, parent: QObject | None = None):
        super().__init__(parent)
        self._ctx = ctx
        self.api = api
        self.network = QNetworkAccessManager(self)
        self.busy = False

    def _track(self, step: QObject) -> None:
        self.busy = True
        step.status.connect(self.status)  # type: ignore[attr-defined]
        step.progress.connect(self.progress)  # type: ignore[attr-defined]

        def done(ok: bool, key: str) -> None:
            self.busy = False
            step.deleteLater()
            self.finished.emit(ok, key)

        step.finished.connect(done)  # type: ignore[attr-defined]

    def check(self) -> None:
        """Comprueba yt-dlp y la app; avisa con ``available`` si hay versiones nuevas."""
        settings = self._ctx.settings
        settings.last_update_check = now_iso()
        self._ctx.save_settings()
        launcher = default_launcher(self._ctx.paths)
        check = YtdlpVersionCheck(self.network, launcher, settings.update_channel, self.api, self)
        self._track(check)

        def ytdlp_done(ok: bool, _key: str) -> None:
            if ok and check.update_available:
                self.available.emit("ytdlp", check.latest, "")

        check.finished.connect(ytdlp_done)
        check.start()
        if settings.app_update_repo.strip():
            app = ReleaseCheck(self.network, settings.app_update_repo.strip(), self.api, self)

            def app_done(ok: bool, _key: str) -> None:
                app.deleteLater()
                release = app.release
                if ok and release is not None and is_newer(release.tag, __version__):
                    self.available.emit("app", release.tag, release.url)

            app.finished.connect(app_done)
            app.start()

    def update_ytdlp(self, self_update: bool = True) -> YtdlpUpdate:
        paths = self._ctx.paths
        step = YtdlpUpdate(
            self.network,
            default_launcher(paths),
            paths.bin_dir,
            self._ctx.settings.update_channel,
            self.api,
            self_update,
            self,
        )
        self._track(step)
        step.start()
        return step

    def update_ffmpeg(self) -> FfmpegUpdate:
        paths = self._ctx.paths
        step = FfmpegUpdate(
            self.network,
            tool_launcher(paths, Tool.FFMPEG),
            paths.bin_dir,
            paths.cache_dir,
            self.api,
            self,
        )
        self._track(step)
        step.start()
        return step


class UpdatesBox(QWidget):
    """Bloque "Actualizaciones" de Ajustes."""

    def __init__(self, ctx: AppContext, updates: Updates, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ctx = ctx
        self.updates = updates
        settings = ctx.settings
        self.channel = QComboBox()
        self.interval = QSpinBox()
        self.interval.setRange(0, 24 * 30)
        self.interval.setValue(settings.update_check_hours)
        self.repo = QLineEdit(settings.app_update_repo)
        self.check_button = QPushButton()
        self.ytdlp_button = QPushButton()
        self.ffmpeg_button = QPushButton()
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setProperty("muted", True)
        self.bar = QProgressBar()
        self.bar.setFixedHeight(6)
        self.bar.setTextVisible(False)
        self.bar.setVisible(False)
        self.channel_label = QLabel()
        self.interval_label = QLabel()
        self.repo_label = QLabel()
        form = QFormLayout(self)
        form.setContentsMargins(0, 0, 0, 0)
        form.addRow(self.channel_label, self.channel)
        form.addRow(self.interval_label, self.interval)
        form.addRow(self.repo_label, self.repo)
        row = QHBoxLayout()
        for button in (self.check_button, self.ytdlp_button, self.ffmpeg_button):
            row.addWidget(button)
        row.addStretch(1)
        form.addRow(row)
        form.addRow(self.bar)
        form.addRow(self.status)
        self.channel.currentIndexChanged.connect(self._save)
        self.interval.valueChanged.connect(self._save)
        self.repo.editingFinished.connect(self._save)
        self.check_button.clicked.connect(updates.check)
        self.ytdlp_button.clicked.connect(lambda: updates.update_ytdlp())
        self.ffmpeg_button.clicked.connect(updates.update_ffmpeg)
        updates.status.connect(self._on_status)
        updates.progress.connect(self._on_progress)
        updates.finished.connect(self._on_finished)
        updates.available.connect(self._on_available)
        self.retranslate()

    def retranslate(self) -> None:
        self.channel.blockSignals(True)
        self.channel.clear()
        for channel in UPDATE_CHANNELS:
            self.channel.addItem(tr(f"updates.channel.{channel}"), channel)
        index = self.channel.findData(self._ctx.settings.update_channel)
        self.channel.setCurrentIndex(max(0, index))
        self.channel.blockSignals(False)
        self.channel_label.setText(tr("updates.channel"))
        self.interval_label.setText(tr("updates.interval"))
        self.interval.setSuffix(tr("updates.interval.suffix"))
        self.interval.setSpecialValueText(tr("updates.interval.never"))
        self.repo_label.setText(tr("updates.repo"))
        self.repo.setPlaceholderText(tr("updates.repo.placeholder"))
        self.check_button.setText(tr("updates.check"))
        self.ytdlp_button.setText(tr("updates.ytdlp"))
        self.ffmpeg_button.setText(tr("updates.ffmpeg"))
        self.ffmpeg_button.setToolTip(tr("updates.ffmpeg.tooltip"))

    def _save(self) -> None:
        settings = self._ctx.settings
        settings.update_channel = str(self.channel.currentData() or "stable")
        settings.update_check_hours = self.interval.value()
        settings.app_update_repo = self.repo.text().strip()
        self._ctx.save_settings()

    def _set_busy(self, busy: bool) -> None:
        for button in (self.check_button, self.ytdlp_button, self.ffmpeg_button):
            button.setEnabled(not busy)

    def _on_status(self, key: str) -> None:
        self._set_busy(True)
        self.status.setText(tr(key))

    def _on_progress(self, done: int, total: int) -> None:
        self.bar.setVisible(True)
        self.bar.setRange(0, max(0, total))
        if total > 0:
            self.bar.setValue(done)

    def _on_finished(self, _ok: bool, key: str) -> None:
        self._set_busy(False)
        self.bar.setVisible(False)
        if key:
            self.status.setText(tr(key))

    def _on_available(self, what: str, version: str, _url: str) -> None:
        self.status.setText(tr(f"updates.available.{what}", version=version))


class UpdateBar(QFrame):
    """Aviso en la parte superior de la ventana: hay una versión nueva."""

    def __init__(self, updates: Updates, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("UpdateBar")
        self.updates = updates
        self._what = ""
        self._url = ""
        self.label = QLabel()
        self.label.setWordWrap(True)
        self.action_button = QPushButton()
        self.action_button.setProperty("primary", True)
        self.close_button = QPushButton(tr("updates.bar.close"))
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 8, 16, 8)
        layout.addWidget(self.label, 1)
        layout.addWidget(self.action_button)
        layout.addWidget(self.close_button)
        self.setVisible(False)
        self.close_button.clicked.connect(self.hide)
        self.action_button.clicked.connect(self._act)
        updates.available.connect(self.show_update)
        updates.finished.connect(self._on_finished)

    def show_update(self, what: str, version: str, url: str) -> None:
        self._what, self._url = what, url
        self.label.setText(tr(f"updates.available.{what}", version=version))
        self.action_button.setText(tr(f"updates.bar.action.{what}"))
        self.action_button.setEnabled(True)
        self.setVisible(True)

    def _act(self) -> None:
        if self._what == "app":
            QDesktopServices.openUrl(QUrl(self._url))
            self.hide()
        else:
            self.action_button.setEnabled(False)
            self.label.setText(tr("updates.status.self_update"))
            self.updates.update_ytdlp()

    def _on_finished(self, ok: bool, key: str) -> None:
        if self.isVisible() and self._what == "ytdlp" and key.startswith("updates.done"):
            self.label.setText(tr(key))
            self.action_button.setVisible(False)
        elif self.isVisible() and not ok and self._what == "ytdlp":
            self.label.setText(tr(key))
            self.action_button.setEnabled(True)


class DependencyWizard(QDialog):
    """Falta yt-dlp o ffmpeg (por ejemplo, un antivirus los ha borrado): ofrece descargarlos."""

    def __init__(self, ctx: AppContext, updates: Updates, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("wizard.deps.title"))
        self._ctx = ctx
        self.updates = updates
        self.text = QLabel(tr("wizard.deps.text"))
        self.text.setWordWrap(True)
        self.ytdlp_check = QCheckBox("yt-dlp")
        self.ffmpeg_check = QCheckBox("ffmpeg + ffprobe")
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.bar = QProgressBar()
        self.bar.setVisible(False)
        self.buttons = QDialogButtonBox()
        self.download_button = self.buttons.addButton(
            tr("wizard.deps.download"), QDialogButtonBox.ButtonRole.AcceptRole
        )
        self.buttons.addButton(tr("wizard.deps.later"), QDialogButtonBox.ButtonRole.RejectRole)
        self.buttons.rejected.connect(self.reject)
        self.download_button.clicked.connect(self.download)
        layout = QVBoxLayout(self)
        layout.addWidget(self.text)
        layout.addWidget(self.ytdlp_check)
        layout.addWidget(self.ffmpeg_check)
        layout.addWidget(self.bar)
        layout.addWidget(self.status)
        layout.addWidget(self.buttons)
        self.refresh()
        updates.progress.connect(self._on_progress)
        updates.status.connect(lambda key: self.status.setText(tr(key)))
        self._queue: list[str] = []
        updates.finished.connect(self._next)

    @staticmethod
    def missing(ctx: AppContext) -> list[Tool]:
        return [t for t in (Tool.YTDLP, Tool.FFMPEG) if not locate(t, ctx.paths).found]

    def refresh(self) -> None:
        missing = self.missing(self._ctx)
        for check, tool in ((self.ytdlp_check, Tool.YTDLP), (self.ffmpeg_check, Tool.FFMPEG)):
            check.setChecked(tool in missing)
            check.setEnabled(tool in missing)

    def download(self) -> None:
        self._queue = [
            name
            for name, check in (("ytdlp", self.ytdlp_check), ("ffmpeg", self.ffmpeg_check))
            if check.isChecked()
        ]
        self.download_button.setEnabled(False)
        self._next(True, "")

    def _on_progress(self, done: int, total: int) -> None:
        self.bar.setVisible(True)
        self.bar.setRange(0, max(0, total))
        if total > 0:
            self.bar.setValue(done)

    def _next(self, ok: bool, key: str) -> None:
        if key:
            self.status.setText(tr(key))
        if not ok:
            self.download_button.setEnabled(True)
            return
        if not self._queue:
            if self.download_button.isEnabled() is False and key:
                self.refresh()
                if not self.missing(self._ctx):
                    self.status.setText(tr("wizard.deps.done"))
            return
        name = self._queue.pop(0)
        if name == "ytdlp":
            self.updates.update_ytdlp(self_update=False)
        else:
            self.updates.update_ffmpeg()
