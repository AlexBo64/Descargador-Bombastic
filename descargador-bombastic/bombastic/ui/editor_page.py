"""Página del editor: abrir un archivo, verlo con marcadores I/O y aplicarle herramientas."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QDragEnterEvent, QDropEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QFileDialog,
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
from bombastic.core.edit_manager import EditManager
from bombastic.core.ffmpeg_command import EditPlan
from bombastic.core.formatting import format_bytes, format_timecode
from bombastic.core.i18n import tr
from bombastic.core.media_probe import ProbeInfo
from bombastic.core.media_prober import MediaProber, tool_launcher
from bombastic.core.ytdlp_runner import Launcher, describe
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


class EditorPage(Page):
    #: Se ha abierto un archivo con éxito (ruta).
    file_opened = Signal(str)

    def __init__(
        self,
        ctx: AppContext,
        manager: EditManager,
        probe_launcher: Launcher | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__("editor", parent)
        self.setAcceptDrops(True)
        self._ctx = ctx
        self.manager = manager
        self.prober = MediaProber(probe_launcher or tool_launcher(ctx.paths, Tool.FFPROBE), self)
        self.source: Path | None = None
        self.probe: ProbeInfo | None = None
        self._pending: Path | None = None

        self.open_button = QPushButton()
        self.open_button.setProperty("primary", True)
        self.file_label = QLabel()
        self.file_label.setProperty("muted", True)
        top = QHBoxLayout()
        top.addWidget(self.open_button)
        top.addWidget(self.file_label, 1)

        self.player = PlayerWidget()
        self._apply_theme()
        self.info = QPlainTextEdit()
        self.info.setReadOnly(True)
        self.info.setMaximumHeight(130)

        self.forms: list[ToolForm] = [
            ConvertForm(),
            TrimForm(),
            SegmentsForm(),
            ConcatForm(),
            CompressForm(),
        ]
        self.tools = QTabWidget()
        for form in self.forms:
            self.tools.addTab(form, "")
        self.command_button = QPushButton()
        self.queue_button = QPushButton()
        self.queue_button.setProperty("primary", True)
        self.feedback = QLabel()
        self.feedback.setWordWrap(True)
        actions = QHBoxLayout()
        actions.addWidget(self.feedback, 1)
        actions.addWidget(self.command_button)
        actions.addWidget(self.queue_button)

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
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        self.body.addLayout(top)
        self.body.addWidget(splitter, 1)

        self.open_button.clicked.connect(self._browse)
        self.command_button.clicked.connect(self.show_command)
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
        self.retranslate()
        self._refresh()

    def _apply_theme(self) -> None:
        self.player.slider.marker_color = QColor(self._ctx.theme.palette["accent"])
        self.player.slider.update()

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
        task_id = self.manager.add(title, plan)
        self.feedback.setText(tr("editor.queued", name=plan.output.name))
        return task_id

    def shutdown(self) -> None:
        self.player.unload()
