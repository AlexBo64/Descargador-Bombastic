from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from bombastic.context import AppContext
from bombastic.core.chain import ChainAction, ChainError, ChainRunner, build_chain_plan
from bombastic.core.db import Database
from bombastic.core.download_manager import DownloadManager, ItemState
from bombastic.core.edit_manager import EditManager, EditState
from bombastic.core.history import (
    HistoryRecorder,
    HistoryStore,
    Profile,
    ProfileError,
    ProfileStore,
)
from bombastic.core.media_probe import ProbeInfo, StreamInfo
from bombastic.core.media_prober import MediaProber
from bombastic.core.recipes import Recipe, RecipeStore
from bombastic.core.ytdlp_command import DownloadOptions, Preset
from bombastic.core.ytdlp_runner import Launcher
from bombastic.ui.downloads_page import DownloadsPage
from bombastic.ui.history_page import HistoryPage
from bombastic.ui.library_page import ProfilesView
from bombastic.ui.main_window import MainWindow

TIMEOUT = 20_000
SRC = Path("C:/d/vídeo.webm")
PROBE = ProbeInfo(
    "webm", 60.0, 1, 1, (StreamInfo(0, "video", "vp9", 1920, 1080), StreamInfo(1, "audio", "opus"))
)


def test_chain_action_json() -> None:
    action = ChainAction("trim", "00:00:10-00:01:00", True)
    assert ChainAction.from_json(action.to_json()) == action
    assert ChainAction().to_json() == ""
    for bad in ("", "{", '{"kind": "explotar"}', "[]"):
        assert ChainAction.from_json(bad) == ChainAction()


@pytest.mark.parametrize(
    ("kind", "value", "tool", "ext"),
    [
        ("convert", "MKV", "convert", ".mkv"),
        ("trim", "00:00:10-00:01:00", "trim", ".webm"),
        ("compress", "25", "compress", ".mp4"),
        ("normalize", "", "audio", ".mp4"),
        ("extract_audio", "mp3", "audio", ".mp3"),
        ("resize", "720", "transform", ".mp4"),
    ],
)
def test_build_chain_plan(kind: str, value: str, tool: str, ext: str) -> None:
    plan = build_chain_plan(ChainAction(kind, value), SRC, PROBE)
    assert (plan.tool, plan.output.suffix) == (tool, ext)
    assert plan.inputs[0] == SRC


def test_chain_plan_errors_and_recipe() -> None:
    for kind, value in (
        ("convert", "xyz"),
        ("trim", "10"),
        ("trim", "00:02-00:01"),
        ("compress", "mucho"),
        ("extract_audio", "mp4"),
        ("resize", "alto"),
        ("recipe", "no existe"),
        ("none", ""),
    ):
        with pytest.raises(ChainError):
            build_chain_plan(ChainAction(kind, value), SRC, PROBE, RecipeStore(None))
    recipes = RecipeStore(None)
    recipes.save(Recipe("Gris", "-i {input} -vf hue=s=0 {output}", output_ext="mkv"))
    plan = build_chain_plan(ChainAction("recipe", "gris"), SRC, PROBE, recipes)
    assert plan.tool == "expert" and plan.output.suffix == ".mkv"


def test_history_store_search_and_delete(tmp_path: Path) -> None:
    store = HistoryStore(None)
    file = tmp_path / "a.mp4"
    file.write_bytes(b"12345")
    options = DownloadOptions(tmp_path, preset=Preset.MP3, profile="Música")
    first = store.add("Canción 100%", "https://e.com/a", [file], "completed", "", options)
    store.add("Otro_vídeo", "https://e.com/b", [], "failed", "private: x")
    assert [e.title for e in store.search()] == ["Otro_vídeo", "Canción 100%"]
    assert [e.title for e in store.search("100%")] == ["Canción 100%"]
    assert [e.title for e in store.search("o_v")] == ["Otro_vídeo"]
    assert [e.title for e in store.search("", "failed")] == ["Otro_vídeo"]
    entry = store.get(first)
    assert entry is not None
    assert (entry.size, entry.profile, entry.files) == (5, "Música", [file])
    assert entry.options is not None and entry.options.preset is Preset.MP3
    store.set_edit_output(first, tmp_path / "a_editado.mp4")
    assert store.get(first).edit_output.endswith("a_editado.mp4")  # type: ignore[union-attr]
    store.delete([first])
    assert len(store.search()) == 1
    store.clear()
    assert store.search() == []


def test_profile_store(tmp_path: Path) -> None:
    db = Database(tmp_path / "p.sqlite3")
    store = ProfileStore(db)
    music = store.save(Profile("Música", {"download_preset": "mp3"}, is_default=True))
    video = store.save(Profile("música", {"download_preset": "720p"}, is_default=True))
    assert video.name == "música (2)"
    assert store.default() == video  # solo uno es el predeterminado
    store.set_default(music.profile_id)
    assert store.default() is not None and store.default().name == "Música"  # type: ignore[union-attr]
    exported = store.export_json(store.all())
    store.delete(music.profile_id)
    imported = store.import_json(exported)
    assert [p.name for p in imported] == ["Música", "música (3)"]
    assert all(not p.is_default for p in imported)
    filtered = store.import_json(
        '{"profiles": [{"name": "x", "values": {"hack": 1, "mp3_quality": "320"}}]}'
    )
    assert filtered[0].values == {"mp3_quality": "320"}
    for bad in ("{", "{}", '{"profiles": [1]}'):
        with pytest.raises(ProfileError):
            store.import_json(bad)
    db.close()


