"""Modo experto y recetas: comandos de ffmpeg escritos a mano con variables.

Un comando es texto con variables entre llaves que se sustituyen al ejecutar:
``{input}``, ``{inputs[1]}``, ``{output}``, ``{start}``, ``{end}``, ``{dir}``, ``{name}`` y los
parámetros propios de cada receta (``{crf}``…). El texto se separa en argumentos *antes* de
sustituir, así que una ruta con espacios sigue siendo un único argumento.
"""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from bombastic.core.db import Database, now_iso
from bombastic.core.ffmpeg_command import COMMON, EditPlan
from bombastic.core.formatting import format_timecode
from bombastic.core.ytdlp_options import ExtraArgsError, split_extra_args

_VARIABLE = re.compile(r"\{([a-z_][a-z0-9_]*)(?:\[(\d+)\])?\}")
BUILTIN_VARIABLES: tuple[str, ...] = (
    "input",
    "inputs[1]",
    "output",
    "start",
    "end",
    "dir",
    "name",
)
#: Opciones que el modo experto ya pone o que romperían el progreso.
_MANAGED = frozenset({"-progress", "-nostats", "-hide_banner", "-nostdin", "-y"})


class RecipeError(ValueError):
    """El comando no se puede preparar. ``key`` es el mensaje (``expert.error.*``)."""

    def __init__(self, key: str, detail: str = "") -> None:
        super().__init__(f"{key}: {detail}")
        self.key = key
        self.detail = detail


def variables_for(
    inputs: Sequence[Path],
    output: Path,
    start: float | None = None,
    end: float | None = None,
) -> dict[str, str | list[str]]:
    first = inputs[0] if inputs else None
    return {
        "input": str(first) if first else "",
        "inputs": [str(p) for p in inputs],
        "output": str(output),
        "start": format_timecode(start or 0.0),
        "end": format_timecode(end) if end is not None else "",
        "dir": str(first.parent) if first else "",
        "name": first.stem if first else "",
    }


def substitute(arg: str, variables: Mapping[str, str | list[str]]) -> str:
    """Sustituye las variables de un argumento. Lanza :class:`RecipeError` si falta alguna."""

    def repl(match: re.Match[str]) -> str:
        name, index = match.group(1), match.group(2)
        value = variables.get(name)
        if value is None:
            raise RecipeError("expert.error.unknown_variable", match.group(0))
        if index is not None:
            if not isinstance(value, list) or int(index) >= len(value):
                raise RecipeError("expert.error.missing_input", match.group(0))
            return value[int(index)]
        if isinstance(value, list):
            return value[0] if value else ""
        if not value:
            raise RecipeError("expert.error.empty_variable", match.group(0))
        return value

    return _VARIABLE.sub(repl, arg)


def parse_template(text: str) -> list[str]:
    """Separa el comando en argumentos (sin sustituir). Quita un ``ffmpeg`` inicial."""
    try:
        args = split_extra_args(text.replace("\r", " ").replace("\n", " "))
    except ExtraArgsError as exc:
        raise RecipeError("expert.error.quotes", str(exc)) from exc
    if args and Path(args[0]).stem.lower() == "ffmpeg":
        args = args[1:]
    if not args:
        raise RecipeError("expert.error.empty")
    return args


def template_variables(text: str) -> list[str]:
    """Variables propias (no las de serie) que aparecen en el comando, en orden."""
    seen: list[str] = []
    for match in _VARIABLE.finditer(text):
        name = match.group(1)
        builtin = {"input", "inputs", "output", "start", "end", "dir", "name"}
        if name not in builtin and name not in seen:
            seen.append(name)
    return seen


def build_expert_plan(
    template: str,
    inputs: Sequence[Path],
    output: Path,
    duration: float | None,
    params: Mapping[str, str] | None = None,
    start: float | None = None,
    end: float | None = None,
) -> EditPlan:
    """Plan de una pasada a partir del comando escrito a mano."""
    variables: dict[str, str | list[str]] = dict(params or {})
    variables.update(variables_for(inputs, output, start, end))
    args = [substitute(arg, variables) for arg in parse_template(template)]
    args = [a for a in args if a not in _MANAGED]
    if str(output) not in args:
        raise RecipeError("expert.error.no_output")
    return EditPlan("expert", ((*COMMON, *args),), output, duration, tuple(inputs))


