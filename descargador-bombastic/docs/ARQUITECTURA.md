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
