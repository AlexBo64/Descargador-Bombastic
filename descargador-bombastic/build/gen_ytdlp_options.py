"""Genera ``bombastic/resources/ytdlp_options.json`` a partir de ``yt-dlp --help``.

Uso: ``python build/gen_ytdlp_options.py [ruta de yt-dlp]``. Sin argumento busca ``yt-dlp`` en
el PATH. Se ejecuta en la compilación con el mismo ``yt-dlp.exe`` que se incluye en la app.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bombastic.core.ytdlp_options import CATALOG_FILE, catalog_to_json, parse_help  # noqa: E402


def run(program: str, *args: str) -> str:
    result = subprocess.run(
        [program, *args], capture_output=True, check=True, encoding="utf-8", errors="replace"
    )
    return result.stdout


def main(argv: list[str]) -> int:
    program = argv[1] if len(argv) > 1 else shutil.which("yt-dlp")
    if not program:
        print("No se encuentra yt-dlp: pasa su ruta como argumento.", file=sys.stderr)
        return 1
    version = run(program, "--version").strip()
    options = parse_help(run(program, "--help"))
    target = ROOT / "bombastic" / "resources" / CATALOG_FILE
    target.write_text(catalog_to_json(options, version), encoding="utf-8")
    print(f"{len(options)} opciones de yt-dlp {version}: {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
