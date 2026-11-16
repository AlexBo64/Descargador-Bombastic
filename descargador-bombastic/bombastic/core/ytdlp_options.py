"""Catálogo de opciones de yt-dlp para el modo avanzado.

El catálogo se obtiene parseando ``yt-dlp --help``: en la compilación (``build/
gen_ytdlp_options.py`` genera ``resources/ytdlp_options.json``) y en tiempo de ejecución, tras
actualizar yt-dlp, para que las opciones nuevas aparezcan sin recompilar. Si el parseo falla se
usa el JSON incluido.
"""

from __future__ import annotations

import json
import logging
import re
import shlex
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

CATALOG_FILE = "ytdlp_options.json"

_GROUP = re.compile(r"^  (\S.*):\s*$")
_OPTION = re.compile(r"^    (-\S.*)$")
_CONTINUATION = re.compile(r"^ {20,}(\S.*)$")
#: Separación entre "flags metavar" y la ayuda: dos o más espacios.
_HELP_SPLIT = re.compile(r"\s{2,}")
_PATH_HINT = re.compile(r"\b(FILE|PATH|DIR|LOCATION)\b")
#: Grupos que no se muestran: los alias de presets (``-t mp3``) chocan con los del modo simple.
HIDDEN_GROUPS = frozenset({"Preset Aliases"})

#: Opciones que la app controla o que romperían su lectura de la salida de yt-dlp.
HIDDEN_FLAGS = frozenset(
    {
        "--help",
        "--version",
        "--update",
        "--no-update",
        "--update-to",
        "--newline",
        "--no-progress",
        "--progress",
        "--progress-template",
        "--console-title",
        "--print",
        "--quiet",
        "--no-quiet",
        "--simulate",
        "--no-simulate",
        "--dump-json",
        "--dump-single-json",
        "--print-json",
        "--list-extractors",
        "--extractor-descriptions",
        "--list-formats",
        "--list-subs",
        "--list-thumbnails",
        "--list-impersonate-targets",
        "--encoding",
        "--no-colors",
        "--color",
        "--get-url",
        "--get-title",
        "--get-id",
        "--get-thumbnail",
        "--get-description",
        "--get-duration",
        "--get-filename",
        "--get-format",
    }
)


class HelpParseError(ValueError):
    """La salida de ``--help`` no tiene el formato esperado."""


@dataclass(frozen=True)
class YtdlpOption:
    group: str
    #: Todos los flags, el largo primero si existe (``--format``, ``-f``).
    flags: tuple[str, ...]
    #: Nombre del argumento (``FORMAT``, ``FILE``…); vacío si es una casilla.
    metavar: str
    help: str

    @property
    def key(self) -> str:
        """Flag que identifica la opción (el largo si lo hay)."""
        return self.flags[0]

    @property
    def takes_value(self) -> bool:
        return bool(self.metavar)

    @property
    def kind(self) -> str:
        """``flag``, ``path`` o ``text``: el tipo de control de la interfaz."""
        if not self.metavar:
            return "flag"
        return "path" if _PATH_HINT.search(self.metavar.upper()) else "text"


def _split_flags(spec: str) -> tuple[tuple[str, ...], str]:
    """``"-o, --output [TYPES:]TEMPLATE"`` → ``(("--output", "-o"), "[TYPES:]TEMPLATE")``."""
    parts = spec.split(", ")
    flags: list[str] = []
    metavar = ""
    for index, part in enumerate(parts):
        flag, _, rest = part.partition(" ")
        if not flag.startswith("-"):
            # Comas dentro del metavar: forma parte de él.
            metavar = ", ".join(parts[index:])
            break
        flags.append(flag)
        if rest:
            metavar = ", ".join([rest, *parts[index + 1 :]])
            break
    longs = [f for f in flags if f.startswith("--")]
    shorts = [f for f in flags if not f.startswith("--")]
    return tuple(longs + shorts), metavar.strip()


def parse_help(text: str) -> list[YtdlpOption]:
    """Convierte la salida de ``yt-dlp --help`` en opciones. Lanza :class:`HelpParseError`."""
    options: list[YtdlpOption] = []
    group = ""
    current: dict[str, Any] | None = None

    def flush() -> None:
        if current is not None:
            options.append(
                YtdlpOption(
                    group=current["group"],
                    flags=current["flags"],
                    metavar=current["metavar"],
                    help=" ".join(current["help"]).strip(),
                )
            )

    for raw in text.splitlines():
        line = raw.rstrip()
        group_match = _GROUP.match(line)
        if group_match and not line.startswith("    "):
            flush()
            current = None
            group = group_match.group(1)
            continue
        option_match = _OPTION.match(line)
        if option_match and group:
            flush()
            spec, *help_parts = _HELP_SPLIT.split(option_match.group(1), maxsplit=1)
            flags, metavar = _split_flags(spec)
            current = {"group": group, "flags": flags, "metavar": metavar, "help": help_parts}
            continue
        continuation = _CONTINUATION.match(line)
        if continuation and current is not None:
            current["help"].append(continuation.group(1))
    flush()
    if len(options) < 50 or len({o.group for o in options}) < 5:
        raise HelpParseError(f"only {len(options)} options found")
    return options


