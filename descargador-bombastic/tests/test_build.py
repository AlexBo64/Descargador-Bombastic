import struct
import sys
from pathlib import Path

from bombastic.core.binaries import seed_bundled
from bombastic.core.cli import parse_command
from bombastic.core.paths import AppPaths

BUILD = Path(__file__).resolve().parents[1] / "build"
sys.path.insert(0, str(BUILD))

import gen_installer_registry  # noqa: E402
import make_icon  # noqa: E402
import version_info  # noqa: E402


def test_seed_bundled_copies_only_missing(tmp_path: Path) -> None:
    paths = AppPaths(app_dir=tmp_path / "app", data_dir=tmp_path / "datos", portable=False)
    paths.bundled_bin_dir.mkdir(parents=True)
    (paths.bundled_bin_dir / "yt-dlp.exe").write_bytes(b"incluido")
    (paths.bundled_bin_dir / "ffmpeg.exe").write_bytes(b"incluido")
    paths.bin_dir.mkdir(parents=True)
    (paths.bin_dir / "ffmpeg.exe").write_bytes(b"actualizado")
    copied = seed_bundled(paths, platform="win32")
    assert copied == [paths.bin_dir / "yt-dlp.exe"]
    assert (paths.bin_dir / "ffmpeg.exe").read_bytes() == b"actualizado"
    assert seed_bundled(paths, platform="win32") == []


def test_minimized_flag() -> None:
    assert parse_command(["--minimized"]).minimized
    assert parse_command(["--minimized"]).empty
    assert not parse_command([]).minimized


def test_installer_registry_quotes() -> None:
    text = gen_installer_registry.render()
    assert text.count("Flags: uninsdeletekey") == 18  # una por extensión
    assert (
        'ValueData: """{app}\\DescargadorBombastic.exe"" --edit ""%1"""; Tasks: contextmenu'
    ) in text
    assert 'ValueData: "{cm:CtxConvert}"' in text


def test_version_info_and_icon() -> None:
    assert version_info.version_tuple("0.10.0") == (0, 10, 0, 0)
    assert version_info.version_tuple("1.2") == (1, 2, 0, 0)
    assert "StringStruct('ProductVersion', '0.10.0')" in version_info.render("0.10.0")
    ico = make_icon.build_ico([(16, b"a" * 10), (256, b"b" * 20)])
    reserved, kind, count = struct.unpack("<HHH", ico[:6])
    assert (reserved, kind, count) == (0, 1, 2)
    width, height, *_rest, size, offset = struct.unpack("<BBBBHHII", ico[6 + 16 : 6 + 32])
    assert (width, height, size, offset) == (0, 0, 20, 6 + 32 + 10)
    assert (Path(make_icon.ICONS) / "app.ico").read_bytes()[:4] == b"\x00\x00\x01\x00"
