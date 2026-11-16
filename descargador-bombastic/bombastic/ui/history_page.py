"""Página de historial: todo lo descargado, con búsqueda, filtros y acciones."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
)

from bombastic.core.formatting import format_bytes
from bombastic.core.history import HISTORY_RESULTS, HistoryEntry, HistoryStore
from bombastic.core.i18n import tr
from bombastic.ui.pages import Page

_COLUMNS = ("date", "title", "result", "size", "profile", "file")


class HistoryPage(Page):
    #: Volver a descargar: emite la entrada.
    redownload_requested = Signal(object)
    #: Abrir un archivo en el editor: emite su ruta.
    edit_requested = Signal(str)

    def __init__(self, store: HistoryStore, parent: QWidget | None = None) -> None:
        super().__init__("history", parent)
        self.store = store
        self.entries: list[HistoryEntry] = []
        self.search_edit = QLineEdit()
        self.search_edit.setClearButtonEnabled(True)
        self.result_combo = QComboBox()
        top = QHBoxLayout()
        top.addWidget(self.search_edit, 1)
        top.addWidget(self.result_combo)
        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.empty_label = QLabel()
        self.empty_label.setObjectName("Placeholder")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.redownload_button = QPushButton()
        self.open_file_button = QPushButton()
        self.open_folder_button = QPushButton()
        self.edit_button = QPushButton()
        self.delete_button = QPushButton()
        self.clear_button = QPushButton()
        actions = QHBoxLayout()
        for button in (
            self.redownload_button,
            self.open_file_button,
            self.open_folder_button,
            self.edit_button,
            self.delete_button,
        ):
            actions.addWidget(button)
        actions.addStretch(1)
        actions.addWidget(self.clear_button)
        self.body.addLayout(top)
        self.body.addWidget(self.empty_label)
        self.body.addWidget(self.table, 1)
        self.body.addLayout(actions)

        self.search_edit.textChanged.connect(lambda _t: self.refresh())
        self.result_combo.currentIndexChanged.connect(lambda _i: self.refresh())
        self.table.itemSelectionChanged.connect(self._sync_buttons)
        self.table.itemDoubleClicked.connect(lambda _item: self.open_file())
        self.redownload_button.clicked.connect(self._redownload)
        self.open_file_button.clicked.connect(self.open_file)
        self.open_folder_button.clicked.connect(self.open_folder)
        self.edit_button.clicked.connect(self._send_to_editor)
        self.delete_button.clicked.connect(self.delete_selected)
        self.clear_button.clicked.connect(self._confirm_clear)
        self.retranslate()

    def retranslate(self) -> None:
        super().retranslate()
        self.search_edit.setPlaceholderText(tr("history.search"))
        current = self.result_combo.currentData()
        self.result_combo.blockSignals(True)
        self.result_combo.clear()
        self.result_combo.addItem(tr("history.result.all"), "")
        for result in HISTORY_RESULTS:
            self.result_combo.addItem(tr(f"history.result.{result}"), result)
        self.result_combo.setCurrentIndex(max(0, self.result_combo.findData(current)))
        self.result_combo.blockSignals(False)
        self.table.setHorizontalHeaderLabels([tr(f"history.column.{c}") for c in _COLUMNS])
        self.empty_label.setText(tr("history.empty"))
        self.redownload_button.setText(tr("history.redownload"))
        self.open_file_button.setText(tr("downloads.menu.open_file"))
        self.open_folder_button.setText(tr("downloads.card.open_folder"))
        self.edit_button.setText(tr("history.send_to_editor"))
        self.delete_button.setText(tr("library.delete"))
        self.clear_button.setText(tr("history.clear"))
        self.refresh()

    def refresh(self) -> None:
        result = str(self.result_combo.currentData() or "")
        self.entries = self.store.search(self.search_edit.text(), result)
        self.table.setRowCount(len(self.entries))
        for row, entry in enumerate(self.entries):
            file = entry.edit_output or (str(entry.files[0]) if entry.files else "")
            cells = (
                entry.created_at.replace("T", " "),
                entry.title,
                tr(f"history.result.{entry.result}"),
                format_bytes(entry.size),
                entry.profile,
                Path(file).name if file else "",
            )
            for column, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if column == 2 and entry.error:
                    item.setToolTip(entry.error)
                if column == 1:
                    item.setToolTip(entry.url)
                self.table.setItem(row, column, item)
        self.empty_label.setVisible(not self.entries)
        self.table.setVisible(bool(self.entries))
        self.clear_button.setEnabled(bool(self.entries) or bool(self.store.search()))
        self._sync_buttons()

    def selected(self) -> list[HistoryEntry]:
        rows = sorted({index.row() for index in self.table.selectionModel().selectedRows()})
        return [self.entries[row] for row in rows if row < len(self.entries)]

    def _first_file(self) -> Path | None:
        entries = self.selected()
        if not entries:
            return None
        entry = entries[0]
        candidates = [Path(entry.edit_output)] if entry.edit_output else []
        candidates += entry.files
        return next((path for path in candidates if path.exists()), None)

    def _sync_buttons(self) -> None:
        entries = self.selected()
        has_file = self._first_file() is not None
        self.redownload_button.setEnabled(any(e.options is not None for e in entries))
        self.open_file_button.setEnabled(has_file)
        self.open_folder_button.setEnabled(has_file)
        self.edit_button.setEnabled(has_file)
        self.delete_button.setEnabled(bool(entries))

    def _redownload(self) -> None:
        for entry in self.selected():
            if entry.options is not None:
                self.redownload_requested.emit(entry)

    def open_file(self) -> None:
        path = self._first_file()
        if path is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def open_folder(self) -> None:
        path = self._first_file()
        if path is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))

    def _send_to_editor(self) -> None:
        path = self._first_file()
        if path is not None:
            self.edit_requested.emit(str(path))

    def delete_selected(self) -> None:
        ids = [entry.entry_id for entry in self.selected()]
        if ids:
            self.store.delete(ids)
            self.refresh()

    def _confirm_clear(self) -> None:
        answer = QMessageBox.question(self, tr("history.clear"), tr("history.clear.confirm"))
        if answer == QMessageBox.StandardButton.Yes:
            self.store.clear()
            self.refresh()