def visible_options(options: list[YtdlpOption]) -> list[YtdlpOption]:
    """Las que tiene sentido mostrar en la interfaz."""
    return [
        o
        for o in options
        if o.group not in HIDDEN_GROUPS and not HIDDEN_FLAGS.intersection(o.flags)
    ]


# ----------------------------------------------------------------- archivo JSON


def catalog_to_json(options: list[YtdlpOption], version: str) -> str:
    data = {"version": version, "options": [asdict(o) for o in options]}
    return json.dumps(data, ensure_ascii=False, indent=1) + "\n"


def catalog_from_json(text: str) -> tuple[str, list[YtdlpOption]]:
    data = json.loads(text)
    options = [
        YtdlpOption(o["group"], tuple(o["flags"]), o["metavar"], o["help"]) for o in data["options"]
    ]
    return str(data.get("version", "")), options


def load_catalog(data_dir: Path, bundled_dir: Path) -> tuple[str, list[YtdlpOption]]:
    """El catálogo regenerado en la carpeta de datos o, si no hay o está roto, el incluido."""
    for folder in (data_dir, bundled_dir):
        path = folder / CATALOG_FILE
        try:
            return catalog_from_json(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            continue
        except (OSError, ValueError, KeyError, TypeError):
            log.exception("Ignoring broken option catalog %s", path)
    return "", []


def save_catalog(data_dir: Path, help_text: str, version: str) -> list[YtdlpOption]:
    """Parsea ``--help`` y guarda el catálogo en la carpeta de datos. Lanza si no se entiende."""
    options = parse_help(help_text)
    data_dir.mkdir(parents=True, exist_ok=True)
    target = data_dir / CATALOG_FILE
    tmp = target.with_suffix(".tmp")
    tmp.write_text(catalog_to_json(options, version), encoding="utf-8")
    tmp.replace(target)
    return options


def load_help_translations(resources: Path) -> tuple[dict[str, str], dict[str, str]]:
    """Nombres de grupo y ayudas en español: ``(grupos, opciones)``. Vacíos si falta el archivo."""
    try:
        data = json.loads((resources / "ytdlp_help_es.json").read_text(encoding="utf-8"))
        return dict(data["groups"]), dict(data["options"])
    except (OSError, ValueError, KeyError, TypeError):
        log.exception("Could not load the Spanish yt-dlp help")
        return {}, {}


# ------------------------------------------------------------------ argumentos


class ExtraArgsError(ValueError):
    """Los argumentos libres tienen comillas sin cerrar."""


def split_extra_args(text: str) -> list[str]:
    """Separa los argumentos escritos a mano respetando comillas.

    Las barras invertidas se dejan tal cual, para que las rutas de Windows funcionen.
    """
    lexer = shlex.shlex(text, posix=True)
    lexer.whitespace_split = True
    lexer.escape = ""
    lexer.commenters = ""
    try:
        return list(lexer)
    except ValueError as exc:
        raise ExtraArgsError(str(exc)) from exc


def build_advanced_args(options: list[YtdlpOption], values: Mapping[str, object]) -> list[str]:
    """Argumentos de las opciones del modo avanzado que tienen valor.

    ``values`` va de :attr:`YtdlpOption.key` a ``True`` (casillas) o a un texto.
    """
    args: list[str] = []
    for option in options:
        value = values.get(option.key)
        if option.takes_value:
            if isinstance(value, str) and value.strip():
                args += [option.key, value.strip()]
        elif value is True:
            args.append(option.key)
    return args


_AUDIO_ONLY = ("-x", "--extract-audio")


def find_conflicts(args: list[str], audio_preset: bool, ffmpeg_found: bool) -> list[str]:
    """Claves de aviso (``downloads.conflict.<clave>``) para combinaciones problemáticas."""
    conflicts: list[str] = []
    extracting = audio_preset or any(a in _AUDIO_ONLY for a in args)
    if extracting and not ffmpeg_found:
        conflicts.append("extract_without_ffmpeg")
    if extracting and "--merge-output-format" in args:
        conflicts.append("merge_with_audio")
    if any(a in ("-o", "--output", "-P", "--paths") for a in args):
        conflicts.append("output_overridden")
    if any(a in ("-f", "--format") for a in args):
        conflicts.append("format_overridden")
    return conflicts
