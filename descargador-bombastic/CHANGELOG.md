# Changelog

## 1.2.0 — Actualizar la app desde la propia app

- Cuando sale una versión nueva, la barra de aviso tiene el botón "Actualizar ahora": descarga
  el instalador de la release de GitHub, lo comprueba con `SHA256SUMS.txt` (si no coincide no
  se ejecuta), cierra la app como "Salir" (pregunta si hay descargas o ediciones en marcha) y
  lanza el instalador en modo silencioso. Al terminar, el instalador vuelve a abrir la app
  (`/relaunch=1`). La cola se recupera como en cualquier reinicio.
- La versión portable y la ejecución desde el código siguen enlazando la página de descarga.
- El instalador descargado se borra al arrancar la siguiente vez.

## 1.1.0 — Nuevo aspecto

- Estilo "aurora + cristal": fondo con degradado y manchas de color difuminadas, paneles y
  tarjetas translúcidos con borde luminoso, esquinas más redondeadas y degradado violeta → cian
  en los botones principales, la sección activa, la barra de progreso y los deslizadores.
- Estilo propio para todos los controles que salían con el aspecto por defecto de Windows:
  casillas, pestañas (con flechas para desplazarse), botones de menú, deslizadores, spinbox,
  listas, tablas, menús, diálogos y el asistente.
- Fundido suave al cambiar de sección.
- El puntero pasa a ser una mano sobre todo lo pulsable (botones, desplegables, pestañas,
  deslizadores, menús y la navegación lateral).
- Los spinbox y desplegables ya no cambian de valor al hacer scroll con el puntero encima:
  hay que pincharlos antes; mientras tanto, la rueda desplaza la página.
- "Después de descargar": el valor de la acción es un desplegable con las opciones típicas
  (contenedores, formatos de audio, resoluciones, tamaños en MB, objetivos LUFS o tus recetas)
  en el que también se puede escribir otro valor; sin opciones (recortar) no muestra flecha.
- Animaciones: al quitar una descarga o edición, su tarjeta se rompe en fragmentos que se
  dispersan y el hueco se cierra suavemente; al pasar a la Cola se desvanece y se pliega; las
  tarjetas nuevas aparecen con un fundido y la línea de estado destella al cambiar de estado.
- README en la raíz del repositorio de GitHub con botón grande "Descargar para Windows",
  capturas y la lista de funciones. Cada release incluye el instalador y el zip portable
  también con nombre fijo (`DescargadorBombastic-Setup.exe`), al que enlaza el botón.
- Corregido: las tarjetas de descarga y de edición se aplastaban (botones cortados) cuando la
  lista llenaba la pantalla.
- Editor: los controles del reproductor y los botones de acción se reparten en dos filas para
  que no se corten.

## 1.0.0 — Fase 11: Pulido

- Asistente de primer arranque: idioma y tema (en vivo), carpeta de descargas, comprobación de
  yt-dlp y ffmpeg con descarga de lo que falte y menú contextual (en la portable se explica que
  lo añade el instalador).
- Ventana "Acerca de" con la versión de la app, de yt-dlp, de ffmpeg y de ffprobe, las licencias
  y el aviso sobre derechos de autor.
- Teclado: `Ctrl+V` fuera del campo pega y añade enlaces; todos los atajos (navegación,
  descargas, reproductor, marcadores, fotogramas) están en Ajustes → Atajos.
- Rendimiento comprobado con 150 elementos en la cola (≈0,3 ms por actualización de progreso)
  con un test que lo vigila.
- Revisión de las 589 traducciones (español e inglés) y test de que todas las páginas se
  retraducen.
- Test de integración opcional (`pytest -m integration`): descarga 5 s de un vídeo con licencia
  libre y lo convierte a MP3 con yt-dlp y ffmpeg reales.
- Manual de usuario en `docs/manual_usuario.md`.

## 0.11.0 — Fase 10: Distribución

- `build/DescargadorBombastic.spec` (PyInstaller `--onedir`, sin UPX, icono e información de
  versión del `.exe`).
- Icono `.ico` multi-resolución generado desde `app.svg` (`build/make_icon.py`).
- Instalador Inno Setup 6 (`build/installer.iss`): por usuario sin administrador u opción para
  todos, español e inglés, acceso directo, menú contextual (las mismas claves que registra la
  app, generadas con `build/gen_installer_registry.py`), inicio con Windows minimizado en la
  bandeja (`--minimized`) y desinstalador que quita el registro y pregunta si borrar los datos.
