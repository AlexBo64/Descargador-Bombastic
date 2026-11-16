"""Diálogo del modo avanzado: todas las opciones de yt-dlp, cookies y argumentos libres.

La interfaz se construye a partir del catálogo generado desde ``yt-dlp --help``: una pestaña
por grupo, una casilla por opción sin argumento y un campo por opción con argumento.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QAbstractButton,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from bombastic.context import AppContext
from bombastic.core.i18n import tr
from bombastic.core.ytdlp_command import COOKIE_BROWSERS, COOKIE_MODES
from bombastic.core.ytdlp_options import ExtraArgsError, YtdlpOption, split_extra_args

#: Devuelve ``(comando como texto, claves de conflicto)`` con los ajustes actuales.
PreviewFn = Callable[[], tuple[str, list[str]]]


class OptionRow(QWidget):
    """Una opción de yt-dlp: casilla o campo, con su flag real y su ayuda."""

    def __init__(self, option: YtdlpOption, help_text: str, value: bool | str) -> None:
        super().__init__()
        self.option = option
        self.help_text = help_text
        self.check: QCheckBox | None = None
        self.edit: QLineEdit | None = None
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 4, 0, 4)
        grid.setHorizontalSpacing(10)
        flags = ", ".join(option.flags)
        self.name: QLabel | QAbstractButton
        if option.takes_value:
            self.name = QLabel(f"{flags} {option.metavar}")
            self.edit = QLineEdit(value if isinstance(value, str) else "")
            self.edit.setPlaceholderText(option.metavar)
            self.name.setBuddy(self.edit)
            grid.addWidget(self.name, 0, 0)
            grid.addWidget(self.edit, 0, 1)
            if option.kind == "path":
                self.browse = QPushButton("…")
                self.browse.setFixedWidth(36)
                self.browse.clicked.connect(self._browse)
                grid.addWidget(self.browse, 0, 2)
        else:
            self.check = QCheckBox(flags)
            self.check.setChecked(value is True)
            self.name = self.check
            grid.addWidget(self.check, 0, 0, 1, 2)
        self.help_label = QLabel(help_text)
        self.help_label.setProperty("muted", True)
        self.help_label.setWordWrap(True)
        grid.addWidget(self.help_label, 1, 0, 1, 3)
        grid.setColumnStretch(1, 1)
        self.refresh_marker()

    def value(self) -> bool | str:
        if self.check is not None:
            return self.check.isChecked()
        assert self.edit is not None
        return self.edit.text().strip()

    def set_value(self, value: bool | str) -> None:
        if self.check is not None:
            self.check.setChecked(value is True)
        elif self.edit is not None:
            self.edit.setText(value if isinstance(value, str) else "")

    def is_modified(self) -> bool:
        return bool(self.value())

    def refresh_marker(self) -> None:
        """Las opciones modificadas se ven en negrita."""
        font = QFont(self.name.font())
        font.setBold(self.is_modified())
        self.name.setFont(font)

    def matches(self, needle: str) -> bool:
        haystack = " ".join((*self.option.flags, self.help_text, self.option.help)).lower()
        return needle in haystack

    def _browse(self) -> None:
        assert self.edit is not None
        if "DIR" in self.option.metavar.upper():
            chosen = QFileDialog.getExistingDirectory(self, self.option.key, self.edit.text())
        else:
            chosen, _ = QFileDialog.getOpenFileName(self, self.option.key, self.edit.text())
        if chosen:
            self.edit.setText(chosen)


class AdvancedDialog(QDialog):
    def __init__(
        self,
        ctx: AppContext,
        options: list[YtdlpOption],
        preview: PreviewFn,
        translations: tuple[dict[str, str], dict[str, str]] = ({}, {}),
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("AdvancedDialog")
        self.setWindowTitle(tr("advanced.title"))
        self.resize(900, 680)
        self._ctx = ctx
        self._preview = preview
        self.rows: list[OptionRow] = []
        self._group_rows: dict[int, list[OptionRow]] = {}

        # Nombres de grupo y ayudas traducidas; lo que no esté traducido sale en inglés.
        group_names, help_es = translations if ctx.translator.language == "es" else ({}, {})

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText(tr("advanced.search"))
        self.search_edit.setClearButtonEnabled(True)
        self.reset_all_button = QPushButton(tr("advanced.reset_all"))
        top = QHBoxLayout()
        top.addWidget(self.search_edit, 1)
        top.addWidget(self.reset_all_button)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._cookies_tab(), tr("advanced.cookies"))
        groups: dict[str, list[YtdlpOption]] = {}
        for option in options:
            groups.setdefault(option.group, []).append(option)
        values = ctx.settings.advanced_options
        for group, members in groups.items():
            rows = [
                OptionRow(option, help_es.get(option.key, option.help), values.get(option.key, ""))
                for option in members
            ]
            index = self.tabs.addTab(self._group_tab(rows), group_names.get(group, group))
            self._group_rows[index] = rows
            self.rows += rows

        self.extra_label = QLabel(tr("advanced.extra_args"))
        self.extra_edit = QLineEdit(ctx.settings.extra_args)
        self.extra_edit.setPlaceholderText(tr("advanced.extra_args.placeholder"))
        self.extra_label.setBuddy(self.extra_edit)
        self.extra_error = QLabel()
        self.extra_error.setObjectName("Warning")
        self.conflicts_label = QLabel()
        self.conflicts_label.setObjectName("Warning")
        self.conflicts_label.setWordWrap(True)
        self.preview_label = QLabel(tr("advanced.preview"))
        self.preview_edit = QPlainTextEdit()
        self.preview_edit.setReadOnly(True)
        self.preview_edit.setFixedHeight(84)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.tabs, 1)
        extra = QHBoxLayout()
        extra.addWidget(self.extra_label)
        extra.addWidget(self.extra_edit, 1)
        layout.addLayout(extra)
        layout.addWidget(self.extra_error)
        layout.addWidget(self.conflicts_label)
        layout.addWidget(self.preview_label)
        layout.addWidget(self.preview_edit)
        layout.addWidget(buttons)

        self.search_edit.textChanged.connect(self.filter)
        self.reset_all_button.clicked.connect(self.reset_all)
        self.extra_edit.textChanged.connect(self._on_changed)
        for row in self.rows:
            if row.check is not None:
                row.check.toggled.connect(lambda _=False, r=row: self._on_row_changed(r))
            elif row.edit is not None:
                row.edit.textChanged.connect(lambda _="", r=row: self._on_row_changed(r))
        self.finished.connect(lambda _result: ctx.save_settings())
        self._on_changed()

    # --------------------------------------------------------------- pestañas

    def _group_tab(self, rows: list[OptionRow]) -> QWidget:
        content = QWidget()
        column = QVBoxLayout(content)
        reset = QPushButton(tr("advanced.reset_group"))
        reset.clicked.connect(lambda: self.reset_rows(rows))
        head = QHBoxLayout()
        head.addStretch(1)
        head.addWidget(reset)
        column.addLayout(head)
        for row in rows:
            column.addWidget(row)
        column.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)
        return scroll

    def _cookies_tab(self) -> QWidget:
        settings = self._ctx.settings
        page = QWidget()
        form = QFormLayout(page)
        explain = QLabel(tr("advanced.cookies.explain"))
        explain.setWordWrap(True)
        explain.setProperty("muted", True)
        form.addRow(explain)
        self.cookies_mode = QComboBox()
        for mode in COOKIE_MODES:
            self.cookies_mode.addItem(tr(f"advanced.cookies.mode.{mode}"), mode)
        self.cookies_mode.setCurrentIndex(max(0, self.cookies_mode.findData(settings.cookies_mode)))
        self.cookies_browser = QComboBox()
        for browser in COOKIE_BROWSERS:
            self.cookies_browser.addItem(browser.capitalize(), browser)
        self.cookies_browser.setCurrentIndex(
            max(0, self.cookies_browser.findData(settings.cookies_browser))
        )
        self.cookies_profile = QLineEdit(settings.cookies_profile)
        self.cookies_profile.setPlaceholderText(tr("advanced.cookies.profile.placeholder"))
        self.cookies_file = QLineEdit(settings.cookies_file)
        browse = QPushButton(tr("settings.browse"))
        browse.clicked.connect(self._browse_cookies)
        file_row = QHBoxLayout()
        file_row.addWidget(self.cookies_file, 1)
        file_row.addWidget(browse)
        form.addRow(tr("advanced.cookies.mode"), self.cookies_mode)
        form.addRow(tr("advanced.cookies.browser"), self.cookies_browser)
        form.addRow(tr("advanced.cookies.profile"), self.cookies_profile)
        form.addRow(tr("advanced.cookies.file"), file_row)
        self.cookies_mode.currentIndexChanged.connect(self._on_changed)
        self.cookies_browser.currentIndexChanged.connect(self._on_changed)
        self.cookies_profile.textChanged.connect(self._on_changed)
        self.cookies_file.textChanged.connect(self._on_changed)
        return page

    def _browse_cookies(self) -> None:
        chosen, _ = QFileDialog.getOpenFileName(
            self, tr("advanced.cookies.file"), self.cookies_file.text(), "cookies.txt (*.txt);;*"
        )
        if chosen:
            self.cookies_file.setText(chosen)

    # ---------------------------------------------------------------- acciones

    def filter(self, text: str) -> None:
        """Muestra solo las opciones cuyo flag o descripción contienen el texto."""
        needle = text.strip().lower()
        for index, rows in self._group_rows.items():
            visible = 0
            for row in rows:
                shown = not needle or row.matches(needle)
                row.setVisible(shown)
                visible += shown
            self.tabs.setTabVisible(index, visible > 0)
        self.tabs.setTabVisible(0, not needle)

    def reset_rows(self, rows: list[OptionRow]) -> None:
        for row in rows:
            row.set_value("")

    def reset_all(self) -> None:
        self.reset_rows(self.rows)
        self.extra_edit.clear()
        self.cookies_mode.setCurrentIndex(self.cookies_mode.findData("off"))

    def _on_row_changed(self, row: OptionRow) -> None:
        row.refresh_marker()
        value = row.value()
        values = self._ctx.settings.advanced_options
        if value:
            values[row.option.key] = value
        else:
            values.pop(row.option.key, None)
        self._on_changed()

    def _on_changed(self) -> None:
        settings = self._ctx.settings
        settings.cookies_mode = str(self.cookies_mode.currentData())
        settings.cookies_browser = str(self.cookies_browser.currentData())
        settings.cookies_profile = self.cookies_profile.text().strip()
        settings.cookies_file = self.cookies_file.text().strip()
        mode = settings.cookies_mode
        self.cookies_browser.setEnabled(mode == "browser")
        self.cookies_profile.setEnabled(mode == "browser")
        self.cookies_file.setEnabled(mode == "file")

        text = self.extra_edit.text()
        try:
            split_extra_args(text)
            self.extra_error.setText("")
            settings.extra_args = text.strip()
        except ExtraArgsError:
            self.extra_error.setText(tr("advanced.extra_args.unbalanced"))
        self.extra_error.setVisible(bool(self.extra_error.text()))

        command, conflicts = self._preview()
        self.preview_edit.setPlainText(command)
        self.conflicts_label.setText("\n".join(tr(f"downloads.conflict.{c}") for c in conflicts))
        self.conflicts_label.setVisible(bool(conflicts))

    def modified_count(self) -> int:
        return sum(row.is_modified() for row in self.rows)
