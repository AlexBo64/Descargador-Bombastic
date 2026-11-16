# Prompt: construir "Descargador Bombastic" (app de Windows con yt-dlp + ffmpeg)

Eres un ingeniero de software senior especializado en aplicaciones de escritorio para Windows. Tu tarea es diseñar y construir desde cero una aplicación completa, robusta y lista para distribuir a otras personas. Trabaja **por fases**, entregando en cada una algo que funcione, con tests y documentación. No te saltes fases ni dejes partes "para más adelante" sin decirlo explícitamente.

Antes de escribir código, lee todo este documento, propón la arquitectura (estructura de carpetas, módulos y flujo de datos) y una lista de riesgos técnicos. Luego empieza por la Fase 0.

---

## 1. Visión general

**Nombre:** Descargador Bombastic
**Plataforma:** Windows 10 y 11 (64 bits)
**Idioma:** español por defecto, con inglés como segundo idioma (todas las cadenas traducibles, nada de texto fijo en el código).
**Tema:** oscuro y claro, cambiables en caliente desde ajustes, más la opción "seguir al sistema".

La app tiene dos grandes áreas:

1. **Descargas**: una interfaz gráfica para yt-dlp que expone **todas** sus opciones. Tiene un modo simple con presets y un modo avanzado con todas las opciones agrupadas por categorías.
2. **Editor**: una interfaz gráfica para ffmpeg con herramientas visuales para editar vídeo y audio, reproductor con vista previa y marcadores de inicio/fin, y un **modo experto** para escribir cualquier comando o cadena de filtros de ffmpeg.

Las dos áreas se conectan: al terminar una descarga se puede lanzar automáticamente una acción de edición ("descargar y editar encadenado").

---

## 2. Stack técnico (obligatorio salvo que justifiques un cambio)

- **Lenguaje:** Python 3.12.
- **GUI:** PySide6 (Qt 6). Usa QtMultimedia (`QMediaPlayer` + `QVideoWidget`) para la vista previa.
- **yt-dlp:** se usa como **ejecutable externo (`yt-dlp.exe`)** lanzado con `QProcess`, no como librería importada. Motivos: se puede actualizar solo con `yt-dlp -U` sin recompilar la app, cualquier opción nueva de yt-dlp queda disponible al momento, y un fallo de yt-dlp no tumba la interfaz.
  - El progreso se obtiene con `--newline --progress-template` usando una plantilla con un prefijo propio y JSON, por ejemplo `download:BMBPROG {"p":"%(progress._percent_str)s","s":"%(progress._speed_str)s","e":"%(progress._eta_str)s","d":%(progress.downloaded_bytes)s,"t":%(progress.total_bytes)s}`, parseada de forma tolerante (los campos pueden venir como `NA`).
  - Los metadatos (título, miniatura, formatos disponibles, duración, si es lista) se obtienen con `yt-dlp -J --flat-playlist` (o `-J` para un único vídeo) antes de descargar.
