"""Modo experto: editor de comandos de ffmpeg con variables, filtros y recetas."""

from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import QStringListModel, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QKeyEvent,
    QSyntaxHighlighter,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QCompleter,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from bombastic.core.ffmpeg_command import EditPlan
from bombastic.core.i18n import tr
from bombastic.core.output_paths import safe_output
from bombastic.core.recipes import (
    BUILTIN_VARIABLES,
    COMMON_OPTIONS,
    FilterInfo,
    Recipe,
    RecipeError,
    RecipeStore,
    build_expert_plan,
    parse_params,
    template_variables,
)
from bombastic.ui.editor_tools import ToolContext, ToolError, ToolForm, _hint


class CommandHighlighter(QSyntaxHighlighter):
    """Resaltado básico: opciones (``-x``), variables (``{input}``) y textos entre comillas."""

    _RULES = (
        (re.compile(r"(?<!\S)-[\w:+.-]+"), "accent"),
        (re.compile(r"\{[a-z_][a-z0-9_]*(?:\[\d+\])?\}"), "accent_text"),
        (re.compile(r"\"[^\"]*\"|'[^']*'"), "muted"),
    )

    def __init__(self, document: QTextDocument, palette: dict[str, str]) -> None:
        super().__init__(document)
        self.set_palette(palette)

    def set_palette(self, palette: dict[str, str]) -> None:
        self._formats: dict[str, QTextCharFormat] = {}
        for _rule, key in self._RULES:
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(palette[key]))
            if key == "accent":
                fmt.setFontWeight(QFont.Weight.Bold)
            self._formats[key] = fmt
        self.rehighlight()

    def highlightBlock(self, text: str) -> None:
        for pattern, key in self._RULES:
            for match in pattern.finditer(text):
                self.setFormat(match.start(), match.end() - match.start(), self._formats[key])


class CommandEdit(QPlainTextEdit):
    """Editor con autocompletado de opciones, filtros y variables."""

    def __init__(self) -> None:
        super().__init__()
        self.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.words = QStringListModel(
            [*COMMON_OPTIONS, *(f"{{{v}}}" for v in BUILTIN_VARIABLES)], self
        )
        self.completer = QCompleter(self.words, self)
        self.completer.setWidget(self)
        self.completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.completer.activated.connect(self._insert_completion)

    def add_words(self, words: list[str]) -> None:
        self.words.setStringList(sorted({*self.words.stringList(), *words}))

    def _current_word(self) -> str:
        cursor = self.textCursor()
        text = cursor.block().text()[: cursor.positionInBlock()]
        match = re.search(r"[\w{:+.\-\[\]]+$", text)
        return match.group(0) if match else ""

    def _insert_completion(self, completion: str) -> None:
        word = self._current_word()
        cursor = self.textCursor()
        cursor.movePosition(
            QTextCursor.MoveOperation.Left, QTextCursor.MoveMode.KeepAnchor, len(word)
        )
        cursor.insertText(completion)
        self.setTextCursor(cursor)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        popup = self.completer.popup()
        assert popup is not None
        if popup.isVisible() and event.key() in (
            Qt.Key.Key_Enter,
            Qt.Key.Key_Return,
            Qt.Key.Key_Tab,
            Qt.Key.Key_Escape,
        ):
            event.ignore()
            return
        super().keyPressEvent(event)
        word = self._current_word()
        if len(word) < 2:
            popup.hide()
            return
        self.completer.setCompletionPrefix(word)
        if self.completer.completionCount() == 0:
            popup.hide()
            return
        rect = self.cursorRect()
        rect.setWidth(260)
        self.completer.complete(rect)


