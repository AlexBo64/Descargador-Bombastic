"""Metadatos de un enlace, a partir de la salida de ``yt-dlp -J --flat-playlist``."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit


class MediaInfoError(ValueError):
    """La salida de yt-dlp no es el JSON esperado."""


@dataclass(frozen=True)
class PlaylistEntry:
    """Un elemento de una lista de reproducción (``index`` empieza en 1)."""

    index: int
    title: str
    duration: float | None = None


@dataclass(frozen=True)
class MediaInfo:
    url: str
    media_id: str
    title: str
    channel: str
    #: Segundos. ``None`` en listas, directos o cuando la web no lo indica.
    duration: float | None
    thumbnail_url: str
    is_playlist: bool
    #: Número de elementos de la lista (``None`` si no es una lista o no se conoce).
    entry_count: int | None
    is_live: bool
    extractor: str
    #: Elementos de la lista, si yt-dlp los ha enumerado.
    entries: tuple[PlaylistEntry, ...] = ()


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _is_jpeg_or_png(url: str) -> bool:
    return urlsplit(url).path.lower().endswith((".jpg", ".jpeg", ".png"))


def _pick_thumbnail(data: dict[str, Any]) -> str:
    """Elige una miniatura, prefiriendo JPG/PNG (Qt puede no traer el plugin de WebP)."""
    main = _text(data.get("thumbnail"))
    if main and _is_jpeg_or_png(main):
        return main
    candidates: list[str] = []
    thumbnails = data.get("thumbnails")
    if isinstance(thumbnails, list):
        for entry in thumbnails:
            if isinstance(entry, dict):
                url = _text(entry.get("url"))
                if url:
                    candidates.append(url)
    # yt-dlp ordena las miniaturas de peor a mejor.
    for url in reversed(candidates):
        if _is_jpeg_or_png(url):
            return url
    if main:
        return main
    return candidates[-1] if candidates else ""


def _entries(raw: Any) -> tuple[PlaylistEntry, ...]:
    if not isinstance(raw, list):
        return ()
    result: list[PlaylistEntry] = []
    for index, entry in enumerate(raw, start=1):
        if not isinstance(entry, dict):
            continue
        title = _text(entry.get("title")) or _text(entry.get("url")) or f"#{index}"
        result.append(PlaylistEntry(index, title, _number(entry.get("duration"))))
    return tuple(result)


def parse_media_info(output: str, fallback_url: str) -> MediaInfo:
    """Interpreta la salida de ``yt-dlp -J``. Lanza :class:`MediaInfoError` si no es válida."""
    data: Any = None
    # El JSON va en una sola línea; se ignora cualquier aviso que se cuele antes o después.
    for line in reversed(output.splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                data = json.loads(line)
            except ValueError as exc:
                raise MediaInfoError(str(exc)) from exc
            break
    if not isinstance(data, dict):
        raise MediaInfoError("no JSON object in yt-dlp output")

    is_playlist = data.get("_type") in ("playlist", "multi_video")
    raw_entries = data.get("entries")
    entries = _entries(raw_entries) if is_playlist else ()
    entry_count: int | None = None
    thumbnail = _pick_thumbnail(data)
    if is_playlist:
        count = _number(data.get("playlist_count"))
        if count is not None:
            entry_count = int(count)
        elif isinstance(raw_entries, list):
            entry_count = len(raw_entries)
        if not thumbnail and isinstance(raw_entries, list):
            for entry in raw_entries:
                if isinstance(entry, dict):
                    thumbnail = _pick_thumbnail(entry)
                    if thumbnail:
                        break

    media_id = data.get("id")
    return MediaInfo(
        url=_text(data.get("webpage_url")) or _text(data.get("original_url")) or fallback_url,
        media_id=str(media_id) if isinstance(media_id, (str, int)) else "",
        title=_text(data.get("title")) or fallback_url,
        channel=(
            _text(data.get("channel")) or _text(data.get("uploader")) or _text(data.get("creator"))
        ),
        duration=None if is_playlist else _number(data.get("duration")),
        thumbnail_url=thumbnail,
        is_playlist=is_playlist,
        entry_count=entry_count,
        is_live=data.get("live_status") == "is_live" or data.get("is_live") is True,
        extractor=_text(data.get("extractor_key")) or _text(data.get("extractor")),
        entries=entries,
    )


def info_to_dict(info: MediaInfo) -> dict[str, Any]:
    """Para guardarlo en la base de datos."""
    return {
        "url": info.url,
        "media_id": info.media_id,
        "title": info.title,
        "channel": info.channel,
        "duration": info.duration,
        "thumbnail_url": info.thumbnail_url,
        "is_playlist": info.is_playlist,
        "entry_count": info.entry_count,
        "is_live": info.is_live,
        "extractor": info.extractor,
        "entries": [[e.index, e.title, e.duration] for e in info.entries],
    }


def info_from_dict(data: Any, fallback_url: str) -> MediaInfo | None:
    """Inverso de :func:`info_to_dict`, tolerante con datos incompletos o de otra versión."""
    if not isinstance(data, dict):
        return None
    entries: list[PlaylistEntry] = []
    raw_entries = data.get("entries")
    if isinstance(raw_entries, list):
        for raw in raw_entries:
            if isinstance(raw, list) and len(raw) == 3 and isinstance(raw[0], int):
                entries.append(PlaylistEntry(raw[0], str(raw[1]), _number(raw[2])))
    count = _number(data.get("entry_count"))
    return MediaInfo(
        url=_text(data.get("url")) or fallback_url,
        media_id=_text(data.get("media_id")),
        title=_text(data.get("title")) or fallback_url,
        channel=_text(data.get("channel")),
        duration=_number(data.get("duration")),
        thumbnail_url=_text(data.get("thumbnail_url")),
        is_playlist=data.get("is_playlist") is True,
        entry_count=int(count) if count is not None else None,
        is_live=data.get("is_live") is True,
        extractor=_text(data.get("extractor")),
        entries=tuple(entries),
    )
