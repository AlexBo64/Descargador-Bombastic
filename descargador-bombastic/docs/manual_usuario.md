# Manual de usuario de Descargador Bombastic

Descargador Bombastic descarga vídeo y audio de cientos de webs con **yt-dlp** y los edita con
**ffmpeg**, sin escribir comandos. Este manual recorre cada sección de la ventana.

> Eres responsable de respetar los derechos de autor y las condiciones de uso de cada web.

## Primer arranque

La primera vez se abre un asistente:

1. **Idioma y aspecto**: español o inglés, y tema claro, oscuro o "seguir al sistema". Se
   aplican al momento.
2. **Carpeta de descargas**: dónde se guardará todo (se puede cambiar cuando quieras).
3. **Programas necesarios**: comprueba si están yt-dlp y ffmpeg. Si falta alguno, al terminar
   se ofrece descargarlo (va a la carpeta de datos, sin permisos de administrador). Aquí también
   puedes añadir el menú contextual del Explorador (en la versión portable lo añade el
   instalador).

Para moverte entre secciones usa la barra lateral o `Ctrl+1` … `Ctrl+6`.

## Descargas (`Ctrl+1`)

1. **Pega uno o varios enlaces** en el campo grande (uno por línea o separados por espacios) y
   pulsa "Añadir enlaces" o `Ctrl+Intro`. También puedes pulsar `Ctrl+V` fuera del campo, o
   **arrastrar** enlaces o un archivo `.txt` con enlaces a cualquier parte de la ventana.
2. Cada enlace aparece en una **tarjeta** con miniatura, título, canal y duración. Si es una
   lista de reproducción, indica cuántos elementos tiene.
3. Elige el **formato**: vídeo en la mejor calidad (MP4 compatible), 1080p, 720p, 480p, o solo
   audio (MP3 con calidad 128/192/320 kbps o V0, M4A, Opus, FLAC o WAV). Puedes incrustar los
   subtítulos y la miniatura con los metadatos.
4. Pulsa **Descargar** en la tarjeta o **Descargar todo**. Los enlaces pasan a la **Cola**.

### Formato manual

En un vídeo suelto, **Formatos…** muestra todos los formatos disponibles (resolución, fps,
códecs, bitrate y tamaño). Elige uno de vídeo y, si no lleva audio, uno de audio: se descargará
exactamente esa combinación.

### Opciones avanzadas

**Opciones avanzadas…** abre todas las opciones de yt-dlp agrupadas por pestañas (Red,
Selección de vídeo, Subtítulos, Post-procesado, SponsorBlock…), con buscador. Las opciones que
cambias se ven en negrita y se pueden restablecer por grupo o todas a la vez.

- **Argumentos extra**: escribe flags de yt-dlp a mano. Si hay comillas sin cerrar, se avisa
  y no se usan.
- **Vista previa del comando**: el comando exacto que se ejecutará.
- **Avisos**: por ejemplo, extraer audio sin ffmpeg o un `-f` que sustituye al formato elegido.
- **Cookies** (desactivadas por defecto): para vídeos que piden iniciar sesión, con restricción
  de edad o solo para miembros. Elige el navegador (Chrome, Edge, Firefox, Brave, Opera,
  Vivaldi) y, si quieres, el perfil, o un archivo `cookies.txt`. Con Chrome y Edge puede hacer
  falta cerrar el navegador antes de descargar.

### Después de descargar (acciones encadenadas)

En "Después de descargar" puedes hacer que, al terminar, el archivo pase solo por el editor:
convertir a otro formato, recortar entre dos tiempos (`00:00:10-00:01:30`), comprimir a un
tamaño en MB, normalizar el volumen, extraer el audio, cambiar la resolución o aplicar una
receta. Marca "Borrar el original al terminar" si solo quieres el resultado.

### Perfiles

"Guardar como perfil…" guarda todas las opciones (formato, carpeta, modo avanzado, cookies y
acción encadenada) con un nombre. Elige un perfil en el desplegable para volver a usarlo.

## Cola (`Ctrl+2`)

La cola tiene dos pestañas: **Descargas** y **Ediciones**.

- Cada elemento muestra su estado, la barra de progreso, la velocidad, el tamaño y el tiempo
  restante.
