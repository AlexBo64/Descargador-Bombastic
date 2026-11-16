"""Constructores de los comandos de ffmpeg de las herramientas del editor.

Cada herramienta devuelve un :class:`EditPlan`: una o varias pasadas (listas de argumentos,
nunca cadenas para la shell), el archivo de salida y la duración esperada del resultado, que
sirve para calcular el progreso a partir de ``out_time``.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from bombastic.core.formatting import format_timecode
from bombastic.core.media_probe import ProbeInfo

#: Va delante de cada pasada: progreso legible por la app y sin preguntas por consola.
#: ``-y`` es seguro porque la salida siempre es un archivo nuevo (ver ``output_paths``).
COMMON = ("-hide_banner", "-nostdin", "-y", "-nostats", "-progress", "pipe:1")

VIDEO_CODECS: dict[str, str] = {
    "h264": "libx264",
    "h265": "libx265",
    "vp9": "libvpx-vp9",
    "av1": "libsvtav1",
    "prores": "prores_ks",
    "copy": "copy",
}
AUDIO_CODECS: dict[str, str] = {
    "aac": "aac",
    "mp3": "libmp3lame",
    "opus": "libopus",
    "flac": "flac",
    "pcm": "pcm_s16le",
    "copy": "copy",
}
VIDEO_CONTAINERS: tuple[str, ...] = ("mp4", "mkv", "webm", "mov")
AUDIO_CONTAINERS: tuple[str, ...] = ("mp3", "m4a", "opus", "flac", "wav")
CONTAINERS: tuple[str, ...] = (*VIDEO_CONTAINERS, *AUDIO_CONTAINERS)
#: Códec de audio natural de cada contenedor solo de audio.
AUDIO_FOR_CONTAINER: dict[str, str] = {
    "mp3": "mp3",
    "m4a": "aac",
    "opus": "opus",
    "flac": "flac",
    "wav": "pcm",
}
#: Nombre que da ffprobe a cada códec de audio de la app.
_CODEC_NAMES: dict[str, str] = {
    "aac": "aac",
    "mp3": "mp3",
    "opus": "opus",
    "flac": "flac",
    "pcm": "pcm_s16le",
}
X26X_PRESETS: tuple[str, ...] = (
    "ultrafast",
    "superfast",
    "veryfast",
    "faster",
    "fast",
    "medium",
    "slow",
    "slower",
    "veryslow",
)
DEFAULT_AUDIO_KBPS = 128


@dataclass(frozen=True)
class EditPlan:
    tool: str
    passes: tuple[tuple[str, ...], ...]
    output: Path
    #: Segundos del resultado (para el progreso); ``None`` si no se sabe.
    duration: float | None
    inputs: tuple[Path, ...] = ()
    #: Archivos temporales que se borran al terminar (lista de concat, logs de 2 pasadas).
    temp_files: tuple[Path, ...] = field(default_factory=tuple)


def _ts(seconds: float) -> str:
    return format_timecode(seconds)


def _faststart(output: Path) -> list[str]:
    return ["-movflags", "+faststart"] if output.suffix.lower() in (".mp4", ".mov", ".m4a") else []


# ------------------------------------------------------------------- convertir


@dataclass(frozen=True)
class ConvertOptions:
    container: str = "mp4"
    video_codec: str = "h264"
    audio_codec: str = "aac"
    #: ``crf`` o ``bitrate``.
    quality_mode: str = "crf"
    crf: int = 23
    video_kbps: int = 4000
    audio_kbps: int = 192
    preset: str = "medium"


def video_codec_args(codec: str, options: ConvertOptions) -> list[str]:
    encoder = VIDEO_CODECS[codec]
    args = ["-c:v", encoder]
    if codec == "copy":
        return args
    if codec == "prores":
        return [*args, "-profile:v", "3"]
    if options.quality_mode == "bitrate":
        args += ["-b:v", f"{options.video_kbps}k"]
    elif codec == "vp9":
        args += ["-crf", str(options.crf), "-b:v", "0"]
    else:
        args += ["-crf", str(options.crf)]
    if codec in ("h264", "h265") and options.preset in X26X_PRESETS:
        args += ["-preset", options.preset]
    if codec == "h264":
        # Máxima compatibilidad con reproductores.
        args += ["-pix_fmt", "yuv420p"]
    return args


def audio_codec_args(codec: str, kbps: int) -> list[str]:
    args = ["-c:a", AUDIO_CODECS[codec]]
    if codec in ("aac", "mp3", "opus"):
        args += ["-b:a", f"{kbps}k"]
    return args


def build_convert(
    source: Path, output: Path, probe: ProbeInfo, options: ConvertOptions
) -> EditPlan:
    args = ["-i", str(source)]
    if options.container in AUDIO_CONTAINERS:
        # Cada contenedor de audio admite su códec: solo se copia si el original ya lo es.
        codec = AUDIO_FOR_CONTAINER[options.container]
        source_audio = probe.first("audio")
        source_codec = source_audio.codec if source_audio is not None else ""
        if options.audio_codec == "copy" and _CODEC_NAMES.get(codec) == source_codec:
            codec = "copy"
        args += ["-vn", *audio_codec_args(codec, options.audio_kbps)]
    else:
        if probe.has_video:
            args += video_codec_args(options.video_codec, options)
        if probe.has_audio:
            args += audio_codec_args(options.audio_codec, options.audio_kbps)
        args += ["-sn"] if options.container in ("mp4", "mov", "webm") else ["-c:s", "copy"]
    args += [*_faststart(output), str(output)]
    return EditPlan("convert", ((*COMMON, *args),), output, probe.duration, (source,))


def can_copy(probe: ProbeInfo, container: str) -> bool:
    """Si el contenedor admite los códecs actuales sin recodificar (aproximado)."""
    video = probe.first("video")
    audio = probe.first("audio")
    allowed: dict[str, tuple[set[str], set[str]]] = {
        "mp4": ({"h264", "hevc", "av1", "mpeg4"}, {"aac", "mp3", "opus", "flac", "ac3"}),
        "mov": ({"h264", "hevc", "prores", "mpeg4"}, {"aac", "mp3", "pcm_s16le", "alac"}),
        "webm": ({"vp8", "vp9", "av1"}, {"opus", "vorbis"}),
        "mkv": (set(), set()),  # Matroska admite casi todo
    }
    if container not in allowed:
        return False
    videos, audios = allowed[container]
    if container == "mkv":
        return True
    return (video is None or video.codec in videos) and (audio is None or audio.codec in audios)


# --------------------------------------------------------------------- recortar


def build_trim(
    source: Path, output: Path, probe: ProbeInfo, start: float, end: float, precise: bool
) -> EditPlan:
    """Recorta ``[start, end]``. Rápido = sin recodificar (corta en fotogramas clave)."""
    if end <= start:
        raise ValueError("end must be after start")
    if precise:
        args = ["-i", str(source), "-ss", _ts(start), "-to", _ts(end)]
        if probe.has_video:
            args += ["-c:v", "libx264", "-crf", "18", "-preset", "medium", "-pix_fmt", "yuv420p"]
        if probe.has_audio:
            args += audio_codec_args("aac", 192)
    else:
        args = ["-ss", _ts(start), "-to", _ts(end), "-i", str(source), "-map", "0"]
        args += ["-c", "copy", "-avoid_negative_ts", "make_zero"]
    args += [*_faststart(output), str(output)]
    return EditPlan("trim", ((*COMMON, *args),), output, end - start, (source,))


# ----------------------------------------------------------- varios fragmentos

Segment = tuple[float, float]


def normalize_segments(segments: Sequence[Segment], duration: float | None) -> list[Segment]:
    """Ordena, recorta a la duración y une los tramos que se solapan."""
    result: list[Segment] = []
    limit = duration if duration is not None else float("inf")
    for start, end in sorted(segments):
        start, end = max(0.0, start), min(end, limit)
        if end <= start:
            continue
        if result and start <= result[-1][1]:
            result[-1] = (result[-1][0], max(result[-1][1], end))
        else:
            result.append((start, end))
    return result


def invert_segments(segments: Sequence[Segment], duration: float) -> list[Segment]:
    """Tramos que quedan al eliminar ``segments`` de ``[0, duration]``."""
    kept: list[Segment] = []
    cursor = 0.0
    for start, end in normalize_segments(segments, duration):
        if start > cursor:
            kept.append((cursor, start))
        cursor = end
    if cursor < duration:
        kept.append((cursor, duration))
    return kept


def build_segments(
    source: Path,
    output: Path,
    probe: ProbeInfo,
    segments: Sequence[Segment],
    remove: bool,
) -> EditPlan:
    """Conserva (o elimina, si ``remove``) varios tramos y une el resultado recodificando."""
    if remove:
        if probe.duration is None:
            raise ValueError("duration needed to remove segments")
        kept = invert_segments(segments, probe.duration)
    else:
        kept = normalize_segments(segments, probe.duration)
    if not kept:
        raise ValueError("no segments")
    video, audio = probe.has_video, probe.has_audio
    parts: list[str] = []
    labels: list[str] = []
    for i, (start, end) in enumerate(kept):
        if video:
            parts.append(f"[0:v]trim=start={start:.3f}:end={end:.3f},setpts=PTS-STARTPTS[v{i}]")
            labels.append(f"[v{i}]")
        if audio:
            parts.append(f"[0:a]atrim=start={start:.3f}:end={end:.3f},asetpts=PTS-STARTPTS[a{i}]")
            labels.append(f"[a{i}]")
    outs = ("[v]" if video else "") + ("[a]" if audio else "")
    parts.append(f"{''.join(labels)}concat=n={len(kept)}:v={int(video)}:a={int(audio)}{outs}")
    args = ["-i", str(source), "-filter_complex", ";".join(parts)]
    if video:
        args += ["-map", "[v]", "-c:v", "libx264", "-crf", "18", "-preset", "medium"]
        args += ["-pix_fmt", "yuv420p"]
    if audio:
        args += ["-map", "[a]", *audio_codec_args("aac", 192)]
    args += [*_faststart(output), str(output)]
    total = sum(end - start for start, end in kept)
    return EditPlan("segments", ((*COMMON, *args),), output, total, (source,))


# ------------------------------------------------------------------------ unir


def concat_compatible(probes: Sequence[ProbeInfo]) -> bool:
    """Los archivos se pueden unir sin recodificar (mismos códecs y parámetros)."""

    def signature(probe: ProbeInfo) -> tuple[object, ...]:
        video, audio = probe.first("video"), probe.first("audio")
        return (
            (video.codec, video.width, video.height) if video else None,
            (audio.codec, audio.sample_rate, audio.channels) if audio else None,
        )

    return len(probes) > 1 and len({signature(p) for p in probes}) == 1


def concat_list_text(sources: Sequence[Path]) -> str:
    """Contenido de la lista del demuxer concat (comillas simples escapadas)."""
    lines = []
    for source in sources:
        escaped = str(source).replace("'", "'\\''")
        lines.append(f"file '{escaped}'")
    return "\n".join(lines) + "\n"


def build_concat(
    sources: Sequence[Path],
    output: Path,
    probes: Sequence[ProbeInfo],
    list_file: Path,
) -> EditPlan:
    """Une archivos. Con el demuxer concat si son compatibles; si no, recodificando.

    En el modo de recodificación todo se ajusta a la resolución y fps del primer archivo.
    ``list_file`` es donde se escribe la lista del demuxer (la escribe quien ejecuta el plan).
    """
    if len(sources) < 2 or len(sources) != len(probes):
        raise ValueError("need at least two files with their probes")
    durations = [p.duration for p in probes]
    total = sum(d for d in durations if d is not None) if None not in durations else None
    if concat_compatible(probes):
        copy = ["-f", "concat", "-safe", "0", "-i", str(list_file), "-map", "0", "-c", "copy"]
        copy += [*_faststart(output), str(output)]
        return EditPlan("concat", ((*COMMON, *copy),), output, total, tuple(sources), (list_file,))

    first_video = next((p.first("video") for p in probes if p.has_video), None)
    video = first_video is not None and all(p.has_video for p in probes)
    audio = all(p.has_audio for p in probes)
    args: list[str] = []
    for source in sources:
        args += ["-i", str(source)]
    parts: list[str] = []
    labels: list[str] = []
    for i in range(len(sources)):
        if video and first_video is not None:
            width, height = first_video.width or 1280, first_video.height or 720
            fps = first_video.fps or 30
            parts.append(
                f"[{i}:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
                f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps:g}[v{i}]"
            )
            labels.append(f"[v{i}]")
        if audio:
            parts.append(f"[{i}:a]aresample=48000,aformat=channel_layouts=stereo[a{i}]")
            labels.append(f"[a{i}]")
    outs = ("[v]" if video else "") + ("[a]" if audio else "")
    parts.append(f"{''.join(labels)}concat=n={len(sources)}:v={int(video)}:a={int(audio)}{outs}")
    args += ["-filter_complex", ";".join(parts)]
    if video:
        args += ["-map", "[v]", "-c:v", "libx264", "-crf", "20", "-preset", "medium"]
        args += ["-pix_fmt", "yuv420p"]
    if audio:
        args += ["-map", "[a]", *audio_codec_args("aac", 192)]
    args += [*_faststart(output), str(output)]
    return EditPlan("concat", ((*COMMON, *args),), output, total, tuple(sources))


# -------------------------------------------------------------------- comprimir


def target_video_kbps(target_mb: float, duration: float, audio_kbps: int) -> int:
    """Bitrate de vídeo para que el archivo ocupe ``target_mb`` MB (MiB)."""
    total_kbit = target_mb * 1024 * 1024 * 8 / 1000
    # Un 2 % de margen para el contenedor.
    return max(100, int(total_kbit * 0.98 / duration) - audio_kbps)


def build_compress_crf(source: Path, output: Path, probe: ProbeInfo, crf: int) -> EditPlan:
    args = ["-i", str(source)]
    if probe.has_video:
        args += ["-c:v", "libx264", "-crf", str(crf), "-preset", "medium", "-pix_fmt", "yuv420p"]
    if probe.has_audio:
        args += audio_codec_args("aac", DEFAULT_AUDIO_KBPS)
    args += [*_faststart(output), str(output)]
    return EditPlan("compress", ((*COMMON, *args),), output, probe.duration, (source,))


def build_compress_size(
    source: Path, output: Path, probe: ProbeInfo, target_mb: float, passlog: Path
) -> EditPlan:
    """Dos pasadas con el bitrate calculado para llegar al tamaño pedido."""
    if not probe.duration:
        raise ValueError("duration needed for a target size")
    audio_kbps = DEFAULT_AUDIO_KBPS if probe.has_audio else 0
    kbps = target_video_kbps(target_mb, probe.duration, audio_kbps)
    video = ["-c:v", "libx264", "-b:v", f"{kbps}k", "-preset", "medium", "-pix_fmt", "yuv420p"]
    log = ["-passlogfile", str(passlog)]
    first = ["-i", str(source), *video, "-pass", "1", *log, "-an", "-f", "null", os.devnull]
    second = ["-i", str(source), *video, "-pass", "2", *log]
    if probe.has_audio:
        second += audio_codec_args("aac", audio_kbps)
    second += [*_faststart(output), str(output)]
    temp = (Path(f"{passlog}-0.log"), Path(f"{passlog}-0.log.mbtree"))
    return EditPlan(
        "compress",
        ((*COMMON, *first), (*COMMON, *second)),
        output,
        probe.duration,
        (source,),
        temp,
    )
