"""Lista de la cola de edición (pestaña "Ediciones" de la página Cola)."""

from __future__ import annotations

import contextlib

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from bombastic.core.edit_manager import EDIT_FINISHED, EditManager, EditState, EditTask
from bombastic.core.formatting import format_bytes
from bombastic.core.i18n import tr
from bombastic.ui.download_card import ElidedLabel

_STEPS = 1000


def edit_status_text(task: EditTask) -> str:
    state = task.state
    if state is EditState.FAILED:
        return tr(
            "editor.status.failed",
            message=tr(f"editor.error.{task.error_code}", detail=task.error_detail),
        )
    if state is EditState.COMPLETED:
        size = ""
        with contextlib.suppress(OSError):
            size = format_bytes(task.plan.output.stat().st_size)
        return tr("editor.status.completed", name=task.plan.output.name, size=size)
    text = tr(f"editor.status.{state.value}")
    if state is EditState.RUNNING:
        if task.fraction is not None:
            text += f" · {round(task.fraction * 100)} %"
        if task.speed:
            text += f" · {task.speed:g}x"
        if len(task.plan.passes) > 1:
            text += " · " + tr("editor.status.passes", count=len(task.plan.passes))
    return text


class EditCard(QFrame):
    def __init__(self, manager: EditManager, task: EditTask) -> None:
        super().__init__()
        self.setObjectName("DownloadCard")
        self.manager = manager
        self.task = task
        self.title = ElidedLabel()
        self.title.setObjectName("CardTitle")
        self.status = ElidedLabel()
        self.status.setObjectName("CardStatus")
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(6)
        self.pause_button = QPushButton()
        self.cancel_button = QPushButton()
        self.retry_button = QPushButton()
        self.open_button = QPushButton()
        self.folder_button = QPushButton()
        self.log_button = QPushButton()
        self.remove_button = QPushButton()
        self.up_button = QPushButton("↑")
        self.down_button = QPushButton("↓")
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        for button in (
            self.pause_button,
            self.cancel_button,
            self.retry_button,
            self.open_button,
            self.folder_button,
            self.log_button,
            self.remove_button,
            self.up_button,
            self.down_button,
        ):
            buttons.addWidget(button)
        buttons.addStretch(1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.addWidget(self.title)
        layout.addWidget(self.status)
        layout.addWidget(self.bar)
        layout.addLayout(buttons)
        tid = task.task_id
        self.pause_button.clicked.connect(self._toggle_pause)
        self.cancel_button.clicked.connect(lambda: manager.cancel(tid))
        self.retry_button.clicked.connect(lambda: manager.retry(tid))
        self.remove_button.clicked.connect(lambda: manager.remove(tid))
        self.up_button.clicked.connect(lambda: manager.move(tid, -1))
        self.down_button.clicked.connect(lambda: manager.move(tid, 1))
        self.open_button.clicked.connect(lambda: self._open(self.task.plan.output))
        self.folder_button.clicked.connect(lambda: self._open(self.task.plan.output.parent))
        self.log_button.clicked.connect(self._show_log)
        self.refresh()

    def _toggle_pause(self) -> None:
        if self.task.state is EditState.PAUSED:
            self.manager.resume(self.task.task_id)
        else:
            self.manager.pause(self.task.task_id)

    @staticmethod
    def _open(path: object) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _show_log(self) -> None:
        box = QMessageBox(
            QMessageBox.Icon.Information, tr("queue.log.title"), self.task.title, parent=self
        )
        box.setDetailedText("\n\n".join(self.task.commands) + "\n\n" + "\n".join(self.task.log))
        box.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        box.open()

    def refresh(self) -> None:
        task, state = self.task, self.task.state
        self.title.set_full_text(task.title)
        self.status.set_full_text(edit_status_text(task))
        is_error = state is EditState.FAILED
        if self.status.property("error") != is_error:
            self.status.setProperty("error", is_error)
            self.status.style().unpolish(self.status)
            self.status.style().polish(self.status)
        if state is EditState.RUNNING and task.fraction is None:
            self.bar.setRange(0, 0)
        else:
            self.bar.setRange(0, _STEPS)
            self.bar.setValue(round((task.fraction or 0) * _STEPS))
        self.bar.setVisible(state in (EditState.RUNNING, EditState.QUEUED, EditState.PAUSED))
        paused = state is EditState.PAUSED
        self.pause_button.setText(tr("downloads.card.resume" if paused else "downloads.card.pause"))
        self.pause_button.setVisible(state in (EditState.QUEUED, EditState.RUNNING) or paused)
        self.cancel_button.setText(tr("downloads.card.cancel"))
        self.cancel_button.setVisible(state not in EDIT_FINISHED)
        self.retry_button.setText(tr("downloads.card.retry"))
        self.retry_button.setVisible(state in (EditState.FAILED, EditState.CANCELLED))
        self.open_button.setText(tr("downloads.menu.open_file"))
        self.open_button.setVisible(state is EditState.COMPLETED)
        self.folder_button.setText(tr("downloads.card.open_folder"))
        self.folder_button.setVisible(state is EditState.COMPLETED)
        self.log_button.setText(tr("editor.queue.details"))
        self.remove_button.setText(tr("downloads.card.remove"))
        self.remove_button.setVisible(state in EDIT_FINISHED or paused)


class EditQueueView(QWidget):
    def __init__(self, manager: EditManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.manager = manager
        self.cards: dict[int, EditCard] = {}
        self.empty_label = QLabel()
        self.empty_label.setObjectName("Placeholder")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setWordWrap(True)
        self.clear_button = QPushButton()
        top = QHBoxLayout()
        top.addStretch(1)
        top.addWidget(self.clear_button)
        host = QWidget()
        self._layout = QVBoxLayout(host)
        self._layout.setContentsMargins(0, 0, 8, 0)
        self._layout.setSpacing(10)
        self._layout.addWidget(self.empty_label)
        self._layout.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(host)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.addLayout(top)
        layout.addWidget(scroll, 1)
        self.clear_button.clicked.connect(self.clear_finished)
        manager.task_added.connect(self._sync)
        manager.task_changed.connect(self._sync)
        manager.task_removed.connect(self._drop)
        self.retranslate()

    def retranslate(self) -> None:
        self.empty_label.setText(tr("editor.queue.empty"))
        self.clear_button.setText(tr("queue.clear_finished"))
        for card in self.cards.values():
            card.refresh()
        self._refresh()

    def clear_finished(self) -> None:
        for task in self.manager.tasks():
            if task.state in EDIT_FINISHED:
                self.manager.remove(task.task_id)

    def _sync(self, task_id: int) -> None:
        task = self.manager.task(task_id)
        if task is None:
            return
        card = self.cards.get(task_id)
        if card is None:
            card = EditCard(self.manager, task)
            self.cards[task_id] = card
        card.refresh()
        for index, item in enumerate(self.manager.tasks(), start=1):
            widget = self.cards.get(item.task_id)
            if widget is not None and self._layout.indexOf(widget) != index:
                self._layout.insertWidget(index, widget)
        self._refresh()

    def _drop(self, task_id: int) -> None:
        card = self.cards.pop(task_id, None)
        if card is not None:
            self._layout.removeWidget(card)
            card.deleteLater()
        self._refresh()

    def _refresh(self) -> None:
        tasks = self.manager.tasks()
        self.empty_label.setVisible(not tasks)
        self.clear_button.setEnabled(any(t.state in EDIT_FINISHED for t in tasks))
