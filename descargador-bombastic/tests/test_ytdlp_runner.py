from pathlib import Path

from pytestqt.qtbot import QtBot

from bombastic.core.binaries import Tool, exe_name
from bombastic.core.paths import AppPaths
from bombastic.core.ytdlp_command import (
    DownloadOptions,
    Preset,
    build_download_args,
    build_info_args,
)
from bombastic.core.ytdlp_progress import ProgressSnapshot
from bombastic.core.ytdlp_runner import (
    ERROR_BAD_INFO,
    ERROR_EXIT_CODE,
    ERROR_START_FAILED,
    ERROR_TIMEOUT,
    ERROR_YTDLP,
    DownloadJob,
    InfoFetcher,
    Launcher,
    _LineBuffer,
    default_launcher,
    describe,
)

TIMEOUT = 20_000


def test_line_buffer_joins_chunks_and_keeps_multibyte_characters() -> None:
    buffer = _LineBuffer()
    data = "uno ñ\r\ndos\nsin terminar".encode()
    # Se parte justo en medio de la "ñ" (dos bytes en UTF-8).
    assert buffer.feed(data[:5]) == []
    assert buffer.feed(data[5:]) == ["uno ñ", "dos"]
    assert buffer.flush() == ["sin terminar"]
    assert buffer.flush() == []


def test_default_launcher_uses_the_located_ytdlp(paths: AppPaths) -> None:
    launcher = default_launcher(paths)
    exe = paths.bin_dir / exe_name(Tool.YTDLP)
    exe.touch()
    assert launcher(["-J", "x"]) == (str(exe), ["-J", "x"])


def test_describe_quotes_arguments_with_spaces() -> None:
    assert describe(("yt-dlp", ["-P", "C:/Mis vídeos", "url"])) == 'yt-dlp -P "C:/Mis vídeos" url'


def test_info_fetcher_success(qtbot: QtBot, fake_launcher: Launcher) -> None:
    url = "https://example.com/video"
    launch = fake_launcher(build_info_args(url))
    assert launch is not None
    fetcher = InfoFetcher(launch, url)
    with qtbot.waitSignal(fetcher.succeeded, timeout=TIMEOUT) as blocker:
        fetcher.start()
    info = blocker.args[0]
    assert info.title == "Vídeo de prueba ñ"
    assert info.channel == "Canal ñ"
    assert info.duration == 75
    assert not info.is_playlist


def test_info_fetcher_reports_ytdlp_error(qtbot: QtBot, fake_launcher: Launcher) -> None:
    url = "https://example.com/badinfo"
    launch = fake_launcher(build_info_args(url))
    assert launch is not None
    fetcher = InfoFetcher(launch, url)
    with qtbot.waitSignal(fetcher.failed, timeout=TIMEOUT) as blocker:
        fetcher.start()
    assert blocker.args == [ERROR_YTDLP, "[fake] abc: This video is private"]


def test_info_fetcher_bad_output_and_missing_program(qtbot: QtBot, fake_launcher: Launcher) -> None:
    url = "https://example.com/garbage"
    launch = fake_launcher(build_info_args(url))
    assert launch is not None
    fetcher = InfoFetcher(launch, url)
    with qtbot.waitSignal(fetcher.failed, timeout=TIMEOUT) as blocker:
        fetcher.start()
    assert blocker.args[0] == ERROR_BAD_INFO

    fetcher = InfoFetcher(("no-existe-este-programa", []), url)
    with qtbot.waitSignal(fetcher.failed, timeout=TIMEOUT) as blocker:
        fetcher.start()
    assert blocker.args == [ERROR_START_FAILED, "no-existe-este-programa"]


def test_info_fetcher_timeout_kills_the_process(qtbot: QtBot, fake_launcher: Launcher) -> None:
    url = "https://example.com/slowinfo"
    launch = fake_launcher(build_info_args(url))
    assert launch is not None
    fetcher = InfoFetcher(launch, url, timeout_ms=1500)
    with qtbot.waitSignal(fetcher.failed, timeout=TIMEOUT) as blocker:
        fetcher.start()
    assert blocker.args[0] == ERROR_TIMEOUT
    qtbot.waitUntil(
        lambda: fetcher._process.state() == fetcher._process.ProcessState.NotRunning,
        timeout=TIMEOUT,
    )


def _job(
    fake_launcher: Launcher, url: str, folder: Path, preset: Preset = Preset.BEST
) -> DownloadJob:
    launch = fake_launcher(build_download_args(url, DownloadOptions(folder, preset=preset)))
    assert launch is not None
    return DownloadJob(launch)


