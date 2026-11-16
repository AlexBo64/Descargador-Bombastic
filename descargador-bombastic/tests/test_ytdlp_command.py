from pathlib import Path

import pytest

from bombastic.core.ytdlp_command import (
    AUDIO_PRESETS,
    VIDEO_PRESETS,
    DownloadOptions,
    Preset,
    build_download_args,
    build_info_args,
    is_audio,
)
from bombastic.core.ytdlp_progress import DOWNLOAD_TEMPLATE, FILE_TEMPLATE, POSTPROCESS_TEMPLATE

URL = "https://example.com/watch?v=abc&list=x y"
FOLDER = Path("C:/Mis vídeos ñ/con 'comillas' & símbolos")

HEAD = [
    "--newline",
    "--no-playlist",
    "--no-colors",
    "--encoding",
    "utf-8",
    "--progress-template",
    DOWNLOAD_TEMPLATE,
    "--progress-template",
    POSTPROCESS_TEMPLATE,
    "--print",
    FILE_TEMPLATE,
    "--no-quiet",
    "--no-simulate",
]
TAIL = ["-P", str(FOLDER), "-o", "%(title)s [%(id)s].%(ext)s", "--", URL]
SORT = "vcodec:h264,lang,quality,res,fps,hdr:12,acodec:aac"


def video_args(sort: str) -> list[str]:
    return ["-f", "bv*+ba/b", "-S", sort, "--merge-output-format", "mp4", "--remux-video", "mp4"]


def test_presets_are_classified() -> None:
    assert set(VIDEO_PRESETS) | set(AUDIO_PRESETS) == set(Preset)
    assert not set(VIDEO_PRESETS) & set(AUDIO_PRESETS)
    assert is_audio(Preset.FLAC)
    assert not is_audio(Preset.P720)


def test_info_args() -> None:
    assert build_info_args(URL) == [
        "-J",
        "--flat-playlist",
        "--no-warnings",
        "--no-playlist",
        "--no-colors",
        "--encoding",
        "utf-8",
        "--",
        URL,
    ]


@pytest.mark.parametrize(
    ("preset", "sort"),
    [
        (Preset.BEST, SORT),
        (Preset.P1080, f"res:1080,{SORT}"),
        (Preset.P720, f"res:720,{SORT}"),
        (Preset.P480, f"res:480,{SORT}"),
    ],
)
def test_video_presets(preset: Preset, sort: str) -> None:
    options = DownloadOptions(output_dir=FOLDER, preset=preset)
    assert build_download_args(URL, options) == [*HEAD, *video_args(sort), *TAIL]


@pytest.mark.parametrize(
    ("quality", "expected"),
    [("128", "128K"), ("192", "192K"), ("320", "320K"), ("v0", "0"), ("inventada", "192K")],
)
def test_mp3_preset(quality: str, expected: str) -> None:
    options = DownloadOptions(output_dir=FOLDER, preset=Preset.MP3, mp3_quality=quality)
    assert build_download_args(URL, options) == [
        *HEAD,
        "-f",
        "ba/b",
        "-x",
        "--audio-format",
        "mp3",
        "--audio-quality",
        expected,
        *TAIL,
    ]


@pytest.mark.parametrize("preset", [Preset.M4A, Preset.OPUS, Preset.FLAC, Preset.WAV])
def test_other_audio_presets(preset: Preset) -> None:
    options = DownloadOptions(output_dir=FOLDER, preset=preset, mp3_quality="320")
    assert build_download_args(URL, options) == [
        *HEAD,
        "-f",
        "ba/b",
        "-x",
        "--audio-format",
        preset.value,
        *TAIL,
    ]


def test_embedded_subtitles_thumbnail_and_metadata_for_video() -> None:
    options = DownloadOptions(output_dir=FOLDER, embed_subs=True, embed_extras=True)
    assert build_download_args(URL, options) == [
        *HEAD,
        *video_args(SORT),
        "--embed-subs",
        "--sub-langs",
        "all,-live_chat",
        "--embed-metadata",
        "--embed-thumbnail",
        *TAIL,
    ]


def test_audio_ignores_subtitles_and_wav_skips_thumbnail() -> None:
    mp3 = DownloadOptions(output_dir=FOLDER, preset=Preset.MP3, embed_subs=True, embed_extras=True)
    args = build_download_args(URL, mp3)
    assert "--embed-subs" not in args
    assert args[-8:-6] == ["--embed-metadata", "--embed-thumbnail"]

    wav = DownloadOptions(output_dir=FOLDER, preset=Preset.WAV, embed_extras=True)
    args = build_download_args(URL, wav)
    assert "--embed-metadata" in args
    assert "--embed-thumbnail" not in args


def test_ffmpeg_location_and_playlist_template() -> None:
    ffmpeg_dir = Path("C:/Program Files/ffmpeg ñ/bin")
    options = DownloadOptions(output_dir=FOLDER, ffmpeg_dir=ffmpeg_dir, playlist=True)
    assert build_download_args(URL, options) == [
        *HEAD,
        "--ffmpeg-location",
        str(ffmpeg_dir),
        *video_args(SORT),
        "-P",
        str(FOLDER),
        "-o",
        "%(playlist_title)s/%(playlist_index)03d - %(title)s [%(id)s].%(ext)s",
        "--",
        URL,
    ]


def test_url_that_looks_like_an_option_stays_an_argument() -> None:
    """Un "enlace" que empiece por guion nunca se interpreta como opción de yt-dlp."""
    args = build_download_args("--exec=calc", DownloadOptions(output_dir=FOLDER))
    assert args[-2:] == ["--", "--exec=calc"]
    assert build_info_args("--exec=calc")[-2:] == ["--", "--exec=calc"]
