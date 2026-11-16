from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from bombastic.context import AppContext
from bombastic.core.download_manager import ItemState
from bombastic.core.settings import SettingsStore
from bombastic.core.ytdlp_runner import Launch, Launcher
from bombastic.ui.downloads_page import DownloadsPage
from bombastic.ui.main_window import MainWindow
from bombastic.ui.queue_page import QueuePage
from bombastic.ui.settings_page import SettingsPage

TIMEOUT = 20_000


@pytest.fixture
def pages(
    qtbot: QtBot, ctx: AppContext, fake_launcher: Launcher, tmp_path: Path
) -> tuple[DownloadsPage, QueuePage]:
    ctx.settings.download_dir = str(tmp_path / "descargas")
    downloads = DownloadsPage(ctx, launcher=fake_launcher)
    queue = QueuePage(downloads.manager, downloads.thumbnails)
    qtbot.addWidget(downloads)
    qtbot.addWidget(queue)
    queue.show()
    return downloads, queue


def _wait_state(qtbot: QtBot, page: DownloadsPage, item_id: int, state: ItemState) -> None:
    def reached() -> bool:
        item = page.manager.item(item_id)
        return item is not None and item.state is state

    qtbot.waitUntil(reached, timeout=TIMEOUT)


def _ready(qtbot: QtBot, page: DownloadsPage, text: str) -> list[int]:
    ids = page.add_text(text)
    for item_id in ids:
        _wait_state(qtbot, page, item_id, ItemState.READY)
    return ids


def test_started_downloads_show_up_in_the_queue(
    qtbot: QtBot, pages: tuple[DownloadsPage, QueuePage]
) -> None:
    downloads, queue = pages
    assert queue.empty_label.isVisible()
    _ready(qtbot, downloads, "https://example.com/video https://example.com/fail")
    assert queue.cards == {}
    downloads.download_all()
    assert list(queue.cards) == [1, 2]
    assert not queue.empty_label.isVisible()

    _wait_state(qtbot, downloads, 1, ItemState.COMPLETED)
    _wait_state(qtbot, downloads, 2, ItemState.FAILED)
    assert queue.cards[1].status_label.full_text() == "Completado: Vídeo de prueba ñ.mp4"
    # Error legible en español; el original queda en el log.
    assert queue.cards[2].status_label.full_text() == "Error: Este vídeo es privado"
    assert queue.summary_label.text() == "0 en curso · 0 en espera · 2 en total"
    assert queue.retry_failed_button.isEnabled()
    assert queue.cards[2].more_button.isVisible()

    queue.retry_failed()
    assert not queue.cards[2].status_label.full_text().startswith("Error")
    _wait_state(qtbot, downloads, 2, ItemState.FAILED)
    queue.clear_finished()
    assert queue.cards == {}
    assert downloads.manager.items() == []


def test_pause_resume_and_move_from_the_cards(
    qtbot: QtBot, pages: tuple[DownloadsPage, QueuePage], fake_launcher: Launcher
) -> None:
    downloads, queue = pages
    first, second = _ready(qtbot, downloads, "https://example.com/a https://example.com/b")

    def slow(args: list[str]) -> Launch | None:
        return fake_launcher([*args[:-1], args[-1] + "/slow"])

    downloads.manager._launcher = slow
    downloads.manager.max_concurrent = 1
    downloads.download_all()
    card = queue.cards[first]
    # Las tarjetas nuevas se muestran en la siguiente vuelta del bucle de eventos.
    qtbot.waitUntil(card.pause_button.isVisible)
    assert card.pause_button.text() == "Pausar"

    card.pause_button.click()
    _wait_state(qtbot, downloads, first, ItemState.PAUSED)
    assert card.pause_button.text() == "Reanudar"
    assert queue.resume_all_button.isEnabled()
    _wait_state(qtbot, downloads, second, ItemState.DOWNLOADING)

    # "Bajar" desde el menú reordena la cola y las tarjetas.
    card.menu_requested.emit(first, "down")
    assert [i.item_id for i in downloads.manager.queue_items()] == [second, first]
    layout = queue._cards_layout
    assert layout.indexOf(queue.cards[second]) < layout.indexOf(card)

    card.menu_requested.emit(first, "copy_url")
    assert QApplication.clipboard().text() == "https://example.com/a"

    queue.pause_all_button.click()
    _wait_state(qtbot, downloads, second, ItemState.PAUSED)
    assert not downloads.has_active_downloads()
    downloads.manager.shutdown()


def test_queue_settings_are_saved_and_applied(qtbot: QtBot, ctx: AppContext) -> None:
    window = MainWindow(ctx)
    qtbot.addWidget(window)
    settings_page: SettingsPage = window.settings_page
    settings_page.concurrent_spin.setValue(5)
    settings_page.retries_spin.setValue(0)
    settings_page.rate_edit.setText("1.5m")
    settings_page.rate_edit.editingFinished.emit()
    manager = window.downloads_page.manager
    assert (manager.max_concurrent, manager.max_retries, manager.rate_limit) == (5, 0, "1.5M")
    saved = SettingsStore(ctx.paths.settings_path).load()
    assert (saved.max_concurrent, saved.auto_retries, saved.rate_limit) == (5, 0, "1.5M")

    settings_page.rate_edit.setText("rápido")
    settings_page.rate_edit.editingFinished.emit()
    assert settings_page.rate_edit.text() == "1.5M"
    assert window.pages["queue"] is window.queue_page
    window.close()
