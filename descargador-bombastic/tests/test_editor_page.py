from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from bombastic.context import AppContext
from bombastic.core.download_manager import DownloadManager
from bombastic.core.edit_manager import EditManager, EditState
from bombastic.core.thumbnails import ThumbnailLoader
from bombastic.core.ytdlp_runner import Launcher
from bombastic.ui.editor_page import EditorPage
from bombastic.ui.editor_tools import ConcatForm, SegmentsForm, TrimForm
from bombastic.ui.main_window import MainWindow
from bombastic.ui.queue_page import QueuePage

TIMEOUT = 20_000


@pytest.fixture
def editor(qtbot: QtBot, ctx: AppContext, fake_ffmpeg: Launcher) -> tuple[EditorPage, EditManager]:
    manager = EditManager(fake_ffmpeg)
    page = EditorPage(ctx, manager, probe_launcher=fake_ffmpeg)
    # El archivo de prueba no es un vídeo real: sin esto se generaría la copia ligera y su
    # mensaje podría pisar el que comprueba el test (la copia tiene su propio test).
    page.player.playback_failed.disconnect(page._on_playback_failed)
    qtbot.addWidget(page)
    page.show()
    return page, manager


def _open(qtbot: QtBot, page: EditorPage, path: Path) -> None:
    path.write_bytes(b"x")
    with qtbot.waitSignal(page.file_opened, timeout=TIMEOUT):
        page.open_file(path)


def test_open_file_shows_info_and_enables_tools(
    qtbot: QtBot, editor: tuple[EditorPage, EditManager], tmp_path: Path
) -> None:
    page, _manager = editor
    assert not page.queue_button.isEnabled()
    assert page.file_label.text() == "Ningún archivo abierto. Ábrelo o arrástralo aquí."
    _open(qtbot, page, tmp_path / "clip ñ.mp4")
    assert page.queue_button.isEnabled()
    info = page.info.toPlainText()
    assert "Duración: 00:00:10.000" in info
    assert "#0 · video · h264 · 640x360 · 29.97 fps" in info
    assert "#1 · audio · aac · 48000 Hz · 2 canales · spa" in info
    assert page.player.fps == pytest.approx(29.97)

    with qtbot.assertNotEmitted(page.file_opened, wait=300):
        page.open_file(tmp_path / "broken.mp4")
        qtbot.waitUntil(lambda: "No se puede leer" in page.feedback.text(), timeout=TIMEOUT)


def test_markers_fill_trim_and_queue_runs(
    qtbot: QtBot, editor: tuple[EditorPage, EditManager], tmp_path: Path
) -> None:
    page, manager = editor
    _open(qtbot, page, tmp_path / "clip.mp4")
    trim = page.forms[1]
    assert isinstance(trim, TrimForm)
    page.player.set_markers(4.5, 1.25)  # al revés: se intercambian
    assert (page.player.marker_in, page.player.marker_out) == (1.25, 4.5)
    assert (trim.start.text(), trim.end.text()) == ("00:00:01.250", "00:00:04.500")
    assert page.player.slider.marker_in == 1250

    page.tools.setCurrentWidget(trim)
    plan = page.current_plan()
    assert plan is not None
    assert plan.output == tmp_path / "clip_editado.mp4"
    assert "-c" in plan.passes[0] and "copy" in plan.passes[0]
    trim.end.setText("00:00:01")
    assert page.current_plan() is None
    assert page.feedback.text() == "El tiempo de fin tiene que ser posterior al de inicio."
    trim.end.setText("00:00:04.5")

    task_id = page.add_to_queue()
    assert task_id is not None
    assert "Añadido a la cola de edición" in page.feedback.text()
    qtbot.waitUntil(
        lambda: manager.task(task_id).state is EditState.COMPLETED,  # type: ignore[union-attr]
        timeout=TIMEOUT,
    )
    assert (tmp_path / "clip_editado.mp4").is_file()
    # La siguiente salida no pisa la anterior.
    second = page.current_plan()
    assert second is not None
    assert second.output.name == "clip_editado (1).mp4"


