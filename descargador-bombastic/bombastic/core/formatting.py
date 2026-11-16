"""Formato legible de tamaños, velocidades y tiempos. No depende del idioma."""

from __future__ import annotations

_UNITS = ("B", "KB", "MB", "GB", "TB")


def format_bytes(size: float | None) -> str:
    """``1536`` → ``"1.5 KB"``. Devuelve cadena vacía si no hay dato."""
    if size is None or size < 0:
        return ""
    value = float(size)
    for unit in _UNITS[:-1]:
        if value < 1024:
            return f"{int(value)} B" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} {_UNITS[-1]}"


def format_speed(bytes_per_second: float | None) -> str:
    text = format_bytes(bytes_per_second)
    return f"{text}/s" if text else ""


def format_duration(seconds: float | None) -> str:
    """``75`` → ``"1:15"``; ``3723`` → ``"1:02:03"``. Cadena vacía si no hay dato."""
    if seconds is None or seconds < 0:
        return ""
    total = round(seconds)
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"
