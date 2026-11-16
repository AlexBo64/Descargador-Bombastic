from pathlib import Path

import pytest
from PySide6.QtWidgets import QDialogButtonBox
from pytestqt.qtbot import QtBot

from bombastic.context import AppContext
from bombastic.core.download_manager import ItemState
from bombastic.core.settings import SettingsStore
from bombastic.core.ytdlp_runner import Launcher
from bombastic.ui.downloads_page import DownloadsPage
from bombastic.ui.formats_dialog import format_spec

TIMEOUT = 20_000


@pytest.fixture
def page(qtbot: QtBot, ctx: AppContext, fake_launcher: Launcher, tmp_path: Path) -> DownloadsPage:
    ctx.settings.download_dir = str(tmp_path / "descargas")
    downloads_page = DownloadsPage(ctx, launcher=fake_launcher)
    qtbot.addWidget(downloads_page)
    return downloads_page


def test_advanced_dialog_builds_options_and_preview(
    qtbot: QtBot, page: DownloadsPage, ctx: AppContext
) -> None:
    dialog = page.open_advanced()
    qtbot.addWidget(dialog)
    # Cookies + un grupo por cada grupo visible de yt-dlp, con nombres en español.
    titles = [dialog.tabs.tabText(i) for i in range(dialog.tabs.count())]
    assert titles[:3] == ["Cookies", "General", "Red"]
    rows = {row.option.key: row for row in dialog.rows}
    chapters = rows["--embed-chapters"]
    assert chapters.help_label.text() == "Añade marcadores de capítulos al vídeo."

    assert chapters.check is not None
    chapters.check.setChecked(True)
    assert chapters.name.font().bold()
    proxy = rows["--proxy"]
    assert proxy.edit is not None
    proxy.edit.setText("socks5://127.0.0.1:9050")
    assert ctx.settings.advanced_options == {
        "--embed-chapters": True,
        "--proxy": "socks5://127.0.0.1:9050",
    }
    preview = dialog.preview_edit.toPlainText()
    assert "--embed-chapters" in preview
    assert "--proxy socks5://127.0.0.1:9050" in preview

    dialog.extra_edit.setText('--output "sin cerrar')
    assert dialog.extra_error.isVisibleTo(dialog)
    dialog.extra_edit.setText("-f bestaudio")
    assert not dialog.extra_error.text()
    assert "-f bestaudio --" in dialog.preview_edit.toPlainText()
    assert "-f sustituye" in dialog.conflicts_label.text()

    dialog.cookies_mode.setCurrentIndex(dialog.cookies_mode.findData("browser"))
    dialog.cookies_browser.setCurrentIndex(dialog.cookies_browser.findData("firefox"))
    assert "--cookies-from-browser firefox" in dialog.preview_edit.toPlainText()

    dialog.filter("subtítulos")
    assert not rows["--proxy"].isVisibleTo(dialog)
    assert dialog.tabs.isTabVisible(titles.index("Subtítulos"))
    assert not dialog.tabs.isTabVisible(0)
    dialog.filter("")

    dialog.reject()
    saved = SettingsStore(ctx.paths.settings_path).load()
    assert saved.advanced_options["--embed-chapters"] is True
    assert saved.cookies_mode == "browser"
    assert "2 opciones avanzadas activas" not in page.advanced_status.text()
    assert "Cookies activadas" in page.advanced_status.text()

    dialog = page.open_advanced()
    qtbot.addWidget(dialog)
    dialog.reset_all()
    assert ctx.settings.advanced_options == {}
    assert ctx.settings.extra_args == ""
    assert ctx.settings.cookies_mode == "off"
    dialog.reject()


def test_formats_dialog_and_manual_format_download(
    qtbot: QtBot, page: DownloadsPage, ctx: AppContext
) -> None:
    assert format_spec("137", "140") == "137+140"
    assert format_spec("", "140") == "140"
    (item_id,) = page.add_text("https://example.com/video")
    qtbot.waitUntil(
        lambda: page.manager.item(item_id).state is ItemState.READY,  # type: ignore[union-attr]
        timeout=TIMEOUT,
    )
    card = page.cards[item_id]
    page.show()
    qtbot.waitUntil(card.formats_button.isVisible)

    dialog = page.choose_format(item_id)
    assert dialog is not None
    qtbot.addWidget(dialog)
    ok = dialog.buttons.button(QDialogButtonBox.StandardButton.Ok)
    assert not ok.isEnabled()
    # Los mejores primero: 137 (1080p) antes que 18 (360p).
    assert dialog.video_table.item(0, 0).text() == "18"
    assert dialog.video_table.item(1, 0).text() == "137"
    dialog.video_table.selectRow(1)
    dialog.audio_table.selectRow(0)
    assert dialog.spec() == "137+140"
    assert ok.isEnabled()
    dialog.video_table.selectRow(0)  # el 18 ya lleva audio
    assert dialog.spec() == "18"
    dialog.video_table.selectRow(1)
    dialog.accept()
    assert page.format_specs == {item_id: "137+140"}
    assert "137+140" in page.feedback_label.text()

    card.download_button.click()
    qtbot.waitUntil(
        lambda: page.manager.item(item_id).state is ItemState.COMPLETED,  # type: ignore[union-attr]
        timeout=TIMEOUT,
    )
    item = page.manager.item(item_id)
    assert item is not None
    assert "-f 137+140" in item.command
    assert page.format_specs == {}
