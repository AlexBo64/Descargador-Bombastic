from pathlib import Path

import pytest
from PySide6.QtCore import QUrl
from PySide6.QtGui import QColor, QImage
from pytestqt.qtbot import QtBot

from bombastic.context import AppContext
from bombastic.core.download_manager import DownloadItem, ItemState
from bombastic.core.media_info import MediaInfo
from bombastic.core.settings import SettingsStore
from bombastic.core.thumbnails import ThumbnailLoader, cache_path
from bombastic.core.ytdlp_command import DownloadOptions, Preset
from bombastic.core.ytdlp_progress import ProgressSnapshot
from bombastic.core.ytdlp_runner import ERROR_YTDLP, Launcher
from bombastic.ui.download_card import DownloadCard, meta_text, output_folder, status_text
from bombastic.ui.downloads_page import DownloadsPage
from bombastic.ui.main_window import MainWindow

TIMEOUT = 20_000


@pytest.fixture
def page(qtbot: QtBot, ctx: AppContext, fake_launcher: Launcher, tmp_path: Path) -> DownloadsPage:
    ctx.settings.download_dir = str(tmp_path / "descargas ñ")
    downloads_page = DownloadsPage(ctx, launcher=fake_launcher)
    qtbot.addWidget(downloads_page)
    downloads_page.show()
    return downloads_page


def _wait_state(qtbot: QtBot, page: DownloadsPage, item_id: int, state: ItemState) -> None:
    def reached() -> bool:
        item = page.manager.item(item_id)
        return item is not None and item.state is state

    qtbot.waitUntil(reached, timeout=TIMEOUT)


def _info(**changes: object) -> MediaInfo:
    values: dict[str, object] = {
        "url": "https://example.com/v",
        "media_id": "abc",
        "title": "Título",
        "channel": "Canal",
        "duration": 75.0,
        "thumbnail_url": "",
        "is_playlist": False,
        "entry_count": None,
        "is_live": False,
        "extractor": "Fake",
    }
    values.update(changes)
    return MediaInfo(**values)  # type: ignore[arg-type]


# --------------------------------------------------------------------- textos


def test_meta_text(translator: object) -> None:
    item = DownloadItem(1, "https://example.com/v")
    assert meta_text(item) == ""
    item.info = _info()
    assert meta_text(item) == "Canal · 1:15"
    item.info = _info(is_playlist=True, entry_count=12, duration=None)
    assert meta_text(item) == "Canal · Lista de reproducción · 12 elementos"
    item.info = _info(is_playlist=True, channel="")
    assert meta_text(item) == "Lista de reproducción"
    item.info = _info(is_live=True)
    assert meta_text(item) == "Canal · En directo"


def test_status_text_for_every_state(translator: object) -> None:
    item = DownloadItem(1, "https://example.com/v")
    assert status_text(item) == "Obteniendo información…"
    item.state = ItemState.READY
    assert status_text(item) == "Listo para descargar"
    item.state = ItemState.CANCELLED
    assert status_text(item) == "Cancelado"

    item.state = ItemState.DOWNLOADING
    assert status_text(item) == "Descargando"
    item.snapshot = ProgressSnapshot(
        fraction=0.456, downloaded=1536, total=4096, speed=2048, eta=75, item_index=2, item_count=5
    )
    assert status_text(item) == (
        "Elemento 2 de 5 · Descargando · 46 % · 1.5 KB de 4.0 KB · 2.0 KB/s · quedan 1:15"
    )
    item.snapshot = ProgressSnapshot(downloaded=1536)
    assert status_text(item) == "Descargando · 1.5 KB"
    item.state = ItemState.PROCESSING
    item.snapshot = ProgressSnapshot(phase="processing", fraction=1.0, speed=5.0)
    assert status_text(item) == "Procesando con ffmpeg · 100 %"

    item.state = ItemState.COMPLETED
    assert status_text(item) == "Completado"
    item.files = [Path("C:/x/Vídeo ñ.mp4")]
    assert status_text(item) == "Completado: Vídeo ñ.mp4"
    item.files.append(Path("C:/x/otro.mp4"))
    assert status_text(item) == "Completado: 2 archivos"

    item.state = ItemState.FAILED
    item.error_code, item.error_detail = ERROR_YTDLP, "Video unavailable"
    assert status_text(item) == "Error: Video unavailable"
    item.error_code, item.error_detail = "exit_code", "3"
    assert status_text(item) == "Error: yt-dlp terminó con el código 3 sin explicar el motivo"
    item.state = ItemState.INFO_ERROR
    item.error_code = "timeout"
    assert status_text(item) == (
        "No se pudo obtener la información: yt-dlp ha tardado demasiado en responder"
    )


