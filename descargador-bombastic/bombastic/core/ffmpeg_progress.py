"""Progreso de ffmpeg con ``-progress pipe:1``: bloques de líneas ``clave=valor``."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FfmpegProgress:
    #: Segundos ya procesados del resultado.
    out_time: float | None
    #: Velocidad respecto al tiempo real (``2.5`` = 2,5x).
    speed: float | None
    #: ``True`` en el último bloque (``progress=end``).
    ended: bool


class FfmpegProgressParser:
    """Acumula líneas y devuelve un :class:`FfmpegProgress` al final de cada bloque."""

    def __init__(self) -> None:
        self._values: dict[str, str] = {}

    def feed(self, line: str) -> FfmpegProgress | None:
        key, sep, value = line.strip().partition("=")
        if not sep:
            return None
        self._values[key] = value.strip()
        if key != "progress":
            return None
        values, self._values = self._values, {}
        return FfmpegProgress(_out_time(values), _speed(values.get("speed")), value == "end")


def _out_time(values: dict[str, str]) -> float | None:
    # out_time_us y out_time_ms valen lo mismo (microsegundos, por un error histórico de ffmpeg).
    for key in ("out_time_us", "out_time_ms"):
        raw = values.get(key, "")
        if raw.lstrip("-").isdigit():
            return max(0.0, int(raw) / 1_000_000)
    return _parse_clock(values.get("out_time", ""))


def _parse_clock(text: str) -> float | None:
    parts = text.split(":")
    if len(parts) != 3:
        return None
    try:
        hours, minutes, seconds = int(parts[0]), int(parts[1]), float(parts[2])
    except ValueError:
        return None
    return max(0.0, hours * 3600 + minutes * 60 + seconds)


def _speed(raw: str | None) -> float | None:
    if not raw or not raw.endswith("x"):
        return None
    try:
        return float(raw[:-1])
    except ValueError:
        return None
