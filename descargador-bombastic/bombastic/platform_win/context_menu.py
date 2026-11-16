"""Menú contextual del Explorador para archivos de vídeo y audio.

Se registra en ``HKCU\\Software\\Classes\\SystemFileAssociations\\<ext>\\shell\\…``, así que no
hace falta ser administrador. En Windows 11 aparece en "Mostrar más opciones": el menú moderno
exige un ``IExplorerCommand`` con paquete MSIX disperso, que queda fuera de esta versión.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Sequence
from pathlib import Path

log = logging.getLogger(__name__)

MEDIA_EXTENSIONS: tuple[str, ...] = (
    ".mp4", ".mkv", ".webm", ".mov", ".avi", ".m4v", ".wmv", ".flv", ".ts", ".mpg",
    ".mp3", ".m4a", ".wav", ".flac", ".opus", ".ogg", ".aac", ".wma",
)  # fmt: skip
ROOT = r"Software\Classes\SystemFileAssociations"
MENU_KEY = "DescargadorBombastic"

#: Entrada del registro: ``(subclave relativa a HKCU, nombre del valor, valor)``.
Entry = tuple[str, str, str]


def launch_command() -> str:
    """Programa a ejecutar: el ``.exe`` empaquetado o ``pythonw -m bombastic`` en desarrollo."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    interpreter = pythonw if pythonw.is_file() else Path(sys.executable)
    return f'"{interpreter}" -m bombastic'


def registry_entries(
    program: str, labels: dict[str, str], favorites: Sequence[str] = ()
) -> list[Entry]:
    """Todas las claves y valores del submenú, para cada extensión.

    ``labels`` lleva los textos ya traducidos: ``menu``, ``edit``, ``convert_mp4``,
    ``extract_mp3``, ``compress`` y ``recipe`` (con ``{name}``).
    """
    commands = [
        ("1_edit", labels["edit"], f'{program} --edit "%1"'),
        ("2_convert", labels["convert_mp4"], f'{program} --action convert_mp4 "%1"'),
        ("3_mp3", labels["extract_mp3"], f'{program} --action extract_mp3 "%1"'),
        ("4_compress", labels["compress"], f'{program} --action compress "%1"'),
    ]
    for index, name in enumerate(favorites, start=5):
        # Comillas dobles en el nombre romperían la línea de comandos: se quitan.
        clean = name.replace('"', "")
        label = labels["recipe"].replace("{name}", clean)
        commands.append((f"{index}_recipe", label, f'{program} --action "recipe:{clean}" "%1"'))
    entries: list[Entry] = []
    for ext in MEDIA_EXTENSIONS:
        base = rf"{ROOT}\{ext}\shell\{MENU_KEY}"
        entries.append((base, "MUIVerb", labels["menu"]))
        entries.append((base, "SubCommands", ""))
        for key, label, command in commands:
            entries.append((rf"{base}\shell\{key}", "", label))
            entries.append((rf"{base}\shell\{key}\command", "", command))
    return entries


def register(entries: list[Entry]) -> bool:
    """Escribe las entradas. Borra antes el menú anterior (para quitar recetas que ya no son)."""
    if sys.platform != "win32":
        return False
    import winreg

    unregister()
    try:
        for subkey, name, value in entries:
            with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, subkey) as key:
                winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
    except OSError:
        log.exception("Could not register the Explorer context menu")
        return False
    return True


def _delete_tree(path: str) -> None:
    """Borra una clave de HKCU con todas sus subclaves (winreg no lo hace solo)."""
    if sys.platform != "win32":
        return
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_ALL_ACCESS) as key:
            children: list[str] = []
            index = 0
            while True:
                try:
                    children.append(winreg.EnumKey(key, index))
                except OSError:
                    break
                index += 1
        for child in children:
            _delete_tree(rf"{path}\{child}")
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)
    except FileNotFoundError:
        return


def unregister() -> bool:
    """Quita el submenú de todas las extensiones (lo usa también el desinstalador)."""
    if sys.platform != "win32":
        return False
    for ext in MEDIA_EXTENSIONS:
        try:
            _delete_tree(rf"{ROOT}\{ext}\shell\{MENU_KEY}")
        except OSError:
            log.exception("Could not remove the context menu for %s", ext)
            return False
    return True


def is_registered() -> bool:
    if sys.platform != "win32":
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, rf"{ROOT}\.mp4\shell\{MENU_KEY}"):
            return True
    except OSError:
        return False
