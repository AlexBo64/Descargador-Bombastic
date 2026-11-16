# Arquitectura

## Capas

| Carpeta | Contenido | Regla |
|---|---|---|
| `bombastic/core/` | Rutas, ajustes, logs, traducciones, localización de binarios. Más adelante: constructores de comandos, parsers de progreso, cola, SQLite, actualizador | Sin Qt Widgets. Se testea sin abrir ventanas. Solo `binary_probe` usa QtCore (`QProcess`) |
| `bombastic/ui/` | Ventana principal, páginas, temas | No lanza procesos ni toca disco directamente: llama a `core` |
| `bombastic/platform_win/` | Bandeja, notificaciones, instancia única, registro | Único sitio con código específico de Windows (Fase 9) |
| `bombastic/resources/` | Iconos SVG, `app.qss`, catálogos `i18n/*.json` | Solo datos |
| `build/` | Spec de PyInstaller, Inno Setup, `build.ps1` (Fase 10) | La salida va a `out/` |

`bombastic/context.py` define `AppContext`, el objeto que reciben las ventanas con las rutas,
los ajustes, el traductor y el gestor de temas. No hay variables globales salvo el atajo `tr()`.

## Flujo de datos (a partir de la Fase 1)

```
UI ──señales──▶ gestor de cola (core) ──▶ constructor de comando (lista de argumentos)
 ▲                                                    │
 └──señales── parser de progreso ◀── QProcess ◀───────┘
```

- Los comandos son siempre listas de argumentos, nunca cadenas para la shell.
- El estado duradero (cola, historial, perfiles) vive en SQLite; las preferencias, en
  `settings.json`.

## Módulos de descarga (Fase 1)

| Módulo | Qué hace |
|---|---|
| `core/urls.py` | Saca los enlaces del texto pegado |
| `core/ytdlp_command.py` | Presets y construcción de argumentos (`-J` y descarga) |
| `core/ytdlp_progress.py` | Plantillas `BMBPROG`/`BMBPP`/`BMBFILE`, parser tolerante y `ProgressTracker` |
| `core/media_info.py` | Interpreta la salida de `-J` |
| `core/ytdlp_runner.py` | `InfoFetcher` y `DownloadJob` sobre `QProcess` |
| `core/download_manager.py` | Estado de cada enlace y turno de descargas |
| `core/thumbnails.py` | Descarga y caché de miniaturas con QtNetwork |
| `platform_win/process.py` | `taskkill /T /F` para matar el árbol de procesos |

## Cola (Fase 2)

| Módulo | Qué hace |
|---|---|
| `core/download_models.py` | `DownloadItem` y los estados (`STAGING` en Descargas, `QUEUE_STATES` en la Cola) |
| `core/download_manager.py` | Metadatos, cola ordenada por `position`, simultáneas, pausa, reintentos y guardado |
| `core/db.py` | Conexión SQLite con migraciones por `PRAGMA user_version` |
| `core/errors.py` | Patrones de la salida de yt-dlp → clave de mensaje legible (y si se reintenta) |
| `ui/queue_page.py` | Página Cola, acciones en lote y menú "Más" |

- Los enlaces recién añadidos no se guardan; solo lo que se ha mandado a la cola.
- Al abrir la app, lo que estaba en marcha o esperando se restaura **en pausa**: no se lanzan
  descargas sin que el usuario lo pida.
- Pausar = matar el árbol de procesos; yt-dlp reanuda desde los `.part` al relanzarlo.
- Los reintentos automáticos solo se hacen ante errores marcados como pasajeros (red, 429).
- Un `QProcess` nunca se borra con el proceso vivo (Qt aborta más tarde): las consultas
  canceladas se borran al recibir la señal de fin y al cerrar la app se espera a que mueran.

## Modo avanzado (Fase 3)

| Módulo | Qué hace |
|---|---|
| `core/ytdlp_options.py` | Parser de `--help`, catálogo JSON, argumentos del modo avanzado y libres, conflictos |
| `build/gen_ytdlp_options.py` | Genera el catálogo incluido con el `yt-dlp` de la compilación |
| `resources/ytdlp_help_es.json` | Nombres de grupo y ayuda en español de las opciones más usadas |
| `ui/advanced_dialog.py` | Diálogo dinámico por grupos, cookies, argumentos libres y vista previa |
| `ui/formats_dialog.py` | Tabla de formatos y construcción del `-f` |

