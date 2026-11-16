import json
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from bombastic.core.media_info import parse_media_info
from bombastic.core.paths import resources_dir
from bombastic.core.ytdlp_command import (
    DownloadOptions,
    Preset,
    build_download_args,
    cookie_args,
    options_from_dict,
    options_to_dict,
)
from bombastic.core.ytdlp_options import (
    CATALOG_FILE,
    ExtraArgsError,
    HelpParseError,
    build_advanced_args,
    catalog_from_json,
    catalog_to_json,
    find_conflicts,
    load_catalog,
    load_help_translations,
    parse_help,
    split_extra_args,
    visible_options,
)
from bombastic.core.ytdlp_runner import CatalogRefresher, Launcher

HELP = (Path(__file__).with_name("fixtures") / "ytdlp_help.txt").read_text(encoding="utf-8")


def test_parse_help_fixture() -> None:
    options = parse_help(HELP)
    by_key = {o.key: o for o in options}
    assert len(options) > 200
    assert len({o.group for o in options}) == 17

    output = by_key["--output"]
    assert output.flags == ("--output", "-o")
    assert output.metavar == "[TYPES:]TEMPLATE"
    assert output.group == "Filesystem Options"
    assert output.kind == "text"
    assert by_key["--cookies"].kind == "path"
    assert by_key["--cookies-from-browser"].kind == "text"
    assert by_key["--embed-subs"].kind == "flag"
    # La ayuda de varias líneas se une en un solo texto.
    assert by_key["--ignore-errors"].help == (
        "Ignore download and postprocessing errors. The download will be considered "
        "successful even if the postprocessing fails"
    )


def test_visible_options_hide_what_the_app_controls() -> None:
    keys = {o.key for o in visible_options(parse_help(HELP))}
    assert {"--help", "--print", "--newline", "--progress-template", "--quiet"}.isdisjoint(keys)
    assert "-t" not in keys  # alias de presets
    assert {"--format", "--sub-langs", "--proxy"} <= keys


@pytest.mark.parametrize("text", ["", "Usage: nada\n", "garbage\n" * 300])
def test_parse_help_rejects_unknown_output(text: str) -> None:
    with pytest.raises(HelpParseError):
        parse_help(text)


def test_catalog_json_roundtrip_and_loading(tmp_path: Path) -> None:
    options = parse_help(HELP)
    version, loaded = catalog_from_json(catalog_to_json(options, "2026.01.01"))
    assert (version, loaded) == ("2026.01.01", options)

    data_dir, bundled = tmp_path / "datos", tmp_path / "incluido"
    bundled.mkdir()
    (bundled / CATALOG_FILE).write_text(catalog_to_json(options[:3], "viejo"), encoding="utf-8")
    assert load_catalog(data_dir, bundled)[0] == "viejo"
    data_dir.mkdir()
    (data_dir / CATALOG_FILE).write_text("{roto", encoding="utf-8")
    assert load_catalog(data_dir, bundled)[0] == "viejo"
    (data_dir / CATALOG_FILE).write_text(catalog_to_json(options, "nuevo"), encoding="utf-8")
    assert load_catalog(data_dir, bundled)[0] == "nuevo"
    assert load_catalog(tmp_path / "x", tmp_path / "y") == ("", [])


def test_bundled_catalog_and_spanish_help_match() -> None:
    version, options = load_catalog(Path("no-existe"), resources_dir())
    assert version
    keys = {o.key for o in options}
    groups, help_es = load_help_translations(resources_dir())
    assert len(help_es) >= 80
    assert set(help_es) <= keys, set(help_es) - keys
    assert {o.group for o in options} <= set(groups)


def test_split_extra_args() -> None:
    assert split_extra_args('--sleep-interval 5 -o "%(title)s ñ.%(ext)s"') == [
        "--sleep-interval",
        "5",
        "-o",
        "%(title)s ñ.%(ext)s",
    ]
    assert split_extra_args(r"--cookies C:\Users\Ana\cookies.txt") == [
        "--cookies",
        r"C:\Users\Ana\cookies.txt",
    ]
    assert split_extra_args("  ") == []
    with pytest.raises(ExtraArgsError):
        split_extra_args('--output "sin cerrar')


def test_build_advanced_args_and_conflicts() -> None:
    options = visible_options(parse_help(HELP))
    values = {"--embed-chapters": True, "--proxy": " socks5://x:1 ", "--format": "", "-z": True}
    assert build_advanced_args(options, values) == [
        "--proxy",
        "socks5://x:1",
        "--embed-chapters",
    ]
    assert find_conflicts([], audio_preset=False, ffmpeg_found=True) == []
    assert find_conflicts(["-x", "--merge-output-format", "mp4", "-f", "b"], False, False) == [
        "extract_without_ffmpeg",
        "merge_with_audio",
        "format_overridden",
    ]
    assert find_conflicts(["-P", "x"], True, True) == ["output_overridden"]


def test_extra_args_go_last_and_manual_format_replaces_preset(tmp_path: Path) -> None:
    options = DownloadOptions(
        tmp_path, preset=Preset.MP3, format_spec="137+140", extra_args=("-o", "x.%(ext)s")
    )
    args = build_download_args("https://e.com/v", options)
    assert args[-4:] == ["-o", "x.%(ext)s", "--", "https://e.com/v"]
    assert args[args.index("-f") + 1] == "137+140"
    assert "-x" not in args

    restored = options_from_dict(json.loads(json.dumps(options_to_dict(options))))
    assert restored == options


def test_cookie_args() -> None:
    assert cookie_args("off", "chrome", "", "x") == []
    assert cookie_args("browser", "edge", "", "") == ["--cookies-from-browser", "edge"]
    assert cookie_args("browser", "firefox", "Perfil 1", "") == [
        "--cookies-from-browser",
        "firefox:Perfil 1",
    ]
    assert cookie_args("browser", "netscape", "", "") == []
    assert cookie_args("file", "chrome", "", r" C:\c ñ.txt ") == ["--cookies", r"C:\c ñ.txt"]
    assert cookie_args("file", "chrome", "", "") == []


def test_formats_are_parsed_without_storyboards() -> None:
    output = json.dumps(
        {
            "id": "a",
            "title": "t",
            "formats": [
                {"format_id": "sb0", "ext": "mhtml", "format_note": "storyboard"},
                {"format_id": "140", "ext": "m4a", "vcodec": "none", "acodec": "mp4a"},
                {
                    "format_id": "137",
                    "ext": "mp4",
                    "vcodec": "avc1",
                    "acodec": "none",
                    "height": 1080,
                    "width": 1920,
                    "filesize_approx": 10.5,
                },
                {"ext": "mp4"},
            ],
        }
    )
    formats = parse_media_info(output, "u").formats
    assert [f.format_id for f in formats] == ["140", "137"]
    assert formats[0].has_audio and not formats[0].has_video
    assert formats[1].has_video and formats[1].size == 10.5


def test_catalog_refresher_saves_a_new_catalog(
    qtbot: QtBot, fake_launcher: Launcher, tmp_path: Path
) -> None:
    refresher = CatalogRefresher(fake_launcher, tmp_path)
    with qtbot.waitSignal(refresher.finished, timeout=20_000) as blocker:
        refresher.start()
    assert blocker.args == [True]
    version, options = load_catalog(tmp_path, Path("no-existe"))
    assert version == "2099.01.01"
    assert len(options) > 200

    missing = CatalogRefresher(lambda _args: None, tmp_path)
    with qtbot.waitSignal(missing.finished) as blocker:
        missing.start()
    assert blocker.args == [False]
