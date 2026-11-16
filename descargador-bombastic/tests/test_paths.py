from pathlib import Path

from bombastic.core.paths import PORTABLE_FLAG, default_download_dir, resolve_paths


def test_windows_uses_localappdata(tmp_path: Path) -> None:
    local = tmp_path / "AppData" / "Local"
    paths = resolve_paths(
        app_dir=tmp_path / "app", env={"LOCALAPPDATA": str(local)}, platform="win32", home=tmp_path
    )
    assert paths.data_dir == local / "DescargadorBombastic"
    assert paths.portable is False
    assert paths.bin_dir == paths.data_dir / "bin"
    assert paths.settings_path.name == "settings.json"


def test_windows_without_localappdata_falls_back_to_home(tmp_path: Path) -> None:
    paths = resolve_paths(app_dir=tmp_path / "app", env={}, platform="win32", home=tmp_path)
    assert paths.data_dir == tmp_path / "AppData" / "Local" / "DescargadorBombastic"


def test_portable_flag_keeps_data_next_to_executable(tmp_path: Path) -> None:
    app_dir = tmp_path / "Bombastic portátil"
    app_dir.mkdir()
    (app_dir / PORTABLE_FLAG).touch()
    paths = resolve_paths(
        app_dir=app_dir, env={"LOCALAPPDATA": "C:/x"}, platform="win32", home=tmp_path
    )
    assert paths.portable is True
    assert paths.data_dir == app_dir / "data"


def test_non_windows_uses_xdg_or_local_share(tmp_path: Path) -> None:
    xdg = resolve_paths(
        app_dir=tmp_path, env={"XDG_DATA_HOME": str(tmp_path / "xdg")}, platform="linux"
    )
    assert xdg.data_dir == tmp_path / "xdg" / "DescargadorBombastic"
    plain = resolve_paths(app_dir=tmp_path, env={}, platform="linux", home=tmp_path)
    assert plain.data_dir == tmp_path / ".local" / "share" / "DescargadorBombastic"


def test_ensure_creates_folders(tmp_path: Path) -> None:
    paths = resolve_paths(app_dir=tmp_path, env={}, platform="linux", home=tmp_path)
    paths.ensure()
    assert paths.bin_dir.is_dir()
    assert paths.logs_dir.is_dir()
    assert paths.thumbnails_dir.is_dir()


def test_default_download_dir(tmp_path: Path) -> None:
    assert default_download_dir(tmp_path) == tmp_path / "Downloads"
