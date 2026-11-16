"""Genera la sección ``[Registry]`` del menú contextual para Inno Setup.

Usa :func:`bombastic.platform_win.context_menu.registry_entries`, el mismo código que la app,
así el instalador y el botón de Ajustes registran exactamente las mismas claves.
Uso: ``python build/gen_installer_registry.py out/registry.iss``.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bombastic.platform_win.context_menu import registry_entries  # noqa: E402

#: Los textos salen de [CustomMessages] del .iss, en el idioma del instalador.
LABELS = {
    "menu": "{cm:CtxMenu}",
    "edit": "{cm:CtxEdit}",
    "convert_mp4": "{cm:CtxConvert}",
    "extract_mp3": "{cm:CtxMp3}",
    "compress": "{cm:CtxCompress}",
    "recipe": "{cm:CtxRecipe}",
}
PROGRAM = '"{app}\\DescargadorBombastic.exe"'


def quote(value: str) -> str:
    """Comillas de Inno Setup: el valor entre comillas y las comillas internas duplicadas."""
    return '"' + value.replace('"', '""') + '"'


def render() -> str:
    lines = ["; Generado por build/gen_installer_registry.py: no editar a mano."]
    keys_with_delete: set[str] = set()
    for subkey, name, value in registry_entries(PROGRAM, LABELS):
        # La clave raíz del submenú se borra entera al desinstalar.
        top = subkey.split("\\shell\\")[0] + "\\shell\\DescargadorBombastic"
        flags = "uninsdeletekey" if top not in keys_with_delete else ""
        keys_with_delete.add(top)
        flag_text = f"; Flags: {flags}" if flags else ""
        lines.append(
            f"Root: HKA; Subkey: {quote(subkey)}; ValueType: string; "
            f"ValueName: {quote(name)}; ValueData: {quote(value)}; Tasks: contextmenu{flag_text}"
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    target = Path(argv[1]) if len(argv) > 1 else ROOT / "out" / "registry.iss"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render(), encoding="utf-8-sig")
    print(target)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