- yt-dlp y ffmpeg se descargan y verifican al compilar (`build/fetch_binaries.py`, con
  `bin\SOURCES.txt`); la app los copia a la carpeta de datos en el primer arranque.
- Versión portable en zip con `portable.flag`.
- `build/build.ps1` y workflow `release.yml` que publica instalador, portable y
  `SHA256SUMS.txt` en cada tag `v*`. Firma opcional con `signtool`.
- README: instalación, compilación, SmartScreen y antivirus.

## 0.10.0 — Fase 9: Integración con Windows

- Arrastrar y soltar en toda la ventana: enlaces y `.txt` a Descargas; vídeo y audio al Editor.
- Bandeja del sistema: mostrar, pausar o reanudar todas las colas, abrir la carpeta de
  descargas y salir; tooltip con el progreso global y opción de seguir en la bandeja al cerrar.
- Notificaciones al terminar o fallar una descarga o edición; clic para abrir el resultado.
  Se pueden desactivar.
- Instancia única con `QLocalServer`: una segunda instancia pasa sus argumentos a la abierta.
- Línea de comandos `--download`, `--edit` y `--action` (`convert_mp4`, `extract_mp3`,
  `compress`, `recipe:<nombre>`).
- Menú contextual del Explorador en `HKCU\Software\Classes\SystemFileAssociations\<ext>`
  (sin administrador): editar, convertir a MP4, extraer MP3, comprimir y recetas favoritas.
  Desde Ajustes (no en la portable); el instalador lo registrará en la Fase 10.
- Icono propio de la app.
- No incluido: progreso en el icono de la barra de tareas (opcional; Qt 6 no lo ofrece).

## 0.9.0 — Fase 8: Actualizaciones

- yt-dlp: comprobación al arrancar (cada 24 h por defecto, configurable o nunca) contra la
  última release de GitHub, canal estable o nightly, y aviso con botón "Actualizar". Se usa
  `yt-dlp -U` y, si falla (instalado con winget o pip), se descarga `yt-dlp.exe` de la release
  a la carpeta de datos verificando `SHA2-256SUMS`, con vuelta atrás si la nueva no responde.
- ffmpeg: descarga de la build `win64-gpl` de BtbN con `checksums.sha256`; se extraen
  `ffmpeg.exe` y `ffprobe.exe` en otro hilo y se conserva la versión anterior hasta comprobar
  que la nueva funciona (`ffmpeg -version`).
- Aviso de versión nueva de la app (repositorio de GitHub configurable) que abre la descarga.
- Asistente al arrancar si faltan yt-dlp o ffmpeg.

## 0.8.0 — Fase 7: Perfiles, historial y encadenado

- Perfiles: guardan formato, calidad, incrustados, carpeta, modo avanzado, argumentos libres,
  cookies y acción encadenada. Aplicar, renombrar, duplicar, eliminar, exportar e importar en
  JSON y uno predeterminado que se aplica al abrir la app.
- Historial en SQLite de cada descarga terminada (fecha, título, enlace, archivos, tamaño,
  perfil, resultado y error), con búsqueda, filtro, volver a descargar con las mismas opciones,
  abrir archivo o carpeta, enviar al editor, borrar entradas y vaciar.
- Evitar duplicados con `--download-archive` gestionado por la app (opcional, en Ajustes).
- Acciones encadenadas descarga → edición: convertir, recortar, comprimir a un tamaño,
  normalizar, extraer audio, cambiar resolución o una receta. La tarea entra sola en la cola
  de edición, el historial enlaza el resultado y se puede borrar el original al terminar.

## 0.7.0 — Fase 6: Modo experto y recetas

- Pestaña **Experto** del editor: comando de ffmpeg con resaltado básico (opciones,
  variables y comillas), autocompletado de opciones comunes, variables y filtros, y variables
  `{input}`, `{inputs[1]}`, `{output}`, `{start}`, `{end}`, `{dir}`, `{name}` más parámetros
  propios. El texto se separa en argumentos antes de sustituir: una ruta con espacios sigue
  siendo un solo argumento.
