"""Traducción de los errores de yt-dlp a mensajes comprensibles.

:func:`classify_error` busca patrones conocidos en el mensaje de error (y, si hace falta, en las
últimas líneas del log) y devuelve una clave. La interfaz la muestra con ``tr("errors.<clave>")``
y deja el mensaje original en "Ver detalles".
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class ErrorInfo:
    key: str
    #: Merece la pena reintentar solo (fallos de red pasajeros).
    retryable: bool = False


#: Reglas en orden: la primera que coincide gana. Las más concretas van primero.
_RULES: tuple[tuple[str, bool, tuple[str, ...]], ...] = (
    ("disk_full", False, ("no space left on device", "errno 28", "disk full")),
    (
        "ffmpeg_missing",
        False,
        ("ffmpeg not found", "ffprobe and ffmpeg not found", "ffmpeg is not installed"),
    ),
    (
        "js_runtime",
        False,
        ("no supported javascript runtime", "javascript runtime", "js runtime", "jsc runtime"),
    ),
    ("private", False, ("private video", "this video is private", "video is private")),
    (
        "age",
        False,
        ("confirm your age", "age-restricted", "age restricted", "inappropriate for some users"),
    ),
    ("bot_check", False, ("not a bot", "confirm you're not a bot", "confirm you are not a bot")),
    (
        "members",
        False,
        (
            "members-only",
            "members only",
            "join this channel",
            "available to this channel's members",
        ),
    ),
    (
        "login",
        False,
        (
            "login required",
            "sign in",
            "log in to",
            "requires authentication",
            "account cookies",
            "use --cookies",
            "--cookies-from-browser",
        ),
    ),
    (
        "geo",
        False,
        (
            "not available in your country",
            "geo restrict",
            "geo-restrict",
            "blocked it in your country",
            "not made this video available in your country",
        ),
    ),
    ("copyright", False, ("copyright",)),
    (
        "not_started",
        False,
        ("premieres in", "live event will begin", "this live event", "is upcoming"),
    ),
    ("unsupported", False, ("unsupported url",)),
    ("format", False, ("requested format is not available", "no video formats found")),
    ("rate_limited", True, ("http error 429", "too many requests")),
    ("forbidden", False, ("http error 403", "forbidden")),
    (
        "outdated",
        False,
        (
            "please update",
            "is outdated",
            "nsig extraction failed",
            "signature extraction failed",
            "unable to extract",
            "update yt-dlp",
        ),
    ),
    (
        "network",
        True,
        (
            "unable to download",
            "timed out",
            "timeout",
            "connection reset",
            "connection refused",
            "connection aborted",
            "getaddrinfo",
            "name resolution",
            "network is unreachable",
            "temporary failure",
            "remote end closed",
            "incompleteread",
            "ssl:",
            "http error 5",
        ),
    ),
    (
        "unavailable",
        False,
        (
            "video unavailable",
            "is not available",
            "has been removed",
            "does not exist",
            "http error 404",
            "no longer available",
            "account associated with this video has been terminated",
        ),
    ),
)

UNKNOWN = ErrorInfo("unknown")
ERROR_KEYS: tuple[str, ...] = tuple(rule[0] for rule in _RULES)


def classify_error(message: str, log_lines: Iterable[str] = ()) -> ErrorInfo:
    """Clasifica un error. Mira primero el mensaje y, si no basta, las líneas del log."""
    for text in (message, "\n".join(log_lines)):
        lowered = text.lower()
        if not lowered.strip():
            continue
        for key, retryable, needles in _RULES:
            if any(needle in lowered for needle in needles):
                return ErrorInfo(key, retryable)
    return UNKNOWN
