# Changelog

## 0.1.0 — Fase 0: esqueleto

- Estructura del proyecto por capas (`core`, `ui`, `platform_win`, `resources`).
- Ventana principal con navegación lateral (Descargas, Cola, Editor, Historial, Perfiles y
  recetas, Ajustes) y atajos Ctrl+1 … Ctrl+6. Las secciones aún sin implementar indican su fase.
- Temas claro y oscuro cambiables en caliente, y opción "seguir al sistema".
- Traducciones español/inglés cambiables en caliente (catálogos JSON).
- Ajustes persistentes en `settings.json` (tolerante a archivos dañados, escritura atómica).
- Rutas de datos en `%LOCALAPPDATA%\DescargadorBombastic` o modo portable con `portable.flag`.
- Logs rotativos y botón "Abrir carpeta de logs".
- Detección de `yt-dlp`, `ffmpeg` y `ffprobe` (carpeta de datos, carpeta de la app y PATH) con
  lectura asíncrona de la versión.
- `ruff`, `mypy` (estricto) y `pytest` + `pytest-qt` configurados; CI en `windows-latest`.
