<#
.SYNOPSIS
  Compila Descargador Bombastic: instalador y zip portable.

.DESCRIPTION
  1. Crea .venv-build con Python 3.12 e instala las dependencias fijadas.
  2. Descarga y verifica (SHA-256) yt-dlp y ffmpeg en out\bin y, con ese yt-dlp, genera el
     catálogo de opciones; además el icono, la versión del .exe y el registro del instalador.
  3. Ejecuta ruff, mypy y los tests.
  4. PyInstaller (--onedir) en out\dist.
  6. Firma opcional con signtool (si se define $env:SIGN_CERT_FILE).
  7. Instalador con Inno Setup 6 y zip portable en out\release.

  Las traducciones no se compilan: son catálogos JSON (ver docs\ARQUITECTURA.md).

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File build\build.ps1
#>
[CmdletBinding()]
param(
    [switch]$SkipTests,
    [string]$Python = "py -3.12"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$Out = Join-Path $Root "out"
New-Item -ItemType Directory -Force $Out | Out-Null

function Run([string]$Command) {
    Write-Host "> $Command" -ForegroundColor Cyan
    & cmd /c $Command
    if ($LASTEXITCODE -ne 0) { throw "Ha fallado: $Command" }
}

# 1. Entorno
$Venv = Join-Path $Root ".venv-build"
if (-not (Test-Path $Venv)) { Run "$Python -m venv `"$Venv`"" }
$Py = Join-Path $Venv "Scripts\python.exe"
Run "`"$Py`" -m pip install --upgrade pip"
Run "`"$Py`" -m pip install -r requirements-dev.txt -r requirements-build.txt"

# 2. Recursos generados
$Version = (& $Py -c "import bombastic; print(bombastic.__version__)").Trim()
Write-Host "Versión $Version"
$env:QT_QPA_PLATFORM = "offscreen"
Run "`"$Py`" build\fetch_binaries.py out\bin"
Run "`"$Py`" build\gen_ytdlp_options.py out\bin\yt-dlp.exe"
Run "`"$Py`" build\make_icon.py"
Run "`"$Py`" build\version_info.py out\version_info.txt"
Run "`"$Py`" build\gen_installer_registry.py out\registry.iss"

# 3. Calidad
if (-not $SkipTests) {
    Run "`"$Py`" -m ruff check ."
    Run "`"$Py`" -m ruff format --check ."
    Run "`"$Py`" -m mypy"
    Run "`"$Py`" -m pytest -q"
}

# 4. PyInstaller
Run "`"$Py`" -m PyInstaller build\DescargadorBombastic.spec --noconfirm --distpath out\dist --workpath out\work"
$Dist = Join-Path $Out "dist\DescargadorBombastic"

# 6. Firma de código opcional (sin firma, SmartScreen avisa: ver README)
function Sign([string]$File) {
    if (-not $env:SIGN_CERT_FILE) { return }
    $signtool = (Get-Command signtool.exe -ErrorAction SilentlyContinue).Source
    if (-not $signtool) { throw "SIGN_CERT_FILE definido pero no se encuentra signtool.exe" }
    & $signtool sign /f $env:SIGN_CERT_FILE /p $env:SIGN_CERT_PASSWORD /fd sha256 /tr http://timestamp.digicert.com /td sha256 $File
    if ($LASTEXITCODE -ne 0) { throw "No se ha podido firmar $File" }
}
Sign (Join-Path $Dist "DescargadorBombastic.exe")

# 7a. Instalador
$Release = Join-Path $Out "release"
New-Item -ItemType Directory -Force $Release | Out-Null
$Iscc = @(
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $Iscc) { throw "No se encuentra Inno Setup 6 (ISCC.exe). Instálalo: winget install JRSoftware.InnoSetup" }
Run "`"$Iscc`" /DAppVersion=$Version build\installer.iss"
$Setup = Join-Path $Out "installer\DescargadorBombastic-Setup-$Version.exe"
Sign $Setup
Copy-Item $Setup $Release -Force

# 7b. Portable: la carpeta onedir + bin + portable.flag
$Portable = Join-Path $Out "portable\DescargadorBombastic"
if (Test-Path $Portable) { Remove-Item -Recurse -Force $Portable }
New-Item -ItemType Directory -Force $Portable | Out-Null
Copy-Item -Recurse "$Dist\*" $Portable
New-Item -ItemType Directory -Force "$Portable\bin" | Out-Null
Copy-Item "$Out\bin\*.exe", "$Out\bin\SOURCES.txt" "$Portable\bin"
Copy-Item THIRD_PARTY_LICENSES.txt $Portable
New-Item -ItemType File -Force "$Portable\portable.flag" | Out-Null
$Zip = Join-Path $Release "DescargadorBombastic-Portable-$Version.zip"
if (Test-Path $Zip) { Remove-Item $Zip }
Compress-Archive -Path $Portable -DestinationPath $Zip

Get-ChildItem $Release | ForEach-Object {
    $hash = (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLower()
    "$hash  $($_.Name)"
} | Set-Content (Join-Path $Release "SHA256SUMS.txt") -Encoding ascii
Write-Host "Listo: $Release" -ForegroundColor Green