- **Pausar** detiene la descarga conservando lo ya bajado; **Reanudar** sigue desde ahí.
  También puedes cancelar, reintentar y quitar.
- El botón **Más** permite subir y bajar en la cola, abrir el archivo, copiar el enlace, ver el
  log y ver el comando.
- En lote: pausar todo, reanudar todo, reintentar las fallidas y quitar las terminadas.
- Si cierras la app con descargas en marcha, al volver a abrirla siguen en la cola, en pausa.
- Los errores se explican en español ("Este vídeo es privado", "Necesitas iniciar sesión:
  prueba a activar las cookies", "yt-dlp está desactualizado: actualízalo"…). Los errores de
  red se reintentan solos.

En **Ajustes → Descargas** eliges cuántas descargas van a la vez (1–8), cuántos reintentos
automáticos se hacen y un límite de velocidad (por ejemplo `2M`).

## Editor (`Ctrl+3`)

1. **Abre** un vídeo o audio con "Abrir archivo…" o arrastrándolo. Abajo se ve su información
   (contenedor, duración, tamaño y cada pista).
2. **Reproductor**: `Espacio` reproduce o pausa; las flechas saltan ±1 s (±5 s con `Mayús`);
   coma y punto avanzan fotograma a fotograma (aproximado). Hay velocidad y volumen.
3. **Marcadores**: `I` marca el inicio y `O` el fin del tramo. Se ven en la barra de tiempo y
   rellenan los tiempos de la herramienta activa. También puedes escribirlos
   (`hh:mm:ss.mmm`).
4. Elige una **herramienta**, ajusta sus opciones y pulsa **Añadir a la cola de edición**. El
   progreso se ve en Cola → Ediciones.

El original **nunca se sobrescribe**: el resultado se llama `nombre_editado.ext` (y `(1)`,
`(2)`… si ya existe). Antes de empezar se comprueba el espacio libre y, si cancelas, se borra
el archivo a medias.

| Herramienta | Para qué sirve |
|---|---|
| Convertir | Cambiar contenedor y códecs (H.264, H.265, VP9, AV1, ProRes; AAC, MP3, Opus, FLAC, PCM). "Copiar sin recodificar" es instantáneo y sin pérdida si el contenedor lo admite. |
| Recortar | Quedarse con un tramo. Rápido (sin recodificar, corta en fotogramas clave) o preciso. |
| Fragmentos | Conservar o eliminar varios tramos y unir el resultado. |
| Unir | Juntar varios archivos (arrastra para ordenarlos). Si son compatibles, sin recodificar. |
| Comprimir | Por calidad (CRF) o a un tamaño objetivo en MB (dos pasadas). |
| Imagen | Cambiar la resolución, recortar la imagen, rotar o voltear. |
| Velocidad | Acelerar o ralentizar vídeo y audio a la vez, sin cambiar el tono. |
| Audio | Extraer, quitar o sustituir el audio; volumen, fundidos, canales, frecuencia y normalizar (LUFS). |
| Subtítulos | Incrustarlos como pista, grabarlos en la imagen (con fuente y tamaño) o extraerlos. |
| Marca de agua | Superponer una imagen o un texto, con posición, opacidad y tamaño. |
| GIF / WebP | Animación de un tramo con paleta optimizada. |
| Capturas | El fotograma actual o uno cada N segundos. |
| Metadatos | Título, artista, álbum… y la carátula de archivos de audio. |
| Experto | Cualquier comando de ffmpeg (ver más abajo). |

- **Previsualizar resultado**: genera 10 segundos del resultado y los reproduce, para
  comprobarlo antes de procesar el archivo entero.
- **Ver comando**: el comando de ffmpeg exacto.
- Si el reproductor no puede con un formato, la app crea sola una copia ligera para la vista
  previa; las herramientas siguen usando el original.
- **Aceleración por hardware**: en Ajustes → Editor, "Detectar" prueba NVIDIA, Intel y AMD. Si
  una edición acelerada falla, se repite sola por la CPU.

### Modo experto y recetas

En la pestaña **Experto** escribes cualquier comando de ffmpeg (sin "ffmpeg" delante), con
variables que se sustituyen al ejecutar:

| Variable | Valor |
|---|---|
| `{input}` | El archivo abierto |
| `{inputs[1]}`, `{inputs[2]}`… | Las entradas adicionales (separadas por `;`) |
| `{output}` | El archivo de salida (obligatorio) |
| `{start}`, `{end}` | Los marcadores I y O |
| `{dir}`, `{name}` | Carpeta y nombre (sin extensión) del archivo abierto |
| `{lo que quieras}` | Tus parámetros, definidos en "Parámetros" (`crf=23, preset=slow`) |

- **Filtros…** lista todos los filtros de ffmpeg con buscador.
- **Ejecutar ahora** muestra la salida en vivo y se puede cancelar; también puedes añadirlo a
  la cola.
- **Abrir en modo experto**, en cualquier herramienta, copia su comando aquí para retocarlo.
- **Guardar como receta…** lo guarda con nombre y descripción. Las recetas **favoritas**
  aparecen en el menú contextual del Explorador.

## Historial (`Ctrl+4`)

Todo lo descargado, con fecha, título, resultado, tamaño, perfil y archivo. Puedes buscar por
título o enlace, filtrar por resultado, **volver a descargar** con las mismas opciones, abrir
el archivo o la carpeta, **enviar al editor**, borrar entradas o vaciar el historial (los
archivos no se tocan).

En Ajustes, "Evitar descargar dos veces lo mismo" hace que yt-dlp se salte lo ya descargado.

## Perfiles y recetas (`Ctrl+5`)

Gestiona los perfiles de descarga y las recetas: aplicar o abrir, renombrar, duplicar,
eliminar, exportar e importar en JSON (para pasarlos a otro equipo). Un perfil marcado como
predeterminado se aplica al abrir la app.

## Ajustes (`Ctrl+6`)

- **Apariencia**: idioma y tema.
- **Descargas**: carpeta, simultáneas, reintentos, límite de velocidad y evitar duplicados.
- **Editor**: ediciones simultáneas y aceleración por hardware.
- **Windows**: seguir en la bandeja al cerrar, notificaciones y menú contextual del Explorador.
- **Actualizaciones**: canal de yt-dlp (estable o nightly), cada cuántas horas comprobar,
  actualizar yt-dlp y descargar o actualizar ffmpeg. Todo se comprueba con su SHA-256 y, si la
  versión nueva no funciona, se vuelve a la anterior. Cuando hay una versión nueva de la app,
  la barra de arriba ofrece **Actualizar ahora**: la descarga, la comprueba, se cierra, la
  instala y se vuelve a abrir sola. En la versión portable, el botón abre la página de descarga.
- **Dependencias**: dónde está cada programa y su versión.
- **Datos y registros**: dónde se guardan tus datos y un botón para abrir los logs.
- **Atajos** y **Acerca de** (versiones y licencias).

## Integración con Windows

- **Bandeja del sistema**: mostrar la ventana, pausar o reanudar todas las colas, abrir la
  carpeta de descargas y salir. El tooltip muestra el progreso.
- **Notificaciones** al terminar o fallar una descarga o edición; haz clic para abrir el
  resultado.
- **Menú contextual**: clic derecho sobre un vídeo o audio → "Descargador Bombastic" →
  editar, convertir a MP4, extraer MP3, comprimir o una receta favorita. En Windows 11 está en
  "Mostrar más opciones".
- **Línea de comandos**: `DescargadorBombastic.exe --download <enlace>`, `--edit <archivo>` o
  `--action convert_mp4 <archivos…>`. Si la app ya está abierta, se usa esa misma ventana.

## Problemas frecuentes

- **Una web deja de descargar**: actualiza yt-dlp (Ajustes → Actualizaciones). Si sigue,
  prueba el canal nightly.
- **"Necesitas iniciar sesión" o restricción de edad**: activa las cookies en Opciones
  avanzadas → Cookies.
- **YouTube pide un "runtime de JavaScript"**: yt-dlp necesita Deno. Instálalo
  (`winget install DenoLand.Deno`) o copia `deno.exe` en la carpeta de binarios.
- **El antivirus borra yt-dlp o ffmpeg**: añade una excepción y vuelve a descargarlos desde el
  asistente que aparece al arrancar.
- **"Windows protegió tu PC"** al instalar: "Más información" → "Ejecutar de todas formas" (el
  ejecutable no está firmado).
- **Algo no funciona**: Ajustes → "Abrir carpeta de logs" y adjunta el último log al pedir
  ayuda.
