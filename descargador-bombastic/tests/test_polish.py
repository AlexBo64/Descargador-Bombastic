import time
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from bombastic.context import AppContext
from bombastic.core.download_manager import DownloadManager, ItemState
from bombastic.core.download_models import DownloadItem
from bombastic.core.settings import SettingsStore
from bombastic.core.thumbnails import ThumbnailLoader
from bombastic.core.ytdlp_command import DownloadOptions
from bombastic.core.ytdlp_progress import ProgressSnapshot
from bombastic.core.ytdlp_runner import Launcher
from bombastic.ui.downloads_page import DownloadsPage
from bombastic.ui.first_run import AboutDialog, FirstRunWizard
from bombastic.ui.main_window import MainWindow
from bombastic.ui.queue_page import QueuePage


def test_first_run_wizard(qtbot: QtBot, ctx: AppContext, tmp_path: Path) -> None:
    wizard = FirstRunWizard(ctx)
    qtbot.addWidget(wizard)
    wizard.language.setCurrentIndex(wizard.language.findData("en"))
    assert ctx.translator.language == "en"
    wizard.theme.setCurrentIndex(wizard.theme.findData("light"))
    assert ctx.theme.effective == "light"
    wizard.folder.setText(str(tmp_path / "Vídeos"))
    wizard.accept()
    saved = SettingsStore(ctx.paths.settings_path).load()
    assert saved.first_run_done and saved.language == "en"
    assert saved.download_dir == str(tmp_path / "Vídeos")


def test_startup_shows_the_wizard_once(qtbot: QtBot, ctx: AppContext) -> None:
    ctx.settings.update_check_hours = 0  # sin red en los tests
    window = MainWindow(ctx)
    qtbot.addWidget(window)
    window.startup_checks()
    wizards = window.findChildren(FirstRunWizard)
    assert len(wizards) == 1
    wizards[0].accept()
    window.startup_checks()
    assert len(window.findChildren(FirstRunWizard)) == 1
    window.close()


def test_about_dialog(qtbot: QtBot, ctx: AppContext) -> None:
    dialog = AboutDialog({"yt-dlp": "2026.10.26", "ffmpeg": ""})
    qtbot.addWidget(dialog)
    assert dialog.versions.text() == "yt-dlp: 2026.10.26\nffmpeg: No encontrado"
    assert AboutDialog.licenses_path().is_file()


def test_ctrl_v_pastes_and_adds(qtbot: QtBot, ctx: AppContext, fake_launcher: Launcher) -> None:
    page = DownloadsPage(ctx, launcher=fake_launcher)
    qtbot.addWidget(page)
    QApplication.clipboard().setText("https://example.com/v1 y https://example.com/v2")
    assert page.paste_and_add() == [1, 2]
    page.show()
    page.url_input.setFocus()
    qtbot.waitUntil(page.url_input.hasFocus)
    assert page.paste_and_add() == []
    assert "example.com/v1" in page.url_input.toPlainText()


def test_queue_page_handles_many_items(qtbot: QtBot, tmp_path: Path) -> None:
    manager = DownloadManager(lambda _args: None)
    page = QueuePage(manager, ThumbnailLoader(tmp_path))
    qtbot.addWidget(page)
    for n in range(1, 151):
        manager._items[n] = DownloadItem(
            n, f"https://e.com/{n}", state=ItemState.QUEUED, position=n,
            options=DownloadOptions(tmp_path),
        )  # fmt: skip
        manager.item_added.emit(n)
    assert len(page.cards) == 150
    item = manager._items[75]
    item.state = ItemState.DOWNLOADING
    start = time.perf_counter()
    for k in range(50):
        item.snapshot = ProgressSnapshot(fraction=k / 50)
        manager.item_changed.emit(75)
    per_update = (time.perf_counter() - start) / 50
    # Hoy ronda 0,3 ms; el margen es amplio para máquinas lentas de CI.
    assert per_update < 0.02
    manager.move(150, -149)
    layout = page._cards_layout
    assert layout.indexOf(page.cards[150]) < layout.indexOf(page.cards[1])


@pytest.mark.parametrize("language", ["es", "en"])
def test_every_page_retranslates(qtbot: QtBot, ctx: AppContext, language: str) -> None:
    window = MainWindow(ctx)
    qtbot.addWidget(window)
    ctx.translator.set_language(language)
    for page in window.pages.values():
        assert page.title_label.text() and not page.title_label.text().startswith("nav.")
    window.close()
