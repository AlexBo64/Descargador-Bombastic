"""Constructor de los comandos de yt-dlp. Siempre listas de argumentos, nunca cadenas."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from bombastic.core.ytdlp_progress import DOWNLOAD_TEMPLATE, FILE_TEMPLATE, POSTPROCESS_TEMPLATE


class Preset(StrEnum):
    BEST = "best"
    P1080 = "1080p"
    P720 = "720p"
    P480 = "480p"
    MP3 = "mp3"
    M4A = "m4a"
    OPUS = "opus"
    FLAC = "flac"
    WAV = "wav"


_HEIGHTS: dict[Preset, int] = {Preset.P1080: 1080, Preset.P720: 720, Preset.P480: 480}
VIDEO_PRESETS: tuple[Preset, ...] = (Preset.BEST, Preset.P1080, Preset.P720, Preset.P480)
AUDIO_PRESETS: tuple[Preset, ...] = (Preset.MP3, Preset.M4A, Preset.OPUS, Preset.FLAC, Preset.WAV)

#: Calidades de MP3: kbps constantes o ``v0`` (bitrate variable de máxima calidad).
MP3_QUALITIES: tuple[str, ...] = ("128", "192", "320", "v0")
DEFAULT_MP3_QUALITY = "192"

DEFAULT_OUTPUT_TEMPLATE = "%(title)s [%(id)s].%(ext)s"
#: En listas de reproducción cada lista va a su carpeta y los archivos llevan su posición.
PLAYLIST_OUTPUT_TEMPLATE = "%(playlist_title)s/%(playlist_index)03d - " + DEFAULT_OUTPUT_TEMPLATE

#: Orden de preferencia para que el MP4 se reproduzca en cualquier sitio: H.264 + AAC.
_COMPATIBLE_SORT = "vcodec:h264,lang,quality,res,fps,hdr:12,acodec:aac"


@dataclass(frozen=True)
class DownloadOptions:
    output_dir: Path
    preset: Preset = Preset.BEST
    mp3_quality: str = DEFAULT_MP3_QUALITY
    #: Incrusta los subtítulos disponibles (solo vídeo).
    embed_subs: bool = False
    #: Incrusta la miniatura como carátula y los metadatos (título, autor, fecha…).
    embed_extras: bool = False
    #: El enlace es una lista de reproducción.
    playlist: bool = False
    #: Carpeta donde están ffmpeg y ffprobe, si no están en el PATH.
    ffmpeg_dir: Path | None = None


def is_audio(preset: Preset) -> bool:
    return preset in AUDIO_PRESETS


def _common_args() -> list[str]:
    # --no-playlist: si el enlace es un vídeo dentro de una lista, se trata solo el vídeo.
    # Un enlace que es una lista en sí se sigue tratando como lista.
    return ["--no-playlist", "--no-colors", "--encoding", "utf-8"]


def build_info_args(url: str) -> list[str]:
    """Argumentos para obtener los metadatos (título, miniatura, si es una lista…)."""
    return ["-J", "--flat-playlist", "--no-warnings", *_common_args(), "--", url]


def _format_args(options: DownloadOptions) -> list[str]:
    preset = options.preset
    if is_audio(preset):
        args = ["-f", "ba/b", "-x", "--audio-format", preset.value]
        if preset is Preset.MP3:
            quality = (
                options.mp3_quality if options.mp3_quality in MP3_QUALITIES else DEFAULT_MP3_QUALITY
            )
            args += ["--audio-quality", "0" if quality == "v0" else f"{quality}K"]
        return args
    height = _HEIGHTS.get(preset)
    sort = _COMPATIBLE_SORT if height is None else f"res:{height},{_COMPATIBLE_SORT}"
    return ["-f", "bv*+ba/b", "-S", sort, "--merge-output-format", "mp4", "--remux-video", "mp4"]


def build_download_args(url: str, options: DownloadOptions) -> list[str]:
    """Argumentos completos de una descarga, con progreso legible por la app."""
    args = [
        "--newline",
        *_common_args(),
        "--progress-template",
        DOWNLOAD_TEMPLATE,
        "--progress-template",
        POSTPROCESS_TEMPLATE,
        # --print activa el modo silencioso y la simulación: se desactivan los dos.
        "--print",
        FILE_TEMPLATE,
        "--no-quiet",
        "--no-simulate",
    ]
    if options.ffmpeg_dir is not None:
        args += ["--ffmpeg-location", str(options.ffmpeg_dir)]
    args += _format_args(options)
    if options.embed_subs and not is_audio(options.preset):
        args += ["--embed-subs", "--sub-langs", "all,-live_chat"]
    if options.embed_extras:
        args.append("--embed-metadata")
        # WAV no admite carátula.
        if options.preset is not Preset.WAV:
            args.append("--embed-thumbnail")
    template = PLAYLIST_OUTPUT_TEMPLATE if options.playlist else DEFAULT_OUTPUT_TEMPLATE
    args += ["-P", str(options.output_dir), "-o", template, "--", url]
    return args
