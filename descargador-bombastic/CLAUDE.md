# Descargador Bombastic

App de escritorio para Windows 10/11 (Python 3.12 + PySide6) que pone interfaz gráfica a yt-dlp
y ffmpeg. Se construye por fases.

- Especificación completa: `docs/ESPECIFICACION.md` (léela antes de empezar una fase).
- Arquitectura, decisiones y riesgos: `docs/ARQUITECTURA.md`.
- Estado actual y lo hecho en cada fase: `CHANGELOG.md` y la hoja de ruta del `README.md`.
- Para empezar una fase usa la skill `/nueva-fase`.

## Comandos

```powershell
.venv\Scripts\Activate.ps1
python -m bombastic            # arrancar la app
ruff check . ; ruff format .   # lint y formato
mypy                           # tipos (modo estricto)
python -m pytest               # tests
```

Una fase no está terminada hasta que `ruff check .`, `ruff format --check .`, `mypy` y
`python -m pytest` pasan sin errores.

## Reglas del proyecto

- `bombastic/core/` no importa Qt Widgets. Solo QtCore donde haga falta (`QProcess`, señales).
  Todo lo de `core` se testea sin abrir ventanas.
- Nunca bloquear el hilo de la interfaz: los procesos externos van con `QProcess` o `QThreadPool`
  y se comunican por señales.
- Los comandos de yt-dlp y ffmpeg se construyen siempre como lista de argumentos, nunca
  concatenando cadenas para la shell.
- yt-dlp, ffmpeg y ffprobe son ejecutables externos; no se importa `yt_dlp` en tiempo de ejecución.
- Ningún texto visible fijo en el código: todo pasa por `tr("clave")` y se añade la clave a
  `bombastic/resources/i18n/es.json` y `en.json` (un test falla si no coinciden).
- Cada página implementa `retranslate()` para el cambio de idioma en caliente.
- Colores solo mediante los marcadores de `resources/styles/app.qss` y las paletas de
  `ui/theme.py`; si añades un color, añádelo a las dos paletas.
- Nombres de variables y funciones en inglés; docstrings y comentarios en español.
- Código completo: nada de "resto igual" ni TODO sin explicar.
- Código específico de Windows solo en `bombastic/platform_win/`. Los tests deben pasar también
  en Linux (CI y desarrollo), usando procesos falsos en vez de binarios reales.
- No generar el `.exe` fuera de Windows.

## Desviaciones acordadas respecto a la especificación

- Traducciones en catálogos JSON propios, no `.ts/.qm` de Qt.
- El código vive dentro del paquete `bombastic/` (`bombastic/core`, `bombastic/ui`…).
- La salida de PyInstaller irá a `out/`; `build/` queda para los scripts.
- Plantilla de progreso de yt-dlp: se usa la conversión `j`, pero los campos sin valor siguen
  saliendo como `NA` sin comillas; `core/ytdlp_progress.py` los convierte en `null`.

## Notas verificadas

- yt-dlp necesita Deno para YouTube: se trata como una dependencia más (`deno.exe` en `bin\`
  o en el PATH).
- `yt-dlp.exe` se relanza a sí mismo como proceso hijo: cancelar exige matar el árbol
  (`platform_win/process.py`).
- Tests: `tests/fake_ytdlp.py` imita la salida de yt-dlp; nunca se usan binarios reales.