def test_segments_and_concat_forms(
    qtbot: QtBot, editor: tuple[EditorPage, EditManager], tmp_path: Path
) -> None:
    page, _manager = editor
    _open(qtbot, page, tmp_path / "a.mp4")
    segments = page.forms[2]
    assert isinstance(segments, SegmentsForm)
    page.tools.setCurrentWidget(segments)
    assert page.current_plan() is None
    assert page.feedback.text() == "Añade al menos un tramo."
    page.player.set_markers(1, 2)
    assert segments.add_marked()
    page.player.set_markers(5, 6)
    assert segments.add_marked()
    assert segments.list.count() == 2
    plan = page.current_plan()
    assert plan is not None and plan.duration == 2

    concat = page.concat_form
    assert isinstance(concat, ConcatForm)
    page.tools.setCurrentWidget(concat)
    concat.add_current.click()
    other = tmp_path / "b.mp4"
    other.write_bytes(b"x")
    concat.add_path(other)
    qtbot.waitUntil(lambda: "compatibles" in concat.status.text(), timeout=TIMEOUT)
    plan = page.current_plan()
    assert plan is not None and "concat" in plan.passes[0]
    listing = plan.temp_files[0]
    assert listing.read_text(encoding="utf-8").count("file '") == 2

    big = tmp_path / "big.mp4"
    big.write_bytes(b"x")
    concat.add_path(big)
    qtbot.waitUntil(lambda: "se recodificarán" in concat.status.text(), timeout=TIMEOUT)


def test_language_change_retranslates_forms(
    qtbot: QtBot, editor: tuple[EditorPage, EditManager], ctx: AppContext
) -> None:
    page, _manager = editor
    ctx.translator.set_language("en")
    page.retranslate()
    assert page.tools.tabText(0) == "Convert"
    trim = page.forms[1]
    assert isinstance(trim, TrimForm)
    assert trim.precise.text() == "Precise mode (re-encodes)"
    convert = page.forms[0]
    combo = convert.container  # type: ignore[attr-defined]
    assert combo.itemText(combo.findData("mp3")) == "MP3 (audio only)"


def test_edit_queue_tab_in_queue_page(
    qtbot: QtBot, editor: tuple[EditorPage, EditManager], tmp_path: Path
) -> None:
    page, manager = editor
    downloads = DownloadManager(lambda _args: None)
    queue = QueuePage(downloads, ThumbnailLoader(tmp_path / "miniaturas"), manager)
    qtbot.addWidget(queue)
    assert queue.tabs.tabText(1) == "Ediciones"
    assert queue.edit_view is not None
    _open(qtbot, page, tmp_path / "c.mp4")
    task_id = page.add_to_queue()
    assert task_id in queue.edit_view.cards
    qtbot.waitUntil(
        lambda: "Terminado" in queue.edit_view.cards[task_id].status.full_text(),  # type: ignore[union-attr]
        timeout=TIMEOUT,
    )
    queue.edit_view.clear_finished()
    assert queue.edit_view.cards == {}


def test_main_window_has_the_editor(qtbot: QtBot, ctx: AppContext) -> None:
    window = MainWindow(ctx)
    qtbot.addWidget(window)
    assert window.pages["editor"] is window.editor_page
    assert window.queue_page.edit_view is not None
    QApplication.processEvents()
    assert window.close()


def test_player_volume_label_and_hidden_subtitles(
    qtbot: QtBot, editor: tuple[EditorPage, EditManager], tmp_path: Path
) -> None:
    page, _manager = editor
    player = page.player
    assert player.volume_label.text() == "Volumen"
    player.volume.setValue(35)
    assert player.volume.toolTip() == "Volumen: 35 %"
    assert player.audio.volume() == pytest.approx(0.35)
    # Sin pistas de subtítulos (archivo falso) el selector no se ve.
    _open(qtbot, page, tmp_path / "a.mp4")
    assert not player.subs_combo.isVisibleTo(page)
