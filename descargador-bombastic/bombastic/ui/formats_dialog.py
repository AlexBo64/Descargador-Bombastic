"""Selector manual de formatos: tabla de la salida de ``-J`` con vídeo y audio por separado."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from bombastic.core.formatting import format_bytes
from bombastic.core.i18n import tr
from bombastic.core.media_info import FormatInfo

_COLUMNS = ("id", "ext", "resolution", "fps", "vcodec", "acodec", "bitrate", "size")


def format_spec(video: str, audio: str) -> str:
    """Construye el ``-f``: ``vídeo+audio``, solo uno de los dos o vacío."""
    return "+".join(part for part in (video, audio) if part)


def _cells(fmt: FormatInfo) -> list[str]:
    resolution = f"{fmt.width}x{fmt.height}" if fmt.width and fmt.height else (fmt.note or "")
    return [
        fmt.format_id,
        fmt.ext,
        resolution if fmt.has_video else "",
        f"{fmt.fps:g}" if fmt.fps else "",
        fmt.vcodec if fmt.has_video else "",
        fmt.acodec if fmt.has_audio else "",
        f"{fmt.bitrate:.0f} kbps" if fmt.bitrate else "",
        format_bytes(fmt.size) or "",
    ]


class FormatsDialog(QDialog):
    """Dos tablas: formatos con vídeo y formatos solo de audio. Se elige uno de cada (o ninguno)."""

    def __init__(self, formats: tuple[FormatInfo, ...], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("formats.title"))
        self.resize(820, 560)
        self.video_formats = [f for f in formats if f.has_video]
        self.audio_formats = [f for f in formats if f.has_audio and not f.has_video]
        self.video_table = self._table(self.video_formats)
        self.audio_table = self._table(self.audio_formats)
        hint = QLabel(tr("formats.hint"))
        hint.setWordWrap(True)
        hint.setProperty("muted", True)
        self.spec_label = QLabel()
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(hint)
        layout.addWidget(QLabel(tr("formats.video")))
        layout.addWidget(self.video_table, 3)
        layout.addWidget(QLabel(tr("formats.audio")))
        layout.addWidget(self.audio_table, 2)
        layout.addWidget(self.spec_label)
        layout.addWidget(self.buttons)
        self.video_table.itemSelectionChanged.connect(self._refresh)
        self.audio_table.itemSelectionChanged.connect(self._refresh)
        self._refresh()

    def _table(self, formats: list[FormatInfo]) -> QTableWidget:
        table = QTableWidget(len(formats), len(_COLUMNS))
        table.setHorizontalHeaderLabels([tr(f"formats.column.{c}") for c in _COLUMNS])
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        # yt-dlp ordena de peor a mejor; se muestran los mejores arriba.
        for row, fmt in enumerate(reversed(formats)):
            for column, text in enumerate(_cells(fmt)):
                table.setItem(row, column, QTableWidgetItem(text))
        return table

    @staticmethod
    def _selected(table: QTableWidget) -> str:
        rows = table.selectionModel().selectedRows()
        if not rows:
            return ""
        item = table.item(rows[0].row(), 0)
        return item.text() if item is not None else ""

    def spec(self) -> str:
        video = self._selected(self.video_table)
        audio = self._selected(self.audio_table)
        # Si el vídeo elegido ya lleva audio, no se añade otro.
        chosen = next((f for f in self.video_formats if f.format_id == video), None)
        if chosen is not None and chosen.has_audio:
            audio = ""
        return format_spec(video, audio)

    def _refresh(self) -> None:
        spec = self.spec()
        self.spec_label.setText(tr("formats.spec", spec=spec) if spec else tr("formats.none"))
        ok = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok.setEnabled(bool(spec))
