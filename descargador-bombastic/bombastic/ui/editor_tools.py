"""Formularios de las herramientas del editor. Cada uno convierte lo elegido en un ``EditPlan``."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from bombastic.core import ffmpeg_command as fc
from bombastic.core.formatting import format_timecode, parse_timecode
from bombastic.core.i18n import tr
from bombastic.core.media_probe import ProbeInfo
from bombastic.core.output_paths import safe_output


class ToolError(ValueError):
    """Lo elegido no permite generar el comando; ``key`` es el mensaje (``editor.error.*``)."""

    def __init__(self, key: str) -> None:
        super().__init__(key)
        self.key = key


@dataclass(frozen=True)
class ToolContext:
    source: Path
    probe: ProbeInfo
    marker_in: float | None
    marker_out: float | None
    #: Carpeta para archivos temporales (lista de concat, logs de dos pasadas).
    temp_dir: Path


def _combo(values: tuple[str, ...], prefix: str, current: str) -> QComboBox:
    combo = QComboBox()
    combo.setProperty("i18n_prefix", prefix)
    for value in values:
        combo.addItem(tr(f"{prefix}.{value}"), value)
    combo.setCurrentIndex(max(0, combo.findData(current)))
    return combo


def _hint() -> QLabel:
    label = QLabel()
    label.setWordWrap(True)
    label.setProperty("muted", True)
    return label


class ToolForm(QWidget):
    key = ""

    def __init__(self) -> None:
        super().__init__()
        #: Textos fijos ``(función que los pone, clave)``, para retraducirlos en caliente.
        self._texts: list[tuple[Callable[[str], None], str]] = []

    def text(self, setter: Callable[[str], None], key: str) -> None:
        setter(tr(key))
        self._texts.append((setter, key))

    def label(self, key: str) -> QLabel:
        label = QLabel()
        self.text(label.setText, key)
        return label

    def retranslate(self) -> None:
        for setter, key in self._texts:
            setter(tr(key))
        for combo in self.findChildren(QComboBox):
            prefix = combo.property("i18n_prefix")
            if prefix:
                for index in range(combo.count()):
                    combo.setItemText(index, tr(f"{prefix}.{combo.itemData(index)}"))
        self.refresh_hints()

    def refresh_hints(self) -> None:
        """Vuelve a calcular los textos que dependen del estado."""

    def plan(self, ctx: ToolContext) -> fc.EditPlan:
        raise NotImplementedError

    def on_file(self, probe: ProbeInfo | None) -> None:
        """Se ha abierto otro archivo."""

    def on_markers(self, start: float | None, end: float | None) -> None:
        """Han cambiado los marcadores I/O."""


class ConvertForm(ToolForm):
    key = "convert"

    def __init__(self) -> None:
        super().__init__()
        form = QFormLayout(self)
        self.container = _combo(fc.CONTAINERS, "editor.container", "mp4")
        self.vcodec = _combo(tuple(fc.VIDEO_CODECS), "editor.vcodec", "h264")
        self.acodec = _combo(tuple(fc.AUDIO_CODECS), "editor.acodec", "aac")
        self.quality = _combo(("crf", "bitrate"), "editor.quality", "crf")
        self.crf = QSpinBox()
        self.crf.setRange(0, 63)
        self.crf.setValue(23)
        self.vkbps = QSpinBox()
        self.vkbps.setRange(100, 200_000)
        self.vkbps.setValue(4000)
        self.vkbps.setSuffix(" kbps")
        self.akbps = QSpinBox()
        self.akbps.setRange(32, 512)
        self.akbps.setValue(192)
        self.akbps.setSuffix(" kbps")
        self.preset = QComboBox()
        for preset in fc.X26X_PRESETS:
            self.preset.addItem(preset, preset)
        self.preset.setCurrentIndex(fc.X26X_PRESETS.index("medium"))
        self.hint = _hint()
        for label, widget in (
            ("editor.container", self.container),
            ("editor.vcodec", self.vcodec),
            ("editor.acodec", self.acodec),
            ("editor.quality", self.quality),
            ("editor.crf", self.crf),
            ("editor.video_bitrate", self.vkbps),
            ("editor.audio_bitrate", self.akbps),
            ("editor.preset", self.preset),
        ):
            form.addRow(self.label(label), widget)
        form.addRow(self.hint)
        self.quality.currentIndexChanged.connect(self.refresh_hints)
        self.container.currentIndexChanged.connect(self.refresh_hints)
        self.vcodec.currentIndexChanged.connect(self.refresh_hints)
        self._probe: ProbeInfo | None = None
        self.refresh_hints()

    def refresh_hints(self) -> None:
        audio_only = self.container.currentData() in fc.AUDIO_CONTAINERS
        copying = self.vcodec.currentData() == "copy"
        self.vcodec.setEnabled(not audio_only)
        self.crf.setEnabled(not audio_only and not copying and self.quality.currentData() == "crf")
        self.vkbps.setEnabled(
            not audio_only and not copying and self.quality.currentData() == "bitrate"
        )
        self.preset.setEnabled(self.vcodec.currentData() in ("h264", "h265"))
        text = tr("editor.convert.copy_hint")
        if self._probe is not None and fc.can_copy(self._probe, str(self.container.currentData())):
            text += " " + tr("editor.convert.can_copy")
        self.hint.setText(text)

    def on_file(self, probe: ProbeInfo | None) -> None:
        self._probe = probe
        self.refresh_hints()

    def options(self) -> fc.ConvertOptions:
        return fc.ConvertOptions(
            container=str(self.container.currentData()),
            video_codec=str(self.vcodec.currentData()),
            audio_codec=str(self.acodec.currentData()),
            quality_mode=str(self.quality.currentData()),
            crf=self.crf.value(),
            video_kbps=self.vkbps.value(),
            audio_kbps=self.akbps.value(),
            preset=str(self.preset.currentData()),
        )

    def plan(self, ctx: ToolContext) -> fc.EditPlan:
        options = self.options()
        output = safe_output(ctx.source, options.container)
        return fc.build_convert(ctx.source, output, ctx.probe, options)


class TimeEdit(QLineEdit):
    """Campo de tiempo ``hh:mm:ss.mmm``."""

    def __init__(self) -> None:
        super().__init__()
        self.setPlaceholderText("00:00:00.000")

    def seconds(self) -> float | None:
        return parse_timecode(self.text()) if self.text().strip() else None

    def set_seconds(self, value: float | None) -> None:
        self.setText(format_timecode(value) if value is not None else "")


class TrimForm(ToolForm):
    key = "trim"

    def __init__(self) -> None:
        super().__init__()
        form = QFormLayout(self)
        self.start = TimeEdit()
        self.end = TimeEdit()
        self.precise = QCheckBox()
        self.text(self.precise.setText, "editor.trim.precise")
        self.hint = _hint()
        form.addRow(self.label("editor.start"), self.start)
        form.addRow(self.label("editor.end"), self.end)
        form.addRow(self.precise)
        form.addRow(self.hint)
        self.precise.toggled.connect(self.refresh_hints)
        self.refresh_hints()

    def refresh_hints(self) -> None:
        precise = self.precise.isChecked()
        self.hint.setText(tr("editor.trim.precise_hint" if precise else "editor.trim.fast_hint"))

    def on_markers(self, start: float | None, end: float | None) -> None:
        self.start.set_seconds(start)
        self.end.set_seconds(end)

    def plan(self, ctx: ToolContext) -> fc.EditPlan:
        start = self.start.seconds() or 0.0
        end = self.end.seconds()
        if end is None:
            end = ctx.probe.duration
        if end is None or end <= start:
            raise ToolError("editor.error.bad_range")
        extension = ctx.source.suffix.lstrip(".") or "mp4"
        output = safe_output(ctx.source, extension if not self.precise.isChecked() else "mp4")
        return fc.build_trim(ctx.source, output, ctx.probe, start, end, self.precise.isChecked())


class SegmentsForm(ToolForm):
    key = "segments"

    def __init__(self) -> None:
        super().__init__()
        self.segments: list[fc.Segment] = []
        self._markers: tuple[float | None, float | None] = (None, None)
        self.mode = _combo(("keep", "remove"), "editor.segments.mode", "keep")
        self.list = QListWidget()
        self.add_button = QPushButton()
        self.text(self.add_button.setText, "editor.segments.add")
        self.remove_button = QPushButton()
        self.text(self.remove_button.setText, "editor.segments.remove")
        buttons = QHBoxLayout()
        buttons.addWidget(self.add_button)
        buttons.addWidget(self.remove_button)
        buttons.addStretch(1)
        hint = _hint()
        self.text(hint.setText, "editor.segments.hint")
        layout = QVBoxLayout(self)
        layout.addWidget(self.mode)
        layout.addWidget(self.list, 1)
        layout.addLayout(buttons)
        layout.addWidget(hint)
        self.add_button.clicked.connect(self.add_marked)
        self.remove_button.clicked.connect(self.remove_selected)

    def on_markers(self, start: float | None, end: float | None) -> None:
        self._markers = (start, end)

    def on_file(self, probe: ProbeInfo | None) -> None:
        self.segments.clear()
        self._refresh()

    def add_marked(self) -> bool:
        start, end = self._markers
        if start is None or end is None or end <= start:
            return False
        self.segments.append((start, end))
        self.segments.sort()
        self._refresh()
        return True

    def remove_selected(self) -> None:
        row = self.list.currentRow()
        if 0 <= row < len(self.segments):
            del self.segments[row]
            self._refresh()

    def _refresh(self) -> None:
        self.list.clear()
        for start, end in self.segments:
            self.list.addItem(f"{format_timecode(start)} - {format_timecode(end)}")

    def plan(self, ctx: ToolContext) -> fc.EditPlan:
        if not self.segments:
            raise ToolError("editor.error.no_segments")
        try:
            return fc.build_segments(
                ctx.source,
                safe_output(ctx.source, "mp4"),
                ctx.probe,
                self.segments,
                remove=self.mode.currentData() == "remove",
            )
        except ValueError as exc:
            raise ToolError("editor.error.no_segments") from exc


class ConcatForm(ToolForm):
    """Lista reordenable de archivos. Las sondas de ffprobe las pide la página."""

    key = "concat"
    #: Se ha añadido un archivo que hay que sondear.
    probe_requested = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.probes: dict[str, ProbeInfo] = {}
        self.list = QListWidget()
        self.list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.add_current = QPushButton()
        self.text(self.add_current.setText, "editor.concat.add_current")
        self.add_files = QPushButton()
        self.text(self.add_files.setText, "editor.concat.add_files")
        self.remove_button = QPushButton()
        self.text(self.remove_button.setText, "editor.segments.remove")
        buttons = QHBoxLayout()
        for button in (self.add_current, self.add_files, self.remove_button):
            buttons.addWidget(button)
        buttons.addStretch(1)
        self.status = _hint()
        layout = QVBoxLayout(self)
        layout.addWidget(self.list, 1)
        layout.addLayout(buttons)
        layout.addWidget(self.status)
        self.add_files.clicked.connect(self._browse)
        self.remove_button.clicked.connect(self._remove)
        self.list.model().rowsMoved.connect(lambda *_: self.refresh_status())
        self._current: Path | None = None
        self.add_current.clicked.connect(self._add_current)
        self.refresh_status()

    def set_current(self, path: Path | None, probe: ProbeInfo | None) -> None:
        self._current = path
        if path is not None and probe is not None:
            self.probes[str(path)] = probe

    def _add_current(self) -> None:
        if self._current is not None:
            self.add_path(self._current)

    def paths(self) -> list[Path]:
        return [
            Path(self.list.item(i).data(Qt.ItemDataRole.UserRole)) for i in range(self.list.count())
        ]

    def add_path(self, path: Path) -> None:
        item = QListWidgetItem(path.name)
        item.setData(Qt.ItemDataRole.UserRole, str(path))
        item.setToolTip(str(path))
        self.list.addItem(item)
        if str(path) not in self.probes:
            self.probe_requested.emit(str(path))
        self.refresh_status()

    def set_probe(self, path: str, probe: ProbeInfo) -> None:
        self.probes[path] = probe
        self.refresh_status()

    def _browse(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, tr("editor.concat.add_files"))
        for file in files:
            self.add_path(Path(file))

    def _remove(self) -> None:
        row = self.list.currentRow()
        if row >= 0:
            self.list.takeItem(row)
            self.refresh_status()

    def refresh_hints(self) -> None:
        self.refresh_status()

    def refresh_status(self) -> None:
        paths = self.paths()
        probes = [self.probes.get(str(p)) for p in paths]
        if len(paths) < 2:
            key = "editor.concat.need_two"
        elif any(p is None for p in probes):
            key = "editor.concat.checking"
        elif fc.concat_compatible([p for p in probes if p is not None]):
            key = "editor.concat.compatible"
        else:
            key = "editor.concat.recode"
        self.status.setText(tr(key))

    def plan(self, ctx: ToolContext) -> fc.EditPlan:
        paths = self.paths()
        probes = [self.probes.get(str(p)) for p in paths]
        if len(paths) < 2:
            raise ToolError("editor.concat.need_two")
        known = [p for p in probes if p is not None]
        if len(known) != len(paths):
            raise ToolError("editor.concat.checking")
        list_file = ctx.temp_dir / f"concat-{abs(hash(tuple(paths)))}.txt"
        ctx.temp_dir.mkdir(parents=True, exist_ok=True)
        list_file.write_text(fc.concat_list_text(paths), encoding="utf-8")
        extension = paths[0].suffix.lstrip(".") if fc.concat_compatible(known) else "mp4"
        output = safe_output(paths[0], extension or "mp4", suffix="_unido")
        return fc.build_concat(paths, output, known, list_file)


class CompressForm(ToolForm):
    key = "compress"

    def __init__(self) -> None:
        super().__init__()
        form = QFormLayout(self)
        self.mode = _combo(("crf", "size"), "editor.compress.mode", "crf")
        self.crf = QSpinBox()
        self.crf.setRange(18, 40)
        self.crf.setValue(28)
        self.size_mb = QDoubleSpinBox()
        self.size_mb.setRange(1, 100_000)
        self.size_mb.setValue(25)
        self.size_mb.setSuffix(" MB")
        self.hint = _hint()
        form.addRow(self.label("editor.compress.mode"), self.mode)
        form.addRow(self.label("editor.crf"), self.crf)
        form.addRow(self.label("editor.compress.size"), self.size_mb)
        form.addRow(self.hint)
        self.mode.currentIndexChanged.connect(self.refresh_hints)
        self.size_mb.valueChanged.connect(self.refresh_hints)
        self._probe: ProbeInfo | None = None
        self.refresh_hints()

    def on_file(self, probe: ProbeInfo | None) -> None:
        self._probe = probe
        self.refresh_hints()

    def refresh_hints(self) -> None:
        by_size = self.mode.currentData() == "size"
        self.crf.setEnabled(not by_size)
        self.size_mb.setEnabled(by_size)
        if by_size and self._probe is not None and self._probe.duration:
            audio = fc.DEFAULT_AUDIO_KBPS if self._probe.has_audio else 0
            kbps = fc.target_video_kbps(self.size_mb.value(), self._probe.duration, audio)
            self.hint.setText(tr("editor.compress.size_hint", kbps=kbps))
        else:
            self.hint.setText(tr("editor.compress.crf_hint"))

    def plan(self, ctx: ToolContext) -> fc.EditPlan:
        output = safe_output(ctx.source, "mp4")
        if self.mode.currentData() == "crf":
            return fc.build_compress_crf(ctx.source, output, ctx.probe, self.crf.value())
        if not ctx.probe.duration:
            raise ToolError("editor.error.no_duration")
        passlog = ctx.temp_dir / f"2pass-{output.stem}"
        ctx.temp_dir.mkdir(parents=True, exist_ok=True)
        return fc.build_compress_size(ctx.source, output, ctx.probe, self.size_mb.value(), passlog)
