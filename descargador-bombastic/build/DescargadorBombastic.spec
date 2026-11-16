# PyInstaller, modo --onedir (arranca más rápido y da menos falsos positivos que --onefile).
# Uso: pyinstaller build/DescargadorBombastic.spec --distpath out/dist --workpath out/work
# Antes: python build/version_info.py out/version_info.txt
# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

ROOT = Path(SPECPATH).parent  # noqa: F821 (lo define PyInstaller)

a = Analysis(  # noqa: F821
    [str(ROOT / "bombastic" / "__main__.py")],
    pathex=[str(ROOT)],
    datas=[(str(ROOT / "bombastic" / "resources"), "bombastic/resources")],
    hiddenimports=["PySide6.QtSvg", "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets"],
    excludes=["tkinter", "PySide6.QtWebEngineCore", "PySide6.QtQuick", "PySide6.Qt3DCore"],
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821
exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="DescargadorBombastic",
    console=False,
    icon=str(ROOT / "bombastic" / "resources" / "icons" / "app.ico"),
    version=str(ROOT / "out" / "version_info.txt"),
    upx=False,  # UPX dispara más falsos positivos del antivirus
)
coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="DescargadorBombastic",
)
