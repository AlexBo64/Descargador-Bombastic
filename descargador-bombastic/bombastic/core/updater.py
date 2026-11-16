"""Actualizaciones de yt-dlp, de ffmpeg y aviso de versiones nuevas de la app.

- yt-dlp: se compara ``yt-dlp --version`` con la última release de GitHub. Se actualiza con
  ``yt-dlp -U`` y, si no funciona (por ejemplo, instalado con winget o pip), se descarga
  ``yt-dlp.exe`` de la release a la carpeta ``bin`` de datos, verificando el SHA-256.
- ffmpeg: build "win64-gpl" de BtbN (GitHub), con su ``checksums.sha256``. Se extraen
  ``ffmpeg.exe`` y ``ffprobe.exe`` a ``bin``, guardando la versión anterior hasta comprobar que
  la nueva responde a ``-version``; si no, se vuelve atrás.
- La app: se consulta la última release de un repositorio configurable. En la versión instalada
  se descarga ``DescargadorBombastic-Setup.exe`` verificando ``SHA256SUMS.txt`` y se ejecuta en
  modo silencioso al cerrar la app; el instalador la vuelve a abrir al terminar.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QThreadPool, Signal
from PySide6.QtNetwork import QNetworkAccessManager

from bombastic.core.net import FileFetch, TextFetch
from bombastic.core.ytdlp_runner import Launcher, OutputCollector

log = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com/repos"
YTDLP_REPOS = {"stable": "yt-dlp/yt-dlp", "nightly": "yt-dlp/yt-dlp-nightly-builds"}
FFMPEG_REPO = "BtbN/FFmpeg-Builds"
FFMPEG_ASSET = "ffmpeg-master-latest-win64-gpl.zip"
YTDLP_ASSET = "yt-dlp.exe"
DEFAULT_APP_REPO = "AlexBo64/Descargador-Bombastic"
APP_INSTALLER_ASSET = "DescargadorBombastic-Setup.exe"
APP_SUMS_ASSET = "SHA256SUMS.txt"
UPDATE_CHANNELS: tuple[str, ...] = ("stable", "nightly")


# ------------------------------------------------------------------ lógica pura


def version_key(text: str) -> tuple[int, ...]:
    """``"v2026.08.19"`` → ``(2026, 8, 19)``; ``"0.8.0"`` → ``(0, 8, 0)``. Vacío si no hay."""
    return tuple(int(part) for part in re.findall(r"\d+", text)[:4])


def is_newer(latest: str, current: str) -> bool:
    latest_key, current_key = version_key(latest), version_key(current)
    return bool(latest_key) and latest_key > current_key


def should_check(last_check: str, interval_hours: int, now: datetime | None = None) -> bool:
    """Toca comprobar si nunca se ha hecho o ha pasado el intervalo. 0 horas = nunca."""
    if interval_hours <= 0:
        return False
    if not last_check:
        return True
    try:
        last = datetime.fromisoformat(last_check)
    except ValueError:
        return True
    return (now or datetime.now()) - last >= timedelta(hours=interval_hours)


@dataclass(frozen=True)
class Release:
    tag: str
    name: str
    url: str
    published: str
    #: Nombre del archivo → enlace de descarga.
    assets: dict[str, str]


def parse_release(text: str) -> Release:
    """JSON de ``/releases/latest`` de GitHub. Lanza ``ValueError`` si no lo es."""
    data: Any = json.loads(text)
    if not isinstance(data, dict) or not isinstance(data.get("tag_name"), str):
        raise ValueError("not a release")
    assets: dict[str, str] = {}
    for asset in data.get("assets") or []:
        if isinstance(asset, dict) and asset.get("name") and asset.get("browser_download_url"):
            assets[str(asset["name"])] = str(asset["browser_download_url"])
    return Release(
        tag=data["tag_name"],
        name=str(data.get("name") or data["tag_name"]),
        url=str(data.get("html_url") or ""),
        published=str(data.get("published_at") or ""),
        assets=assets,
    )


def parse_checksums(text: str) -> dict[str, str]:
    """Líneas ``<sha256>  <archivo>`` (formato de ``sha256sum``)."""
    sums: dict[str, str] = {}
    for line in text.splitlines():
        match = re.match(r"^([0-9a-fA-F]{64})\s+\*?(\S.*)$", line.strip())
        if match:
            sums[match.group(2).strip()] = match.group(1).lower()
    return sums


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def extract_ffmpeg(archive: Path, target_dir: Path) -> list[Path]:
    """Saca ``ffmpeg.exe`` y ``ffprobe.exe`` del zip a ``target_dir`` como ``*.new``."""
    wanted = {"ffmpeg.exe", "ffprobe.exe"}
    written: list[Path] = []
    with zipfile.ZipFile(archive) as bundle:
        for member in bundle.namelist():
            name = member.rsplit("/", 1)[-1]
            if name in wanted and "/bin/" in f"/{member}":
                destination = target_dir / f"{name}.new"
                with bundle.open(member) as source, destination.open("wb") as out:
                    while chunk := source.read(1 << 20):
                        out.write(chunk)
                written.append(destination)
                wanted.discard(name)
    if wanted:
        for path in written:
            path.unlink(missing_ok=True)
        raise ValueError(f"missing in archive: {sorted(wanted)}")
    return written


def swap_in(new_files: list[Path]) -> list[tuple[Path, Path | None]]:
    """Pone ``x.exe.new`` en lugar de ``x.exe`` guardando ``x.exe.old``. Devuelve cómo deshacer."""
    undo: list[tuple[Path, Path | None]] = []
    for new in new_files:
        final = new.with_suffix("")  # quita ".new"
        old = final.with_name(final.name + ".old")
        backup: Path | None = None
        if final.exists():
            old.unlink(missing_ok=True)
            final.replace(old)
            backup = old
        new.replace(final)
        undo.append((final, backup))
    return undo


def roll_back(undo: list[tuple[Path, Path | None]]) -> None:
    for final, backup in undo:
        final.unlink(missing_ok=True)
        if backup is not None and backup.exists():
            backup.replace(final)


def drop_backups(undo: list[tuple[Path, Path | None]]) -> None:
    for _final, backup in undo:
        if backup is not None:
            backup.unlink(missing_ok=True)


def installer_args() -> list[str]:
    """Inno Setup sin preguntas, cerrando la app si sigue abierta y volviéndola a abrir."""
    return ["/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS", "/relaunch=1"]


# ------------------------------------------------------------- operaciones Qt


class _Step(QObject):
    """Base: emite ``status(clave)`` y termina con ``finished(ok, clave del mensaje)``."""

    status = Signal(str)
    progress = Signal(object, object)
    finished = Signal(bool, str)

    def __init__(self, network: QNetworkAccessManager, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._network = network
        self._done = False

    def _finish(self, ok: bool, key: str) -> None:
        if not self._done:
            self._done = True
            self.finished.emit(ok, key)

    def _get_text(self, url: str, slot: Callable[[str], None]) -> None:
        fetch = TextFetch(self._network, url, self)

        def done(text: str, error: str) -> None:
            fetch.deleteLater()
            if error:
                self._finish(False, "updates.error.network")
            else:
                slot(text)

        fetch.finished.connect(done)

    def _get_file(self, url: str, target: Path, slot: Callable[[], None]) -> FileFetch:
        fetch = FileFetch(self._network, url, target, self)
        fetch.progress.connect(self.progress)

        def done(error: str) -> None:
            fetch.deleteLater()
            if error:
                self._finish(False, "updates.error.network")
            else:
                slot()

        fetch.finished.connect(done)
        return fetch

    def _run(self, launcher: Launcher, args: list[str], slot: Callable[[int, str], None]) -> None:
        launch = launcher(args)
        if launch is None:
            slot(-1, "")
            return
        collector = OutputCollector(launch, self)
        collector.finished.connect(collector.deleteLater)
        collector.finished.connect(slot)
        collector.start()


class ReleaseCheck(_Step):
    """Última release de un repositorio. Al terminar, ``release`` tiene el resultado."""

    def __init__(
        self,
        network: QNetworkAccessManager,
        repo: str,
        api: str = GITHUB_API,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(network, parent)
        self.release: Release | None = None
        self._url = f"{api}/{repo}/releases/latest"

    def start(self) -> None:
        self._get_text(self._url, self._parsed)

    def _parsed(self, text: str) -> None:
        try:
            self.release = parse_release(text)
        except ValueError:
            self._finish(False, "updates.error.bad_release")
            return
        self._finish(True, "")


class YtdlpVersionCheck(_Step):
    """Versión local de yt-dlp y la última del canal elegido."""

    def __init__(
        self,
        network: QNetworkAccessManager,
        launcher: Launcher,
        channel: str = "stable",
        api: str = GITHUB_API,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(network, parent)
        self._launcher = launcher
        repo = YTDLP_REPOS.get(channel, YTDLP_REPOS["stable"])
        self._release = ReleaseCheck(network, repo, api, self)
        self.local = ""
        self.latest = ""

    def start(self) -> None:
        self._run(self._launcher, ["--version"], self._on_version)

    def _on_version(self, code: int, output: str) -> None:
        self.local = output.strip() if code == 0 else ""
        self._release.finished.connect(self._on_release)
        self._release.start()

    def _on_release(self, ok: bool, key: str) -> None:
        if not ok or self._release.release is None:
            self._finish(False, key)
            return
        self.latest = self._release.release.tag
        key = "updates.ytdlp.newer" if self.update_available else "updates.ytdlp.current"
        self._finish(True, key)

    @property
    def update_available(self) -> bool:
        return not self.local or is_newer(self.latest, self.local)


class YtdlpUpdate(_Step):
    """``yt-dlp -U``; si falla, descarga directa del exe a ``bin`` con SHA-256 y vuelta atrás."""

    def __init__(
        self,
        network: QNetworkAccessManager,
        launcher: Launcher,
        bin_dir: Path,
        channel: str = "stable",
        api: str = GITHUB_API,
        self_update: bool = True,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(network, parent)
        self._launcher = launcher
        self._bin = bin_dir
        self._channel = channel if channel in UPDATE_CHANNELS else "stable"
        self._api = api
        #: ``False`` para ir directamente a la descarga (asistente de dependencias).
        self._self_update = self_update
        self._release: Release | None = None
        self._undo: list[tuple[Path, Path | None]] = []

    def start(self) -> None:
        if not self._self_update:
            self._direct()
            return
        self.status.emit("updates.status.self_update")
        args = ["-U"] if self._channel == "stable" else ["--update-to", "nightly@latest"]
        self._run(self._launcher, args, self._on_self_update)

    def _on_self_update(self, code: int, output: str) -> None:
        if code == 0 and "ERROR" not in output:
            self._finish(True, "updates.done.ytdlp")
            return
        log.info("yt-dlp -U failed (%s); downloading the release directly", code)
        self._direct()

    def _direct(self) -> None:
        self.status.emit("updates.status.downloading")
        check = ReleaseCheck(self._network, YTDLP_REPOS[self._channel], self._api, self)
        check.finished.connect(lambda ok, key: self._on_release(check, ok, key))
        check.start()

    def _on_release(self, check: ReleaseCheck, ok: bool, key: str) -> None:
        release = check.release
        if not ok or release is None or YTDLP_ASSET not in release.assets:
            self._finish(False, key or "updates.error.no_asset")
            return
        self._release = release
        sums_url = release.assets.get("SHA2-256SUMS")
        if sums_url is None:
            self._finish(False, "updates.error.no_checksum")
            return
        self._get_text(sums_url, self._on_sums)

    def _on_sums(self, text: str) -> None:
        assert self._release is not None
        expected = parse_checksums(text).get(YTDLP_ASSET)
        if expected is None:
            self._finish(False, "updates.error.no_checksum")
            return
        target = self._bin / f"{YTDLP_ASSET}.new"
        url = self._release.assets[YTDLP_ASSET]
        self._get_file(url, target, lambda: self._verify(target, expected))

    def _verify(self, path: Path, expected: str) -> None:
        if sha256_of(path) != expected:
            path.unlink(missing_ok=True)
            self._finish(False, "updates.error.checksum")
            return
        try:
            self._undo = swap_in([path])
        except OSError:
            log.exception("Could not install the new yt-dlp")
            self._finish(False, "updates.error.install")
            return
        self._run(self._launcher, ["--version"], self._on_new_version)

    def _on_new_version(self, code: int, _output: str) -> None:
        if code != 0:
            roll_back(self._undo)
            self._finish(False, "updates.error.broken")
            return
        drop_backups(self._undo)
        self._finish(True, "updates.done.ytdlp")


class FfmpegUpdate(_Step):
    """Descarga e instala la última build de ffmpeg de BtbN en ``bin``."""

    def __init__(
        self,
        network: QNetworkAccessManager,
        launcher: Launcher,
        bin_dir: Path,
        cache_dir: Path,
        api: str = GITHUB_API,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(network, parent)
        self._launcher = launcher
        self._bin = bin_dir
        self._cache = cache_dir
        self._api = api
        self._undo: list[tuple[Path, Path | None]] = []
        self.release: Release | None = None
        self._pool = QThreadPool.globalInstance()

    def start(self) -> None:
        self.status.emit("updates.status.checking")
        check = ReleaseCheck(self._network, FFMPEG_REPO, self._api, self)
        check.finished.connect(lambda ok, key: self._on_release(check, ok, key))
        check.start()

    def _on_release(self, check: ReleaseCheck, ok: bool, key: str) -> None:
        release = check.release
        if not ok or release is None or FFMPEG_ASSET not in release.assets:
            self._finish(False, key or "updates.error.no_asset")
            return
        self.release = release
        sums = release.assets.get("checksums.sha256")
        if sums is None:
            self._finish(False, "updates.error.no_checksum")
            return
        self._get_text(sums, self._on_sums)

    def _on_sums(self, text: str) -> None:
        assert self.release is not None
        expected = parse_checksums(text).get(FFMPEG_ASSET)
        if expected is None:
            self._finish(False, "updates.error.no_checksum")
            return
        self.status.emit("updates.status.downloading")
        archive = self._cache / FFMPEG_ASSET
        url = self.release.assets[FFMPEG_ASSET]
        self._get_file(url, archive, lambda: self._unpack(archive, expected))

    def _unpack(self, archive: Path, expected: str) -> None:
        """Comprueba y extrae en otro hilo: son decenas de MB."""
        self.status.emit("updates.status.installing")
        self._bin.mkdir(parents=True, exist_ok=True)

        def work() -> None:
            try:
                if sha256_of(archive) != expected:
                    self._unpacked.emit("updates.error.checksum")
                    return
                self._new = extract_ffmpeg(archive, self._bin)
                self._unpacked.emit("")
            except (OSError, ValueError, zipfile.BadZipFile):
                log.exception("Could not unpack %s", archive)
                self._unpacked.emit("updates.error.install")
            finally:
                archive.unlink(missing_ok=True)

        self._unpacked.connect(self._install)
        self._pool.start(work)

    #: Fin de la extracción en el hilo (clave de error o vacío).
    _unpacked = Signal(str)

    def _install(self, error: str) -> None:
        if error:
            self._finish(False, error)
            return
        try:
            self._undo = swap_in(self._new)
        except OSError:
            log.exception("Could not install the new ffmpeg")
            self._finish(False, "updates.error.install")
            return
        self._run(self._launcher, ["-version"], self._on_new_version)

    def _on_new_version(self, code: int, _output: str) -> None:
        if code != 0:
            roll_back(self._undo)
            self._finish(False, "updates.error.broken")
            return
        drop_backups(self._undo)
        self._finish(True, "updates.done.ffmpeg")


class AppUpdate(_Step):
    """Descarga el instalador de una release de la app y comprueba su SHA-256.

    Al terminar bien, ``installer`` es la ruta del ``.exe`` listo para ejecutar.
    """

    def __init__(
        self,
        network: QNetworkAccessManager,
        release: Release,
        cache_dir: Path,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(network, parent)
        self._release = release
        self._cache = cache_dir
        self.installer: Path | None = None

    def start(self) -> None:
        assets = self._release.assets
        if APP_INSTALLER_ASSET not in assets:
            self._finish(False, "updates.error.no_asset")
            return
        if APP_SUMS_ASSET not in assets:
            self._finish(False, "updates.error.no_checksum")
            return
        self.status.emit("updates.status.downloading")
        self._get_text(assets[APP_SUMS_ASSET], self._on_sums)

    def _on_sums(self, text: str) -> None:
        expected = parse_checksums(text).get(APP_INSTALLER_ASSET)
        if expected is None:
            self._finish(False, "updates.error.no_checksum")
            return
        target = self._cache / APP_INSTALLER_ASSET
        url = self._release.assets[APP_INSTALLER_ASSET]
        self._get_file(url, target, lambda: self._verify(target, expected))

    def _verify(self, path: Path, expected: str) -> None:
        if sha256_of(path) != expected:
            path.unlink(missing_ok=True)
            self._finish(False, "updates.error.checksum")
            return
        self.installer = path
        self._finish(True, "updates.done.app")
