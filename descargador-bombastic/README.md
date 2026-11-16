# Descargador Bombastic

Aplicación de escritorio para Windows 10/11 que pone una interfaz gráfica a
[yt-dlp](https://github.com/yt-dlp/yt-dlp) (descargas) y a [ffmpeg](https://ffmpeg.org) (edición
de vídeo y audio).

> **Estado: Fase 0 (esqueleto).** La ventana, los temas, los idiomas, los ajustes, los logs y la
> detección de dependencias funcionan. Todavía **no descarga ni edita**: eso llega en las fases 1
> a 7. Tampoco hay instalador (Fase 10).

## Probarlo en Windows (desarrollo)

Requiere [Python 3.12](https://www.python.org/downloads/) de 64 bits. En PowerShell, dentro de la
carpeta del proyecto:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
python -m bombastic
```

Qué comprobar:

1. Se abre la ventana con seis secciones; `Ctrl+1` … `Ctrl+6` cambia entre ellas.
2. En **Ajustes**, cambia el idioma y el tema: se aplican al momento y se conservan al reabrir.
3. En **Ajustes → Dependencias** aparece la versión de `yt-dlp`, `ffmpeg` y `ffprobe` si están en
   el PATH o en la carpeta de binarios ("Abrir carpeta de binarios" y copia ahí los `.exe`).
4. "Abrir carpeta de logs" abre `%LOCALAPPDATA%\DescargadorBombastic\logs`.

### Modo portable

Crea un archivo vacío `portable.flag` junto al ejecutable (en desarrollo, en la raíz del
proyecto). Los datos se guardan entonces en la carpeta `data\` de al lado.

## Tests y calidad

```powershell
ruff check .
ruff format --check .
mypy
python -m pytest
```

El workflow `.github/workflows/ci.yml` ejecuta lo mismo en `windows-latest` en cada push.

## Estructura

```
bombastic/
  app.py            arranque
  context.py        objetos compartidos (rutas, ajustes, traductor, tema)
  core/             lógica sin widgets (rutas, ajustes, logs, i18n, binarios)
  ui/               ventana principal, páginas, temas
  platform_win/     integración con Windows (Fase 9)
  resources/        iconos SVG, app.qss, i18n/es.json, i18n/en.json
tests/
docs/ARQUITECTURA.md      arquitectura y riesgos
docs/ESPECIFICACION.md    especificación completa del proyecto
CLAUDE.md                 contexto y reglas para Claude Code
.claude/skills/nueva-fase skill para construir cada fase
```

Más detalle, decisiones y riesgos en [docs/ARQUITECTURA.md](docs/ARQUITECTURA.md).

## Añadir o cambiar textos

Todos los textos están en `bombastic/resources/i18n/es.json` y `en.json` con la misma clave.
En el código se usan con `tr("clave")`. Un test falla si a un idioma le falta una clave.

## Hoja de ruta

| Fase | Contenido | Estado |
|---|---|---|
| 0 | Esqueleto | Hecha |
| 1 | MVP de descarga | Pendiente |
| 2 | Cola | Pendiente |
| 3 | Modo avanzado de yt-dlp | Pendiente |
| 4 | Editor básico | Pendiente |
| 5 | Editor completo | Pendiente |
| 6 | Modo experto y recetas | Pendiente |
| 7 | Perfiles, historial y encadenado | Pendiente |
| 8 | Actualizaciones | Pendiente |
| 9 | Integración con Windows | Pendiente |
| 10 | Distribución (instalador, portable, GitHub Actions de release) | Pendiente |
| 11 | Pulido y manual de usuario | Pendiente |

## Preguntas frecuentes

Las entradas sobre SmartScreen, antivirus, cookies y "yt-dlp no descarga" se añadirán cuando
existan las funciones correspondientes (fases 1, 3, 8 y 10).

## Aviso

Eres responsable de respetar los derechos de autor y las condiciones de uso de cada web.