class FiltersDialog(QDialog):
    """Lista de filtros de ffmpeg con buscador; el elegido se inserta en el comando."""

    def __init__(self, filters: list[FilterInfo], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("expert.filters.title"))
        self.resize(640, 520)
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("expert.filters.search"))
        self.search.setClearButtonEnabled(True)
        self.list = QListWidget()
        for info in filters:
            item = QListWidgetItem(f"{info.name}  ({info.io})  {info.description}")
            item.setData(Qt.ItemDataRole.UserRole, info.name)
            self.list.addItem(item)
        empty = QLabel(tr("expert.filters.empty"))
        empty.setVisible(not filters)
        empty.setWordWrap(True)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(self.search)
        layout.addWidget(empty)
        layout.addWidget(self.list, 1)
        layout.addWidget(buttons)
        self.search.textChanged.connect(self.filter)
        self.list.itemDoubleClicked.connect(lambda _item: self.accept())

    def filter(self, text: str) -> None:
        needle = text.strip().lower()
        for row in range(self.list.count()):
            item = self.list.item(row)
            item.setHidden(bool(needle) and needle not in item.text().lower())

    def chosen(self) -> str:
        item = self.list.currentItem()
        return str(item.data(Qt.ItemDataRole.UserRole)) if item is not None else ""


class SaveRecipeDialog(QDialog):
    def __init__(self, recipe: Recipe, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("expert.save.title"))
        self.recipe = recipe
        self.name = QLineEdit(recipe.name)
        self.description = QLineEdit(recipe.description)
        self.favorite = QCheckBox(tr("expert.save.favorite"))
        self.favorite.setChecked(recipe.favorite)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.accepted.connect(self._accept)
        self.buttons.rejected.connect(self.reject)
        form = QFormLayout(self)
        form.addRow(tr("expert.save.name"), self.name)
        form.addRow(tr("expert.save.description"), self.description)
        form.addRow(self.favorite)
        form.addRow(self.buttons)

    def _accept(self) -> None:
        if not self.name.text().strip():
            self.name.setFocus()
            return
        self.recipe.name = self.name.text().strip()
        self.recipe.description = self.description.text().strip()
        self.recipe.favorite = self.favorite.isChecked()
        self.accept()


