# Changelog

## 0.4.0 — Fase 3: Modo avanzado de yt-dlp

- Catálogo de opciones generado a partir de `yt-dlp --help` (`build/gen_ytdlp_options.py` →
  `resources/ytdlp_options.json`, 255 opciones de yt-dlp 2026.08.19) y regenerable desde
  Ajustes con el yt-dlp instalado. Si el parseo falla se usa el incluido.
- Diálogo "Opciones avanzadas…": una pestaña por grupo de yt-dlp, casilla o campo (con
  selector de archivo o carpeta) por opción, flag real y ayuda (traducida al español en 115
  opciones), buscador, opciones modificadas en negrita y restablecer por grupo o en total.
- Argumentos libres con validación de comillas y vista previa del comando final.
- Avisos de conflictos: extraer audio sin ffmpeg, `--merge-output-format` con audio, `-o`/`-P`
  y `-f` que sustituyen a los de la app.
- Cookies (desactivadas por defecto): de Chrome, Edge, Firefox, Brave, Opera o Vivaldi con
  perfil opcional, o de un `cookies.txt`, con explicación en la interfaz.
- Selector manual de formatos: tabla con id, extensión, resolución, fps, códecs, bitrate y
  tamaño; se elige vídeo y audio por separado y la app construye el `-f`.

## 0.3.0 — Fase 2: Cola

- Página **Cola**: lo que se manda a descargar pasa de Descargas a la Cola, con estado, barra de
  progreso, velocidad, tamaño y tiempo restante.
- Cola persistente en SQLite (`PRAGMA user_version` para migrar): al cerrar la app lo que estaba
  en marcha o esperando queda en pausa y se recupera al abrir.
- Descargas simultáneas configurables (1–8, por defecto 3).
- Pausar (mata yt-dlp y conserva los `.part`), reanudar, cancelar, reintentar, quitar, subir y
  bajar; en lote: pausar todo, reanudar todo, reintentar fallidas y quitar terminadas.
- Menú "Más" por descarga: abrir archivo, copiar enlace, ver log y ver comando.
- Reintentos automáticos ante errores de red (configurables, por defecto 2) y límite global de
  velocidad (`--limit-rate`).
- Errores de yt-dlp traducidos a mensajes legibles ("Este vídeo es privado", "Necesitas iniciar
  sesión: prueba a activar las cookies", "yt-dlp está desactualizado: actualízalo"…); el mensaje
  original queda en el log.
- Corregido: quitar un enlace mientras se obtenía su información borraba el proceso aún vivo y
  Qt podía cerrar la app de golpe más tarde.

## 0.2.0 — Fase 1: MVP de descarga

- Página de Descargas: pegar uno o varios enlaces (Ctrl+Intro), con o sin `https://`.
- Tarjeta por enlace con miniatura, título, canal, duración y aviso de lista de reproducción,
  obtenidos con `yt-dlp -J --flat-playlist`.
- Presets del modo simple: vídeo mejor calidad (MP4 H.264/AAC compatible), 1080p, 720p, 480p,
  audio MP3 (128/192/320 kbps o V0), M4A, Opus, FLAC y WAV; subtítulos incrustados; miniatura y
  metadatos incrustados. Las opciones se recuerdan.
- Descarga con progreso real (una barra para vídeo + audio y para listas), velocidad, tamaño y
  tiempo restante; fase de post-procesado; cancelar (mata yt-dlp y sus procesos hijo) y abrir
  la carpeta.
- Avisos si faltan yt-dlp o ffmpeg y confirmación al salir con una descarga en curso.
- Constructor de comandos, parser de progreso, metadatos y gestor de descargas con tests
  (yt-dlp falso en `tests/fake_ytdlp.py`).

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
