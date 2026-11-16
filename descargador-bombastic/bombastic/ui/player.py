"""Reproductor con vista previa, barra de tiempo con marcadores de inicio (I) y fin (O)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRect, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QPainter, QPaintEvent
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QStyle,
    QStyleOptionSlider,
    QVBoxLayout,
    QWidget,
)

from bombastic.core.formatting import format_timecode
from bombastic.core.i18n import tr

SPEEDS: tuple[float, ...] = (0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0)
#: Paso de "fotograma a fotograma" si no se conoce el fps.
_DEFAULT_FPS = 30.0


class MarkerSlider(QSlider):
    """Barra de tiempo (milisegundos) que dibuja el tramo entre los marcadores I y O."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.marker_in: int | None = None
        self.marker_out: int | None = None
        #: La pone la página con el color de acento del tema.
        self.marker_color = QColor()

    def _x(self, value: int) -> int:
        option = QStyleOptionSlider()
        self.initStyleOption(option)
        groove = self.style().subControlRect(
            QStyle.ComplexControl.CC_Slider, option, QStyle.SubControl.SC_SliderGroove, self
        )
        span = max(1, self.maximum() - self.minimum())
        return groove.left() + round((value - self.minimum()) * groove.width() / span)

    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)
        if self.marker_in is None and self.marker_out is None:
            return
        painter = QPainter(self)
        color = QColor(self.marker_color)
        start = self._x(self.marker_in if self.marker_in is not None else self.minimum())
        end = self._x(self.marker_out if self.marker_out is not None else self.maximum())
        color.setAlpha(70)
        painter.fillRect(QRect(start, 2, max(1, end - start), self.height() - 4), color)
        color.setAlpha(255)
        for value in (self.marker_in, self.marker_out):
            if value is not None:
                painter.fillRect(QRect(self._x(value) - 1, 0, 3, self.height()), color)
        painter.end()


