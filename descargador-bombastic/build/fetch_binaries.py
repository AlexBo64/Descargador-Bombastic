"""Descarga y verifica ``yt-dlp.exe``, ``ffmpeg.exe`` y ``ffprobe.exe`` para empaquetarlos.

Uso: ``python build/fetch_binaries.py <carpeta>``. Usa las mismas fuentes y comprobaciones que
el actualizador de la app (releases de GitHub con SHA-256 publicado) y escribe en
``<carpeta>/SOURCES.txt`` la versión, la URL y el SHA-256 de cada binario, para la licencia.
"""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bombastic.core.updater import (  # noqa: E402
    FFMPEG_ASSET,
    FFMPEG_REPO,
    GITHUB_API,
    YTDLP_ASSET,
    YTDLP_REPOS,
    extract_ffmpeg,
    parse_checksums,
    parse_release,
    sha256_of,
)

USER_AGENT = "DescargadorBombastic-build"


def get(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=120) as response:
        data: bytes = response.read()
        return data


def download(url: str, target: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=600) as response, target.open("wb") as out:
        while chunk := response.read(1 << 20):
            out.write(chunk)


def fetch(repo: str, asset: str, sums_name: str, folder: Path) -> tuple[str, str, Path, str]:
    release = parse_release(get(f"{GITHUB_API}/{repo}/releases/latest").decode("utf-8"))
    if asset not in release.assets or sums_name not in release.assets:
        raise SystemExit(f"{repo} {release.tag}: falta {asset} o {sums_name}")
    expected = parse_checksums(get(release.assets[sums_name]).decode("utf-8")).get(asset)
    if expected is None:
        raise SystemExit(f"{repo}: {sums_name} no incluye {asset}")
    target = folder / asset
    download(release.assets[asset], target)
    actual = sha256_of(target)
    if actual != expected:
        target.unlink()
        raise SystemExit(f"{asset}: SHA-256 {actual} no coincide con {expected}")
    return release.tag, release.assets[asset], target, actual


def main(argv: list[str]) -> int:
    folder = Path(argv[1]) if len(argv) > 1 else ROOT / "out" / "bin"
    folder.mkdir(parents=True, exist_ok=True)
    sources: list[dict[str, str]] = []

    tag, url, _path, digest = fetch(YTDLP_REPOS["stable"], YTDLP_ASSET, "SHA2-256SUMS", folder)
    sources.append({"name": "yt-dlp.exe", "version": tag, "url": url, "sha256": digest})

    tag, url, archive, digest = fetch(FFMPEG_REPO, FFMPEG_ASSET, "checksums.sha256", folder)
    for new in extract_ffmpeg(archive, folder):
        final = new.with_suffix("")
        final.unlink(missing_ok=True)
        new.replace(final)
    archive.unlink()
    name = "ffmpeg.exe, ffprobe.exe"
    sources.append({"name": name, "version": tag, "url": url, "sha256": digest})

    lines = [
        f"{s['name']}\n  Versión: {s['version']}\n  Origen:  {s['url']}\n  SHA-256: {s['sha256']}\n"
        for s in sources
    ]
    (folder / "SOURCES.txt").write_text("\n".join(lines), encoding="utf-8")
    (folder / "sources.json").write_text(json.dumps(sources, indent=2), encoding="utf-8")
    for line in lines:
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