def _wait(qtbot: QtBot, manager: DownloadManager, item_id: int, state: ItemState) -> None:
    qtbot.waitUntil(
        lambda: (i := manager.item(item_id)) is not None and i.state is state, timeout=TIMEOUT
    )


def test_recorder_and_chain_runner(
    qtbot: QtBot, fake_launcher: Launcher, fake_ffmpeg: Launcher, tmp_path: Path
) -> None:
    downloads = DownloadManager(fake_launcher)
    edits = EditManager(fake_ffmpeg)
    store = HistoryStore(None)
    recorder = HistoryRecorder(downloads, store)
    runner = ChainRunner(downloads, edits, MediaProber(fake_ffmpeg), RecipeStore(None))
    ok, bad = downloads.add_urls(["https://example.com/video", "https://example.com/fail"])
    _wait(qtbot, downloads, ok, ItemState.READY)
    _wait(qtbot, downloads, bad, ItemState.READY)
    chain = ChainAction("convert", "mkv", delete_original=True).to_json()
    downloads.start(ok, DownloadOptions(tmp_path, chain=chain, profile="P"))
    downloads.start(bad, DownloadOptions(tmp_path))
    _wait(qtbot, downloads, ok, ItemState.COMPLETED)
    _wait(qtbot, downloads, bad, ItemState.FAILED)
    entries = {e.url: e for e in store.search()}
    assert entries["https://example.com/video"].result == "completed"
    assert entries["https://example.com/video"].profile == "P"
    assert entries["https://example.com/fail"].error.startswith("private")
    assert set(recorder.entry_for) == {ok, bad}

    qtbot.waitUntil(lambda: len(edits.tasks()) == 1, timeout=TIMEOUT)
    task = edits.tasks()[0]
    assert task.plan.output.name == "Vídeo de prueba ñ_editado.mkv"
    assert runner.task_download == {task.task_id: ok}
    qtbot.waitUntil(lambda: task.state is EditState.COMPLETED, timeout=TIMEOUT)
    qtbot.waitUntil(lambda: not (tmp_path / "Vídeo de prueba ñ.mp4").exists(), timeout=TIMEOUT)
    # Refrescar la tarjeta no encadena otra vez.
    downloads.item_changed.emit(ok)
    assert len(edits.tasks()) == 1


def test_history_page_and_redownload(
    qtbot: QtBot, ctx: AppContext, fake_launcher: Launcher, tmp_path: Path
) -> None:
    store = HistoryStore(None)
    file = tmp_path / "x.mp4"
    file.write_bytes(b"x")
    store.add("Uno", "https://e.com/1", [file], "completed", "", DownloadOptions(tmp_path))
    store.add("Dos", "https://e.com/2", [], "failed", "error")
    page = HistoryPage(store)
    qtbot.addWidget(page)
    assert page.table.rowCount() == 2
    page.search_edit.setText("uno")
    assert page.table.rowCount() == 1
    page.table.selectRow(0)
    assert page.redownload_button.isEnabled() and page.edit_button.isEnabled()
    with qtbot.waitSignal(page.edit_requested) as blocker:
        page.edit_button.click()
    assert blocker.args == [str(file)]
    with qtbot.waitSignal(page.redownload_requested) as blocker:
        page.redownload_button.click()
    entry = blocker.args[0]
    downloads = DownloadManager(fake_launcher)
    item_id = downloads.requeue(entry.url, entry.options)
    _wait(qtbot, downloads, item_id, ItemState.COMPLETED)
    page.delete_selected()
    page.search_edit.clear()
    assert page.table.rowCount() == 1


def test_profiles_and_chain_in_downloads_page(
    qtbot: QtBot, ctx: AppContext, fake_launcher: Launcher, tmp_path: Path
) -> None:
    profiles = ProfileStore(None)
    page = DownloadsPage(ctx, launcher=fake_launcher, profiles=profiles)
    qtbot.addWidget(page)
    page.preset_combo.setCurrentIndex(page.preset_combo.findData("mp3"))
    page.chain_combo.setCurrentIndex(page.chain_combo.findData("extract_audio"))
    page.chain_value.setText("wav")
    page.chain_value.editingFinished.emit()
    assert ChainAction.from_json(ctx.settings.chain_action) == ChainAction("extract_audio", "wav")
    saved = page.save_profile("Audio")
    assert saved.values["download_preset"] == "mp3"
    assert page.profile_combo.currentData() == "Audio"
    assert page.current_options().profile == "Audio"
    assert page.current_options().chain == ctx.settings.chain_action

    page.preset_combo.setCurrentIndex(page.preset_combo.findData("720p"))
    page.chain_combo.setCurrentIndex(page.chain_combo.findData("none"))
    assert page.current_preset() is Preset.P720
    page.apply_profile(saved)
    assert page.current_preset() is Preset.MP3
    assert page.chain_combo.currentData() == "extract_audio"
    assert page.feedback_label.text() == "Perfil aplicado: Audio."

    ctx.settings.use_download_archive = True
    args = list(page.current_options().extra_args)
    assert args[args.index("--download-archive") + 1].endswith("download-archive.txt")

    view = ProfilesView(profiles)
    qtbot.addWidget(view)
    assert view.list.count() == 1
    view.toggle_default()
    assert profiles.default() is not None
    view.duplicate()
    target = tmp_path / "perfiles.json"
    view.export_to(target)
    assert len(view.import_from(target)) == 1
    assert len(profiles.all()) == 3


def test_main_window_has_history_and_default_profile(qtbot: QtBot, ctx: AppContext) -> None:
    window = MainWindow(ctx)
    qtbot.addWidget(window)
    assert window.pages["history"] is window.history_page
    assert window.pages["library"].tabs.count() == 2
    window.close()