class PlayerWidget(QWidget):
    #: Han cambiado los marcadores: ``(inicio o None, fin o None)`` en segundos.
    markers_changed = Signal(object, object)
    #: El reproductor no puede abrir el archivo (códec no soportado…).
    playback_failed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Player")
        self.fps = _DEFAULT_FPS
        self.marker_in: float | None = None
        self.marker_out: float | None = None
        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.player.setAudioOutput(self.audio)
        self.video = QVideoWidget()
        self.video.setMinimumHeight(220)
        self.player.setVideoOutput(self.video)

        self.slider = MarkerSlider()
        self.slider.setObjectName("Timeline")
        self.time_label = QLabel(format_timecode(0))
        self.play_button = QPushButton()
        self.back5 = QPushButton("-5 s")
        self.back1 = QPushButton("-1 s")
        self.frame_back = QPushButton("◀|")
        self.frame_forward = QPushButton("|▶")
        self.fwd1 = QPushButton("+1 s")
        self.fwd5 = QPushButton("+5 s")
        self.in_button = QPushButton()
        self.out_button = QPushButton()
        self.clear_markers_button = QPushButton()
        self.speed_combo = QComboBox()
        for speed in SPEEDS:
            self.speed_combo.addItem(f"{speed:g}x", speed)
        self.speed_combo.setCurrentIndex(SPEEDS.index(1.0))
        self.volume = QSlider(Qt.Orientation.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setValue(80)
        self.volume.setFixedWidth(90)
        self.audio.setVolume(0.8)

        controls = QHBoxLayout()
        controls.setSpacing(6)
        for widget in (
            self.back5,
            self.back1,
            self.frame_back,
            self.play_button,
            self.frame_forward,
            self.fwd1,
            self.fwd5,
        ):
            controls.addWidget(widget)
        controls.addStretch(1)
        controls.addWidget(self.time_label)
        # Segunda fila: marcadores, velocidad y volumen (en una sola no caben).
        extras = QHBoxLayout()
        extras.setSpacing(6)
        extras.addWidget(self.in_button)
        extras.addWidget(self.out_button)
        extras.addWidget(self.clear_markers_button)
        extras.addStretch(1)
        extras.addWidget(self.speed_combo)
        extras.addWidget(self.volume)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.video, 1)
        layout.addWidget(self.slider)
        layout.addLayout(controls)
        layout.addLayout(extras)

        self.play_button.clicked.connect(self.toggle_play)
        self.back5.clicked.connect(lambda: self.seek_relative(-5))
        self.back1.clicked.connect(lambda: self.seek_relative(-1))
        self.fwd1.clicked.connect(lambda: self.seek_relative(1))
        self.fwd5.clicked.connect(lambda: self.seek_relative(5))
        self.frame_back.clicked.connect(lambda: self.step_frames(-1))
        self.frame_forward.clicked.connect(lambda: self.step_frames(1))
        self.in_button.clicked.connect(self.mark_in)
        self.out_button.clicked.connect(self.mark_out)
        self.clear_markers_button.clicked.connect(self.clear_markers)
        self.speed_combo.currentIndexChanged.connect(
            lambda: self.player.setPlaybackRate(float(self.speed_combo.currentData()))
        )
        self.volume.valueChanged.connect(lambda v: self.audio.setVolume(v / 100))
        self.slider.sliderMoved.connect(self.player.setPosition)
        self.player.durationChanged.connect(lambda d: self.slider.setRange(0, max(0, d)))
        self.player.positionChanged.connect(self._on_position)
        self.player.playbackStateChanged.connect(lambda _s: self.retranslate())
        self.player.errorOccurred.connect(
            lambda _e, text: self.playback_failed.emit(text or "error")
        )
        self.retranslate()

    def retranslate(self) -> None:
        playing = self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        self.play_button.setText(tr("player.pause" if playing else "player.play"))
        self.play_button.setToolTip(tr("player.play.tooltip"))
        self.in_button.setText(tr("player.mark_in"))
        self.in_button.setToolTip(tr("player.mark_in.tooltip"))
        self.out_button.setText(tr("player.mark_out"))
        self.out_button.setToolTip(tr("player.mark_out.tooltip"))
        self.clear_markers_button.setText(tr("player.clear_markers"))
        self.frame_back.setToolTip(tr("player.frame_back"))
        self.frame_forward.setToolTip(tr("player.frame_forward"))

    # ----------------------------------------------------------------- archivo

    def load(self, path: Path, fps: float | None = None) -> None:
        self.fps = fps or _DEFAULT_FPS
        self.clear_markers()
        self.player.setSource(QUrl.fromLocalFile(str(path)))

    def unload(self) -> None:
        self.player.stop()
        self.player.setSource(QUrl())

    # -------------------------------------------------------------- reproducción

    @property
    def position(self) -> float:
        return self.player.position() / 1000

    def toggle_play(self) -> None:
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def seek(self, seconds: float) -> None:
        duration = self.player.duration() / 1000
        limit = duration if duration > 0 else seconds
        self.player.setPosition(round(max(0.0, min(seconds, limit)) * 1000))

    def seek_relative(self, seconds: float) -> None:
        self.seek(self.position + seconds)

    def step_frames(self, frames: int) -> None:
        """Avance aproximado: QtMultimedia no da acceso a fotogramas exactos."""
        self.player.pause()
        self.seek_relative(frames / self.fps)

    def _on_position(self, millis: int) -> None:
        if not self.slider.isSliderDown():
            self.slider.setValue(millis)
        self.time_label.setText(format_timecode(millis / 1000))

    # ---------------------------------------------------------------- marcadores

    def mark_in(self) -> None:
        self.set_markers(self.position, self.marker_out)

    def mark_out(self) -> None:
        self.set_markers(self.marker_in, self.position)

    def clear_markers(self) -> None:
        self.set_markers(None, None)

    def set_markers(self, start: float | None, end: float | None) -> None:
        # Si se marcan al revés, se intercambian.
        if start is not None and end is not None and end < start:
            start, end = end, start
        self.marker_in, self.marker_out = start, end
        self.slider.marker_in = round(start * 1000) if start is not None else None
        self.slider.marker_out = round(end * 1000) if end is not None else None
        self.slider.update()
        self.markers_changed.emit(start, end)
