"""Tarjeta de un enlace: miniatura, datos, estado, progreso y acciones."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRect, QSize, Qt, Signal
from PySide6.QtGui import QAction, QPixmap, QResizeEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from bombastic.core.download_manager import (
    ACTIVE,
    CANCELLABLE,
    PAUSABLE,
    QUEUE_STATES,
    DownloadItem,
    ItemState,
)
from bombastic.core.formatting import format_bytes, format_duration, format_speed
from bombastic.core.i18n import tr

THUMBNAIL_SIZE = QSize(160, 90)
#: Acciones del menú "Más" de las tarjetas de la cola, en orden.
MENU_ACTIONS: tuple[str, ...] = ("up", "down", "open_file", "copy_url", "log", "command")
_BAR_STEPS = 1000


class ElidedLabel(QLabel):
    """Etiqueta de una línea que recorta el texto con "…" y lo muestra entero al pasar el ratón."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._full_text = ""
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(60)

    def full_text(self) -> str:
        return self._full_text

    def set_full_text(self, text: str) -> None:
        self._full_text = text
        self._refresh()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._refresh()

    def _refresh(self) -> None:
        elided = self.fontMetrics().elidedText(
            self._full_text, Qt.TextElideMode.ElideRight, max(0, self.width())
        )
        self.setText(elided)
        self.setToolTip(self._full_text if elided != self._full_text else "")


def error_text(item: DownloadItem) -> str:
    """Mensaje de error del elemento en el idioma actual."""
    if not item.error_code:
        return ""
    return tr(f"downloads.error.{item.error_code}", detail=item.error_detail)


def meta_text(item: DownloadItem) -> str:
    """Canal, duración y tipo de enlace, separados por puntos."""
    info = item.info
    if info is None:
        return ""
    parts: list[str] = []
    if info.channel:
        parts.append(info.channel)
    if info.is_playlist:
        if info.entry_count is not None:
            parts.append(tr("downloads.card.playlist", count=info.entry_count))
        else:
            parts.append(tr("downloads.card.playlist_unknown"))
    elif info.is_live:
        parts.append(tr("downloads.card.live"))
    else:
        duration = format_duration(info.duration)
        if duration:
            parts.append(duration)
    return " · ".join(parts)


def status_text(item: DownloadItem) -> str:
    """Línea de estado del elemento en el idioma actual."""
    state = item.state
    if state is ItemState.INFO_ERROR:
        return tr("downloads.status.info_error", message=error_text(item))
    if state is ItemState.FAILED:
        return tr("downloads.status.failed", message=error_text(item))
    if state is ItemState.COMPLETED:
        if len(item.files) == 1:
            return tr("downloads.status.completed_file", name=item.files[0].name)
        if len(item.files) > 1:
            return tr("downloads.status.completed_files", count=len(item.files))
        return tr("downloads.status.completed")
    if state not in ACTIVE or item.snapshot is None:
        return tr(f"downloads.status.{state.value}")

    snapshot = item.snapshot
    parts: list[str] = []
    if snapshot.item_index is not None and snapshot.item_count:
        parts.append(
            tr("downloads.progress.item", index=snapshot.item_index, count=snapshot.item_count)
        )
    parts.append(tr(f"downloads.status.{state.value}"))
    if snapshot.fraction is not None:
        parts.append(f"{round(snapshot.fraction * 100)} %")
    if state is ItemState.DOWNLOADING:
        done = format_bytes(snapshot.downloaded)
        total = format_bytes(snapshot.total)
        if done and total:
            parts.append(tr("downloads.progress.size", done=done, total=total))
        elif done:
            parts.append(done)
        speed = format_speed(snapshot.speed)
        if speed:
            parts.append(speed)
        eta = format_duration(snapshot.eta)
        if eta:
            parts.append(tr("downloads.progress.eta", time=eta))
    return " · ".join(parts)


def output_folder(item: DownloadItem) -> Path | None:
    """Carpeta donde está (o estará) lo descargado."""
    for file in item.files:
        if file.parent.is_dir():
            return file.parent
    if item.options is not None:
        return item.options.output_dir
    return None


