# Descargador Bombastic

Aplicación de escritorio para Windows 10/11 que pone una interfaz gráfica a
[yt-dlp](https://github.com/yt-dlp/yt-dlp) (descargas) y a [ffmpeg](https://ffmpeg.org) (edición
de vídeo y audio).

> **Estado: Fase 7 (Perfiles, historial y encadenado).** Perfiles de opciones, historial con
> búsqueda y acciones de edición encadenadas a cada descarga.
>
> **Fase 6 (Modo experto y recetas):** Comandos de ffmpeg a mano con variables,
> lista de filtros, recetas reutilizables y "Abrir en modo experto" desde cualquier herramienta.
>
> **Fase 5 (Editor completo):** Las 14 herramientas del editor, previsualización del
> resultado, copia ligera para formatos que el reproductor no abre y aceleración por hardware.
>
> **Fase 4 (Editor básico):** Editor con reproductor, marcadores I/O y las
> herramientas convertir, recortar, varios tramos, unir y comprimir, con cola de edición.
>
> **Fase 3 (Modo avanzado de yt-dlp):** Además de lo anterior, todas las opciones
> de yt-dlp, cookies, argumentos libres y selector manual de formatos.
>
> **Fase 2 (Cola):** Se pegan enlaces, se ve su información y se descargan con
> progreso en varios formatos, en una cola persistente con descargas simultáneas, pausa,
> reanudación, reintentos y errores explicados en español. El modo avanzado y el editor llegan
> en las fases siguientes.

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
| 8 | Actualizaciones | Pendiente |
| 9 | Integración con Windows | Pendiente |
| 10 | Distribución (instalador, portable, GitHub Actions de release) | Pendiente |
| 11 | Pulido y manual de usuario | Pendiente |

## Preguntas frecuentes

Las entradas sobre SmartScreen, antivirus, cookies y "yt-dlp no descarga" se añadirán cuando
existan las funciones correspondientes (fases 1, 3, 8 y 10).

## Aviso

Eres responsable de respetar los derechos de autor y las condiciones de uso de cada web.