def test_output_folder(tmp_path: Path) -> None:
    item = DownloadItem(1, "u")
    assert output_folder(item) is None
    item.options = DownloadOptions(tmp_path / "destino")
    assert output_folder(item) == tmp_path / "destino"
    item.files = [tmp_path / "no-existe" / "a.mp4", tmp_path / "a.mp4"]
    assert output_folder(item) == tmp_path


# -------------------------------------------------------------------- tarjeta


def test_card_buttons_follow_the_state(qtbot: QtBot, ctx: AppContext) -> None:
    item = DownloadItem(7, "https://example.com/un-enlace-muy-largo")
    card = DownloadCard(item)
    qtbot.addWidget(card)
    card.show()

    def visible() -> list[str]:
        card.refresh()
        buttons = {
            "download": card.download_button,
            "cancel": card.cancel_button,
            "open": card.open_button,
            "remove": card.remove_button,
        }
        return [name for name, button in buttons.items() if button.isVisible()]

    assert card.title_label.full_text() == item.url
    assert visible() == ["remove"]
    assert card.progress_bar.isVisible()

    item.state, item.info = ItemState.READY, _info()
    assert visible() == ["download", "remove"]
    assert card.title_label.full_text() == "Título"
    assert card.download_button.text() == "Descargar"
    assert not card.progress_bar.isVisible()

    item.state = ItemState.QUEUED
    assert visible() == ["cancel"]

    item.state, item.snapshot = ItemState.DOWNLOADING, ProgressSnapshot(fraction=0.5)
    assert visible() == ["cancel"]
    assert (card.progress_bar.maximum(), card.progress_bar.value()) == (1000, 500)

    item.state = ItemState.PROCESSING
    assert visible() == ["cancel"]
    assert card.progress_bar.maximum() == 0  # barra animada

    item.state = ItemState.COMPLETED
    assert visible() == ["open", "remove"]

    item.state, item.error_code = ItemState.FAILED, "timeout"
    assert visible() == ["download", "remove"]
    assert card.download_button.text() == "Reintentar"
    assert card.status_label.property("error") is True


def test_card_signals(qtbot: QtBot, ctx: AppContext) -> None:
    item = DownloadItem(7, "https://example.com/v", state=ItemState.READY)
    card = DownloadCard(item)
    qtbot.addWidget(card)
    with qtbot.waitSignal(card.download_requested) as blocker:
        card.download_button.click()
    assert blocker.args == [7]
    item.state = ItemState.INFO_ERROR
    with qtbot.waitSignal(card.retry_info_requested) as blocker:
        card.download_button.click()
    assert blocker.args == [7]
    with qtbot.waitSignal(card.remove_requested):
        card.remove_button.click()
    with qtbot.waitSignal(card.cancel_requested):
        card.cancel_button.click()
    with qtbot.waitSignal(card.open_folder_requested):
        card.open_button.click()