- **ffmpeg / ffprobe:** ejecutables externos lanzados con `QProcess`. El progreso se lee con `-progress pipe:1 -nostats` y la duración se saca con `ffprobe -v error -show_format -show_streams -of json`.
- **Persistencia:** SQLite (con `sqlite3` estándar) para historial, cola y perfiles. Un `settings.json` (o `QSettings` en INI) para preferencias.
- **Rutas de datos:** `%LOCALAPPDATA%\DescargadorBombastic\` para la base de datos, los logs, la caché de miniaturas y la carpeta `bin\` con `yt-dlp.exe`, `ffmpeg.exe` y `ffprobe.exe`. Así se pueden actualizar sin permisos de administrador. En la versión portable, todo va junto al ejecutable, en una carpeta `data\`, si existe un archivo `portable.flag`.
- **Empaquetado:** PyInstaller en modo `--onedir`, que arranca más rápido y da menos falsos positivos del antivirus que `--onefile`. Instalador con **Inno Setup 6**.
- **Calidad:** `ruff` (lint + format), `mypy` en modo razonablemente estricto en los módulos de lógica, `pytest` + `pytest-qt`.
- **Licencias:** incluye un `THIRD_PARTY_LICENSES.txt` con las licencias de PySide6 (LGPL), yt-dlp (Unlicense) y ffmpeg (GPL/LGPL según la build), e indica de dónde sale cada binario.

### Arquitectura

Separa claramente estas capas:

- `core/` → lógica pura sin Qt Widgets: constructores de comandos de yt-dlp y ffmpeg, parsers de progreso, modelos de datos, gestor de cola, repositorio SQLite y actualizador. Todo esto debe poderse testear sin abrir ventanas.
- `ui/` → ventanas, widgets, diálogos, temas y traducciones.
- `platform_win/` → integración con Windows: bandeja, notificaciones, instancia única y registro del menú contextual.
- `resources/` → iconos, estilos QSS y archivos de traducción.
- `build/` → spec de PyInstaller, script de Inno Setup y scripts de build y release.
- `tests/`

Reglas:

- Nunca bloquees el hilo de la interfaz. Todo proceso externo va con `QProcess` o en un `QThreadPool`, comunicándose por señales.
- Los comandos se construyen siempre como **lista de argumentos**, nunca concatenando strings para la shell, para evitar problemas de inyección y de comillas.
- Cada comando que se ejecute debe poder verse y copiarse desde la interfaz ("Ver comando").
- Escribe logs rotativos en la carpeta de datos, con un botón "Abrir carpeta de logs" en ajustes.

---

## 3. Área de Descargas (yt-dlp)

### 3.1 Modo simple

- Un campo grande donde pegar uno o varios enlaces (uno por línea, o separados por espacios). También acepta **arrastrar y soltar** enlaces y archivos `.txt` con listas de URLs.
- Al añadir un enlace se muestra una tarjeta con miniatura, título, duración, canal y si es una lista de reproducción (con el número de elementos y la opción de elegir cuáles descargar).
- Presets de un clic:
  - Vídeo mejor calidad (MP4 compatible)
  - Vídeo 1080p / 720p / 480p
  - Solo audio MP3 (con calidad elegible: 128/192/320 kbps o V0)
  - Solo audio M4A / Opus / FLAC / WAV
  - Vídeo + subtítulos incrustados
  - Miniatura + metadatos incrustados
- Selector de carpeta de destino (recordando la última) y plantilla de nombre de archivo con ejemplos.
- Un selector de **formato manual**: botón "Ver formatos disponibles" que muestra una tabla con la salida de `-J` (id, extensión, resolución, fps, códec de vídeo y audio, bitrate, tamaño). Se elige vídeo y audio por separado y la app construye el `-f`.

### 3.2 Modo avanzado: TODAS las opciones de yt-dlp

- El catálogo de opciones **no se escribe a mano**. Se genera automáticamente:
  - En tiempo de build, un script (`build/gen_ytdlp_options.py`) importa `yt_dlp.options.create_parser()` (el paquete `yt-dlp` de pip solo como dependencia de build), recorre los grupos y las opciones del parser y genera `resources/ytdlp_options.json` con el nombre del grupo, los flags, si recibe argumento, el `metavar`, los valores por defecto, las opciones posibles y el texto de ayuda.
  - En tiempo de ejecución, después de actualizar yt-dlp, la app puede regenerar el catálogo parseando `yt-dlp.exe --help`. Así las opciones nuevas aparecen sin recompilar. Si el parseo falla, se usa el JSON incluido.
- La interfaz se construye dinámicamente a partir del catálogo. Hay una pestaña o sección plegable por cada grupo de yt-dlp: General, Red, Geo-restricción, Selección de vídeo, Descarga, Sistema de archivos, Miniaturas, Atajos de internet, Verbosidad/simulación, Workarounds, Formato de vídeo, Subtítulos, Autenticación, Post-procesado, SponsorBlock, Extractor, etc.
  - Cada opción sin argumento es una casilla. Cada opción con argumento es un campo de texto, un número o un desplegable (si tiene `choices`), con un selector de archivo o carpeta cuando el `metavar` lo sugiera (FILE, PATH, DIR).
  - Cada opción muestra su flag real y la ayuda traducida al español. Traduce al menos las ~80 opciones más usadas y deja el resto con la ayuda original en inglés.
  - Un **buscador** filtra opciones por nombre, flag o descripción.
  - Las opciones modificadas se marcan visualmente, y hay un botón para restablecer por grupo o en total.
- Un campo de **argumentos extra libres** para escribir flags a mano, con validación básica (comillas balanceadas) y vista previa del comando final.
- Avisa de los conflictos más evidentes (por ejemplo `-x` sin ffmpeg disponible, o `--merge-output-format` con un formato de solo audio).
- **Cookies (opcional, desactivado por defecto):** elegir `--cookies-from-browser` (Chrome, Edge, Firefox, Brave, Opera, Vivaldi, con perfil opcional) o un archivo `cookies.txt`. Explica en la interfaz para qué sirve (vídeos con inicio de sesión o restricción de edad) y que en Chrome y Edge puede ser necesario cerrar el navegador.

### 3.3 Cola y descargas simultáneas

- Cola persistente en SQLite: si se cierra la app, la cola se recupera al abrirla.
- Número de descargas simultáneas configurable (1–8, por defecto 3).
- Cada elemento muestra estado (en espera, obteniendo info, descargando, procesando, completado, error, cancelado, pausado), barra de progreso, velocidad, ETA y tamaño.
- Acciones por elemento y en lote: pausar (matar el proceso y reanudar después aprovechando los `.part` de yt-dlp), reanudar, cancelar, reintentar, eliminar, reordenar arrastrando, subir y bajar, abrir archivo, abrir carpeta, copiar enlace, ver log y ver comando.
- Reintentos automáticos configurables ante errores de red.
- Límite global de velocidad opcional (`--limit-rate`).
- Los errores muestran un mensaje legible en español ("Este vídeo es privado", "Necesitas iniciar sesión: prueba a activar cookies", "yt-dlp está desactualizado: actualízalo") a partir de patrones comunes en la salida, y el log completo queda disponible.

### 3.4 Perfiles e historial

- **Perfiles:** guardar cualquier combinación de opciones (modo simple o avanzado, carpeta, plantilla de nombre, acción encadenada) con un nombre. Se pueden duplicar, renombrar, exportar e importar como JSON y marcar uno como predeterminado.
- **Historial:** lista de todo lo descargado, con fecha, título, URL, archivo resultante, tamaño, perfil usado y resultado. Tiene búsqueda y filtros, y permite volver a descargar con las mismas opciones, abrir el archivo o la carpeta, enviar al editor, borrar entradas o vaciar el historial. Opción para evitar duplicados usando `--download-archive` gestionado por la app.

### 3.5 Descargar y editar encadenado

- En cada descarga o perfil se puede añadir una **acción posterior** del editor: convertir a otro formato, recortar entre dos tiempos, comprimir a un tamaño objetivo, normalizar audio, extraer audio, cambiar resolución o una receta guardada del modo experto.
- Al terminar la descarga, la tarea se mete sola en la cola de edición, y en el historial queda enlazada a la descarga original.
- Opción de borrar o conservar el archivo original tras la edición.

---

## 4. Área de Editor (ffmpeg)

### 4.1 Entrada de archivos

- Abrir archivos con el diálogo, **arrastrando y soltando** a la ventana, desde el menú contextual del Explorador, desde el historial de descargas o como acción encadenada.
- Panel de información del archivo (vía ffprobe): contenedor, duración, tamaño, bitrate y, por cada pista, códec, resolución, fps, frecuencia de muestreo, canales e idioma.

### 4.2 Reproductor con vista previa

- Reproductor integrado con play/pausa, barra de tiempo, avance fotograma a fotograma (aproximado), saltos de ±1 s y ±5 s, velocidad de reproducción y volumen.
- **Marcadores de inicio (I) y fin (O)** con atajos de teclado, que se muestran sobre la barra de tiempo y rellenan los campos de tiempo de la herramienta activa. Los tiempos también se pueden escribir a mano en formato `hh:mm:ss.mmm`.
- Botón "Previsualizar resultado": genera un clip corto (por ejemplo 10 s alrededor del punto actual o del tramo marcado) en una carpeta temporal y lo reproduce, para comprobar filtros antes de procesar el archivo entero.
- Si QtMultimedia no puede reproducir un códec, la app debe ofrecer generar un proxy de vista previa con ffmpeg (H.264 de baja resolución) de forma transparente.

### 4.3 Herramientas visuales

Cada herramienta es un formulario con valores por defecto sensatos, "Ver comando" y "Añadir a la cola de edición". Como mínimo:

1. **Convertir formato**: contenedor y códecs de vídeo y audio (H.264, H.265/HEVC, VP9, AV1, ProRes, copiar sin recodificar; AAC, MP3, Opus, FLAC, PCM, copiar), CRF o bitrate y preset de velocidad. Usa `-c copy` cuando sea posible y explica la diferencia.
2. **Recortar (trim)**: por marcadores o tiempos. Modo rápido sin recodificar (corta en keyframes, avisa de la imprecisión) y modo preciso con recodificación.
3. **Cortar varios fragmentos y unirlos**: lista de tramos que se conservan o se eliminan.
4. **Unir archivos (concat)**: lista reordenable. Usa el demuxer concat si los archivos son compatibles y, si no, el filtro concat recodificando, detectándolo solo.
5. **Comprimir**: por calidad (CRF) o a un **tamaño objetivo en MB** (calcula el bitrate y hace dos pasadas).
6. **Cambiar resolución / recortar imagen (crop) / rotar / voltear**, con un rectángulo de recorte que se dibuja sobre la vista previa.
7. **Velocidad**: acelerar o ralentizar vídeo y audio de forma sincronizada (`setpts` + `atempo` encadenado para factores fuera de 0.5–2).
8. **Audio**: extraer audio, quitar el audio, reemplazar la pista de audio, ajustar el volumen, normalizar (`loudnorm` en dos pasadas, con objetivo LUFS elegible), fundidos de entrada y salida, y cambiar canales y frecuencia de muestreo.
9. **Subtítulos**: incrustar como pista (soft) o quemados en la imagen (hard, con fuente y tamaño), y extraer subtítulos.
10. **Marca de agua / superponer imagen o texto**, con posición, opacidad y tamaño.
11. **GIF / WebP animado** desde un tramo, con paleta optimizada (`palettegen`/`paletteuse`).
12. **Capturas**: un fotograma en el punto actual, o un fotograma cada N segundos.
13. **Miniatura y metadatos**: editar título, artista, álbum, etc., y la carátula de archivos de audio.
14. **Herramientas de audio puro** para archivos de audio: cortar, convertir, normalizar, fundidos y unir.

### 4.4 Modo experto

- Editor de comandos de ffmpeg con resaltado de sintaxis básico, autocompletado de opciones y filtros comunes y variables `{input}`, `{output}`, `{inputs[1]}`, `{start}`, `{end}`, `{dir}` y `{name}`, que se sustituyen al ejecutar.
- Editor de `-filter_complex` con ayuda de los filtros disponibles (lista obtenida de `ffmpeg -filters`, con buscador).
- Guardar comandos como **recetas** reutilizables (con nombre, descripción y parámetros), que también aparecen como acciones encadenadas y como opciones del menú contextual.
- Cualquier herramienta visual se puede "Abrir en modo experto" para ver y modificar el comando que genera.
- Ejecución con consola de salida en vivo y botón de cancelar.

### 4.5 Cola de edición

Igual que la de descargas: persistente, procesos simultáneos configurables (por defecto 1, porque recodificar ya usa mucha CPU), progreso real calculado con `out_time` frente a la duración, ETA, cancelar, reintentar y abrir resultado. Si hay GPU, opción de aceleración por hardware (NVENC, QSV, AMF), detectada con `ffmpeg -encoders` y `-hwaccels`, con prueba rápida y vuelta automática a CPU si falla.

### 4.6 Seguridad al escribir archivos

- Nunca sobrescribir el original: por defecto se genera `nombre_editado.ext` y se evita colisionar con `(1)`, `(2)`, etc.
- Comprobar el espacio libre en disco antes de tareas grandes.
- Si un proceso se cancela, borrar los archivos de salida a medias.

---

## 5. Actualizaciones

- **yt-dlp:** comprobar al arrancar (como mucho una vez al día, configurable) comparando la versión local (`yt-dlp --version`) con la última release de GitHub (`yt-dlp/yt-dlp`). Si hay versión nueva, avisar con un botón "Actualizar" que ejecute `yt-dlp -U`, o descargar la release directamente si `-U` falla. Opción de canal estable o nightly.
- **ffmpeg:** comprobar y descargar builds de Windows de una fuente fiable (por ejemplo los releases "essentials" de gyan.dev o los de BtbN en GitHub), **verificando el checksum SHA-256** cuando la fuente lo publique, extraer `ffmpeg.exe` y `ffprobe.exe` a `bin\` y conservar la versión anterior hasta comprobar que la nueva funciona (`ffmpeg -version`).
- **La propia app:** comprobar si hay una release nueva en un repositorio de GitHub configurable y enlazar al instalador. No hace falta auto-actualizar la app en sí; basta con avisar y abrir la descarga.
- Si al arrancar no están `yt-dlp.exe` o `ffmpeg.exe` (por ejemplo, porque un antivirus los ha borrado), ofrecer descargarlos con un asistente.

---

## 6. Integración con Windows

- **Arrastrar y soltar** en toda la ventana: los enlaces van a Descargas y los archivos de vídeo o audio van al Editor (detectando el tipo).
- **Bandeja del sistema:** icono con menú (mostrar, pausar o reanudar todas las colas, abrir la carpeta de descargas, salir). Opción "al cerrar, minimizar a la bandeja" y tooltip con el progreso global.
- **Notificaciones** al terminar una descarga o edición, o si hay errores, con un clic que abra el archivo o la app. Deben poderse desactivar.
- **Menú contextual del Explorador** (lo registra el instalador; opcional en la instalación):
  - Sobre archivos de vídeo y audio (`.mp4 .mkv .webm .mov .avi .mp3 .m4a .wav .flac .opus .ogg` y otros comunes): submenú "Descargador Bombastic" con las opciones "Editar en Descargador Bombastic", "Convertir a MP4", "Extraer audio MP3", "Comprimir…" y las recetas marcadas como favoritas.
  - Regístralo en `HKCU\Software\Classes\SystemFileAssociations\<ext>\shell\…` para no necesitar administrador, y elimínalo al desinstalar.
  - Documenta que en Windows 11 aparece en "Mostrar más opciones", salvo que implementes un `IExplorerCommand` con paquete disperso (opcional y fuera del MVP).
- **Instancia única:** si la app ya está abierta y se lanza otra vez (por ejemplo desde el menú contextual con varios archivos seleccionados), los argumentos se pasan a la instancia existente con `QLocalServer`/`QLocalSocket` y no se abre una segunda ventana.
- **Línea de comandos:** `DescargadorBombastic.exe --edit <archivo>`, `--action <receta> <archivos…>` y `--download <url>`.
- Barra de tareas: progreso en el icono si es viable con Qt. Es opcional.

---

## 7. Interfaz y experiencia de uso

- Ventana principal con navegación lateral: **Descargas**, **Cola**, **Editor**, **Historial**, **Perfiles y recetas**, **Ajustes**.
- Estilo moderno y limpio (QSS propio para claro y oscuro, iconos SVG coherentes, buen espaciado), que no parezca un formulario de los 2000. Usa una fuente del sistema (Segoe UI) y respeta el escalado DPI alto.
- Todo usable con teclado. Atajos documentados en Ajustes (por ejemplo Ctrl+V para pegar enlace y añadir, Espacio para play/pausa, I/O para marcadores).
- Primer arranque con asistente breve: idioma, tema, carpeta de descargas, comprobar o descargar yt-dlp y ffmpeg, y si se quiere el menú contextual (si es portable, explicar que requiere el instalador).
- Ventana "Acerca de" con versión de la app, de yt-dlp y de ffmpeg, licencias, y un aviso breve de que el usuario es responsable de respetar los derechos de autor y las condiciones de uso de cada web.
- Los mensajes de error son siempre comprensibles para alguien no técnico, con un "Ver detalles" para el log técnico.

---

## 8. Distribución

Se va a pasar a otras personas, así que:

1. **Instalador principal** (`DescargadorBombastic-Setup-x.y.z.exe`) con Inno Setup:
   - Instalación por usuario por defecto (sin administrador), con opción para todos los usuarios.
   - Incluye `yt-dlp.exe`, `ffmpeg.exe` y `ffprobe.exe`, que se copian a la carpeta de datos en el primer arranque si no existen.
   - Casillas: acceso directo en el escritorio, menú contextual del Explorador e iniciar con Windows minimizado en la bandeja.
   - Desinstalador limpio: quita el registro y pregunta si se borran los datos del usuario (historial, perfiles).
   - Español e inglés en el instalador.
2. **Versión portable** (`DescargadorBombastic-Portable-x.y.z.zip`): la carpeta onedir con `portable.flag`, que guarda los datos junto al ejecutable y no toca el registro.
3. Icono `.ico` propio (multi-resolución) e información de versión en el ejecutable (nombre, versión, descripción).
4. Documenta en el README lo de SmartScreen ("Windows protegió tu PC" → "Más información" → "Ejecutar de todas formas") porque el ejecutable no estará firmado, y deja preparado el paso de firma de código (`signtool`) como opcional en el script de build.
5. **Build reproducible:**
   - `build/build.ps1`, que crea el venv, instala dependencias fijadas (`requirements.txt` + `requirements-dev.txt` con versiones exactas), genera el catálogo de opciones de yt-dlp, compila las traducciones, ejecuta los tests, ejecuta PyInstaller, descarga y verifica yt-dlp y ffmpeg y compila el instalador y el zip portable.
   - Un workflow de **GitHub Actions** en `windows-latest` que haga lo mismo y publique los artefactos en cada tag `v*`.
   - **Importante:** si estás trabajando en un entorno Linux, no intentes generar el `.exe` ahí. Entrega el código, los scripts y el workflow listos, y explica exactamente cómo compilarlo en Windows o con GitHub Actions.

---

## 9. Fases de entrega

Cada fase termina con: código funcionando, tests que pasan, README actualizado, una lista de lo que se ha hecho y lo que falta, y una explicación breve de cómo probarlo. Al final de cada fase, para y resume antes de seguir.

- **Fase 0 – Esqueleto:** estructura del proyecto, ventana principal con navegación vacía, temas claro/oscuro, i18n funcionando (es/en), ajustes persistentes, logging, detección de `yt-dlp.exe`/`ffmpeg.exe`, `ruff`/`mypy`/`pytest` configurados.
- **Fase 1 – MVP de descarga:** pegar enlaces, obtener info con miniatura, presets del modo simple, una descarga con progreso real, cancelar y abrir la carpeta. Constructor de comandos de yt-dlp y parser de progreso con tests.
- **Fase 2 – Cola:** cola persistente, descargas simultáneas, pausar, reanudar, reintentar y reordenar, y mensajes de error legibles.
- **Fase 3 – Modo avanzado de yt-dlp:** generador del catálogo, UI dinámica por grupos, buscador, argumentos libres, vista previa del comando, cookies y selector de formatos manual.
- **Fase 4 – Editor básico:** carga de archivos, ffprobe, reproductor con marcadores I/O, herramientas 1–5 (convertir, recortar, varios tramos, unir, comprimir), cola de edición con progreso real.
- **Fase 5 – Editor completo:** herramientas 6–14, previsualización del resultado, proxy de vista previa y aceleración por hardware.
- **Fase 6 – Modo experto y recetas:** editor de comandos, variables, filter_complex, recetas y "Abrir en modo experto".
- **Fase 7 – Perfiles, historial y encadenado:** perfiles exportables, historial con búsqueda, `--download-archive` y acciones encadenadas descarga → edición.
- **Fase 8 – Actualizaciones:** yt-dlp, ffmpeg (con checksum y vuelta atrás), aviso de nueva versión de la app y asistente de dependencias que faltan.
- **Fase 9 – Integración con Windows:** bandeja, notificaciones, instancia única, argumentos de línea de comandos, arrastrar y soltar global, y registro del menú contextual.
- **Fase 10 – Distribución:** spec de PyInstaller, Inno Setup, zip portable, icono, información de versión, `build.ps1`, GitHub Actions y documentación de SmartScreen.
- **Fase 11 – Pulido:** asistente de primer arranque, accesibilidad por teclado, revisión de todas las traducciones, rendimiento con colas grandes (100+ elementos), revisión final de errores y manual de usuario en `docs/`.

---

## 10. Tests mínimos

- Constructores de comandos de yt-dlp y ffmpeg: para cada preset y herramienta, verificar la lista exacta de argumentos generada, incluidas rutas con espacios, tildes y caracteres raros.
- Parsers: progreso de yt-dlp (con valores `NA`, listas de reproducción, fases de post-procesado), progreso de ffmpeg y salida de ffprobe.
- Generador del catálogo de opciones y parser de `--help` (con un `--help` de ejemplo guardado como fixture).
- Repositorio SQLite: cola, historial y perfiles, incluida la migración de esquema (versionado con `PRAGMA user_version`).
- Gestor de cola: concurrencia, pausa y reanudación, reintentos y cancelación, con procesos externos simulados (un script falso que imita la salida de yt-dlp y ffmpeg).
- Sustitución de variables en las recetas del modo experto.
- Tests de UI básicos con `pytest-qt`: la ventana abre, el cambio de tema funciona, añadir un enlace crea una tarjeta.
- Un test de integración opcional (marcado, desactivado en CI por defecto) que descargue un vídeo de prueba corto y con licencia libre y lo convierta.

---

## 11. Documentación que debes entregar

- `README.md`: qué es, capturas (cuando las haya), instalación para usuarios, compilación para desarrolladores, estructura del proyecto y preguntas frecuentes (SmartScreen, antivirus, "yt-dlp no descarga" → actualizar, cookies).
- `docs/manual_usuario.md` en español: guía paso a paso de cada área.
- `CHANGELOG.md`.
- `THIRD_PARTY_LICENSES.txt`.
- Comentarios y docstrings en el código. Los nombres de variables y funciones van en inglés y los textos de la UI pasan por el sistema de traducción.

---

## 12. Forma de trabajar

- Antes de cada fase, enumera los archivos que vas a crear o modificar.
- Escribe código completo, nunca "…resto igual…" ni marcadores de TODO sin explicar.
- Si una decisión técnica de este documento te parece mala, dilo, propón la alternativa y justifícala antes de aplicarla.
- Si algo no se puede hacer bien (por ejemplo, un menú contextual moderno de Windows 11 sin paquete MSIX), dilo claramente y aplica la mejor alternativa razonable.
- Prioriza que funcione y sea robusto por encima de añadir funciones. Cada fase debe dejar la app en un estado usable.

Empieza ahora: propón la arquitectura y los riesgos, y después construye la Fase 0.