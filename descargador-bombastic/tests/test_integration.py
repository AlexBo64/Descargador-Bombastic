"""Prueba de integración con yt-dlp y ffmpeg reales y red.

Desactivada por defecto (marca ``integration``). Para ejecutarla:
``python -m pytest -m integration``. Descarga 5 segundos de "Big Buck Bunny" (Blender
Foundation, CC BY 3.0) y los convierte a MP3.
"""

from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from bombastic.core.binaries import Tool, locate
from bombastic.core.download_manager import DownloadManager, ItemState
from bombastic.core.edit_manager import EditManager, EditState
from bombastic.core.ffmpeg_tools import build_extract_audio
from bombastic.core.media_probe import parse_probe, probe_args
from bombastic.core.media_prober import tool_launcher
from bombastic.core.paths import AppPaths
from bombastic.core.ytdlp_command import DownloadOptions, Preset
from bombastic.core.ytdlp_runner import default_launcher

pytestmark = pytest.mark.integration

VIDEO = "https://www.youtube.com/watch?v=aqz-KE-bpKQ"


def test_download_and_convert(qtbot: QtBot, paths: AppPaths, tmp_path: Path) -> None:
    if not (locate(Tool.YTDLP, paths).found and locate(Tool.FFMPEG, paths).found):
        pytest.skip("hacen falta yt-dlp y ffmpeg")
    downloads = DownloadManager(default_launcher(paths))
    (item_id,) = downloads.add_urls([VIDEO])
    qtbot.waitUntil(
        lambda: downloads.item(item_id).state in (ItemState.READY, ItemState.INFO_ERROR),  # type: ignore[union-attr]
        timeout=120_000,
    )
    options = DownloadOptions(
        tmp_path, preset=Preset.P480, extra_args=("--download-sections", "*0-5")
    )
    downloads.start(item_id, options)
    qtbot.waitUntil(
        lambda: downloads.item(item_id).state in (ItemState.COMPLETED, ItemState.FAILED),  # type: ignore[union-attr]
        timeout=300_000,
    )
    item = downloads.item(item_id)
    assert item is not None and item.state is ItemState.COMPLETED, item.error_detail
    video = item.files[0]

    import subprocess

    probe_bin = locate(Tool.FFPROBE, paths).path
    assert probe_bin is not None
    probe = parse_probe(
        subprocess.run(
            [str(probe_bin), *probe_args(str(video))], capture_output=True, text=True
        ).stdout
    )
    edits = EditManager(tool_launcher(paths, Tool.FFMPEG))
    task_id = edits.add("mp3", build_extract_audio(video, tmp_path / "audio.mp3", probe, "mp3"))
    qtbot.waitUntil(
        lambda: edits.task(task_id).state in (EditState.COMPLETED, EditState.FAILED),  # type: ignore[union-attr]
        timeout=120_000,
    )
    assert (tmp_path / "audio.mp3").stat().st_size > 1000