- Orden de los argumentos: los de la app, después cookies, modo avanzado y libres. Así lo que
  el usuario pide a mano gana (yt-dlp se queda con el último valor de cada opción).
- Se ocultan las opciones que romperían la lectura de la salida (`--print`, `--quiet`,
  `--progress-template`…) y los alias de presets (`-t`).

## Editor (Fase 4)

| Módulo | Qué hace |
|---|---|
| `core/media_probe.py` | Parser de `ffprobe -show_format -show_streams -of json` |
| `core/media_prober.py` | ffprobe con `QProcess` y `tool_launcher` para ffmpeg/ffprobe |
| `core/ffmpeg_command.py` | Herramientas → `EditPlan` (una o varias pasadas de argumentos) |
| `core/ffmpeg_progress.py` | Parser de `-progress pipe:1` |
| `core/output_paths.py` | Nombres de salida que nunca pisan nada y espacio libre |
| `core/edit_manager.py` | `FfmpegJob` (pasadas en serie) y cola de edición persistente |
| `ui/player.py` | Reproductor y barra con marcadores I/O |
| `ui/editor_tools.py` | Formularios de las herramientas |
| `ui/editor_page.py`, `ui/edit_queue.py` | Página del editor y pestaña Ediciones de la Cola |

- Una edición no se reanuda a medias: pausar o cancelar borra la salida y al reanudar empieza
  de nuevo (ffmpeg no tiene un equivalente a los `.part` de yt-dlp).
- Las listas del demuxer concat y los logs de dos pasadas van a `cache\tmp` y se borran al
  terminar.

## Editor completo (Fase 5)

| Módulo | Qué hace |
|---|---|
| `core/ffmpeg_tools.py` | Herramientas 6–13, previsualización, proxy, escapado de filtros y `apply_hw` |
| `core/hwaccel.py` | `HwProbe`: `-encoders` y prueba real de cada codificador por hardware |
| `ui/editor_tools_extra.py` | Formularios de las herramientas 6–13 |

- `EditPlan.analysis = "loudnorm"`: `FfmpegJob` lee el JSON de la primera pasada y rellena el
  marcador `{loudnorm}` de la segunda.
- `EditPlan.cpu_fallback`: pasadas por CPU; si las aceleradas fallan, el gestor las cambia y
  vuelve a encolar la tarea sin intervención.
- El recorte de imagen se hace con campos numéricos en lugar de dibujar sobre el vídeo:
  `QVideoWidget` es una superficie nativa sobre la que pintar es frágil; la previsualización
  sirve para comprobarlo.

## Modo experto y recetas (Fase 6)

| Módulo | Qué hace |
|---|---|
| `core/recipes.py` | Variables, plantillas → `EditPlan`, recetas en SQLite, parser de `-filters` |
| `ui/expert_panel.py` | Editor con resaltado y autocompletado, filtros, guardar receta, consola |
| `ui/library_page.py` | Página "Perfiles y recetas" (recetas; perfiles en la Fase 7) |

- El modo experto quita del comando `-y`, `-progress`, `-nostats`… y pone los suyos para
  poder mostrar el progreso.

## Perfiles, historial y encadenado (Fase 7)

| Módulo | Qué hace |
|---|---|
| `core/history.py` | `HistoryStore`, `HistoryRecorder` (apunta cada descarga terminada) y perfiles |
| `core/chain.py` | `ChainAction` (va en `DownloadOptions.chain`), plan de edición y `ChainRunner` |
| `ui/history_page.py` | Página de historial |
| `ui/library_page.py` | Pestañas Perfiles y Recetas |

- La acción encadenada viaja como JSON dentro de las opciones de la descarga: se guarda con la
  cola, con los perfiles y con el historial sin tablas aparte.
- Un perfil es una copia de los ajustes de `PROFILE_FIELDS`; al importar se descartan claves
  desconocidas.

## Actualizaciones (Fase 8)

| Módulo | Qué hace |
|---|---|
| `core/net.py` | `TextFetch` y `FileFetch` con QtNetwork (User-Agent genérico, sigue redirecciones) |
| `core/updater.py` | Versiones, releases de GitHub, SHA-256, extracción, cambio con `.old` y vuelta atrás |
| `ui/updates.py` | `Updates`, bloque de Ajustes, barra de aviso y asistente de dependencias |

- Nada se instala sin comprobar su SHA-256 publicado; si la release no lo publica, no se
  instala.
- Los tests usan URLs `file://` que imitan la API de GitHub: no hay red en los tests.

## Integración con Windows (Fase 9)

