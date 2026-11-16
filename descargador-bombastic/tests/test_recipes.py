from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from bombastic.context import AppContext
from bombastic.core import ffmpeg_command as fc
from bombastic.core.db import Database
from bombastic.core.edit_manager import EditManager
from bombastic.core.media_probe import ProbeInfo, StreamInfo
from bombastic.core.recipes import (
    Recipe,
    RecipeError,
    RecipeStore,
    build_expert_plan,
    parse_filters,
    parse_params,
    parse_template,
    plan_to_template,
    substitute,
    template_variables,
    variables_for,
)
from bombastic.core.ytdlp_runner import Launcher
from bombastic.ui.editor_page import EditorPage
from bombastic.ui.library_page import LibraryPage
from bombastic.ui.main_window import MainWindow

TIMEOUT = 20_000
SRC = Path("C:/Vídeos/mi clip ñ.mp4")
OUT = Path("C:/Vídeos/salida.mp4")
PROBE = ProbeInfo("mp4", 10.0, 1, 1, (StreamInfo(0, "video", "h264", 640, 360, 30.0),))


def test_variables_and_substitution() -> None:
    variables = variables_for([SRC, Path("b.wav")], OUT, 1.5, 3)
    assert variables["name"] == "mi clip ñ" and variables["dir"] == str(SRC.parent)
    assert substitute("{input}", variables) == str(SRC)
    assert substitute("{inputs[1]}", variables) == "b.wav"
    assert substitute("trim={start}:{end}", variables) == "trim=00:00:01.500:00:00:03.000"
    assert substitute("{dir}/{name}.png", variables) == f"{SRC.parent}/mi clip ñ.png"
    for bad, key in (
        ("{nada}", "expert.error.unknown_variable"),
        ("{inputs[5]}", "expert.error.missing_input"),
    ):
        with pytest.raises(RecipeError) as info:
            substitute(bad, variables)
        assert info.value.key == key
    with pytest.raises(RecipeError) as info:
        substitute("{end}", variables_for([SRC], OUT))
    assert info.value.key == "expert.error.empty_variable"


def test_parse_template_and_params() -> None:
    assert parse_template('ffmpeg -i {input} -vf "scale=1280:-2"\n{output}') == [
        "-i",
        "{input}",
        "-vf",
        "scale=1280:-2",
        "{output}",
    ]
    assert parse_template(r"C:\bin\ffmpeg.exe -i x {output}")[:2] == ["-i", "x"]
    for bad in ("", "  ffmpeg  ", '-i "sin cerrar'):
        with pytest.raises(RecipeError):
            parse_template(bad)
    assert template_variables("-crf {crf} -preset {preset} {input} {crf} {output}") == [
        "crf",
        "preset",
    ]
    assert parse_params("crf=23, preset = slow\nmal; X=1;=3") == {"crf": "23", "preset": "slow"}


def test_build_expert_plan_keeps_paths_with_spaces_whole() -> None:
    plan = build_expert_plan(
        "-y -i {input} -c:v libx264 -crf {crf} -progress x {output}", [SRC], OUT, 10, {"crf": "20"}
    )
    args = plan.passes[0][len(fc.COMMON) :]
    assert args == ("-i", str(SRC), "-c:v", "libx264", "-crf", "20", "x", str(OUT))
    assert plan.tool == "expert" and plan.duration == 10
    with pytest.raises(RecipeError) as info:
        build_expert_plan("-i {input} salida.mp4", [SRC], OUT, 10)
    assert info.value.key == "expert.error.no_output"


def test_plan_to_template_roundtrip() -> None:
    plan = fc.build_trim(SRC, OUT, PROBE, 1, 2, precise=True)
    template = plan_to_template(plan)
    assert template.startswith("-i {input} -ss 00:00:01.000") and template.endswith("{output}")
    again = build_expert_plan(template, [SRC], OUT, 1)
    assert again.passes[0] == plan.passes[0]
    concat = fc.build_concat([SRC, Path("C:/b c.mp4")], OUT, [PROBE, PROBE], Path("C:/l.txt"))
    assert "{input}" not in plan_to_template(concat)  # la entrada es la lista de concat


def test_recipe_store_crud_and_import(tmp_path: Path) -> None:
    for db in (None, Database(tmp_path / "r.sqlite3")):
        store = RecipeStore(db)
        first = store.save(
            Recipe("Comprimir", "-i {input} -crf {crf} {output}", params={"crf": "28"})
        )
        second = store.save(Recipe("comprimir", "-i {input} {output}", favorite=True))
        assert second.name == "comprimir (2)"
        assert [r.name for r in store.all()] == ["Comprimir", "comprimir (2)"]
        assert [r.name for r in store.favorites()] == ["comprimir (2)"]
        first.description = "nueva"
        store.save(first)
        loaded = store.get(first.recipe_id)
        assert (
            loaded is not None and loaded.description == "nueva" and loaded.params == {"crf": "28"}
        )
        exported = store.export_json(store.all())
        store.delete(first.recipe_id)
        assert store.by_name("Comprimir") is None
        imported = store.import_json(exported)
        assert [r.name for r in imported] == ["Comprimir", "comprimir (3)"]
        for bad in ("{", "[1]", '{"recipes": [{"name": "x"}]}'):
            with pytest.raises(RecipeError):
                store.import_json(bad)
        if db is not None:
            db.close()