- Lista de filtros de `ffmpeg -filters` con buscador; el elegido se inserta en el comando.
- Ejecución inmediata con consola de salida en vivo y cancelar, o a la cola de edición.
- "Abrir en modo experto" desde cualquier herramienta visual.
- Recetas guardadas en SQLite (nombre, descripción, parámetros, extensión de salida, favorita)
  y página **Perfiles y recetas** con abrir, renombrar, duplicar, favorita, eliminar, exportar
  e importar en JSON.

## 0.6.0 — Fase 5: Editor completo

- Herramientas 6–13: resolución, recorte de imagen (campos numéricos), rotar y voltear;
  velocidad sincronizada (`setpts` + `atempo` encadenado fuera de 0,5–2); audio (extraer,
  quitar, sustituir pista, volumen en dB, fundidos, canales, frecuencia y `loudnorm` en dos
  pasadas con objetivo LUFS); subtítulos (incrustar como pista, grabar con fuente y tamaño,
  extraer); marca de agua de imagen o texto con posición, opacidad y tamaño; GIF con
  `palettegen`/`paletteuse` y WebP animado; capturas (punto actual o cada N segundos);
  metadatos y carátula de audio. La 14 (audio puro) son las mismas herramientas sobre un
  archivo de audio: las que necesitan vídeo lo avisan.
- "Previsualizar resultado": 10 s del resultado en una carpeta temporal, en un reproductor.
- Si QtMultimedia no puede reproducir un archivo, se genera solo una copia H.264 480p para la
  vista previa (las herramientas siguen usando el original).
- Aceleración por hardware (NVENC, Quick Sync, AMF): detección con `ffmpeg -encoders` y una
  prueba real de cada codificador; si una edición acelerada falla, se repite por CPU.
- Escapado de dos niveles de las rutas y textos dentro de los filtros (subtítulos y textos con
  `:`, `'` o tildes).

## 0.5.0 — Fase 4: Editor básico

- Página **Editor**: abrir con el diálogo o arrastrando, panel de información con ffprobe
  (contenedor, duración, tamaño, bitrate y cada pista con códec, resolución, fps, frecuencia,
  canales e idioma).
- Reproductor (QtMultimedia) con play/pausa, barra de tiempo, ±1 s y ±5 s, fotograma a
  fotograma aproximado, velocidad y volumen; marcadores de inicio (I) y fin (O) dibujados sobre
  la barra y que rellenan los tiempos de la herramienta activa (`hh:mm:ss.mmm`).
- Herramientas: convertir (contenedor, H.264/H.265/VP9/AV1/ProRes/copiar, AAC/MP3/Opus/FLAC/
  PCM/copiar, CRF o bitrate, preset; explica `-c copy` y avisa si se puede copiar), recortar
  (rápido sin recodificar o preciso), varios fragmentos (conservar o eliminar tramos), unir
  (demuxer concat si son compatibles, si no, filtro concat recodificando, detectado solo) y
  comprimir (CRF o tamaño objetivo en MB con dos pasadas).
- "Ver comando" en todas las herramientas.
- Cola de edición persistente (pestaña **Cola → Ediciones**): progreso real con `out_time`
  frente a la duración (también en dos pasadas), velocidad, pausar, cancelar, reintentar,
  reordenar, abrir resultado y ver detalles. Simultáneas configurables (1 por defecto).
- Seguridad: nunca se sobrescribe el original (`nombre_editado.ext`, `(1)`, `(2)`…), se
  comprueba el espacio libre antes de empezar y se borra la salida a medias si se cancela o
  falla.
- Corregido: convertir a un contenedor solo de audio con "copiar" metía un códec que el
  contenedor no admite.

## 0.4.0 — Fase 3: Modo avanzado de yt-dlp

- Catálogo de opciones generado a partir de `yt-dlp --help` (`build/gen_ytdlp_options.py` →
  `resources/ytdlp_options.json`, 255 opciones de yt-dlp 2026.08.19) y regenerable desde
  Ajustes con el yt-dlp instalado. Si el parseo falla se usa el incluido.
- Diálogo "Opciones avanzadas…": una pestaña por grupo de yt-dlp, casilla o campo (con
  selector de archivo o carpeta) por opción, flag real y ayuda (traducida al español en 113
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