| Módulo | Qué hace |
|---|---|
| `core/cli.py` | `--download`, `--edit`, `--action` → `AppCommand` (y al revés, para reenviar) |
| `platform_win/single_instance.py` | `InstanceServer` y `send_to_running` (JSON por `QLocalSocket`) |
| `platform_win/context_menu.py` | Entradas del registro del submenú y alta/baja en HKCU |
| `platform_win/tray.py` | Icono de bandeja, menú, tooltip y notificaciones |

- Las acciones del menú contextual reutilizan `ChainRunner.queue_files` y los planes de las
  acciones encadenadas; "Comprimir…" abre el editor porque necesita que el usuario elija.
- Los tests comprueban las entradas del registro sin escribirlas; el registro real solo se
  toca desde Ajustes o el instalador.

## Distribución (Fase 10)

| Archivo | Qué hace |
|---|---|
| `build/build.ps1` | Todo el proceso: venv, binarios, recursos, calidad, PyInstaller, firma, instalador, zip |
| `build/DescargadorBombastic.spec` | PyInstaller `--onedir` |
| `build/installer.iss` | Inno Setup 6 (incluye `out/registry.iss`, generado) |
| `build/fetch_binaries.py` | yt-dlp y ffmpeg con SHA-256, mismo código que el actualizador |
| `build/make_icon.py`, `build/version_info.py` | Icono `.ico` y versión del `.exe` |
| `.github/workflows/release.yml` | Release en cada tag `v*` |

- No se ha podido compilar el `.exe` en el equipo de desarrollo (sin PyInstaller ni Inno Setup
  instalados): la compilación real es la de GitHub Actions o `build.ps1` en Windows.

## Aspecto (1.1)

- `ui/theme.py`: paletas con tokens de degradado (`bg_top`, `bg_bottom`, `blob_*`) y de cristal
  (`glass*`, en `rgba`, solo para el QSS); `AuroraBackground` pinta el fondo; `fade_in` hace
  el fundido entre secciones; `InteractionFilter` (uno por aplicación) pone la mano en lo
  pulsable (QSS no puede cambiar el cursor) y hace que spinbox y desplegables solo respondan a
  la rueda tras pincharlos.
- Qt no difumina lo que hay detrás de un widget: el "cristal" son paneles translúcidos sobre
  un fondo que ya está difuminado.
- El editor no tiene fundido: el vídeo es una superficie nativa que no admite efectos.

## Decisiones

- **Traducciones en JSON**, no `.ts/.qm`: sin paso de compilación, cambio en caliente sencillo,
  un test garantiza que todos los idiomas tienen las mismas claves y marcadores, y sirve para la
  ayuda de yt-dlp que se genera dinámicamente. Los diálogos estándar de Qt usan sus propios `.qm`.
- **Un solo QSS con marcadores** (`{{bg}}`, `{{accent}}`…) y dos paletas en `ui/theme.py`, para
  no mantener dos hojas de estilo duplicadas.
- **Cambio de idioma en caliente**: cada página implementa `retranslate()`; la ventana principal
  se suscribe al traductor y las recorre.
- **Binarios**: se buscan primero en la carpeta de datos (actualizable sin administrador),
  después junto al ejecutable y por último en el PATH.

## Riesgos técnicos

1. Pausar o cancelar matando yt-dlp puede dejar procesos hijo (ffmpeg) vivos en Windows →
   Job Objects o `taskkill /T`.
2. yt-dlp necesita un runtime de JavaScript externo (Deno) para YouTube en sus versiones
   recientes. Confirmado en la Fase 1: con Deno en el PATH funciona; se busca como una
   dependencia más (Ajustes → Dependencias) y el asistente lo explica.
3. La plantilla de progreso con campos `NA` produce JSON inválido. Comprobado: incluso con la
   conversión `j`, yt-dlp escribe `NA` sin comillas → el parser lo sustituye por `null`.
4. Parsear `yt-dlp --help` es frágil → catálogo generado en build como respaldo.
5. QtMultimedia: paso de fotograma aproximado y códecs no soportados → proxy H.264.
6. Antivirus y SmartScreen sin firma de código → `--onedir`, documentación, `signtool` opcional.
7. Redistribuir ffmpeg GPL obliga a incluir licencia y origen de las fuentes.
8. Codificación de la salida de consola y rutas con tildes en Windows → UTF-8 forzado y tests.
9. El desarrollo se hace en parte fuera de Windows → CI en `windows-latest` desde la Fase 0.
