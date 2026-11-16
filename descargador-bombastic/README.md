# Descargador Bombastic

Aplicación de escritorio para Windows 10/11 que pone una interfaz gráfica a
[yt-dlp](https://github.com/yt-dlp/yt-dlp) (descargas) y a [ffmpeg](https://ffmpeg.org) (edición
de vídeo y audio).

> **Estado: versión 1.0.** Las 12 fases del plan están hechas: descargas con todas las
> opciones de yt-dlp, cola, editor completo con ffmpeg, modo experto y recetas, perfiles,
> historial, acciones encadenadas, actualizaciones, integración con Windows e instalador.
> Guía paso a paso: [docs/manual_usuario.md](docs/manual_usuario.md).

## Instalación (usuarios)

1. Descarga `DescargadorBombastic-Setup-x.y.z.exe` de la página de releases y ábrelo.
2. Si aparece "Windows protegió tu PC" (SmartScreen), pulsa **Más información → Ejecutar de
   todas formas**: el ejecutable no está firmado (ver preguntas frecuentes).
3. Por defecto se instala solo para tu usuario, sin administrador. Puedes elegir acceso directo
   en el escritorio, el menú contextual del Explorador e iniciar con Windows en la bandeja.

**Portable:** descomprime `DescargadorBombastic-Portable-x.y.z.zip` donde quieras y ejecuta
`DescargadorBombastic.exe`. Guarda todo en la carpeta `data\` de al lado (por el archivo
`portable.flag`) y no toca el registro.

## Compilar el instalador (desarrolladores)

En Windows, con [Python 3.12](https://www.python.org/downloads/) e
[Inno Setup 6](https://jrsoftware.org/isinfo.php) (`winget install JRSoftware.InnoSetup`):

```powershell
powershell -ExecutionPolicy Bypass -File build\build.ps1
```

El script crea `.venv-build`, instala las dependencias fijadas (`requirements*.txt`), descarga
y verifica yt-dlp y ffmpeg, regenera el catálogo de opciones, el icono y la versión del `.exe`,
pasa ruff, mypy y los tests, ejecuta PyInstaller (`--onedir`) y deja en `out\release` el
instalador, el zip portable y `SHA256SUMS.txt`. Para firmar, define `SIGN_CERT_FILE` y
`SIGN_CERT_PASSWORD` (usa `signtool`). No compiles el `.exe` fuera de Windows.

Con GitHub Actions: al subir un tag `v*` (por ejemplo `git tag v1.0.0 && git push --tags`), el
workflow `.github/workflows/release.yml` hace lo mismo en `windows-latest` y publica los
archivos en la release.

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
5. En **Descargas**, pega dos o tres enlaces y pulsa "Descargar todo": pasan a la **Cola**
   (`Ctrl+2`), donde se ven progreso, velocidad y tiempo restante.
6. En la Cola, pausa una descarga y reanúdala (aprovecha lo ya bajado); usa "Más" para subirla,
   bajarla, copiar el enlace o ver el log y el comando.
7. Cierra la app con una descarga en marcha y vuelve a abrirla: la cola sigue ahí, en pausa.
8. En **Ajustes → Descargas** cambia las descargas simultáneas (1–8), los reintentos automáticos
   ante errores de red y el límite de velocidad (por ejemplo `2M`).
9. En Descargas, "Opciones avanzadas…" abre todas las opciones de yt-dlp por grupos, con
   buscador, ayuda en español de las más usadas, vista previa del comando y avisos de
   conflictos. La pestaña Cookies permite usar las de un navegador o un `cookies.txt`.
10. En la tarjeta de un vídeo, "Formatos…" muestra la tabla de formatos; elige vídeo y audio y
    se descargará con ese `-f`.
11. **Ajustes → Dependencias → Actualizar opciones de yt-dlp** relee la lista de opciones del
    yt-dlp instalado (para opciones nuevas tras actualizarlo).
12. En **Editor** (`Ctrl+3`) abre o arrastra un vídeo: se ve su información (ffprobe) y se
    reproduce. `Espacio` reproduce/pausa, `I` y `O` marcan inicio y fin, las flechas saltan
    ±1 s (±5 s con Mayús) y coma/punto avanzan fotograma a fotograma.
13. Elige una herramienta (Convertir, Recortar, Fragmentos, Unir, Comprimir), pulsa "Ver
    comando" para ver el ffmpeg exacto y "Añadir a la cola de edición". El progreso se ve en
    **Cola → Ediciones**. El original nunca se sobrescribe: se crea `nombre_editado.ext`.
14. Herramientas nuevas: Imagen (resolución, recorte, rotar, voltear), Velocidad, Audio
    (extraer, quitar, sustituir, volumen, fundidos, canales, frecuencia y normalizar en dos
    pasadas), Subtítulos (incrustar, grabar en la imagen, extraer), Marca de agua (imagen o
    texto), GIF/WebP, Capturas y Metadatos (con carátula en audio).
15. "Previsualizar resultado" genera 10 s del resultado y los reproduce.
16. **Ajustes → Editor → Aceleración por hardware → Detectar** prueba NVENC, Quick Sync y AMF;
    si una edición acelerada falla, se repite sola por CPU.
17. En el editor, pestaña **Experto**: escribe cualquier comando de ffmpeg con `{input}`,
    `{output}`, `{start}`/`{end}` (marcadores I/O), `{inputs[1]}`, `{dir}`, `{name}` y tus
    propios parámetros (`{crf}` con `crf=23`). "Filtros…" lista los de `ffmpeg -filters`,
    "Ejecutar ahora" muestra la salida en vivo y "Guardar como receta…" la guarda.
18. Desde cualquier herramienta, "Abrir en modo experto" copia su comando para retocarlo.
19. **Perfiles y recetas** (`Ctrl+5`) lista las recetas: abrir, renombrar, duplicar, favorita,
    eliminar, exportar e importar en JSON.
20. En Descargas, "Después de descargar" encadena una edición (convertir, recortar, comprimir a
    MB, normalizar, extraer audio, cambiar resolución o una receta) que entra sola en la cola
    de edición al terminar, con opción de borrar el original.
21. "Guardar como perfil…" guarda todas las opciones; en **Perfiles y recetas → Perfiles** se
    aplican, duplican, exportan/importan y se marca uno como predeterminado (se aplica al abrir).
22. **Historial** (`Ctrl+4`): búsqueda, filtro por resultado, volver a descargar con las mismas
    opciones, abrir archivo o carpeta, enviar al editor, borrar y vaciar. En Ajustes, "Evitar
    descargar dos veces lo mismo" activa `--download-archive` gestionado por la app.
23. **Ajustes → Actualizaciones**: canal de yt-dlp (estable o nightly), cada cuántas horas
    comprobar al arrancar, "Actualizar yt-dlp" y "Descargar o actualizar ffmpeg". Si hay versión
    nueva aparece un aviso arriba con un botón para actualizar.
24. Si falta yt-dlp o ffmpeg al arrancar, un asistente ofrece descargarlos a la carpeta de datos.
25. Arrastra enlaces o un `.txt` con enlaces a cualquier parte de la ventana (van a Descargas) o
    archivos de vídeo/audio (van al Editor).
26. Icono en la bandeja con mostrar, pausar/reanudar colas, abrir la carpeta y salir; el
    tooltip muestra el progreso. En **Ajustes → Windows**: seguir en la bandeja al cerrar,
    notificaciones (clic para abrir el resultado) y añadir/quitar el menú contextual.
27. Línea de comandos: `python -m bombastic --download <url>`, `--edit <archivo>` y
    `--action convert_mp4|extract_mp3|compress|"recipe:<nombre>" <archivos…>`. Si la app ya
    está abierta, los argumentos se pasan a esa ventana.

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
| 1 | MVP de descarga | Hecha |
| 2 | Cola | Hecha |
| 3 | Modo avanzado de yt-dlp | Hecha |
| 4 | Editor básico | Hecha |
| 5 | Editor completo | Hecha |
| 6 | Modo experto y recetas | Hecha |
| 7 | Perfiles, historial y encadenado | Hecha |
| 8 | Actualizaciones | Hecha |
| 9 | Integración con Windows | Hecha |
| 10 | Distribución (instalador, portable, GitHub Actions de release) | Hecha |
| 11 | Pulido y manual de usuario | Hecha |

## Preguntas frecuentes

**"Windows protegió tu PC" al instalar.** Es SmartScreen: avisa de todo ejecutable sin firma de
código o que se descarga poco. Pulsa "Más información" y "Ejecutar de todas formas". El script
de compilación deja preparada la firma con `signtool` para quien tenga un certificado.

**El antivirus borra o bloquea yt-dlp o ffmpeg.** Algunos antivirus marcan por error
ejecutables descargadores. Añade una excepción para la carpeta de la app y para
`%LOCALAPPDATA%\DescargadorBombastic\bin`; al arrancar, la app ofrece volver a descargarlos.

**No veo el menú contextual en Windows 11.** Está en "Mostrar más opciones" (o Mayús + clic
derecho). El menú moderno de Windows 11 exige un paquete MSIX y no se incluye.

**yt-dlp no descarga o da errores raros.** Las webs cambian a menudo: actualiza yt-dlp en
Ajustes → Actualizaciones (o con el aviso que sale al arrancar). Si sigue fallando, prueba el
canal nightly.

**Un vídeo pide iniciar sesión o tiene restricción de edad.** Activa las cookies en
Descargas → Opciones avanzadas → Cookies (de tu navegador o de un `cookies.txt`).

## Aviso

Eres responsable de respetar los derechos de autor y las condiciones de uso de cada web.