def plan_to_template(plan: EditPlan) -> str:
    """El comando de un plan como texto con variables ("Abrir en modo experto").

    shortcut: usa las comillas de Windows (``list2cmdline``); un argumento con comillas
    dobles dentro no vuelve idéntico, mejorar si alguna herramienta llega a generarlo.
    """
    args = list(plan.passes[-1])[len(COMMON) :]
    replacements = {str(plan.output): "{output}"}
    for index, source in enumerate(plan.inputs):
        replacements[str(source)] = "{input}" if index == 0 else f"{{inputs[{index}]}}"
    text = [replacements.get(arg, arg) for arg in args]
    return subprocess.list2cmdline(text)


# ------------------------------------------------------------------- recetas


@dataclass
class Recipe:
    name: str
    command: str
    description: str = ""
    #: Parámetros propios con su valor por defecto (``{"crf": "23"}``).
    params: dict[str, str] = field(default_factory=dict)
    #: Extensión del archivo de salida (``mp4``…).
    output_ext: str = "mp4"
    favorite: bool = False
    recipe_id: int = 0

    def to_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "command": self.command,
            "description": self.description,
            "params": dict(self.params),
            "output_ext": self.output_ext,
            "favorite": self.favorite,
        }

    @classmethod
    def from_json(cls, data: Any) -> Recipe:
        if not isinstance(data, dict) or not isinstance(data.get("name"), str):
            raise RecipeError("expert.error.bad_file")
        command = data.get("command")
        if not isinstance(command, str) or not command.strip():
            raise RecipeError("expert.error.bad_file")
        params: dict[str, Any] = data["params"] if isinstance(data.get("params"), dict) else {}
        return cls(
            name=data["name"].strip() or "?",
            command=command,
            description=str(data.get("description") or ""),
            params={str(k): str(v) for k, v in params.items()},
            output_ext=str(data.get("output_ext") or "mp4").lstrip("."),
            favorite=data.get("favorite") is True,
        )


def parse_params(text: str) -> dict[str, str]:
    """``"crf=23, preset=slow"`` → ``{"crf": "23", "preset": "slow"}``."""
    params: dict[str, str] = {}
    for part in re.split(r"[,\n;]", text):
        key, sep, value = part.partition("=")
        if sep and re.fullmatch(r"[a-z_][a-z0-9_]*", key.strip()):
            params[key.strip()] = value.strip()
    return params


