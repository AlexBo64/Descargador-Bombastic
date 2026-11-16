from pathlib import Path

from pytestqt.qtbot import QtBot

from bombastic.context import AppContext
from bombastic.core.binaries import BinaryLocation, BinaryStatus, Source, Tool
from bombastic.core.settings import PAGES, SettingsStore
from bombastic.ui.main_window import MainWindow
from bombastic.ui.theme import PALETTES


def _window(qtbot: QtBot, ctx: AppContext) -> MainWindow:
    window = MainWindow(ctx)
    qtbot.addWidget(window)
    window.show()
    return window


def test_window_opens_with_all_sections(qtbot: QtBot, ctx: AppContext) -> None:
    window = _window(qtbot, ctx)
    assert window.isVisible()
    assert window.windowTitle() == "Descargador Bombastic"
    assert window.nav.count() == len(PAGES) == window.stack.count()
    assert [window.nav.item(i).text() for i in range(3)] == ["Descargas", "Cola", "Editor"]
    assert window.current_page() == "downloads"


def test_navigation_switches_page(qtbot: QtBot, ctx: AppContext) -> None:
    window = _window(qtbot, ctx)
    window.show_page("settings")
    assert window.stack.currentWidget() is window.settings_page
    assert ctx.settings.last_page == "settings"
    window.nav.setCurrentRow(1)
    assert window.current_page() == "queue"


def test_theme_changes_live_from_settings(qtbot: QtBot, ctx: AppContext) -> None:
    window = _window(qtbot, ctx)
    app = ctx.theme.parent()
    assert PALETTES["dark"]["bg"] in app.styleSheet()  # type: ignore[attr-defined]
    combo = window.settings_page.theme_combo
    combo.setCurrentIndex(combo.findData("light"))
    assert ctx.theme.effective == "light"
    assert PALETTES["light"]["bg"] in app.styleSheet()  # type: ignore[attr-defined]
    assert SettingsStore(ctx.paths.settings_path).load().theme == "light"


def test_language_changes_live_from_settings(qtbot: QtBot, ctx: AppContext) -> None:
    window = _window(qtbot, ctx)
    page = window.settings_page
    page.language_combo.setCurrentIndex(page.language_combo.findData("en"))
    assert window.nav.item(1).text() == "Queue"
    assert page.title_label.text() == "Settings"
    assert page.appearance_box.title() == "Appearance"
    # El desplegable conserva la selección tras retraducirse.
    assert page.language_combo.currentData() == "en"
    assert page.theme_combo.itemText(page.theme_combo.findData("dark")) == "Dark"
    assert SettingsStore(ctx.paths.settings_path).load().language == "en"


def test_download_dir_defaults_and_persists(qtbot: QtBot, ctx: AppContext, tmp_path: Path) -> None:
    window = _window(qtbot, ctx)
    page = window.settings_page
    assert page.download_dir_edit.text().endswith("Downloads")
    target = tmp_path / "Mis vídeos ñ"
    page.set_download_dir(str(target))
    assert page.download_dir_edit.text() == str(target)
    assert SettingsStore(ctx.paths.settings_path).load().download_dir == str(target)


def test_dependency_statuses_are_shown(qtbot: QtBot, ctx: AppContext) -> None:
    window = _window(qtbot, ctx)
    page = window.settings_page
    exe = ctx.paths.bin_dir / "yt-dlp.exe"
    page.show_statuses(
        {
            Tool.YTDLP: BinaryStatus(BinaryLocation(Tool.YTDLP, exe, Source.DATA), "2025.10.22"),
            Tool.FFMPEG: BinaryStatus(BinaryLocation(Tool.FFMPEG, None, Source.MISSING)),
            Tool.FFPROBE: BinaryStatus(
                BinaryLocation(Tool.FFPROBE, exe, Source.DATA), None, "timeout"
            ),
        }
    )
    assert page._tool_status[Tool.YTDLP].text() == "Versión 2025.10.22"
    assert page._tool_path[Tool.YTDLP].text() == str(exe)
    assert page._tool_status[Tool.FFMPEG].text() == "No encontrado"
    assert page._tool_status[Tool.FFPROBE].text() == "Encontrado, pero no responde"


def test_refresh_dependencies_runs_real_probe(qtbot: QtBot, ctx: AppContext) -> None:
    window = _window(qtbot, ctx)
    page = window.settings_page
    page.refresh_dependencies()
    assert not page.recheck_button.isEnabled()
    qtbot.waitUntil(page.recheck_button.isEnabled, timeout=20_000)
    assert page._statuses is not None
    assert set(page._statuses) == set(Tool)


def test_close_persists_window_state(qtbot: QtBot, ctx: AppContext) -> None:
    window = _window(qtbot, ctx)
    window.resize(1000, 700)
    window.show_page("history")
    window.close()
    saved = SettingsStore(ctx.paths.settings_path).load()
    assert (saved.window_width, saved.window_height) == (1000, 700)
    assert saved.last_page == "history"