def test_card_thumbnail(qtbot: QtBot, ctx: AppContext, tmp_path: Path) -> None:
    image = QImage(640, 480, QImage.Format.Format_RGB32)
    image.fill(QColor("#336699"))
    file = tmp_path / "miniatura ñ.png"
    assert image.save(str(file))
    card = DownloadCard(DownloadItem(1, "u"))
    qtbot.addWidget(card)
    card.set_thumbnail(str(tmp_path / "no-existe.png"))
    assert not card.has_thumbnail()
    card.set_thumbnail(str(file))
    assert card.has_thumbnail()
    pixmap = card.thumbnail.pixmap()
    assert pixmap.deviceIndependentSize().toSize() == card.thumbnail.size()


def test_thumbnail_loader_downloads_and_caches(qtbot: QtBot, tmp_path: Path) -> None:
    image = QImage(32, 18, QImage.Format.Format_RGB32)
    image.fill(QColor("#336699"))
    source = tmp_path / "origen.png"
    assert image.save(str(source))
    url = QUrl.fromLocalFile(str(source)).toString()
    cache = tmp_path / "caché ñ"
    loader = ThumbnailLoader(cache)

    with qtbot.waitSignal(loader.loaded, timeout=TIMEOUT) as blocker:
        loader.request(url)
    assert blocker.args == [url, str(cache_path(cache, url))]
    assert Path(blocker.args[1]).read_bytes() == source.read_bytes()

    # La segunda vez sale de la caché aunque el origen ya no exista.
    source.unlink()
    with qtbot.waitSignal(loader.loaded, timeout=TIMEOUT) as blocker:
        loader.request(url)
    assert blocker.args[0] == url

    # Un fallo no emite nada ni deja archivos.
    missing = QUrl.fromLocalFile(str(tmp_path / "no-existe.jpg")).toString()
    with qtbot.assertNotEmitted(loader.loaded, wait=500):
        loader.request(missing)
        loader.request("")
    assert not cache_path(cache, missing).exists()
    assert cache_path(cache, "https://x.example/a?b=1").suffix == ".img"


# --------------------------------------------------------------------- página


def test_adding_a_link_creates_a_card(qtbot: QtBot, page: DownloadsPage) -> None:
    assert page.empty_label.isVisible()
    assert not page.download_all_button.isVisible()
    page.url_input.setPlainText("mira https://example.com/video y esto")
    page.add_button.click()

    assert list(page.cards) == [1]
    assert page.url_input.toPlainText() == ""
    assert not page.empty_label.isVisible()
    card = page.cards[1]
    assert card.status_label.full_text() == "Obteniendo información…"

    _wait_state(qtbot, page, 1, ItemState.READY)
    assert card.title_label.full_text() == "Vídeo de prueba ñ"
    assert card.meta_label.full_text() == "Canal ñ · 1:15"
    assert card.download_button.isVisible()
    assert page.download_all_button.isEnabled()


def test_feedback_for_no_links_and_duplicates(qtbot: QtBot, page: DownloadsPage) -> None:
    page.url_input.setPlainText("esto no es un enlace")
    page.add_from_input()
    assert page.feedback_label.isVisible()
    assert page.feedback_label.text() == "No se ha encontrado ningún enlace en el texto."
    assert page.url_input.toPlainText() == "esto no es un enlace"
    page.url_input.setPlainText("otra cosa")
    assert not page.feedback_label.isVisible()

    assert page.add_text("https://example.com/a https://example.com/b") == [1, 2]
    assert page.add_text("https://example.com/a") == []
    assert page.feedback_label.text() == "Esos enlaces ya estaban en la lista."
    assert len(page.cards) == 2


