"""Información de un archivo multimedia a partir de ``ffprobe -show_format -show_streams``."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


class ProbeError(ValueError):
    """La salida de ffprobe no es el JSON esperado."""


@dataclass(frozen=True)
class StreamInfo:
    index: int
    #: ``video``, ``audio``, ``subtitle``…
    kind: str
    codec: str
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    sample_rate: int | None = None
    channels: int | None = None
    language: str = ""
    #: Carátula de un archivo de audio (no es un vídeo de verdad).
    attached_pic: bool = False


@dataclass(frozen=True)
class ProbeInfo:
    container: str
    duration: float | None
    size: int | None
    #: Bit/s.
    bitrate: int | None
    streams: tuple[StreamInfo, ...]

    def first(self, kind: str) -> StreamInfo | None:
        return next((s for s in self.streams if s.kind == kind and not s.attached_pic), None)

    @property
    def has_video(self) -> bool:
        return self.first("video") is not None

    @property
    def has_audio(self) -> bool:
        return self.first("audio") is not None


def probe_args(path: str) -> list[str]:
    return ["-v", "error", "-show_format", "-show_streams", "-of", "json", "--", path]


def _int(value: Any) -> int | None:
    try:
        return int(value) if value not in (None, "", "N/A") else None
    except (TypeError, ValueError):
        return None


def _float(value: Any) -> float | None:
    try:
        return float(value) if value not in (None, "", "N/A") else None
    except (TypeError, ValueError):
        return None


def _rate(value: Any) -> float | None:
    """``"30000/1001"`` → ``29.97``."""
    if not isinstance(value, str) or "/" not in value:
        return _float(value)
    num, _, den = value.partition("/")
    numerator, denominator = _float(num), _float(den)
    if not numerator or not denominator:
        return None
    return round(numerator / denominator, 3)


def parse_probe(output: str) -> ProbeInfo:
    try:
        data = json.loads(output)
    except ValueError as exc:
        raise ProbeError(str(exc)) from exc
    if not isinstance(data, dict) or not isinstance(data.get("format"), dict):
        raise ProbeError("no format section")
    fmt = data["format"]
    streams: list[StreamInfo] = []
    for raw in data.get("streams") or []:
        if not isinstance(raw, dict):
            continue
        tags: dict[str, Any] = raw["tags"] if isinstance(raw.get("tags"), dict) else {}
        disposition: dict[str, Any] = (
            raw["disposition"] if isinstance(raw.get("disposition"), dict) else {}
        )
        streams.append(
            StreamInfo(
                index=_int(raw.get("index")) or 0,
                kind=str(raw.get("codec_type") or ""),
                codec=str(raw.get("codec_name") or ""),
                width=_int(raw.get("width")),
                height=_int(raw.get("height")),
                fps=_rate(raw.get("avg_frame_rate")) or _rate(raw.get("r_frame_rate")),
                sample_rate=_int(raw.get("sample_rate")),
                channels=_int(raw.get("channels")),
                language=str(tags.get("language") or ""),
                attached_pic=disposition.get("attached_pic") == 1,
            )
        )
    return ProbeInfo(
        container=str(fmt.get("format_name") or ""),
        duration=_float(fmt.get("duration")),
        size=_int(fmt.get("size")),
        bitrate=_int(fmt.get("bit_rate")),
        streams=tuple(streams),
    )