class DownloadCard(QFrame):
    download_requested = Signal(int)
    retry_info_requested = Signal(int)
    cancel_requested = Signal(int)
    remove_requested = Signal(int)
    open_folder_requested = Signal(int)
    #: Pausar o reanudar, según el estado.
    pause_toggled = Signal(int)
    #: ``(id, acción)`` con una acción de :data:`MENU_ACTIONS`.
    menu_requested = Signal(int, str)

    def __init__(self, item: DownloadItem, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("DownloadCard")
        self.item_id = item.item_id
        self._item = item
        self._has_thumbnail = False

        self.thumbnail = QLabel()
        self.thumbnail.setObjectName("Thumbnail")
        self.thumbnail.setFixedSize(THUMBNAIL_SIZE)
        self.thumbnail.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.title_label = ElidedLabel()
        self.title_label.setObjectName("CardTitle")
        self.meta_label = ElidedLabel()
        self.meta_label.setProperty("muted", True)
        self.status_label = ElidedLabel()
        self.status_label.setObjectName("CardStatus")
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(6)

        self.download_button = QPushButton()
        self.download_button.setProperty("primary", True)
        self.pause_button = QPushButton()
        self.cancel_button = QPushButton()
        self.open_button = QPushButton()
        self.remove_button = QPushButton()
        self.more_button = QToolButton()
        self.more_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.more_menu = QMenu(self.more_button)
        self._menu_actions: dict[str, QAction] = {}
        for key in MENU_ACTIONS:
            action = self.more_menu.addAction("")
            action.triggered.connect(
                lambda _=False, k=key: self.menu_requested.emit(self.item_id, k)
            )
            self._menu_actions[key] = action
        self.more_button.setMenu(self.more_menu)
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        for button in (
            self.download_button,
            self.pause_button,
            self.cancel_button,
            self.open_button,
            self.remove_button,
            self.more_button,
        ):
            buttons.addWidget(button)
        buttons.addStretch(1)

        column = QVBoxLayout()
        column.setSpacing(4)
        column.addWidget(self.title_label)
        column.addWidget(self.meta_label)
        column.addWidget(self.status_label)
        column.addWidget(self.progress_bar)
        column.addSpacing(4)
        column.addLayout(buttons)
        column.addStretch(1)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(14)
        layout.addWidget(self.thumbnail, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(column, 1)

        self.download_button.clicked.connect(self._on_primary)
        self.pause_button.clicked.connect(lambda: self.pause_toggled.emit(self.item_id))
        self.cancel_button.clicked.connect(lambda: self.cancel_requested.emit(self.item_id))
        self.open_button.clicked.connect(lambda: self.open_folder_requested.emit(self.item_id))
        self.remove_button.clicked.connect(lambda: self.remove_requested.emit(self.item_id))

        self.refresh()

    @property
    def item(self) -> DownloadItem:
        return self._item

    def _on_primary(self) -> None:
        if self._item.state is ItemState.INFO_ERROR:
            self.retry_info_requested.emit(self.item_id)
        else:
            self.download_requested.emit(self.item_id)

    def set_thumbnail(self, path: str) -> None:
        """Muestra la miniatura recortada al tamaño de la tarjeta, nítida con DPI alto."""
        source = QPixmap(path)
        if source.isNull():
            return
        ratio = self.devicePixelRatioF()
        target = QSize(
            round(THUMBNAIL_SIZE.width() * ratio), round(THUMBNAIL_SIZE.height() * ratio)
        )
        scaled = source.scaled(
            target,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        crop = QRect(
            (scaled.width() - target.width()) // 2,
            (scaled.height() - target.height()) // 2,
            target.width(),
            target.height(),
        )
        pixmap = scaled.copy(crop)
        pixmap.setDevicePixelRatio(ratio)
        self.thumbnail.setPixmap(pixmap)
        self._has_thumbnail = True

    def has_thumbnail(self) -> bool:
        return self._has_thumbnail

    def retranslate(self) -> None:
        self.refresh()

    def refresh(self) -> None:
        """Pinta el estado actual del elemento."""
        item = self._item
        state = item.state
        self.title_label.set_full_text(item.info.title if item.info is not None else item.url)
        meta = meta_text(item)
        self.meta_label.set_full_text(meta)
        self.meta_label.setVisible(bool(meta))
        self.status_label.set_full_text(status_text(item))
        is_error = state in (ItemState.FAILED, ItemState.INFO_ERROR)
        if self.status_label.property("error") != is_error:
            self.status_label.setProperty("error", is_error)
            # Hay que repasar el estilo para que el cambio de propiedad se vea.
            self.status_label.style().unpolish(self.status_label)
            self.status_label.style().polish(self.status_label)

        busy = state in ACTIVE or state in (ItemState.QUEUED, ItemState.FETCHING)
        paused = state is ItemState.PAUSED
        self.progress_bar.setVisible(busy)
        fraction = item.snapshot.fraction if item.snapshot is not None else None
        if state is ItemState.DOWNLOADING and fraction is not None:
            self.progress_bar.setRange(0, _BAR_STEPS)
            self.progress_bar.setValue(round(fraction * _BAR_STEPS))
        elif state is ItemState.QUEUED or paused:
            self.progress_bar.setRange(0, _BAR_STEPS)
            self.progress_bar.setValue(round((fraction or 0) * _BAR_STEPS) if paused else 0)
        else:
            # Sin dato de avance (o procesando): barra animada.
            self.progress_bar.setRange(0, 0)

        self.pause_button.setText(
            tr("downloads.card.resume" if state is ItemState.PAUSED else "downloads.card.pause")
        )
        self.pause_button.setVisible(state in PAUSABLE or state is ItemState.PAUSED)
        self.more_button.setText(tr("downloads.card.more"))
        self.more_button.setVisible(state in QUEUE_STATES)
        for key, action in self._menu_actions.items():
            action.setText(tr(f"downloads.menu.{key}"))
        self._menu_actions["open_file"].setEnabled(bool(item.files))
        self._menu_actions["log"].setEnabled(bool(item.log))
        self._menu_actions["command"].setEnabled(bool(item.command))

        retry = state in (ItemState.FAILED, ItemState.CANCELLED, ItemState.INFO_ERROR)
        self.download_button.setText(
            tr("downloads.card.retry" if retry else "downloads.card.download")
        )
        self.download_button.setVisible(state is ItemState.READY or retry)
        self.cancel_button.setText(tr("downloads.card.cancel"))
        self.cancel_button.setVisible(state in CANCELLABLE)
        self.open_button.setText(tr("downloads.card.open_folder"))
        self.open_button.setVisible(state is ItemState.COMPLETED)
        self.remove_button.setText(tr("downloads.card.remove"))
        self.remove_button.setVisible(state not in ACTIVE and state is not ItemState.QUEUED)
        self.progress_bar.setVisible(busy or state is ItemState.PAUSED)
