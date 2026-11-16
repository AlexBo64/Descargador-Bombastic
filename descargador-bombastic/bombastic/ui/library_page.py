"""Página "Perfiles y recetas": gestión de las recetas del modo experto.

Los perfiles de descarga se añaden en la Fase 7.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from bombastic.core.i18n import tr
from bombastic.core.recipes import Recipe, RecipeError, RecipeStore
from bombastic.ui.pages import Page


class RecipesView(QWidget):
    #: Abrir la receta en el modo experto del editor.
    open_requested = Signal(int)
    #: Las recetas han cambiado (para refrescar otras vistas).
    changed = Signal()

    def __init__(self, store: RecipeStore, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.store = store
        self.list = QListWidget()
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.feedback = QLabel()
        self.feedback.setWordWrap(True)
        self.open_button = QPushButton()
        self.rename_button = QPushButton()
        self.duplicate_button = QPushButton()
        self.favorite_button = QPushButton()
        self.delete_button = QPushButton()
        self.export_button = QPushButton()
        self.import_button = QPushButton()
        buttons = QHBoxLayout()
        for button in (
            self.open_button,
            self.rename_button,
            self.duplicate_button,
            self.favorite_button,
            self.delete_button,
        ):
            buttons.addWidget(button)
        buttons.addStretch(1)
        buttons.addWidget(self.import_button)
        buttons.addWidget(self.export_button)
        self.empty = QLabel()
        self.empty.setObjectName("Placeholder")
        self.empty.setWordWrap(True)
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row = QHBoxLayout()
        row.addWidget(self.list, 2)
        row.addWidget(self.details, 3)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.addWidget(self.empty)
        layout.addLayout(row, 1)
        layout.addLayout(buttons)
        layout.addWidget(self.feedback)
        self.list.currentRowChanged.connect(lambda _row: self._show_details())
        self.list.itemDoubleClicked.connect(lambda _item: self._open())
        self.open_button.clicked.connect(self._open)
        self.rename_button.clicked.connect(self._rename)
        self.duplicate_button.clicked.connect(self.duplicate)
        self.favorite_button.clicked.connect(self.toggle_favorite)
        self.delete_button.clicked.connect(self._delete)
        self.export_button.clicked.connect(self._export)
        self.import_button.clicked.connect(self._import)
        self.retranslate()

    def retranslate(self) -> None:
        self.open_button.setText(tr("library.recipes.open"))
        self.rename_button.setText(tr("library.rename"))
        self.duplicate_button.setText(tr("library.duplicate"))
        self.favorite_button.setText(tr("library.recipes.favorite"))
        self.delete_button.setText(tr("library.delete"))
        self.export_button.setText(tr("library.export"))
        self.import_button.setText(tr("library.import"))
        self.empty.setText(tr("library.recipes.empty"))
        self.refresh()

    def selected(self) -> Recipe | None:
        item = self.list.currentItem()
        return self.store.get(int(item.data(Qt.ItemDataRole.UserRole))) if item else None

    def select(self, recipe_id: int) -> None:
        for row in range(self.list.count()):
            if self.list.item(row).data(Qt.ItemDataRole.UserRole) == recipe_id:
                self.list.setCurrentRow(row)

    def refresh(self) -> None:
        current = self.selected()
        self.list.clear()
        for recipe in self.store.all():
            item = QListWidgetItem(("★ " if recipe.favorite else "") + recipe.name)
            item.setData(Qt.ItemDataRole.UserRole, recipe.recipe_id)
            self.list.addItem(item)
        if current is not None:
            self.select(current.recipe_id)
        elif self.list.count():
            self.list.setCurrentRow(0)
        self.empty.setVisible(self.list.count() == 0)
        self._show_details()

    def _show_details(self) -> None:
        recipe = self.selected()
        for button in (
            self.open_button,
            self.rename_button,
            self.duplicate_button,
            self.favorite_button,
            self.delete_button,
            self.export_button,
        ):
            button.setEnabled(recipe is not None)
        if recipe is None:
            self.details.clear()
            return
        params = ", ".join(f"{k}={v}" for k, v in recipe.params.items()) or "—"
        self.details.setPlainText(
            "\n".join(
                (
                    recipe.description or tr("library.recipes.no_description"),
                    "",
                    recipe.command,
                    "",
                    tr("library.recipes.params", params=params),
                    tr("library.recipes.output", ext=recipe.output_ext),
                )
            )
        )

    def _changed(self, recipe_id: int | None = None) -> None:
        self.refresh()
        if recipe_id is not None:
            self.select(recipe_id)
        self.changed.emit()

    def _open(self) -> None:
        recipe = self.selected()
        if recipe is not None:
            self.open_requested.emit(recipe.recipe_id)

    def rename(self, name: str) -> None:
        recipe = self.selected()
        if recipe is not None and name.strip():
            recipe.name = name.strip()
            self.store.save(recipe)
            self._changed(recipe.recipe_id)

    def _rename(self) -> None:
        recipe = self.selected()
        if recipe is None:
            return
        name, ok = QInputDialog.getText(
            self, tr("library.rename"), tr("expert.save.name"), text=recipe.name
        )
        if ok:
            self.rename(name)

    def duplicate(self) -> None:
        recipe = self.selected()
        if recipe is not None:
            copy = Recipe(**{**recipe.__dict__, "recipe_id": 0, "favorite": False})
            self.store.save(copy)
            self._changed(copy.recipe_id)

    def toggle_favorite(self) -> None:
        recipe = self.selected()
        if recipe is not None:
            recipe.favorite = not recipe.favorite
            self.store.save(recipe)
            self._changed(recipe.recipe_id)

    def delete_selected(self) -> None:
        recipe = self.selected()
        if recipe is not None:
            self.store.delete(recipe.recipe_id)
            self._changed()

    def _delete(self) -> None:
        recipe = self.selected()
        if recipe is None:
            return
        answer = QMessageBox.question(
            self, tr("library.delete"), tr("library.recipes.confirm_delete", name=recipe.name)
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.delete_selected()

    def export_to(self, path: Path) -> None:
        recipe = self.selected()
        recipes = [recipe] if recipe is not None else self.store.all()
        path.write_text(self.store.export_json(recipes), encoding="utf-8")
        self.feedback.setText(tr("library.exported", name=path.name))

    def import_from(self, path: Path) -> list[Recipe]:
        try:
            imported = self.store.import_json(path.read_text(encoding="utf-8"))
        except (OSError, RecipeError):
            self.feedback.setText(tr("library.import_failed", name=path.name))
            return []
        self.feedback.setText(tr("library.imported", count=len(imported)))
        self._changed(imported[-1].recipe_id if imported else None)
        return imported

    def _export(self) -> None:
        recipe = self.selected()
        default = f"{recipe.name if recipe else 'recetas'}.json"
        chosen, _ = QFileDialog.getSaveFileName(
            self, tr("library.export"), default, "JSON (*.json)"
        )
        if chosen:
            self.export_to(Path(chosen))

    def _import(self) -> None:
        chosen, _ = QFileDialog.getOpenFileName(self, tr("library.import"), "", "JSON (*.json)")
        if chosen:
            self.import_from(Path(chosen))


class LibraryPage(Page):
    def __init__(self, recipes: RecipeStore, parent: QWidget | None = None) -> None:
        super().__init__("library", parent)
        self.tabs = QTabWidget()
        self.recipes_view = RecipesView(recipes)
        self.tabs.addTab(self.recipes_view, "")
        self.body.addWidget(self.tabs, 1)
        self.retranslate()

    def retranslate(self) -> None:
        super().retranslate()
        self.tabs.setTabText(self.tabs.indexOf(self.recipes_view), tr("library.tab.recipes"))
        self.recipes_view.retranslate()