def test_download_from_the_card_with_the_chosen_options(
    qtbot: QtBot, page: DownloadsPage, ctx: AppContext, tmp_path: Path
) -> None:
    page.add_text("https://example.com/video")
    _wait_state(qtbot, page, 1, ItemState.READY)

    assert not page.quality_combo.isVisible()
    page.preset_combo.setCurrentIndex(page.preset_combo.findData("mp3"))
    assert page.quality_combo.isVisible()
    assert not page.subs_check.isEnabled()
    page.quality_combo.setCurrentIndex(page.quality_combo.findData("320"))
    page.extras_check.setChecked(True)
    saved = SettingsStore(ctx.paths.settings_path).load()
    assert (saved.download_preset, saved.mp3_quality, saved.embed_extras) == ("mp3", "320", True)

    options = page.current_options()
    assert options.preset is Preset.MP3
    assert options.mp3_quality == "320"
    assert options.embed_extras
    assert options.output_dir == tmp_path / "descargas ñ"

    page.cards[1].download_button.click()
    _wait_state(qtbot, page, 1, ItemState.COMPLETED)
    card = page.cards[1]
    assert card.status_label.full_text() == "Completado: Vídeo de prueba ñ.mp3"
    assert card.open_button.isVisible()
    assert (tmp_path / "descargas ñ" / "Vídeo de prueba ñ.mp3").is_file()
    item = page.manager.item(1)
    assert item is not None
    assert "--audio-quality 320K" in item.command
    assert "--embed-thumbnail" in item.command


def test_cancel_download_all_and_clear_finished(qtbot: QtBot, page: DownloadsPage) -> None:
    page.add_text("https://example.com/slow https://example.com/fail https://example.com/video")
    for item_id in (1, 2, 3):
        _wait_state(qtbot, page, item_id, ItemState.READY)

    page.download_all_button.click()
    assert page.has_active_downloads()
    assert not page.download_all_button.isEnabled()
    assert page.cards[2].status_label.full_text() == "En espera de que termine la descarga en curso"
    qtbot.waitUntil(lambda: page.cards[1].cancel_button.isVisible(), timeout=TIMEOUT)

    page.cards[1].cancel_button.click()
    _wait_state(qtbot, page, 1, ItemState.CANCELLED)
    _wait_state(qtbot, page, 2, ItemState.FAILED)
    _wait_state(qtbot, page, 3, ItemState.COMPLETED)
    assert page.cards[1].status_label.full_text() == "Cancelado"
    assert page.cards[2].status_label.full_text().startswith("Error: [fake] abc: Video unavailable")
    assert not page.has_active_downloads()

    page.clear_button.click()
    assert page.cards == {}
    assert page.empty_label.isVisible()


def test_remove_card_and_change_folder(
    qtbot: QtBot, page: DownloadsPage, ctx: AppContext, tmp_path: Path
) -> None:
    page.add_text("https://example.com/slowinfo")
    page.cards[1].remove_button.click()
    assert page.cards == {}

    target = tmp_path / "otra carpeta"
    page.set_download_dir(str(target))
    assert page.folder_edit.text() == str(target)
    assert SettingsStore(ctx.paths.settings_path).load().download_dir == str(target)


def test_language_change_retranslates_cards(
    qtbot: QtBot, page: DownloadsPage, ctx: AppContext
) -> None:
    page.add_text("https://example.com/video")
    _wait_state(qtbot, page, 1, ItemState.READY)
    page.preset_combo.setCurrentIndex(page.preset_combo.findData("720p"))
    ctx.translator.set_language("en")
    page.retranslate()
    assert page.add_button.text() == "Add links"
    assert page.cards[1].status_label.full_text() == "Ready to download"
    assert page.cards[1].download_button.text() == "Download"
    # El desplegable conserva la selección tras retraducirse.
    assert page.preset_combo.currentData() == "720p"
    assert page.options_box.title() == "Download options"


def test_main_window_shows_the_downloads_page_and_shuts_it_down(
    qtbot: QtBot, ctx: AppContext
) -> None:
    window = MainWindow(ctx)
    qtbot.addWidget(window)
    window.show()
    window.show_page("downloads")
    assert window.stack.currentWidget() is window.downloads_page
    assert window.pages["downloads"] is window.downloads_page
    assert not window.downloads_page.has_active_downloads()
    assert window.close()