class RecipeStore:
    """Recetas guardadas en SQLite. Los nombres no se repiten."""

    def __init__(self, db: Database | None) -> None:
        self._db = db
        self._memory: dict[int, Recipe] = {}
        self._next_id = 1

    def all(self) -> list[Recipe]:
        if self._db is None:
            return sorted(self._memory.values(), key=lambda r: r.name.lower())
        rows = self._db.query("SELECT * FROM recipes ORDER BY name COLLATE NOCASE")
        return [self._from_row(row) for row in rows]

    def favorites(self) -> list[Recipe]:
        return [r for r in self.all() if r.favorite]

    def get(self, recipe_id: int) -> Recipe | None:
        return next((r for r in self.all() if r.recipe_id == recipe_id), None)

    def by_name(self, name: str) -> Recipe | None:
        return next((r for r in self.all() if r.name.lower() == name.lower()), None)

    def save(self, recipe: Recipe) -> Recipe:
        """Crea o actualiza (por id). Si el nombre ya lo usa otra receta, le añade un número."""
        recipe.name = self._unique_name(recipe.name.strip() or "?", recipe.recipe_id)
        if self._db is None:
            if not recipe.recipe_id:
                recipe.recipe_id = self._next_id
                self._next_id += 1
            self._memory[recipe.recipe_id] = recipe
            return recipe
        values = (
            recipe.name,
            recipe.description,
            recipe.command,
            json.dumps(recipe.params, ensure_ascii=False),
            recipe.output_ext,
            int(recipe.favorite),
        )
        if recipe.recipe_id:
            self._db.execute(
                "UPDATE recipes SET name=?, description=?, command=?, params=?, output_ext=?,"
                " favorite=? WHERE id=?",
                (*values, recipe.recipe_id),
            )
        else:
            cursor = self._db.execute(
                "INSERT INTO recipes (name, description, command, params, output_ext, favorite,"
                " created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (*values, now_iso()),
            )
            recipe.recipe_id = int(cursor.lastrowid or 0)
        return recipe

    def delete(self, recipe_id: int) -> None:
        if self._db is None:
            self._memory.pop(recipe_id, None)
        else:
            self._db.execute("DELETE FROM recipes WHERE id = ?", (recipe_id,))

    def export_json(self, recipes: Sequence[Recipe]) -> str:
        return json.dumps({"recipes": [r.to_json() for r in recipes]}, ensure_ascii=False, indent=2)

    def import_json(self, text: str) -> list[Recipe]:
        try:
            data = json.loads(text)
        except ValueError as exc:
            raise RecipeError("expert.error.bad_file") from exc
        items = data.get("recipes") if isinstance(data, dict) else data
        if not isinstance(items, list):
            raise RecipeError("expert.error.bad_file")
        recipes = [Recipe.from_json(item) for item in items]
        return [self.save(recipe) for recipe in recipes]

    def _unique_name(self, name: str, own_id: int) -> str:
        taken = {r.name.lower() for r in self.all() if r.recipe_id != own_id}
        if name.lower() not in taken:
            return name
        # "Receta (2)" repetida pasa a "Receta (3)", no a "Receta (2) (2)".
        name = re.sub(r" \(\d+\)$", "", name)
        candidate, counter = name, 2
        while candidate.lower() in taken:
            candidate = f"{name} ({counter})"
            counter += 1
        return candidate

    @staticmethod
    def _from_row(row: Any) -> Recipe:
        try:
            params = json.loads(row["params"]) if row["params"] else {}
        except ValueError:
            params = {}
        return Recipe(
            name=row["name"],
            command=row["command"],
            description=row["description"],
            params={str(k): str(v) for k, v in params.items()} if isinstance(params, dict) else {},
            output_ext=row["output_ext"],
            favorite=bool(row["favorite"]),
            recipe_id=int(row["id"]),
        )


# ------------------------------------------------------------ filtros de ffmpeg

_FILTER_LINE = re.compile(r"^\s*[TSC.|]{2,3}\s+(\S+)\s+(\S+->\S+)\s+(.*)$")


@dataclass(frozen=True)
class FilterInfo:
    name: str
    #: ``V->V``, ``A->A``…
    io: str
    description: str


def parse_filters(text: str) -> list[FilterInfo]:
    """Lista de ``ffmpeg -filters``."""
    result: list[FilterInfo] = []
    for line in text.splitlines():
        match = _FILTER_LINE.match(line)
        if match:
            result.append(FilterInfo(match.group(1), match.group(2), match.group(3).strip()))
    return result


#: Opciones de ffmpeg habituales para el autocompletado del modo experto.
COMMON_OPTIONS: tuple[str, ...] = (
    "-i", "-c", "-c:v", "-c:a", "-c:s", "-map", "-vf", "-af", "-filter_complex", "-ss", "-to",
    "-t", "-crf", "-preset", "-b:v", "-b:a", "-r", "-s", "-ar", "-ac", "-an", "-vn", "-sn",
    "-pix_fmt", "-movflags", "-metadata", "-shortest", "-f", "-frames:v", "-q:a", "-tune",
    "-profile:v", "-g", "-maxrate", "-bufsize", "libx264", "libx265", "libvpx-vp9", "libsvtav1",
    "aac", "libmp3lame", "libopus", "flac", "copy", "+faststart", "yuv420p",
)  # fmt: skip