def test_download_job_completes_with_progress(
    qtbot: QtBot, fake_launcher: Launcher, tmp_path: Path
) -> None:
    folder = tmp_path / "descargas ñ"
    job = _job(fake_launcher, "https://example.com/video", folder)
    snapshots: list[ProgressSnapshot] = []
    job.progress.connect(snapshots.append)
    with qtbot.waitSignal(job.finished, timeout=TIMEOUT) as blocker:
        job.start()
    result = blocker.args[0]
    assert result.status == "completed"
    assert result.files == (folder / "Vídeo de prueba ñ.mp4",)
    assert result.files[0].is_file()
    downloading = [s.fraction for s in snapshots if s.phase == "downloading"]
    assert downloading == [0.0, 0.25, 0.5, 0.5, 0.75, 1.0]
    assert snapshots[-1].phase == "processing"
    assert snapshots[-1].postprocessor == "Merger"
    assert "--newline" in job.command
    assert any("Extracting URL" in line for line in job.log_lines)
    assert not job.running


def test_download_job_audio_preset(qtbot: QtBot, fake_launcher: Launcher, tmp_path: Path) -> None:
    job = _job(fake_launcher, "https://example.com/video", tmp_path, Preset.MP3)
    with qtbot.waitSignal(job.finished, timeout=TIMEOUT) as blocker:
        job.start()
    assert blocker.args[0].files == (tmp_path / "Vídeo de prueba ñ.mp3",)


def test_download_job_playlist(qtbot: QtBot, fake_launcher: Launcher, tmp_path: Path) -> None:
    job = _job(fake_launcher, "https://example.com/playlist", tmp_path)
    snapshots: list[ProgressSnapshot] = []
    job.progress.connect(snapshots.append)
    with qtbot.waitSignal(job.finished, timeout=TIMEOUT) as blocker:
        job.start()
    result = blocker.args[0]
    assert result.status == "completed"
    assert len(result.files) == 3
    fractions = [s.fraction for s in snapshots if s.fraction is not None]
    assert fractions == sorted(fractions)
    assert fractions[-1] == 1.0
    assert (snapshots[-1].item_index, snapshots[-1].item_count) == (3, 3)


def test_download_job_failures(qtbot: QtBot, fake_launcher: Launcher, tmp_path: Path) -> None:
    job = _job(fake_launcher, "https://example.com/fail", tmp_path)
    with qtbot.waitSignal(job.finished, timeout=TIMEOUT) as blocker:
        job.start()
    result = blocker.args[0]
    assert (result.status, result.error_code) == ("failed", ERROR_YTDLP)
    assert result.error_detail == "[fake] abc: Video unavailable. This video is private"

    job = _job(fake_launcher, "https://example.com/crash", tmp_path)
    with qtbot.waitSignal(job.finished, timeout=TIMEOUT) as blocker:
        job.start()
    result = blocker.args[0]
    assert (result.status, result.error_code, result.error_detail) == (
        "failed",
        ERROR_EXIT_CODE,
        "3",
    )

    job = DownloadJob(("no-existe-este-programa", []))
    with qtbot.waitSignal(job.finished, timeout=TIMEOUT) as blocker:
        job.start()
    assert blocker.args[0].error_code == ERROR_START_FAILED


def test_download_job_cancel_stops_the_process(
    qtbot: QtBot, fake_launcher: Launcher, tmp_path: Path
) -> None:
    job = _job(fake_launcher, "https://example.com/slow", tmp_path)
    results: list[object] = []
    job.finished.connect(results.append)
    with qtbot.waitSignal(job.progress, timeout=TIMEOUT):
        job.start()
    assert job.running
    with qtbot.waitSignal(job.finished, timeout=TIMEOUT) as blocker:
        job.cancel()
        job.cancel()  # repetir no hace nada
    assert blocker.args[0].status == "cancelled"
    qtbot.waitUntil(lambda: not job.running, timeout=TIMEOUT)
    assert len(results) == 1


def test_cancel_before_start_finishes_as_cancelled(
    qtbot: QtBot, fake_launcher: Launcher, tmp_path: Path
) -> None:
    job = _job(fake_launcher, "https://example.com/video", tmp_path)
    with qtbot.waitSignal(job.finished, timeout=TIMEOUT) as blocker:
        job.cancel()
    assert blocker.args[0].status == "cancelled"