def test_parse_filters() -> None:
    text = "Filters:\n ------\n TS scale  V->V  Scale video.\n .. aap AA->A Affine.\n"
    filters = parse_filters(text)
    assert [(f.name, f.io) for f in filters] == [("scale", "V->V"), ("aap", "AA->A")]
    assert filters[0].description == "Scale video."


@pytest.fixture
def editor(qtbot: QtBot, ctx: AppContext, fake_ffmpeg: Launcher, tmp_path: Path) -> EditorPage:
    page = EditorPage(ctx, EditManager(fake_ffmpeg), probe_launcher=fake_ffmpeg)
    # El archivo de prueba no es un vídeo real: sin esto se generaría la copia ligera.
    page.player.playback_failed.disconnect(page._on_playback_failed)
    qtbot.addWidget(page)
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"x")
    with qtbot.waitSignal(page.file_opened, timeout=TIMEOUT):
        page.open_file(source)
    return page


def test_open_in_expert_and_run_with_console(
    qtbot: QtBot, editor: EditorPage, tmp_path: Path
) -> None:
    editor.tools.setCurrentIndex(1)  # recortar
    editor.player.set_markers(1, 2)
    assert editor.open_in_expert()
    expert = editor.expert_form
    assert editor.tools.currentWidget() is expert
    assert "{input}" in expert.editor.toPlainText() and "{output}" in expert.editor.toPlainText()
    assert not editor.expert_button.isEnabled()

    job = editor.run_expert()
    assert job is not None
    qtbot.waitUntil(lambda: "Terminado" in expert.console.toPlainText(), timeout=TIMEOUT)
    assert expert.console.toPlainText().startswith("$ ffmpeg -hide_banner")
    assert (tmp_path / "clip_editado.mp4").is_file()

    expert.set_template("-i {input} -crf {calidad} {output}")
    assert editor.current_plan() is None
    assert editor.feedback.text() == "Variable desconocida: añádela a los parámetros."
    assert "{calidad}" in expert.console.toPlainText()
    expert.params.setText("calidad=30")
    plan = editor.current_plan()
    assert plan is not None and "30" in plan.passes[0]


def test_save_recipe_filters_and_library(qtbot: QtBot, editor: EditorPage, tmp_path: Path) -> None:
    expert = editor.expert_form
    expert.set_template("-i {input} -vf {filtro} {output}")
    expert.params.setText("filtro=hflip")
    dialog = expert.save_recipe()
    dialog.name.setText("Espejo")
    dialog.favorite.setChecked(True)
    dialog.buttons.accepted.emit()
    recipe = editor.recipes.by_name("Espejo")
    assert recipe is not None and recipe.favorite and recipe.params == {"filtro": "hflip"}
    assert expert.recipe_combo.currentText() == "★ Espejo"

    editor.show_filters()
    qtbot.waitUntil(lambda: hasattr(editor, "filters_dialog"), timeout=TIMEOUT)
    filters = editor.filters_dialog
    assert filters.list.count() == 2
    filters.filter("tempo")
    assert [filters.list.item(i).isHidden() for i in range(2)] == [True, False]
    filters.list.setCurrentRow(1)
    filters.accept()
    assert expert.editor.toPlainText().startswith("atempo")  # se inserta en el cursor

    library = LibraryPage(editor.recipes)
    qtbot.addWidget(library)
    view = library.recipes_view
    assert view.list.count() == 1 and view.list.item(0).text() == "★ Espejo"
    assert "-vf {filtro}" in view.details.toPlainText()
    view.rename("Espejo H")
    view.duplicate()
    assert [r.name for r in editor.recipes.all()] == ["Espejo H", "Espejo H (2)"]
    view.toggle_favorite()
    target = tmp_path / "recetas ñ.json"
    view.export_to(target)
    view.delete_selected()
    assert len(editor.recipes.all()) == 1
    assert len(view.import_from(target)) == 1
    assert view.feedback.text() == "Importadas: 1."
    bad = tmp_path / "mal.json"
    bad.write_text("no", encoding="utf-8")
    assert view.import_from(bad) == []


def test_main_window_opens_recipe_in_editor(qtbot: QtBot, ctx: AppContext) -> None:
    window = MainWindow(ctx)
    qtbot.addWidget(window)
    recipe = window.recipes.save(Recipe("Gris", "-i {input} -vf hue=s=0 {output}"))
    window.library_page.recipes_view.refresh()
    window.library_page.recipes_view.open_requested.emit(recipe.recipe_id)
    assert window.current_page() == "editor"
    assert window.editor_page.tools.currentWidget() is window.editor_page.expert_form
    assert "hue=s=0" in window.editor_page.expert_form.editor.toPlainText()
    assert window.close()
