"""Página de la cola: descargas en marcha, en espera, en pausa y terminadas."""

from __future__ import annotations

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from bombastic.core.download_manager import FINISHED, QUEUE_STATES, DownloadManager, ItemState
from bombastic.core.edit_manager import EditManager
from bombastic.core.i18n import tr
from bombastic.core.thumbnails import ThumbnailLoader
from bombastic.ui.download_card import DownloadCard, error_text, output_folder
from bombastic.ui.edit_queue import EditQueueView
from bombastic.ui.pages import Page


class QueuePage(Page):
    def __init__(
        self,
        manager: DownloadManager,
        thumbnails: ThumbnailLoader,
        edits: EditManager | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__("queue", parent)
        self.manager = manager
        self.thumbnails = thumbnails
        self.cards: dict[int, DownloadCard] = {}

        self.summary_label = QLabel()
        self.summary_label.setProperty("muted", True)
        self.pause_all_button = QPushButton()
        self.resume_all_button = QPushButton()
        self.retry_failed_button = QPushButton()
        self.clear_button = QPushButton()
        actions = QHBoxLayout()
        actions.setSpacing(10)
        actions.addWidget(self.summary_label, 1)
        for button in (
            self.pause_all_button,
            self.resume_all_button,
            self.retry_failed_button,
            self.clear_button,
        ):
            actions.addWidget(button)

        self.empty_label = QLabel()
        self.empty_label.setObjectName("Placeholder")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setWordWrap(True)
        host = QWidget()
        self._cards_layout = QVBoxLayout(host)
        self._cards_layout.setContentsMargins(0, 0, 8, 0)
        self._cards_layout.setSpacing(10)
        self._cards_layout.addWidget(self.empty_label)
        self._cards_layout.addStretch(1)
        self.cards_scroll = QScrollArea()
        self.cards_scroll.setWidgetResizable(True)
        self.cards_scroll.setWidget(host)

        downloads = QWidget()
        column = QVBoxLayout(downloads)
        column.setContentsMargins(0, 8, 0, 0)
        column.addLayout(actions)
        column.addWidget(self.cards_scroll, 1)
        self.tabs = QTabWidget()
        self.tabs.addTab(downloads, "")
        self.edit_view = EditQueueView(edits) if edits is not None else None
        if self.edit_view is not None:
            self.tabs.addTab(self.edit_view, "")
        self.body.addWidget(self.tabs, 1)

        self.pause_all_button.clicked.connect(manager.pause_all)
        self.resume_all_button.clicked.connect(manager.resume_all)
        self.retry_failed_button.clicked.connect(self.retry_failed)
        self.clear_button.clicked.connect(self.clear_finished)
        manager.item_added.connect(self._sync)
        manager.item_changed.connect(self._sync)
        manager.item_removed.connect(self._drop)
        thumbnails.loaded.connect(self._on_thumbnail_loaded)

        self.retranslate()
        self._refresh_actions()

    def retranslate(self) -> None:
        super().retranslate()
        self.pause_all_button.setText(tr("queue.pause_all"))
        self.resume_all_button.setText(tr("queue.resume_all"))
        self.retry_failed_button.setText(tr("queue.retry_failed"))
        self.clear_button.setText(tr("queue.clear_finished"))
        self.empty_label.setText(tr("queue.empty"))
        self.tabs.setTabText(0, tr("queue.tab.downloads"))
        if self.edit_view is not None:
            self.tabs.setTabText(1, tr("queue.tab.edits"))
            self.edit_view.retranslate()
        for card in self.cards.values():
            card.retranslate()
        self._refresh_actions()

    # ------------------------------------------------------------------ tarjetas

    def _sync(self, item_id: int) -> None:
        """Crea, actualiza o recoloca la tarjeta de un elemento."""
        item = self.manager.item(item_id)
        if item is None or item.state not in QUEUE_STATES:
            self._drop(item_id)
            return
        card = self.cards.get(item_id)
        if card is None:
            card = DownloadCard(item)
            card.download_requested.connect(self.manager.retry)
            card.pause_toggled.connect(self._toggle_pause)
            card.cancel_requested.connect(self.manager.cancel)
            card.remove_requested.connect(self.manager.remove)
            card.open_folder_requested.connect(self._open_folder)
            card.menu_requested.connect(self._on_menu)
            self.cards[item_id] = card
            if item.info is not None and item.info.thumbnail_url:
                self.thumbnails.request(item.info.thumbnail_url)
        card.refresh()
        self._place_cards()
        self._refresh_actions()

    def _drop(self, item_id: int) -> None:
        card = self.cards.pop(item_id, None)
        if card is not None:
            self._cards_layout.removeWidget(card)
            card.deleteLater()
        self._refresh_actions()

    def _place_cards(self) -> None:
        """Ordena las tarjetas como la cola (solo mueve las que están fuera de sitio)."""
        for index, item in enumerate(self.manager.queue_items(), start=1):
            card = self.cards.get(item.item_id)
            if card is not None and self._cards_layout.indexOf(card) != index:
                self._cards_layout.insertWidget(index, card)

    def _on_thumbnail_loaded(self, url: str, path: str) -> None:
        for card in self.cards.values():
            info = card.item.info
            if info is not None and info.thumbnail_url == url and not card.has_thumbnail():
                card.set_thumbnail(path)

    def _refresh_actions(self) -> None:
        items = self.manager.queue_items()
        states = [item.state for item in items]
        self.empty_label.setVisible(not items)
        active = sum(1 for s in states if s in (ItemState.DOWNLOADING, ItemState.PROCESSING))
        waiting = states.count(ItemState.QUEUED)
        self.summary_label.setText(
            tr("queue.summary", active=active, waiting=waiting, total=len(items)) if items else ""
        )
        self.pause_all_button.setEnabled(active + waiting > 0)
        self.resume_all_button.setEnabled(ItemState.PAUSED in states)
        self.retry_failed_button.setEnabled(ItemState.FAILED in states)
        self.clear_button.setEnabled(any(s in FINISHED for s in states))

    # ------------------------------------------------------------------ acciones

    def retry_failed(self) -> None:
        for item in self.manager.queue_items():
            if item.state is ItemState.FAILED:
                self.manager.retry(item.item_id)

    def clear_finished(self) -> None:
        for item in self.manager.queue_items():
            if item.state in FINISHED:
                self.manager.remove(item.item_id)

    def _toggle_pause(self, item_id: int) -> None:
        item = self.manager.item(item_id)
        if item is not None and item.state is ItemState.PAUSED:
            self.manager.resume(item_id)
        else:
            self.manager.pause(item_id)

    def _open_folder(self, item_id: int) -> None:
        item = self.manager.item(item_id)
        folder = output_folder(item) if item is not None else None
        if folder is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _on_menu(self, item_id: int, action: str) -> None:
        item = self.manager.item(item_id)
        if item is None:
            return
        if action in ("up", "down"):
            self.manager.move(item_id, -1 if action == "up" else 1)
        elif action == "open_file" and item.files:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(item.files[0])))
        elif action == "copy_url":
            QGuiApplication.clipboard().setText(item.url)
        elif action == "log":
            self._show_text(tr("queue.log.title"), error_text(item) or item.title, item.log)
        elif action == "command":
            self._show_text(tr("queue.command.title"), item.title, [item.command])

    def _show_text(self, title: str, summary: str, lines: list[str]) -> None:
        """Muestra un texto largo seleccionable (log o comando) en "Mostrar detalles"."""
        box = QMessageBox(QMessageBox.Icon.Information, title, summary, parent=self)
        box.setDetailedText("\n".join(lines))
        box.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        box.open()
