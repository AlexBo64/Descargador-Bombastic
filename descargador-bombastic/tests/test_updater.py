import hashlib
import json
import sys
import zipfile
from datetime import datetime
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QUrl
from PySide6.QtNetwork import QNetworkAccessManager
from pytestqt.qtbot import QtBot

from bombastic.context import AppContext
from bombastic.core import updater as up
from bombastic.core.ytdlp_runner import Launch, Launcher
from bombastic.ui.updates import DependencyWizard, UpdateBar, Updates

TIMEOUT = 20_000


def test_versions_and_schedule() -> None:
    assert up.version_key("v2026.08.19") == (2026, 8, 19)
    assert up.is_newer("2026.10.26", "2026.08.19")
    assert not up.is_newer("2026.08.19", "2026.08.19")
    assert up.is_newer("v0.10.0", "0.9.0")
    assert not up.is_newer("nightly", "1.0")
    now = datetime(2026, 1, 2, 12, 0)
    assert up.should_check("", 24, now)
    assert up.should_check("garbage", 24, now)
    assert not up.should_check("2026-01-02T00:00:00", 24, now)
    assert up.should_check("2026-01-01T11:00:00", 24, now)
    assert not up.should_check("", 0, now)


def test_parse_release_and_checksums() -> None:
    text = json.dumps(
        {
            "tag_name": "2026.10.26",
            "html_url": "https://github.com/x",
            "assets": [{"name": "yt-dlp.exe", "browser_download_url": "https://d/y"}, {"x": 1}],
        }
    )
    release = up.parse_release(text)
    assert (release.tag, release.url, release.assets) == (
        "2026.10.26",
        "https://github.com/x",
        {"yt-dlp.exe": "https://d/y"},
    )
    for bad in ("[]", "{}", '{"tag_name": 3}'):
        with pytest.raises(ValueError):
            up.parse_release(bad)
    sums = up.parse_checksums(f"{'a' * 64}  yt-dlp.exe\n{'B' * 64} *otro.zip\nbasura\n")
    assert sums == {"yt-dlp.exe": "a" * 64, "otro.zip": "b" * 64}


def _zip(path: Path, members: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w") as bundle:
        for name, data in members.items():
            bundle.writestr(name, data)


def test_extract_swap_and_rollback(tmp_path: Path) -> None:
    archive = tmp_path / "f.zip"
    _zip(archive, {"ffmpeg-x/bin/ffmpeg.exe": b"new ff", "ffmpeg-x/bin/ffprobe.exe": b"new fp",
                   "ffmpeg-x/doc/ffmpeg.exe": b"no"})  # fmt: skip
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "ffmpeg.exe").write_bytes(b"old ff")
    new = up.extract_ffmpeg(archive, bin_dir)
    assert sorted(p.name for p in new) == ["ffmpeg.exe.new", "ffprobe.exe.new"]
    undo = up.swap_in(new)
    assert (bin_dir / "ffmpeg.exe").read_bytes() == b"new ff"
    assert (bin_dir / "ffmpeg.exe.old").read_bytes() == b"old ff"
    up.roll_back(undo)
    assert (bin_dir / "ffmpeg.exe").read_bytes() == b"old ff"
    assert not (bin_dir / "ffprobe.exe").exists()
    broken = tmp_path / "b.zip"
    _zip(broken, {"bin/ffmpeg.exe": b"x"})
    with pytest.raises(ValueError):
        up.extract_ffmpeg(broken, bin_dir)
    assert not (bin_dir / "ffmpeg.exe.new").exists()


class FakeGitHub:
    """Imita la API de GitHub con archivos locales (``file://``)."""

    def __init__(self, root: Path) -> None:
        self.root = root

    @property
    def api(self) -> str:
        return QUrl.fromLocalFile(str(self.root / "api")).toString()

    def release(self, repo: str, tag: str, files: dict[str, bytes], sums_name: str = "") -> None:
        folder = self.root / "files" / repo.replace("/", "_")
        folder.mkdir(parents=True, exist_ok=True)
        assets = []
        for name, data in files.items():
            (folder / name).write_bytes(data)
            assets.append(
                {
                    "name": name,
                    "browser_download_url": QUrl.fromLocalFile(str(folder / name)).toString(),
                }
            )
        if sums_name:
            sums = "".join(f"{hashlib.sha256(d).hexdigest()}  {n}\n" for n, d in files.items())
            (folder / sums_name).write_text(sums, encoding="utf-8")
            assets.append(
                {
                    "name": sums_name,
                    "browser_download_url": QUrl.fromLocalFile(str(folder / sums_name)).toString(),
                }
            )
        target = self.root / "api" / repo / "releases"
        target.mkdir(parents=True, exist_ok=True)
        (target / "latest").write_text(
            json.dumps({"tag_name": tag, "html_url": "https://example.com/r", "assets": assets}),
            encoding="utf-8",
        )


