"""Formularios de las herramientas 6-13 del editor (la 14, audio puro, son las mismas
herramientas aplicadas a un archivo de audio: las que necesitan vídeo lo avisan)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QWidget,
)

from bombastic.core import ffmpeg_tools as ft
from bombastic.core.ffmpeg_command import EditPlan
from bombastic.core.i18n import tr
from bombastic.core.media_probe import ProbeInfo
from bombastic.core.output_paths import safe_output
from bombastic.ui.editor_tools import TimeEdit, ToolContext, ToolError, ToolForm, _combo, _hint


class FileField(QWidget):
    """Campo de ruta con botón para elegir el archivo."""

    def __init__(self, form: ToolForm, file_filter: str = "") -> None:
        super().__init__()
        self.edit = QLineEdit()
        self.button = QPushButton()
        form.text(self.button.setText, "settings.browse")
        self._filter = file_filter
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.edit, 1)
        row.addWidget(self.button)
        self.button.clicked.connect(self._browse)

    def _browse(self) -> None:
        chosen, _ = QFileDialog.getOpenFileName(self, "", self.edit.text(), self._filter)
        if chosen:
            self.edit.setText(chosen)

    def path(self) -> Path | None:
        text = self.edit.text().strip()
        return Path(text) if text else None


def _spin(low: int, high: int, value: int, suffix: str = "") -> QSpinBox:
    spin = QSpinBox()
    spin.setRange(low, high)
    spin.setValue(value)
    if suffix:
        spin.setSuffix(suffix)
    return spin


def _dspin(low: float, high: float, value: float, step: float, suffix: str = "") -> QDoubleSpinBox:
    spin = QDoubleSpinBox()
    spin.setRange(low, high)
    spin.setSingleStep(step)
    spin.setDecimals(2)
    spin.setValue(value)
    if suffix:
        spin.setSuffix(suffix)
    return spin


def _needs_video(ctx: ToolContext) -> None:
    if not ctx.probe.has_video:
        raise ToolError("editor.error.needs_video")


def _needs_file(path: Path | None) -> Path:
    if path is None or not path.is_file():
        raise ToolError("editor.error.needs_file")
    return path


class TransformForm(ToolForm):
    key = "transform"

    def __init__(self) -> None:
        super().__init__()
        form = QFormLayout(self)
        self.width_spin = _spin(0, 16384, 0, " px")
        self.height_spin = _spin(0, 16384, 0, " px")
        self.crop_check = QCheckBox()
        self.text(self.crop_check.setText, "editor.transform.crop")
        self.crop_w = _spin(2, 16384, 640)
        self.crop_h = _spin(2, 16384, 360)
        self.crop_x = _spin(0, 16384, 0)
        self.crop_y = _spin(0, 16384, 0)
        crop_row = QHBoxLayout()
        for spin in (self.crop_w, self.crop_h, self.crop_x, self.crop_y):
            crop_row.addWidget(spin)
        self.rotate = _combo(("0", "90", "180", "270"), "editor.transform.rotate", "0")
        self.flip_h = QCheckBox()
        self.text(self.flip_h.setText, "editor.transform.flip_h")
        self.flip_v = QCheckBox()
        self.text(self.flip_v.setText, "editor.transform.flip_v")
        hint = _hint()
        self.text(hint.setText, "editor.transform.hint")
        form.addRow(self.label("editor.transform.width"), self.width_spin)
        form.addRow(self.label("editor.transform.height"), self.height_spin)
        form.addRow(self.crop_check, crop_row)
        form.addRow(self.label("editor.transform.rotate"), self.rotate)
        form.addRow(self.flip_h)
        form.addRow(self.flip_v)
        form.addRow(hint)

    def on_file(self, probe: ProbeInfo | None) -> None:
        video = probe.first("video") if probe is not None else None
        if video is not None and video.width and video.height:
            self.crop_w.setValue(video.width)
            self.crop_h.setValue(video.height)

    def plan(self, ctx: ToolContext) -> EditPlan:
        _needs_video(ctx)
        crop = None
        if self.crop_check.isChecked():
            crop = (
                self.crop_w.value(),
                self.crop_h.value(),
                self.crop_x.value(),
                self.crop_y.value(),
            )
        filters = ft.transform_filters(
            self.width_spin.value(),
            self.height_spin.value(),
            crop,
            int(self.rotate.currentData()),
            self.flip_h.isChecked(),
            self.flip_v.isChecked(),
        )
        if not filters:
            raise ToolError("editor.error.nothing_to_do")
        return ft.build_transform(ctx.source, safe_output(ctx.source, "mp4"), ctx.probe, filters)


class SpeedForm(ToolForm):
    key = "speed"

    def __init__(self) -> None:
        super().__init__()
        form = QFormLayout(self)
        self.factor = _dspin(0.1, 16, 2.0, 0.25, "x")
        hint = _hint()
        self.text(hint.setText, "editor.speed.hint")
        form.addRow(self.label("editor.speed.factor"), self.factor)
        form.addRow(hint)

    def plan(self, ctx: ToolContext) -> EditPlan:
        factor = self.factor.value()
        if factor == 1:
            raise ToolError("editor.error.nothing_to_do")
        ext = "mp4" if ctx.probe.has_video else "m4a"
        return ft.build_speed(ctx.source, safe_output(ctx.source, ext), ctx.probe, factor)


AUDIO_OPS: tuple[str, ...] = ("extract", "remove", "replace", "adjust", "normalize")


class AudioForm(ToolForm):
    key = "audio"

    def __init__(self) -> None:
        super().__init__()
        form = QFormLayout(self)
        self.operation = _combo(AUDIO_OPS, "editor.audio.op", "extract")
        self.fmt = _combo(tuple(ft.EXTRACT_FORMATS), "editor.audio.format", "mp3")
        self.replacement = FileField(self)
        self.volume = _dspin(-60, 30, 0, 1, " dB")
        self.fade_in = _dspin(0, 600, 0, 0.5, " s")
        self.fade_out = _dspin(0, 600, 0, 0.5, " s")
        self.channels = _combo(("0", "1", "2"), "editor.audio.channels", "0")
        self.rate = _combo(("0", "22050", "44100", "48000"), "editor.audio.rate", "0")
        self.lufs = _dspin(-40, -5, -16, 1, " LUFS")
        self.hint = _hint()
        form.addRow(self.label("editor.audio.operation"), self.operation)
        form.addRow(self.label("editor.audio.format"), self.fmt)
        form.addRow(self.label("editor.audio.replacement"), self.replacement)
        form.addRow(self.label("editor.audio.volume"), self.volume)
        form.addRow(self.label("editor.audio.fade_in"), self.fade_in)
        form.addRow(self.label("editor.audio.fade_out"), self.fade_out)
        form.addRow(self.label("editor.audio.channels"), self.channels)
        form.addRow(self.label("editor.audio.rate"), self.rate)
        form.addRow(self.label("editor.audio.lufs"), self.lufs)
        form.addRow(self.hint)
        self.operation.currentIndexChanged.connect(self.refresh_hints)
        self.refresh_hints()

    def refresh_hints(self) -> None:
        op = self.operation.currentData()
        self.fmt.setEnabled(op == "extract")
        self.replacement.setEnabled(op == "replace")
        for widget in (self.volume, self.fade_in, self.fade_out, self.channels, self.rate):
            widget.setEnabled(op == "adjust")
        self.lufs.setEnabled(op == "normalize")
        self.hint.setText(tr(f"editor.audio.hint.{op}"))

    def plan(self, ctx: ToolContext) -> EditPlan:
        op = self.operation.currentData()
        source, probe = ctx.source, ctx.probe
        if not probe.has_audio and op != "replace":
            raise ToolError("editor.error.needs_audio")
        keep_ext = source.suffix.lstrip(".") or "mp4"
        if op == "extract":
            fmt = str(self.fmt.currentData())
            return ft.build_extract_audio(source, safe_output(source, fmt), probe, fmt)
        if op == "remove":
            _needs_video(ctx)
            return ft.build_remove_audio(source, safe_output(source, keep_ext), probe)
        if op == "replace":
            _needs_video(ctx)
            audio = _needs_file(self.replacement.path())
            return ft.build_replace_audio(source, audio, safe_output(source, "mp4"), probe)
        if op == "normalize":
            out = safe_output(source, keep_ext if not probe.has_video else "mp4")
            return ft.build_normalize(source, out, probe, self.lufs.value())
        try:
            filters = ft.audio_filters(
                probe, self.volume.value(), self.fade_in.value(), self.fade_out.value()
            )
        except ValueError as exc:
            raise ToolError("editor.error.no_duration") from exc
        channels, rate = int(self.channels.currentData()), int(self.rate.currentData())
        if not filters and not channels and not rate:
            raise ToolError("editor.error.nothing_to_do")
        out = safe_output(source, keep_ext if not probe.has_video else "mp4")
        return ft.build_audio_adjust(source, out, probe, filters, channels, rate)


class SubtitlesForm(ToolForm):
    key = "subtitles"

    def __init__(self) -> None:
        super().__init__()
        form = QFormLayout(self)
        self.mode = _combo(("embed", "burn", "extract"), "editor.subs.mode", "embed")
        self.file = FileField(self, "*.srt *.ass *.vtt")
        self.font_edit = QLineEdit("Arial")
        self.size_spin = _spin(8, 120, 24)
        self.hint = _hint()
        form.addRow(self.label("editor.subs.operation"), self.mode)
        form.addRow(self.label("editor.subs.file"), self.file)
        form.addRow(self.label("editor.subs.font"), self.font_edit)
        form.addRow(self.label("editor.subs.size"), self.size_spin)
        form.addRow(self.hint)
        self.mode.currentIndexChanged.connect(self.refresh_hints)
        self.refresh_hints()

    def refresh_hints(self) -> None:
        mode = self.mode.currentData()
        self.file.setEnabled(mode != "extract")
        self.font_edit.setEnabled(mode == "burn")
        self.size_spin.setEnabled(mode == "burn")
        self.hint.setText(tr(f"editor.subs.hint.{mode}"))

    def plan(self, ctx: ToolContext) -> EditPlan:
        mode = self.mode.currentData()
        source = ctx.source
        if mode == "extract":
            if not any(s.kind == "subtitle" for s in ctx.probe.streams):
                raise ToolError("editor.error.no_subtitles")
            return ft.build_extract_subtitles(source, safe_output(source, "srt", ""), ctx.probe)
        _needs_video(ctx)
        subs = _needs_file(self.file.path())
        if mode == "embed":
            ext = "mkv" if source.suffix.lower() == ".mkv" else "mp4"
            return ft.build_embed_subtitles(source, subs, safe_output(source, ext), ctx.probe)
        font = self.font_edit.text().strip() or "Arial"
        return ft.build_burn_subtitles(
            source, subs, safe_output(source, "mp4"), ctx.probe, font, self.size_spin.value()
        )


class WatermarkForm(ToolForm):
    key = "watermark"

    def __init__(self) -> None:
        super().__init__()
        form = QFormLayout(self)
        self.kind = _combo(("image", "text"), "editor.watermark.kind", "image")
        self.image = FileField(self, "*.png *.jpg *.jpeg *.webp")
        self.text_edit = QLineEdit()
        self.position = _combo(tuple(ft.POSITIONS), "editor.watermark.position", "bottom_right")
        self.opacity = _dspin(0.05, 1, 0.8, 0.05)
        self.scale = _dspin(0.02, 1, 0.2, 0.05)
        self.size_spin = _spin(8, 200, 32)
        form.addRow(self.label("editor.watermark.kind"), self.kind)
        form.addRow(self.label("editor.watermark.image"), self.image)
        form.addRow(self.label("editor.watermark.text"), self.text_edit)
        form.addRow(self.label("editor.watermark.position"), self.position)
        form.addRow(self.label("editor.watermark.opacity"), self.opacity)
        form.addRow(self.label("editor.watermark.scale"), self.scale)
        form.addRow(self.label("editor.watermark.size"), self.size_spin)
        self.kind.currentIndexChanged.connect(self.refresh_hints)
        self.refresh_hints()

    def refresh_hints(self) -> None:
        image = self.kind.currentData() == "image"
        self.image.setEnabled(image)
        self.scale.setEnabled(image)
        self.text_edit.setEnabled(not image)
        self.size_spin.setEnabled(not image)

    def plan(self, ctx: ToolContext) -> EditPlan:
        _needs_video(ctx)
        out = safe_output(ctx.source, "mp4")
        position = str(self.position.currentData())
        if self.kind.currentData() == "image":
            image = _needs_file(self.image.path())
            return ft.build_image_watermark(
                ctx.source,
                image,
                out,
                ctx.probe,
                position,
                self.opacity.value(),
                self.scale.value(),
            )
        text = self.text_edit.text().strip()
        if not text:
            raise ToolError("editor.error.needs_text")
        return ft.build_text_watermark(
            ctx.source, out, ctx.probe, text, position, self.opacity.value(), self.size_spin.value()
        )


class AnimationForm(ToolForm):
    key = "animation"

    def __init__(self) -> None:
        super().__init__()
        form = QFormLayout(self)
        self.fmt = _combo(("gif", "webp"), "editor.animation.format", "gif")
        self.start = TimeEdit()
        self.end = TimeEdit()
        self.fps = _spin(1, 60, 12, " fps")
        self.width_spin = _spin(32, 3840, 480, " px")
        hint = _hint()
        self.text(hint.setText, "editor.animation.hint")
        form.addRow(self.label("editor.animation.format"), self.fmt)
        form.addRow(self.label("editor.start"), self.start)
        form.addRow(self.label("editor.end"), self.end)
        form.addRow(self.label("editor.animation.fps"), self.fps)
        form.addRow(self.label("editor.transform.width"), self.width_spin)
        form.addRow(hint)

    def on_markers(self, start: float | None, end: float | None) -> None:
        self.start.set_seconds(start)
        self.end.set_seconds(end)

    def plan(self, ctx: ToolContext) -> EditPlan:
        _needs_video(ctx)
        start = self.start.seconds() or 0.0
        end = self.end.seconds()
        if end is None:
            end = min(start + 5, ctx.probe.duration or start + 5)
        if end <= start:
            raise ToolError("editor.error.bad_range")
        fmt = str(self.fmt.currentData())
        out = safe_output(ctx.source, fmt, "")
        return ft.build_animation(
            ctx.source, out, start, end, self.fps.value(), self.width_spin.value()
        )


class SnapshotForm(ToolForm):
    key = "snapshot"

    def __init__(self) -> None:
        super().__init__()
        form = QFormLayout(self)
        self.mode = _combo(("current", "every"), "editor.snapshot.mode", "current")
        self.every = _dspin(0.1, 3600, 10, 1, " s")
        form.addRow(self.label("editor.snapshot.mode"), self.mode)
        form.addRow(self.label("editor.snapshot.every"), self.every)

    def plan(self, ctx: ToolContext) -> EditPlan:
        _needs_video(ctx)
        if self.mode.currentData() == "current":
            out = safe_output(ctx.source, "png", f"_{round(ctx.position * 1000)}ms")
            return ft.build_snapshot(ctx.source, out, ctx.position)
        folder = ctx.source.with_name(f"{ctx.source.stem}_capturas")
        counter = 1
        while folder.exists():
            folder = ctx.source.with_name(f"{ctx.source.stem}_capturas ({counter})")
            counter += 1
        return ft.build_snapshots_every(
            ctx.source, folder, ctx.probe, self.every.value(), ctx.source.stem
        )


class MetadataForm(ToolForm):
    key = "metadata"

    def __init__(self) -> None:
        super().__init__()
        form = QFormLayout(self)
        self.fields: dict[str, QLineEdit] = {}
        for name in ft.METADATA_FIELDS:
            edit = QLineEdit()
            self.fields[name] = edit
            form.addRow(self.label(f"editor.metadata.{name}"), edit)
        self.cover = FileField(self, "*.png *.jpg *.jpeg")
        form.addRow(self.label("editor.metadata.cover"), self.cover)
        hint = _hint()
        self.text(hint.setText, "editor.metadata.hint")
        form.addRow(hint)

    def plan(self, ctx: ToolContext) -> EditPlan:
        tags = {k: e.text().strip() for k, e in self.fields.items() if e.text().strip()}
        cover = self.cover.path()
        if cover is not None:
            _needs_file(cover)
            if ctx.probe.has_video:
                raise ToolError("editor.error.cover_audio_only")
        if not tags and cover is None:
            raise ToolError("editor.error.nothing_to_do")
        ext = ctx.source.suffix.lstrip(".") or "mp4"
        return ft.build_metadata(ctx.source, safe_output(ctx.source, ext), ctx.probe, tags, cover)
