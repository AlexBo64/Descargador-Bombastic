import sys
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from bombastic.core.binaries import (
    BinaryLocation,
    Source,
    Tool,
    exe_name,
    locate,
    locate_all,
    parse_version,
    version_args,
)
from bombastic.core.binary_probe import BinaryProbe
from bombastic.core.paths import AppPaths


def _touch(folder: Path, tool: Tool) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    file = folder / exe_name(tool)
    file.touch()
    return file


def test_exe_name() -> None:
    assert exe_name(Tool.YTDLP, "win32") == "yt-dlp.exe"
    assert exe_name(Tool.FFPROBE, "linux") == "ffprobe"


def test_locate_prefers_data_then_bundled_then_path(paths: AppPaths) -> None:
    def which(_name: str) -> str:
        return "/usr/bin/ffmpeg"

    assert locate(Tool.FFMPEG, paths, which=which).source is Source.PATH
    bundled = _touch(paths.bundled_bin_dir, Tool.FFMPEG)
    assert locate(Tool.FFMPEG, paths, which=which) == BinaryLocation(
        Tool.FFMPEG, bundled, Source.BUNDLED
    )
    data = _touch(paths.bin_dir, Tool.FFMPEG)
    assert locate(Tool.FFMPEG, paths, which=which) == BinaryLocation(Tool.FFMPEG, data, Source.DATA)


def test_locate_missing(paths: AppPaths) -> None:
    location = locate(Tool.YTDLP, paths, which=lambda _name: None)
    assert location.source is Source.MISSING
    assert not location.found
    assert locate(Tool.YTDLP, paths, search_system_path=False).source is Source.MISSING


def test_locate_all_covers_every_tool(paths: AppPaths) -> None:
    _touch(paths.bin_dir, Tool.YTDLP)
    found = locate_all(paths, search_system_path=False)
    assert set(found) == set(Tool)
    assert found[Tool.YTDLP].found
    assert not found[Tool.FFPROBE].found


def test_version_args() -> None:
    assert version_args(Tool.YTDLP) == ["--version"]
    assert version_args(Tool.FFMPEG) == ["-version"]


@pytest.mark.parametrize(
    ("tool", "output", "expected"),
    [
        (Tool.YTDLP, "2025.10.22\n", "2025.10.22"),
        (Tool.YTDLP, "WARNING: algo\r\n2025.11.03.233024\r\n", "2025.11.03.233024"),
        (Tool.YTDLP, "Traceback (most recent call last):", None),
        (
            Tool.FFMPEG,
            "ffmpeg version 7.1-essentials_build-www.gyan.dev Copyright (c) 2000-2024\nbuilt with",
            "7.1-essentials_build-www.gyan.dev",
        ),
        (Tool.FFPROBE, "ffprobe version n7.1-153-gabc123 Copyright", "n7.1-153-gabc123"),
        (Tool.FFMPEG, "", None),
    ],
)
def test_parse_version(tool: Tool, output: str, expected: str | None) -> None:
    assert parse_version(tool, output) == expected


def _fake_command(tool: Tool, _path: Path) -> tuple[str, list[str]]:
    """Imita la salida de cada ejecutable usando el propio intérprete de Python."""
    scripts = {
        Tool.YTDLP: "print('2025.10.22')",
        Tool.FFMPEG: "print('ffmpeg version 7.1 Copyright (c) the FFmpeg developers')",
        Tool.FFPROBE: "import sys; sys.exit(3)",
    }
    return sys.executable, ["-c", scripts[tool]]


def test_probe_reports_versions_and_failures(qtbot: QtBot, tmp_path: Path) -> None:
    fake = tmp_path / "fake"
    locations = {
        Tool.YTDLP: BinaryLocation(Tool.YTDLP, fake, Source.DATA),
        Tool.FFMPEG: BinaryLocation(Tool.FFMPEG, fake, Source.DATA),
        Tool.FFPROBE: BinaryLocation(Tool.FFPROBE, fake, Source.DATA),
    }
    probe = BinaryProbe(locations, command_factory=_fake_command)
    with qtbot.waitSignal(probe.finished, timeout=15_000) as blocker:
        probe.start()
    statuses = blocker.args[0]
    assert statuses[Tool.YTDLP].version == "2025.10.22"
    assert statuses[Tool.YTDLP].usable
    assert statuses[Tool.FFMPEG].version == "7.1"
    assert statuses[Tool.FFPROBE].version is None
    assert not statuses[Tool.FFPROBE].usable
    assert not probe.running


def test_probe_with_missing_and_unstartable_binaries(qtbot: QtBot, tmp_path: Path) -> None:
    locations = {
        Tool.YTDLP: BinaryLocation(Tool.YTDLP, None, Source.MISSING),
        Tool.FFMPEG: BinaryLocation(Tool.FFMPEG, tmp_path / "no-existe.exe", Source.DATA),
    }
    probe = BinaryProbe(locations)
    with qtbot.waitSignal(probe.finished, timeout=15_000) as blocker:
        probe.start()
    statuses = blocker.args[0]
    assert statuses[Tool.YTDLP].version is None
    assert statuses[Tool.YTDLP].error is None
    assert statuses[Tool.FFMPEG].error == "FailedToStart"


def test_probe_timeout_kills_process(qtbot: QtBot, tmp_path: Path) -> None:
    locations = {Tool.YTDLP: BinaryLocation(Tool.YTDLP, tmp_path / "fake", Source.DATA)}
    probe = BinaryProbe(
        locations,
        timeout_ms=300,
        command_factory=lambda _t, _p: (sys.executable, ["-c", "import time; time.sleep(30)"]),
    )
    with qtbot.waitSignal(probe.finished, timeout=15_000) as blocker:
        probe.start()
    assert blocker.args[0][Tool.YTDLP].error == "timeout"
