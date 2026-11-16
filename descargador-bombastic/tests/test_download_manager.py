from pathlib import Path

from pytestqt.qtbot import QtBot

from bombastic.core.download_manager import DownloadManager, ItemState
from bombastic.core.ytdlp_command import DownloadOptions, Preset
from bombastic.core.ytdlp_runner import ERROR_MISSING, ERROR_YTDLP, Launcher

TIMEOUT = 20_000


def _wait_state(qtbot: QtBot, manager: DownloadManager, item_id: int, *states: ItemState) -> None:
    def reached() -> bool:
        item = manager.item(item_id)
        return item is not None and item.state in states

    qtbot.waitUntil(reached, timeout=TIMEOUT)


def test_add_urls_fetches_info_and_skips_duplicates(qtbot: QtBot, fake_launcher: Launcher) -> None:
    manager = DownloadManager(fake_launcher)
    added: list[int] = []
    manager.item_added.connect(added.append)
    ids = manager.add_urls(
        ["https://example.com/video", "https://example.com/playlist", "https://example.com/video"]
    )
    assert ids == added == [1, 2]
    assert [item.state for item in manager.items()] == [ItemState.FETCHING] * 2
    assert manager.add_urls(["https://example.com/video"]) == []

    _wait_state(qtbot, manager, 1, ItemState.READY)
    _wait_state(qtbot, manager, 2, ItemState.READY)
    video, playlist = manager.items()
    assert video.info is not None
    assert video.info.title == "Vídeo de prueba ñ"
    assert playlist.info is not None
    assert playlist.info.is_playlist
    assert playlist.info.entry_count == 3
    assert not manager.busy


def test_info_error_and_retry(qtbot: QtBot, fake_launcher: Launcher) -> None:
    manager = DownloadManager(fake_launcher)
    (item_id,) = manager.add_urls(["https://example.com/badinfo"])
    _wait_state(qtbot, manager, item_id, ItemState.INFO_ERROR)
    item = manager.item(item_id)
    assert item is not None
    assert (item.error_code, item.error_detail) == (
        ERROR_YTDLP,
        "[fake] abc: This video is private",
    )
    # Sin metadatos no se puede descargar.
    assert not manager.start(item_id, DownloadOptions(Path(".")))

    manager.retry_info(item_id)
    assert item.state is ItemState.FETCHING
    assert item.error_code == ""
    _wait_state(qtbot, manager, item_id, ItemState.INFO_ERROR)


def test_missing_ytdlp_is_reported(qtbot: QtBot, fake_launcher: Launcher, tmp_path: Path) -> None:
    available = {"value": False}

    def launcher(args: list[str]) -> tuple[str, list[str]] | None:
        return fake_launcher(args) if available["value"] else None

    manager = DownloadManager(launcher)
    (item_id,) = manager.add_urls(["https://example.com/video"])
    item = manager.item(item_id)
    assert item is not None
    assert (item.state, item.error_code) == (ItemState.INFO_ERROR, ERROR_MISSING)

    available["value"] = True
    manager.retry_info(item_id)
    _wait_state(qtbot, manager, item_id, ItemState.READY)

    available["value"] = False
    assert manager.start(item_id, DownloadOptions(tmp_path))
    assert (item.state, item.error_code) == (ItemState.FAILED, ERROR_MISSING)
    assert not manager.busy


def test_download_completes_and_can_be_repeated(
    qtbot: QtBot, fake_launcher: Launcher, tmp_path: Path
) -> None:
    manager = DownloadManager(fake_launcher)
    (item_id,) = manager.add_urls(["https://example.com/video"])
    _wait_state(qtbot, manager, item_id, ItemState.READY)
    states: list[ItemState] = []
    manager.item_changed.connect(lambda _id: states.append(manager.items()[0].state))

    assert manager.start(item_id, DownloadOptions(tmp_path, preset=Preset.MP3))
    assert manager.busy
    # Ya está en marcha: no se puede pedir dos veces.
    assert not manager.start(item_id, DownloadOptions(tmp_path))
    _wait_state(qtbot, manager, item_id, ItemState.COMPLETED)

    item = manager.item(item_id)
    assert item is not None
    assert item.files == [tmp_path / "Vídeo de prueba ñ.mp3"]
    assert item.snapshot is not None
    assert item.snapshot.fraction == 1.0
    assert "--audio-format mp3" in item.command
    assert states[0] is ItemState.QUEUED
    assert ItemState.DOWNLOADING in states
    assert ItemState.PROCESSING in states
    assert not manager.busy

    assert manager.start(item_id, DownloadOptions(tmp_path))
    _wait_state(qtbot, manager, item_id, ItemState.COMPLETED)
    assert item.files == [tmp_path / "Vídeo de prueba ñ.mp4"]


def test_playlist_gets_playlist_template(
    qtbot: QtBot, fake_launcher: Launcher, tmp_path: Path
) -> None:
    manager = DownloadManager(fake_launcher)
    (item_id,) = manager.add_urls(["https://example.com/playlist"])
    _wait_state(qtbot, manager, item_id, ItemState.READY)
    manager.start(item_id, DownloadOptions(tmp_path))
    _wait_state(qtbot, manager, item_id, ItemState.COMPLETED)
    item = manager.item(item_id)
    assert item is not None
    assert item.options is not None
    assert item.options.playlist
    assert "%(playlist_title)s" in item.command
    assert len(item.files) == 3


