"""Argumentos de línea de comandos: ``--edit``, ``--action`` y ``--download``.

También los usa la instancia única: la segunda instancia manda sus argumentos a la primera.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from pathlib import Path

#: Acciones de serie del menú contextual; además vale ``recipe:<nombre>``.
BUILTIN_ACTIONS: tuple[str, ...] = ("convert_mp4", "extract_mp3", "compress")


@dataclass
class AppCommand:
    #: Archivos para abrir en el editor (el primero se abre; el resto va a "Unir").
    edit: list[Path] = field(default_factory=list)
    #: Acción a aplicar a ``action_files`` (``convert_mp4``, ``recipe:Mi receta``…).
    action: str = ""
    action_files: list[Path] = field(default_factory=list)
    #: Enlaces para añadir a Descargas.
    download: list[str] = field(default_factory=list)
    #: Arrancar oculto en la bandeja (inicio con Windows).
    minimized: bool = False

    @property
    def empty(self) -> bool:
        return not (self.edit or self.action_files or self.download)


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        # No se sale del programa por un argumento raro (pueden llegar de otra instancia).
        raise ValueError(message)


def _parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="DescargadorBombastic", add_help=False)
    parser.add_argument("--edit", nargs="+", default=[])
    parser.add_argument("--action", nargs="+", default=[])
    parser.add_argument("--download", nargs="+", default=[])
    # Al iniciar con Windows: arrancar oculto en la bandeja.
    parser.add_argument("--minimized", action="store_true")
    parser.add_argument("files", nargs="*", default=[])
    return parser


def parse_command(argv: list[str]) -> AppCommand:
    """``argv`` sin el nombre del programa. Lo que no se entiende se ignora."""
    try:
        namespace, _unknown = _parser().parse_known_args(argv)
    except ValueError:
        return AppCommand()
    command = AppCommand(
        edit=[Path(p) for p in namespace.edit],
        download=[u for u in namespace.download if u.strip()],
        minimized=namespace.minimized,
    )
    if namespace.action:
        command.action = namespace.action[0]
        command.action_files = [Path(p) for p in namespace.action[1:]]
    # Archivos sueltos (por ejemplo "Abrir con…" o arrastrar sobre el .exe): al editor.
    command.edit += [Path(p) for p in namespace.files]
    return command


def command_args(command: AppCommand) -> list[str]:
    """Inverso de :func:`parse_command` (para mandarlo a la otra instancia)."""
    args: list[str] = []
    if command.edit:
        args += ["--edit", *map(str, command.edit)]
    if command.action:
        args += ["--action", command.action, *map(str, command.action_files)]
    if command.download:
        args += ["--download", *command.download]
    return args
