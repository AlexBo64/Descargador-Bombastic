"""yt-dlp falso para los tests: imita su salida sin red ni binarios reales.

Se lanza como ``python fake_ytdlp.py <argumentos de yt-dlp>``. El comportamiento depende de
palabras que aparezcan en el enlace:

- ``playlist``: el enlace es una lista de reproducción de 3 elementos.
- ``badinfo``: la consulta de metadatos falla con un error de yt-dlp.
- ``garbage``: la consulta de metadatos devuelve algo que no es JSON.
- ``fail``: la descarga falla con un error de yt-dlp.
- ``crash``: la descarga termina con código 3 sin explicar nada.
- ``flaky``: la descarga falla con un error de red (se reintenta sola).
- ``slowinfo``: la consulta de metadatos no termina nunca.
- ``slow``: la descarga no termina nunca (para probar cancelaciones).

``--version`` y ``--help`` devuelven una versión inventada y la ayuda de ``fixtures/``.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

TITLE = "Vídeo de prueba ñ"


def out(text: str, stream: str = "stdout") -> None:
    """Escribe en UTF-8 y sin búfer, como hace yt-dlp con ``--encoding utf-8``."""
    target = sys.stdout if stream == "stdout" else sys.stderr
    target.buffer.write((text + "\n").encode("utf-8"))
    target.buffer.flush()


def option(args: list[str], name: str) -> str:
    return args[args.index(name) + 1]


def info(url: str) -> int:
    if "slowinfo" in url:
        time.sleep(60)
    if "badinfo" in url:
        out("WARNING: algo sin importancia", "stderr")
        out("ERROR: [fake] abc: This video is private", "stderr")
        return 1
    if "garbage" in url:
        out("esto no es JSON")
        return 0
    if "playlist" in url:
        data = {
            "_type": "playlist",
            "id": "PL123",
            "title": "Lista de prueba",
            "channel": "Canal ñ",
            "playlist_count": 3,
            "webpage_url": url,
            "extractor_key": "Fake",
            "entries": [
                {"id": f"v{n}", "title": f"Elemento {n}", "thumbnails": [{"url": "x.jpg"}]}
                for n in (1, 2, 3)
            ],
        }
    else:
        data = {
            "_type": "video",
            "id": "abc123",
            "title": TITLE,
            "channel": "Canal ñ",
            "duration": 75,
            "thumbnail": "https://img.example/abc.jpg",
            "webpage_url": url,
            "extractor_key": "Fake",
            "live_status": "not_live",
            "formats": [
                {"format_id": "sb0", "ext": "mhtml", "format_note": "storyboard"},
                {
                    "format_id": "140",
                    "ext": "m4a",
                    "vcodec": "none",
                    "acodec": "mp4a.40.2",
                    "tbr": 129.5,
                    "filesize": 1_200_000,
                    "format_note": "medium",
                },
                {
                    "format_id": "137",
                    "ext": "mp4",
                    "vcodec": "avc1.640028",
                    "acodec": "none",
                    "width": 1920,
                    "height": 1080,
                    "fps": 30,
                    "tbr": 4400.1,
                    "filesize_approx": 41_000_000,
                },
                {
                    "format_id": "18",
                    "ext": "mp4",
                    "vcodec": "avc1.42001E",
                    "acodec": "mp4a.40.2",
                    "width": 640,
                    "height": 360,
                    "fps": 30,
                    "tbr": 600,
                },
            ],
        }
    out(json.dumps(data))
    return 0


def progress(status: str, done: object, total: object, index: object, count: object) -> None:
    # Los campos sin valor salen como NA sin comillas, igual que en el yt-dlp real.
    out(
        f'BMBPROG {{"status":"{status}","d":{done},"t":{total},"te":NA,"s":2048.5,"e":3,'
        f'"i":{index},"n":{count},"fi":NA,"fc":NA}}'
    )


def download(args: list[str], url: str) -> int:
    folder = Path(option(args, "-P"))
    out(f"[fake] Extracting URL: {url}")
    if "fail" in url:
        out("ERROR: [fake] abc: Video unavailable. This video is private", "stderr")
        return 1
    if "flaky" in url:
        out("ERROR: [fake] abc: Unable to download webpage: The read operation timed out", "stderr")
        return 1
    if "crash" in url:
        return 3
    items = 3 if "playlist" in url else 1
    audio = "-x" in args
    extension = option(args, "--audio-format") if audio else "mp4"
    for item in range(1, items + 1):
        index: object = item if items > 1 else "NA"
        count: object = items if items > 1 else "NA"
        if items > 1:
            out(f"[download] Downloading item {item} of {items}")
        parts = ["251"] if audio else ["137", "140"]
        out(f"[info] abc{item}: Downloading 1 format(s): {'+'.join(parts)}")
        for _part in parts:
            progress("downloading", 0, 1000, index, count)
            if "slow" in url:
                while True:
                    time.sleep(0.05)
                    progress("downloading", 100, 1000, index, count)
            progress("downloading", 500, 1000, index, count)
            progress("finished", 1000, 1000, index, count)
        step = "ExtractAudio" if audio else "Merger"
        out(f'BMBPP {{"status":"started","pp":"{step}"}}')
        out(f"[{step}] Trabajando…")
        out(f'BMBPP {{"status":"finished","pp":"{step}"}}')
        out('BMBPP {"status":"started","pp":"MoveFiles"}')
        out('BMBPP {"status":"finished","pp":"MoveFiles"}')
        folder.mkdir(parents=True, exist_ok=True)
        name = f"{TITLE} {item}.{extension}" if items > 1 else f"{TITLE}.{extension}"
        target = folder / name
        target.write_bytes(b"contenido")
        out("BMBFILE " + json.dumps(str(target)))
    return 0


def main(argv: list[str]) -> int:
    if argv == ["--version"]:
        out("2099.01.01")
        return 0
    if argv == ["--help"]:
        help_file = Path(__file__).with_name("fixtures") / "ytdlp_help.txt"
        out(help_file.read_text(encoding="utf-8"))
        return 0
    url = argv[-1]
    if "-J" in argv:
        return info(url)
    return download(argv, url)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