def test_failed_download_keeps_the_error(
    qtbot: QtBot, fake_launcher: Launcher, tmp_path: Path
) -> None:
    manager = DownloadManager(fake_launcher)
    (item_id,) = manager.add_urls(["https://example.com/fail"])
    _wait_state(qtbot, manager, item_id, ItemState.READY)
    manager.start(item_id, DownloadOptions(tmp_path))
    _wait_state(qtbot, manager, item_id, ItemState.FAILED)
    item = manager.item(item_id)
    assert item is not None
    assert item.error_code == ERROR_YTDLP
    assert "Video unavailable" in item.error_detail
    # Reintentar limpia el error anterior.
    manager.start(item_id, DownloadOptions(tmp_path))
    assert item.error_code == ""
    _wait_state(qtbot, manager, item_id, ItemState.FAILED)


def test_downloads_run_one_at_a_time_and_cancel(
    qtbot: QtBot, fake_launcher: Launcher, tmp_path: Path
) -> None:
    manager = DownloadManager(fake_launcher)
    slow, second, third = manager.add_urls(
        ["https://example.com/slow-video", "https://example.com/video", "https://example.com/v3"]
    )
    for item_id in (slow, second, third):
        _wait_state(qtbot, manager, item_id, ItemState.READY)
    for item_id in (slow, second, third):
        manager.start(item_id, DownloadOptions(tmp_path / str(item_id)))

    def state(item_id: int) -> ItemState:
        item = manager.item(item_id)
        assert item is not None
        return item.state

    assert state(slow) is ItemState.DOWNLOADING
    assert state(second) is ItemState.QUEUED
    assert state(third) is ItemState.QUEUED

    # Cancelar una que espera no afecta a la que está en curso.
    manager.cancel(third)
    assert state(third) is ItemState.CANCELLED
    assert state(slow) is ItemState.DOWNLOADING

    # Al cancelar la que está en curso, empieza la siguiente.
    qtbot.waitUntil(lambda: manager.items()[0].snapshot is not None, timeout=TIMEOUT)
    manager.cancel(slow)
    _wait_state(qtbot, manager, slow, ItemState.CANCELLED)
    _wait_state(qtbot, manager, second, ItemState.COMPLETED)
    assert state(third) is ItemState.CANCELLED
    assert not manager.busy


def test_remove_cancels_whatever_is_running(
    qtbot: QtBot, fake_launcher: Launcher, tmp_path: Path
) -> None:
    manager = DownloadManager(fake_launcher)
    removed: list[int] = []
    manager.item_removed.connect(removed.append)

    # Quitar mientras se obtienen los metadatos.
    (fetching,) = manager.add_urls(["https://example.com/slowinfo"])
    manager.remove(fetching)
    assert manager.items() == []

    # Quitar uno que espera turno para descargar.
    slow, second = manager.add_urls(["https://example.com/slow", "https://example.com/video"])
    _wait_state(qtbot, manager, slow, ItemState.READY)
    _wait_state(qtbot, manager, second, ItemState.READY)
    manager.start(slow, DownloadOptions(tmp_path))
    manager.start(second, DownloadOptions(tmp_path))
    manager.remove(second)
    manager.remove(999)  # un id desconocido no hace nada
    assert removed == [fetching, second]
    assert [item.item_id for item in manager.items()] == [slow]

    manager.cancel(slow)
    _wait_state(qtbot, manager, slow, ItemState.CANCELLED)
    assert not manager.busy


def test_remove_active_download_frees_the_turn(
    qtbot: QtBot, fake_launcher: Launcher, tmp_path: Path
) -> None:
    manager = DownloadManager(fake_launcher)
    first, second = manager.add_urls(["https://example.com/a", "https://example.com/b"])
    _wait_state(qtbot, manager, first, ItemState.READY)
    _wait_state(qtbot, manager, second, ItemState.READY)

    def slow_launcher(args: list[str]) -> tuple[str, list[str]] | None:
        # La primera descarga no termina nunca; la segunda es normal.
        url = args[-1]
        return fake_launcher([*args[:-1], url + "/slow" if url.endswith("/a") else url])

    manager._launcher = slow_launcher
    manager.start(first, DownloadOptions(tmp_path))
    manager.start(second, DownloadOptions(tmp_path))
    qtbot.waitUntil(lambda: manager.items()[0].snapshot is not None, timeout=TIMEOUT)
    manager.remove(first)
    _wait_state(qtbot, manager, second, ItemState.COMPLETED)
    assert not manager.busy


def test_shutdown_stops_everything(qtbot: QtBot, fake_launcher: Launcher, tmp_path: Path) -> None:
    manager = DownloadManager(fake_launcher)
    ready, _pending = manager.add_urls(["https://example.com/v", "https://example.com/slowinfo"])
    _wait_state(qtbot, manager, ready, ItemState.READY)

    def slow_launcher(args: list[str]) -> tuple[str, list[str]] | None:
        return fake_launcher([*args[:-1], args[-1] + "/slow"])

    manager._launcher = slow_launcher
    manager.start(ready, DownloadOptions(tmp_path))
    qtbot.waitUntil(lambda: manager.items()[0].snapshot is not None, timeout=TIMEOUT)
    manager.shutdown()
    _wait_state(qtbot, manager, ready, ItemState.CANCELLED)
    assert not manager.busy
