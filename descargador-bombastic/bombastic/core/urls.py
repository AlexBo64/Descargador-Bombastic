"""Extracción de enlaces del texto pegado por el usuario."""

from __future__ import annotations

import re

_SCHEME = re.compile(r"^https?://", re.IGNORECASE)
#: Algo como ``youtu.be/abc`` o ``www.ejemplo.com/video``: dominio con punto y, opcionalmente, ruta.
_BARE_DOMAIN = re.compile(r"^[a-z0-9-]+(\.[a-z0-9-]+)*\.[a-z]{2,}(:\d+)?(/\S*)?$", re.IGNORECASE)
#: Signos que suelen quedar pegados al copiar un enlace de un texto.
_TRAILING = ".,;:!?)]}>\"'"
_LEADING = "([{<\"'"


def extract_urls(text: str) -> list[str]:
    """Devuelve los enlaces de ``text`` (separados por espacios o saltos de línea).

    Acepta enlaces sin ``https://`` delante, descarta lo que no parece un enlace y elimina
    los repetidos conservando el orden.
    """
    urls: list[str] = []
    seen: set[str] = set()
    for raw in text.split():
        token = raw.lstrip(_LEADING).rstrip(_TRAILING)
        if not token:
            continue
        if _SCHEME.match(token):
            # Tras el esquema tiene que haber algo.
            if len(token.split("://", 1)[1]) == 0:
                continue
            url = token
        elif "/" in token and _BARE_DOMAIN.match(token):
            url = f"https://{token}"
        else:
            continue
        if url not in seen:
            seen.add(url)
            urls.append(url)
    return urls