@pytest.fixture
def github(tmp_path: Path) -> FakeGitHub:
    return FakeGitHub(tmp_path / "github")


def _run(qtbot: QtBot, step: up._Step) -> tuple[bool, str]:
    with qtbot.waitSignal(step.finished, timeout=TIMEOUT) as blocker:
        step.start()  # type: ignore[attr-defined]
    # Borrar ya las respuestas de red pendientes: si Python destruye antes el paso (con su
    # FileFetch) que esas respuestas, Qt aborta al acabar el test.
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    return blocker.args[0], blocker.args[1]


def test_ytdlp_version_check(qtbot: QtBot, github: FakeGitHub, fake_launcher: Launcher) -> None:
    network = QNetworkAccessManager()
    github.release("yt-dlp/yt-dlp", "2026.01.01", {})
    check = up.YtdlpVersionCheck(network, fake_launcher, "stable", github.api)
    assert _run(qtbot, check) == (True, "updates.ytdlp.current")
    assert (check.local, check.latest) == ("2099.01.01", "2026.01.01")
    github.release("yt-dlp/yt-dlp-nightly-builds", "2100.01.01", {})
    nightly = up.YtdlpVersionCheck(network, fake_launcher, "nightly", github.api)
    assert _run(qtbot, nightly) == (True, "updates.ytdlp.newer")
    offline = up.YtdlpVersionCheck(network, fake_launcher, "stable", github.api + "/nada")
    assert _run(qtbot, offline) == (False, "updates.error.network")


def test_ytdlp_update_falls_back_to_verified_download(
    qtbot: QtBot, github: FakeGitHub, fake_launcher: Launcher, tmp_path: Path
) -> None:
    network = QNetworkAccessManager()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "yt-dlp.exe").write_bytes(b"vieja")
    github.release("yt-dlp/yt-dlp", "2100.01.01", {"yt-dlp.exe": b"nueva"}, "SHA2-256SUMS")
    step = up.YtdlpUpdate(network, fake_launcher, bin_dir, "stable", github.api)
    statuses: list[str] = []
    step.status.connect(statuses.append)
    assert _run(qtbot, step) == (True, "updates.done.ytdlp")
    assert statuses == ["updates.status.self_update", "updates.status.downloading"]
    assert (bin_dir / "yt-dlp.exe").read_bytes() == b"nueva"
    assert not (bin_dir / "yt-dlp.exe.old").exists()

    # Un SHA-256 que no coincide no se instala.
    sums = next((github.root / "files").glob("*/SHA2-256SUMS"))
    sums.write_text(f"{'0' * 64}  yt-dlp.exe\n", encoding="utf-8")
    bad = up.YtdlpUpdate(network, fake_launcher, bin_dir, "stable", github.api, self_update=False)
    assert _run(qtbot, bad) == (False, "updates.error.checksum")
    assert (bin_dir / "yt-dlp.exe").read_bytes() == b"nueva"
    assert not (bin_dir / "yt-dlp.exe.new").exists()


def _failing(_args: list[str]) -> Launch | None:
    return sys.executable, ["-c", "import sys; sys.exit(1)"]


def test_ffmpeg_update_installs_and_rolls_back(
    qtbot: QtBot, github: FakeGitHub, fake_ffmpeg: Launcher, tmp_path: Path
) -> None:
    network = QNetworkAccessManager()
    archive = tmp_path / "build.zip"
    _zip(archive, {"ffmpeg-master/bin/ffmpeg.exe": b"ff2", "ffmpeg-master/bin/ffprobe.exe": b"fp2"})
    github.release(
        "BtbN/FFmpeg-Builds", "latest", {up.FFMPEG_ASSET: archive.read_bytes()}, "checksums.sha256"
    )
    bin_dir, cache = tmp_path / "bin", tmp_path / "cache"
    bin_dir.mkdir()
    (bin_dir / "ffmpeg.exe").write_bytes(b"ff1")
    step = up.FfmpegUpdate(network, fake_ffmpeg, bin_dir, cache, github.api)
    assert _run(qtbot, step) == (True, "updates.done.ffmpeg")
    assert (bin_dir / "ffmpeg.exe").read_bytes() == b"ff2"
    assert (bin_dir / "ffprobe.exe").read_bytes() == b"fp2"
    assert not list(cache.glob("*.zip"))

    broken = up.FfmpegUpdate(network, _failing, bin_dir, cache, github.api)
    (bin_dir / "ffmpeg.exe").write_bytes(b"buena")
    assert _run(qtbot, broken) == (False, "updates.error.broken")
    assert (bin_dir / "ffmpeg.exe").read_bytes() == b"buena"


