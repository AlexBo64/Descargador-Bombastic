"""Página del editor: abrir un archivo, verlo con marcadores I/O y aplicarle herramientas."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QDragEnterEvent, QDropEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from bombastic.context import AppContext
from bombastic.core.binaries import Tool
from bombastic.core.edit_manager import EditManager, FfmpegJob
from bombastic.core.ffmpeg_command import EditPlan
from bombastic.core.ffmpeg_tools import apply_hw, build_proxy, preview_plan
from bombastic.core.formatting import format_bytes, format_timecode
from bombastic.core.i18n import tr
from bombastic.core.media_probe import ProbeInfo
from bombastic.core.media_prober import MediaProber, tool_launcher
from bombastic.core.recipes import FilterInfo, RecipeStore, parse_filters, plan_to_template
from bombastic.core.ytdlp_runner import Launcher, OutputCollector, describe
from bombastic.ui.editor_tools import (
    CompressForm,
    ConcatForm,
    ConvertForm,
    SegmentsForm,
    ToolContext,
    ToolError,
    ToolForm,
    TrimForm,
)
from bombastic.ui.editor_tools_extra import (
    AnimationForm,
    AudioForm,
    MetadataForm,
    SnapshotForm,
    SpeedForm,
    SubtitlesForm,
    TransformForm,
    WatermarkForm,
)
from bombastic.ui.expert_panel import ExpertForm, FiltersDialog
from bombastic.ui.pages import Page
from bombastic.ui.player import PlayerWidget


def probe_summary(probe: ProbeInfo) -> str:
    """Texto del panel de información (contenedor, duración, pistas…)."""
    lines = [
        tr("editor.info.container", value=probe.container),
        tr("editor.info.duration", value=format_timecode(probe.duration) or "—"),
        tr("editor.info.size", value=format_bytes(probe.size) or "—"),
        tr(
            "editor.info.bitrate",
            value=f"{probe.bitrate // 1000} kbps" if probe.bitrate else "—",
        ),
    ]
    for stream in probe.streams:
        parts = [f"#{stream.index}", stream.kind, stream.codec]
        if stream.width and stream.height:
            parts.append(f"{stream.width}x{stream.height}")
        if stream.fps:
            parts.append(f"{stream.fps:g} fps")
        if stream.sample_rate:
            parts.append(f"{stream.sample_rate} Hz")
        if stream.channels:
            parts.append(tr("editor.info.channels", count=stream.channels))
        if stream.language:
            parts.append(stream.language)
        if stream.attached_pic:
            parts.append(tr("editor.info.cover"))
        lines.append(" · ".join(parts))
    return "\n".join(lines)


class PreviewDialog(QDialog):
    """Reproduce la previsualización del resultado."""

    def __init__(self, path: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("editor.preview"))
        self.resize(720, 480)
        self.player = PlayerWidget()
        layout = QVBoxLayout(self)
        layout.addWidget(self.player)
        self.player.load(path)
        self.player.player.play()
        self.finished.connect(lambda _result: self.player.unload())


class EditorPage(Page):
    #: Se ha abierto un archivo con éxito (ruta).
    file_opened = Signal(str)
    #: La previsualización está lista (ruta del clip).
    preview_ready = Signal(str)
    #: Los tests lo desactivan para no abrir el diálogo de reproducción.
    show_preview_dialog = True

    def __init__(
        self,
        ctx: AppContext,
        manager: EditManager,
        probe_launcher: Launcher | None = None,
        recipes: RecipeStore | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__("editor", parent)
        self.setAcceptDrops(True)
        self._ctx = ctx
        self.manager = manager
        self.prober = MediaProber(probe_launcher or tool_launcher(ctx.paths, Tool.FFPROBE), self)
        self.recipes = recipes if recipes is not None else RecipeStore(ctx.db)
        self.source: Path | None = None
        self.probe: ProbeInfo | None = None
        #: Filtros de ``ffmpeg -filters`` (se piden la primera vez que hacen falta).
        self.filters: list[FilterInfo] | None = None
        self._pending: Path | None = None

        self.open_button = QPushButton()
        self.open_button.setProperty("primary", True)
        self.file_label = QLabel()
        self.file_label.setProperty("muted", True)
        top = QHBoxLayout()
        top.addWidget(self.open_button)
        top.addWidget(self.file_label, 1)

        self.player = PlayerWidget()
        self.info = QPlainTextEdit()
        self.info.setReadOnly(True)
        self.info.setMaximumHeight(130)

        self.forms: list[ToolForm] = [
            ConvertForm(),
            TrimForm(),
            SegmentsForm(),
            ConcatForm(),
            CompressForm(),
            TransformForm(),
            SpeedForm(),
            AudioForm(),
            SubtitlesForm(),
            WatermarkForm(),
            AnimationForm(),
            SnapshotForm(),
            MetadataForm(),
            ExpertForm(self.recipes),
        ]
        self.tools = QTabWidget()
        self.tools.setUsesScrollButtons(True)
        for form in self.forms:
            self.tools.addTab(form, "")
        self.command_button = QPushButton()
        self.preview_button = QPushButton()
        self.expert_button = QPushButton()
        #: Trabajo de previsualización o de proxy en marcha (no pasa por la cola).
        self._side_job: FfmpegJob | None = None
        self._proxy_for: Path | None = None
        self.queue_button = QPushButton()
        self.queue_button.setProperty("primary", True)
        self.feedback = QLabel()
        self.feedback.setWordWrap(True)
        # Aviso arriba y botones en dos filas: en una sola no caben junto a las herramientas.
        actions = QVBoxLayout()
        actions.addWidget(self.feedback)
        buttons = QGridLayout()
        buttons.setHorizontalSpacing(8)
        buttons.setVerticalSpacing(8)
        buttons.addWidget(self.expert_button, 0, 0)
        buttons.addWidget(self.preview_button, 0, 1)
        buttons.addWidget(self.command_button, 1, 0)
        buttons.addWidget(self.queue_button, 1, 1)
        actions.addLayout(buttons)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(self.player, 1)
        left_layout.addWidget(self.info)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addWidget(self.tools, 1)
        right_layout.addLayout(actions)
        splitter = QSplitter()
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 5)
        splitter.setStretchFactor(1, 4)

        self.body.addLayout(top)
        self.body.addWidget(splitter, 1)

        self.open_button.clicked.connect(self._browse)
        self.command_button.clicked.connect(self.show_command)
        self.preview_button.clicked.connect(self.preview)
        self.expert_button.clicked.connect(self.open_in_expert)
        self.tools.currentChanged.connect(lambda _index: self._refresh())
        expert = self.expert_form
        expert.run_requested.connect(self.run_expert)
        expert.cancel_requested.connect(self._cancel_side)
        expert.filters_requested.connect(self.show_filters)
        self.player.playback_failed.connect(self._on_playback_failed)
        self.queue_button.clicked.connect(self.add_to_queue)
        self.prober.probed.connect(self._on_probed)
        self.prober.failed.connect(self._on_probe_failed)
        self.player.markers_changed.connect(self._on_markers)
        concat = self.concat_form
        concat.probe_requested.connect(lambda path: self.prober.probe(Path(path)))
        for sequence, slot in (
            ("Space", self.player.toggle_play),
            ("I", self.player.mark_in),
            ("O", self.player.mark_out),
            ("Left", lambda: self.player.seek_relative(-1)),
            ("Right", lambda: self.player.seek_relative(1)),
            ("Shift+Left", lambda: self.player.seek_relative(-5)),
            ("Shift+Right", lambda: self.player.seek_relative(5)),
            (",", lambda: self.player.step_frames(-1)),
            (".", lambda: self.player.step_frames(1)),
        ):
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(slot)
        ctx.theme.changed.connect(self._apply_theme)
        self._apply_theme()
        self.retranslate()
        self._refresh()

    def _apply_theme(self) -> None:
        self.player.slider.marker_color = QColor(self._ctx.theme.palette["accent"])
        self.player.slider.update()
        self.expert_form.set_palette(self._ctx.theme.palette)

    @property
    def expert_form(self) -> ExpertForm:
        form = self.forms[-1]
        assert isinstance(form, ExpertForm)
        return form

    # ------------------------------------------------------------ modo experto

    def open_in_expert(self) -> bool:
        """Pasa el comando de la herramienta activa al modo experto para retocarlo."""
        plan = self.current_plan()
        if plan is None:
            return False
        expert = self.expert_form
        expert.set_template(plan_to_template(plan))
        expert.output_ext.setText(plan.output.suffix.lstrip(".") or "mp4")
        expert.params.clear()
        self.tools.setCurrentWidget(expert)
        return True

    def open_recipe(self, recipe_id: int) -> None:
        recipe = self.recipes.get(recipe_id)
        if recipe is not None:
            self.expert_form.refresh_recipes()
            self.expert_form.load_recipe(recipe)
            self.tools.setCurrentWidget(self.expert_form)

    def run_expert(self) -> FfmpegJob | None:
        """Ejecuta el comando del modo experto ahora, con su salida en la consola."""
        self.tools.setCurrentWidget(self.expert_form)
        plan = self.current_plan()
        if plan is None or self._side_job is not None:
            return None
        console = self.expert_form.console
        console.clear()
        console.appendPlainText("$ " + describe(("ffmpeg", list(plan.passes[0]))))

        def done(status: str) -> None:
            console.appendPlainText(tr(f"expert.finished.{status}", name=plan.output.name))

        job = self._run_side(plan, done)
        job.output_line.connect(console.appendPlainText)
        return job

    def _cancel_side(self) -> None:
        if self._side_job is not None:
            self._side_job.cancel()

    def show_filters(self) -> None:
        """Lista de filtros de ffmpeg; la primera vez se pide a ffmpeg sin bloquear."""
        if self.filters is not None:
            self._open_filters_dialog()
            return
        launch = self.manager.launcher(["-hide_banner", "-filters"])
        if launch is None:
            self.filters = []
            self._open_filters_dialog()
            return
        collector = OutputCollector(launch, self)

        def done(code: int, output: str) -> None:
            collector.deleteLater()
            self.filters = parse_filters(output) if code == 0 else []
            self.expert_form.editor.add_words([f.name for f in self.filters])
            self._open_filters_dialog()

        collector.finished.connect(done)
        collector.start()

    def _insert_filter(self, name: str) -> None:
        if name:
            self.expert_form.insert(name)

    def _open_filters_dialog(self) -> FiltersDialog:
        dialog = FiltersDialog(self.filters or [], parent=self)
        dialog.accepted.connect(lambda: self._insert_filter(dialog.chosen()))
        dialog.open()
        self.filters_dialog = dialog
        return dialog

    @property
    def concat_form(self) -> ConcatForm:
        form = self.forms[3]
        assert isinstance(form, ConcatForm)
        return form

    def retranslate(self) -> None:
        super().retranslate()
        self.open_button.setText(tr("editor.open"))
        self.open_button.setToolTip(tr("editor.open.tooltip"))
        for index, form in enumerate(self.forms):
            self.tools.setTabText(index, tr(f"editor.tool.{form.key}"))
            form.retranslate()
        self.command_button.setText(tr("editor.show_command"))
        self.preview_button.setText(tr("editor.preview"))
        self.expert_button.setText(tr("editor.open_expert"))
        self.expert_button.setToolTip(tr("editor.open_expert.tooltip"))
        self.preview_button.setToolTip(tr("editor.preview.tooltip"))
        self.queue_button.setText(tr("editor.add_to_queue"))
        self.player.retranslate()
        self._refresh()

    # ----------------------------------------------------------------- archivos

    def _browse(self) -> None:
        chosen, _ = QFileDialog.getOpenFileName(self, tr("editor.open"))
        if chosen:
            self.open_file(Path(chosen))

    def open_file(self, path: Path) -> None:
        """Abre un archivo: primero ffprobe, después el reproductor."""
        self._pending = path
        self.file_label.setText(tr("editor.probing", name=path.name))
        self.prober.probe(path)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if any(url.isLocalFile() for url in event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        files = [Path(url.toLocalFile()) for url in event.mimeData().urls() if url.isLocalFile()]
        if files:
            self.open_file(files[0])
            for extra in files[1:]:
                self.concat_form.add_path(extra)
            event.acceptProposedAction()

    def _on_probed(self, path: str, probe: ProbeInfo) -> None:
        if self._pending is not None and path == str(self._pending):
            self._pending = None
            self.source, self.probe = Path(path), probe
            video = probe.first("video")
            self.player.load(self.source, video.fps if video else None)
            self.info.setPlainText(probe_summary(probe))
            for form in self.forms:
                form.on_file(probe)
            self.concat_form.set_current(self.source, probe)
            self.feedback.setText("")
            self._refresh()
            self.file_opened.emit(path)
        else:
            self.concat_form.set_probe(path, probe)

    def _on_probe_failed(self, path: str, reason: str) -> None:
        if self._pending is not None and path == str(self._pending):
            self._pending = None
            self.feedback.setText(tr(f"editor.probe_failed.{reason}", name=Path(path).name))
        self._refresh()

    def _on_markers(self, start: float | None, end: float | None) -> None:
        for form in self.forms:
            form.on_markers(start, end)

    def _refresh(self) -> None:
        if self.source is not None:
            self.file_label.setText(str(self.source))
        elif self._pending is None:
            self.file_label.setText(tr("editor.no_file"))
        ready = self.source is not None and self.probe is not None
        self.command_button.setEnabled(ready)
        self.preview_button.setEnabled(ready and self._side_job is None)
        on_expert = self.tools.currentWidget() is self.expert_form
        self.expert_button.setEnabled(ready and not on_expert)
        self.expert_form.set_running(self._side_job is not None)
        self.queue_button.setEnabled(ready)

    # ------------------------------------------------------------------ acciones

    def current_plan(self) -> EditPlan | None:
        """Plan de la herramienta activa, o ``None`` (con el motivo en el aviso)."""
        if self.source is None or self.probe is None:
            return None
        form = self.forms[self.tools.currentIndex()]
        context = ToolContext(
            source=self.source,
            probe=self.probe,
            marker_in=self.player.marker_in,
            marker_out=self.player.marker_out,
            temp_dir=self._ctx.paths.cache_dir / "tmp",
            position=self.player.position,
        )
        try:
            plan = form.plan(context)
        except ToolError as exc:
            self.feedback.setText(tr(exc.key))
            return None
        self.feedback.setText("")
        return plan

    def show_command(self) -> None:
        plan = self.current_plan()
        if plan is None:
            return
        text = "\n\n".join(describe(("ffmpeg", list(p))) for p in plan.passes)
        box = QMessageBox(
            QMessageBox.Icon.Information, tr("editor.show_command"), text, parent=self
        )
        box.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        box.open()

    def add_to_queue(self) -> int | None:
        plan = self.current_plan()
        if plan is None:
            return None
        title = tr(f"editor.tool.{plan.tool}") + f": {plan.output.name}"
        if self._ctx.settings.hw_encoder:
            plan = apply_hw(plan, self._ctx.settings.hw_encoder)
        task_id = self.manager.add(title, plan)
        self.feedback.setText(tr("editor.queued", name=plan.output.name))
        return task_id

    # -------------------------------------------------- previsualización y proxy

    def _run_side(self, plan: EditPlan, done: Callable[[str], None]) -> FfmpegJob:
        """Ejecuta un plan corto fuera de la cola (previsualización o proxy)."""
        job = FfmpegJob(plan, self.manager.launcher, parent=self)
        self._side_job = job

        def finished(status: str, _code: str, _detail: str) -> None:
            self._side_job = None
            job.deleteLater()
            self._refresh()
            done(status)

        job.finished.connect(finished)
        job.start()
        self._refresh()
        return job

    def preview(self) -> FfmpegJob | None:
        """Genera unos segundos del resultado en una carpeta temporal y los reproduce."""
        plan = self.current_plan()
        if plan is None:
            return None
        marker = self.player.marker_in
        start = marker if marker is not None else self.player.position
        suffix = plan.output.suffix or ".mp4"
        target = self._ctx.paths.cache_dir / "tmp" / f"preview{suffix}"
        target.parent.mkdir(parents=True, exist_ok=True)
        short = preview_plan(plan, start, target)
        if short is None:
            self.feedback.setText(tr("editor.preview.unavailable"))
            return None
        self.feedback.setText(tr("editor.preview.working"))

        def done(status: str) -> None:
            if status == "completed":
                self.feedback.setText("")
                self.preview_ready.emit(str(target))
                if self.show_preview_dialog:
                    PreviewDialog(target, parent=self).open()
            else:
                self.feedback.setText(tr("editor.preview.failed"))

        return self._run_side(short, done)

    def _on_playback_failed(self, _message: str) -> None:
        """QtMultimedia no puede con el archivo: se reproduce una copia ligera en H.264."""
        source, probe = self.source, self.probe
        if source is None or probe is None or self._proxy_for == source or self._side_job:
            return
        self._proxy_for = source
        digest = hashlib.sha1(str(source).encode("utf-8")).hexdigest()[:16]
        proxy = self._ctx.paths.cache_dir / "proxies" / f"{digest}.mp4"
        if proxy.is_file():
            self.player.load(proxy, self.player.fps)
            self.feedback.setText(tr("editor.proxy.ready"))
            return
        proxy.parent.mkdir(parents=True, exist_ok=True)
        self.feedback.setText(tr("editor.proxy.working"))

        def done(status: str) -> None:
            if status == "completed" and self.source == source:
                self.player.load(proxy, self.player.fps)
                self.feedback.setText(tr("editor.proxy.ready"))
            elif status != "completed":
                self.feedback.setText(tr("editor.proxy.failed"))

        self._run_side(build_proxy(source, proxy, probe), done)

    def shutdown(self) -> None:
        if self._side_job is not None:
            self._side_job.cancel()
            self._side_job.wait(3000)
        self.player.unload()
