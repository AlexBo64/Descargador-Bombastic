"""Información de versión del ``.exe`` (nombre, versión, descripción) para PyInstaller."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bombastic import APP_ID, APP_NAME, __version__  # noqa: E402

TEMPLATE = """# Generado por build/version_info.py
VSVersionInfo(
  ffi=FixedFileInfo(filevers={tuple}, prodvers={tuple}, mask=0x3f, flags=0x0, OS=0x40004,
    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('0C0A04B0', [
      StringStruct('CompanyName', '{name}'),
      StringStruct('FileDescription', '{name}: descargas con yt-dlp y edición con ffmpeg'),
      StringStruct('FileVersion', '{version}'),
      StringStruct('InternalName', '{app_id}'),
      StringStruct('OriginalFilename', '{app_id}.exe'),
      StringStruct('ProductName', '{name}'),
      StringStruct('ProductVersion', '{version}')])]),
    VarFileInfo([VarStruct('Translation', [0x0C0A, 1200])])
  ]
)
"""


def version_tuple(version: str) -> tuple[int, int, int, int]:
    parts = [int(p) for p in version.split(".")[:4] if p.isdigit()]
    while len(parts) < 4:
        parts.append(0)
    return parts[0], parts[1], parts[2], parts[3]


def render(version: str = __version__) -> str:
    return TEMPLATE.format(
        tuple=version_tuple(version), name=APP_NAME, version=version, app_id=APP_ID
    )


def main(argv: list[str]) -> int:
    target = Path(argv[1]) if len(argv) > 1 else ROOT / "out" / "version_info.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render(), encoding="utf-8")
    print(target)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
