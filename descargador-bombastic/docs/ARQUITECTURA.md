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
   recientes → verificar en la Fase 1 y tratarlo como dependencia adicional si se confirma.
3. La plantilla de progreso con campos `NA` produce JSON inválido → usar la conversión `j`
   de yt-dlp y un parser tolerante.
4. Parsear `yt-dlp --help` es frágil → catálogo generado en build como respaldo.
5. QtMultimedia: paso de fotograma aproximado y códecs no soportados → proxy H.264.
6. Antivirus y SmartScreen sin firma de código → `--onedir`, documentación, `signtool` opcional.
7. Redistribuir ffmpeg GPL obliga a incluir licencia y origen de las fuentes.
8. Codificación de la salida de consola y rutas con tildes en Windows → UTF-8 forzado y tests.
9. El desarrollo se hace en parte fuera de Windows → CI en `windows-latest` desde la Fase 0.