def test_updates_ui(
    qtbot: QtBot,
    ctx: AppContext,
    github: FakeGitHub,
    fake_launcher: Launcher,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import bombastic.ui.updates as module

    monkeypatch.setattr(module, "default_launcher", lambda _paths: fake_launcher)
    github.release("yt-dlp/yt-dlp", "2100.01.01", {"yt-dlp.exe": b"y"}, "SHA2-256SUMS")
    github.release("me/app", "v99.0.0", {})
    ctx.settings.app_update_repo = "me/app"
    updates = Updates(ctx, api=github.api)
    bar = UpdateBar(updates)
    qtbot.addWidget(bar)
    seen: list[tuple[str, str, str]] = []
    updates.available.connect(lambda *args: seen.append(args))
    updates.check()
    qtbot.waitUntil(lambda: len(seen) == 2, timeout=TIMEOUT)
    assert {s[0] for s in seen} == {"ytdlp", "app"}
    assert updates.app_release is not None and updates.app_release.tag == "v99.0.0"
    assert ctx.settings.last_update_check
    assert bar.isVisibleTo(bar.parentWidget() or bar) or not bar.isHidden()

    bar.show_update("ytdlp", "2100.01.01", "")
    with qtbot.waitSignal(updates.finished, timeout=TIMEOUT):
        bar.action_button.click()
    assert bar.label.text() == "yt-dlp actualizado."
    assert (ctx.paths.bin_dir / "yt-dlp.exe").read_bytes() == b"y"

    wizard = DependencyWizard(ctx, updates)
    qtbot.addWidget(wizard)
    assert isinstance(DependencyWizard.missing(ctx), list)


def test_app_update_downloads_and_verifies(
    qtbot: QtBot, github: FakeGitHub, tmp_path: Path
) -> None:
    network = QNetworkAccessManager()
    files = {up.APP_INSTALLER_ASSET: b"instalador"}
    github.release("me/app", "v99.0.0", files, up.APP_SUMS_ASSET)
    release = up.parse_release(
        (tmp_path / "github" / "api" / "me" / "app" / "releases" / "latest").read_text()
    )
    step = up.AppUpdate(network, release, tmp_path / "cache")
    assert _run(qtbot, step) == (True, "updates.done.app")
    assert step.installer is not None and step.installer.read_bytes() == b"instalador"

    # Suma que no coincide: se descarta el archivo.
    (tmp_path / "github" / "files" / "me_app" / up.APP_SUMS_ASSET).write_text(
        f"{'0' * 64}  {up.APP_INSTALLER_ASSET}\n", encoding="utf-8"
    )
    bad = up.AppUpdate(network, release, tmp_path / "cache2")
    assert _run(qtbot, bad) == (False, "updates.error.checksum")
    assert not (tmp_path / "cache2" / up.APP_INSTALLER_ASSET).exists()

    # Sin sumas publicadas no se descarga nada.
    no_sums = up.Release("v99", "v99", "", "", {up.APP_INSTALLER_ASSET: "file:///x"})
    no_sums_step = up.AppUpdate(network, no_sums, tmp_path)
    assert _run(qtbot, no_sums_step) == (False, "updates.error.no_checksum")
    assert "/SILENT" in up.installer_args() and "/relaunch=1" in up.installer_args()


def test_update_bar_installs_app(
    qtbot: QtBot,
    ctx: AppContext,
    github: FakeGitHub,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    github.release("me/app", "v99.0.0", {up.APP_INSTALLER_ASSET: b"setup"}, up.APP_SUMS_ASSET)
    updates = Updates(ctx, api=github.api)
    updates.app_release = up.parse_release(
        (tmp_path / "github" / "api" / "me" / "app" / "releases" / "latest").read_text()
    )
    bar = UpdateBar(updates)
    qtbot.addWidget(bar)

    # Código fuente o portable: el botón solo enlaza la página de la release.
    monkeypatch.setattr(updates, "can_install_app", lambda: False)
    bar.show_update("app", "v99.0.0", "https://example.com/r")
    assert bar.action_button.text() == "Ver la descarga"

    monkeypatch.setattr(updates, "can_install_app", lambda: True)
    bar.show_update("app", "v99.0.0", "https://example.com/r")
    assert bar.action_button.text() == "Actualizar ahora"
    with qtbot.waitSignal(bar.install_ready, timeout=TIMEOUT) as blocker:
        bar.action_button.click()
    installer = blocker.args[0]
    assert installer.read_bytes() == b"setup"
    assert installer.parent == ctx.paths.cache_dir

    bar.install_cancelled()
    assert bar.action_button.isEnabled()