class ExpertForm(ToolForm):
    """Herramienta "Modo experto": cualquier comando de ffmpeg con variables."""

    key = "expert"
    #: Ejecutar el comando ahora, con consola en vivo.
    run_requested = Signal()
    cancel_requested = Signal()
    filters_requested = Signal()

    def __init__(self, recipes: RecipeStore) -> None:
        super().__init__()
        self.recipes = recipes
        self.recipe_combo = QComboBox()
        self.load_button = QPushButton()
        self.text(self.load_button.setText, "expert.load")
        self.editor = CommandEdit()
        self.editor.setPlaceholderText("-i {input} -vf scale=1280:-2 -c:a copy {output}")
        self.editor.setPlainText("-i {input} -c:v libx264 -crf {crf} -c:a copy {output}")
        self.params = QLineEdit("crf=23")
        self.extra_inputs = QLineEdit()
        self.output_ext = QLineEdit("mp4")
        self.output_ext.setMaximumWidth(80)
        self.hint = _hint()
        self.text(
            self.hint.setText,
            "expert.hint",
        )
        self.filters_button = QPushButton()
        self.text(self.filters_button.setText, "expert.filters")
        self.save_button = QPushButton()
        self.text(self.save_button.setText, "expert.save")
        self.run_button = QPushButton()
        self.text(self.run_button.setText, "expert.run")
        self.cancel_button = QPushButton()
        self.text(self.cancel_button.setText, "downloads.card.cancel")
        self.cancel_button.setEnabled(False)
        self.console = QPlainTextEdit()
        self.console.setReadOnly(True)
        self.console.setMaximumBlockCount(2000)
        self.console.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.highlighter: CommandHighlighter | None = None

        top = QHBoxLayout()
        top.addWidget(self.recipe_combo, 1)
        top.addWidget(self.load_button)
        form = QFormLayout()
        form.addRow(self.label("expert.params"), self.params)
        form.addRow(self.label("expert.extra_inputs"), self.extra_inputs)
        form.addRow(self.label("expert.output_ext"), self.output_ext)
        buttons = QHBoxLayout()
        for button in (self.filters_button, self.save_button, self.run_button, self.cancel_button):
            buttons.addWidget(button)
        buttons.addStretch(1)
        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.editor, 2)
        layout.addWidget(self.hint)
        layout.addLayout(form)
        layout.addLayout(buttons)
        layout.addWidget(self.console, 1)

        self.load_button.clicked.connect(self._load_selected)
        self.save_button.clicked.connect(self.save_recipe)
        self.run_button.clicked.connect(self.run_requested)
        self.cancel_button.clicked.connect(self.cancel_requested)
        self.filters_button.clicked.connect(self.filters_requested)
        self.refresh_recipes()

    def set_palette(self, palette: dict[str, str]) -> None:
        if self.highlighter is None:
            self.highlighter = CommandHighlighter(self.editor.document(), palette)
        else:
            self.highlighter.set_palette(palette)

    # ---------------------------------------------------------------- recetas

    def refresh_recipes(self) -> None:
        current = self.recipe_combo.currentData()
        self.recipe_combo.clear()
        for recipe in self.recipes.all():
            star = "★ " if recipe.favorite else ""
            self.recipe_combo.addItem(f"{star}{recipe.name}", recipe.recipe_id)
        self.recipe_combo.setCurrentIndex(max(0, self.recipe_combo.findData(current)))
        self.load_button.setEnabled(self.recipe_combo.count() > 0)

    def load_recipe(self, recipe: Recipe) -> None:
        self.editor.setPlainText(recipe.command)
        self.params.setText(", ".join(f"{k}={v}" for k, v in recipe.params.items()))
        self.output_ext.setText(recipe.output_ext)
        self.recipe_combo.setCurrentIndex(max(0, self.recipe_combo.findData(recipe.recipe_id)))

    def _load_selected(self) -> None:
        recipe = self.recipes.get(int(self.recipe_combo.currentData() or 0))
        if recipe is not None:
            self.load_recipe(recipe)

    def current_recipe(self) -> Recipe:
        params = parse_params(self.params.text())
        for name in template_variables(self.editor.toPlainText()):
            params.setdefault(name, "")
        return Recipe(
            name=self.recipe_combo.currentText().removeprefix("★ ")
            or tr("expert.save.default_name"),
            command=self.editor.toPlainText().strip(),
            params=params,
            output_ext=self.output_ext.text().strip().lstrip(".") or "mp4",
        )

    def save_recipe(self) -> SaveRecipeDialog:
        recipe = self.current_recipe()
        existing = self.recipes.by_name(recipe.name)
        if existing is not None:
            recipe.recipe_id, recipe.favorite = existing.recipe_id, existing.favorite
            recipe.description = existing.description
        dialog = SaveRecipeDialog(recipe, parent=self)

        def accepted() -> None:
            self.recipes.save(dialog.recipe)
            self.refresh_recipes()
            self.recipe_combo.setCurrentIndex(self.recipe_combo.findData(dialog.recipe.recipe_id))

        dialog.accepted.connect(accepted)
        dialog.open()
        return dialog

    # ------------------------------------------------------------------ plan

    def set_template(self, text: str) -> None:
        self.editor.setPlainText(text)

    def insert(self, text: str) -> None:
        self.editor.insertPlainText(text)
        self.editor.setFocus()

    def set_running(self, running: bool) -> None:
        self.run_button.setEnabled(not running)
        self.cancel_button.setEnabled(running)

    def plan(self, ctx: ToolContext) -> EditPlan:
        extra = [Path(p.strip()) for p in self.extra_inputs.text().split(";") if p.strip()]
        output = safe_output(ctx.source, self.output_ext.text().strip() or "mp4")
        try:
            return build_expert_plan(
                self.editor.toPlainText(),
                [ctx.source, *extra],
                output,
                ctx.probe.duration,
                parse_params(self.params.text()),
                ctx.marker_in,
                ctx.marker_out,
            )
        except RecipeError as exc:
            # El detalle (la variable o el error de comillas) se ve en la consola.
            self.console.appendPlainText(f"{tr(exc.key)} {exc.detail}".strip())
            raise ToolError(exc.key) from exc
