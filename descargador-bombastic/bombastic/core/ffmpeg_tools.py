"""Herramientas 6-14 del editor, previsualización, proxy y aceleración por hardware.

Igual que :mod:`ffmpeg_command`: todo devuelve un :class:`EditPlan` con listas de argumentos.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path

from bombastic.core.ffmpeg_command import COMMON, EditPlan, _faststart, _ts, audio_codec_args
from bombastic.core.media_probe import ProbeInfo

# ---------------------------------------------------------------- utilidades


def escape_filter_value(text: str) -> str:
    """Escapa un valor para un filtro de ``-vf``/``-filter_complex``.

    ffmpeg lo interpreta en dos niveles (primero el filtergraph y después la opción del filtro),
    así que se escapa dos veces con barras invertidas. Las rutas de Windows pasan a usar ``/``.
    """
    text = text.replace("\\", "/")
    for char in ("\\", "'", ":"):
        text = text.replace(char, "\\" + char)
    for char in ("\\", "'", "[", "]", ",", ";"):
        text = text.replace(char, "\\" + char)
    return text


def _video_encode() -> list[str]:
    return ["-c:v", "libx264", "-crf", "18", "-preset", "medium", "-pix_fmt", "yuv420p"]


def _plan(
    tool: str,
    args: list[str],
    output: Path,
    duration: float | None,
    inputs: Sequence[Path],
    **extra: object,
) -> EditPlan:
    return EditPlan(tool, ((*COMMON, *args),), output, duration, tuple(inputs), **extra)  # type: ignore[arg-type]


# ----------------------------------------------- 6. resolución, recorte, rotación


def transform_filters(
    width: int = 0,
    height: int = 0,
    crop: tuple[int, int, int, int] | None = None,
    rotate: int = 0,
    flip_h: bool = False,
    flip_v: bool = False,
) -> list[str]:
    """Filtros de imagen. ``0`` en ancho o alto conserva la proporción."""
    filters: list[str] = []
    if crop is not None:
        w, h, x, y = crop
        filters.append(f"crop={w}:{h}:{x}:{y}")
    if width or height:
        filters.append(f"scale={width or -2}:{height or -2}")
    filters += {90: ["transpose=1"], 180: ["transpose=1", "transpose=1"], 270: ["transpose=2"]}.get(
        rotate % 360, []
    )
    if flip_h:
        filters.append("hflip")
    if flip_v:
        filters.append("vflip")
    return filters


def build_transform(
    source: Path, output: Path, probe: ProbeInfo, filters: Sequence[str]
) -> EditPlan:
    if not filters:
        raise ValueError("nothing to change")
    args = ["-i", str(source), "-vf", ",".join(filters), *_video_encode()]
    args += ["-c:a", "copy"] if probe.has_audio else []
    args += [*_faststart(output), str(output)]
    return _plan("transform", args, output, probe.duration, [source])


# ---------------------------------------------------------------- 7. velocidad


def atempo_chain(factor: float) -> list[str]:
    """``atempo`` solo admite 0.5-2: se encadena para factores mayores o menores."""
    if factor <= 0:
        raise ValueError("factor must be positive")
    filters: list[str] = []
    while factor > 2.0:
        filters.append("atempo=2.0")
        factor /= 2.0
    while factor < 0.5:
        filters.append("atempo=0.5")
        factor /= 0.5
    filters.append(f"atempo={factor:.6g}")
    return filters


def build_speed(source: Path, output: Path, probe: ProbeInfo, factor: float) -> EditPlan:
    if factor <= 0 or factor == 1:
        raise ValueError("factor must be positive and not 1")
    args = ["-i", str(source)]
    if probe.has_video:
        args += ["-filter:v", f"setpts=PTS/{factor:.6g}", *_video_encode()]
    if probe.has_audio:
        args += ["-filter:a", ",".join(atempo_chain(factor)), *audio_codec_args("aac", 192)]
    args += [*_faststart(output), str(output)]
    duration = probe.duration / factor if probe.duration else None
    return _plan("speed", args, output, duration, [source])


# -------------------------------------------------------------------- 8. audio

#: Códec y opciones de cada formato de extracción de audio.
EXTRACT_FORMATS: dict[str, list[str]] = {
    "mp3": ["-c:a", "libmp3lame", "-q:a", "2"],
    "m4a": ["-c:a", "aac", "-b:a", "192k"],
    "wav": ["-c:a", "pcm_s16le"],
    "flac": ["-c:a", "flac"],
    "opus": ["-c:a", "libopus", "-b:a", "128k"],
}
LOUDNORM_TOKEN = "{loudnorm}"


def build_extract_audio(source: Path, output: Path, probe: ProbeInfo, fmt: str) -> EditPlan:
    args = ["-i", str(source), "-vn", *EXTRACT_FORMATS[fmt], *_faststart(output), str(output)]
    return _plan("audio", args, output, probe.duration, [source])


def build_remove_audio(source: Path, output: Path, probe: ProbeInfo) -> EditPlan:
    args = ["-i", str(source), "-map", "0", "-map", "-0:a", "-c", "copy", str(output)]
    return _plan("audio", args, output, probe.duration, [source])


def build_replace_audio(
    source: Path, audio: Path, output: Path, probe: ProbeInfo, shortest: bool = True
) -> EditPlan:
    args = ["-i", str(source), "-i", str(audio), "-map", "0:v", "-map", "1:a", "-c:v", "copy"]
    args += audio_codec_args("aac", 192)
    args += ["-shortest"] if shortest else []
    args += [*_faststart(output), str(output)]
    return _plan("audio", args, output, probe.duration, [source, audio])


def audio_filters(
    probe: ProbeInfo,
    volume_db: float = 0.0,
    fade_in: float = 0.0,
    fade_out: float = 0.0,
) -> list[str]:
    filters: list[str] = []
    if volume_db:
        filters.append(f"volume={volume_db:g}dB")
    if fade_in > 0:
        filters.append(f"afade=t=in:st=0:d={fade_in:g}")
    if fade_out > 0:
        if not probe.duration:
            raise ValueError("duration needed for a fade out")
        start = max(0.0, probe.duration - fade_out)
        filters.append(f"afade=t=out:st={start:.3f}:d={fade_out:g}")
    return filters


def _audio_output(probe: ProbeInfo, output: Path) -> list[str]:
    """Códec de audio según el contenedor; el vídeo (si lo hay) se copia."""
    suffix = output.suffix.lower().lstrip(".")
    codec = EXTRACT_FORMATS.get(suffix, ["-c:a", "aac", "-b:a", "192k"])
    return (["-c:v", "copy"] if probe.has_video else []) + codec


def build_audio_adjust(
    source: Path,
    output: Path,
    probe: ProbeInfo,
    filters: Sequence[str],
    channels: int = 0,
    sample_rate: int = 0,
) -> EditPlan:
    """Volumen, fundidos, canales y frecuencia de muestreo en una pasada."""
    if not filters and not channels and not sample_rate:
        raise ValueError("nothing to change")
    args = ["-i", str(source)]
    args += ["-af", ",".join(filters)] if filters else []
    args += ["-ac", str(channels)] if channels else []
    args += ["-ar", str(sample_rate)] if sample_rate else []
    args += [*_audio_output(probe, output), *_faststart(output), str(output)]
    return _plan("audio", args, output, probe.duration, [source])


def build_normalize(
    source: Path, output: Path, probe: ProbeInfo, target_lufs: float = -16.0
) -> EditPlan:
    """``loudnorm`` en dos pasadas: la primera mide y la segunda aplica las medidas."""
    base = f"loudnorm=I={target_lufs:g}:TP=-1.5:LRA=11"
    first = ["-i", str(source), "-af", f"{base}:print_format=json", "-vn", "-f", "null", "-"]
    second = ["-i", str(source), "-af", f"{base}:{LOUDNORM_TOKEN}:linear=true"]
    second += [*_audio_output(probe, output), *_faststart(output), str(output)]
    return EditPlan(
        "audio",
        ((*COMMON, *first), (*COMMON, *second)),
        output,
        probe.duration,
        (source,),
        analysis="loudnorm",
    )


def loudnorm_measurements(log_text: str) -> str | None:
    """Saca las medidas del JSON que escribe la primera pasada y las da como opciones."""
    start, end = log_text.rfind("{"), log_text.rfind("}")
    if start < 0 or end < start:
        return None
    try:
        data = json.loads(log_text[start : end + 1])
        values = {
            "measured_I": float(data["input_i"]),
            "measured_TP": float(data["input_tp"]),
            "measured_LRA": float(data["input_lra"]),
            "measured_thresh": float(data["input_thresh"]),
            "offset": float(data["target_offset"]),
        }
    except (ValueError, KeyError, TypeError):
        return None
    return ":".join(f"{key}={value:g}" for key, value in values.items())


def fill_analysis(
    passes: Sequence[Sequence[str]], analysis: str, log_text: str
) -> list[list[str]] | None:
    """Sustituye el marcador de las pasadas siguientes con lo medido. ``None`` si falla."""
    if analysis != "loudnorm":
        return [list(p) for p in passes]
    measured = loudnorm_measurements(log_text)
    if measured is None:
        return None
    return [[a.replace(LOUDNORM_TOKEN, measured) for a in p] for p in passes]


# --------------------------------------------------------------- 9. subtítulos


def build_embed_subtitles(source: Path, subs: Path, output: Path, probe: ProbeInfo) -> EditPlan:
    """Añade los subtítulos como pista (se pueden activar o no en el reproductor)."""
    codec = "mov_text" if output.suffix.lower() in (".mp4", ".mov") else "srt"
    if output.suffix.lower() == ".webm":
        codec = "webvtt"
    args = ["-i", str(source), "-i", str(subs), "-map", "0", "-map", "1", "-c", "copy"]
    args += ["-c:s", codec, *_faststart(output), str(output)]
    return _plan("subtitles", args, output, probe.duration, [source, subs])


def build_burn_subtitles(
    source: Path,
    subs: Path,
    output: Path,
    probe: ProbeInfo,
    font: str = "Arial",
    size: int = 24,
) -> EditPlan:
    """Graba los subtítulos en la imagen (siempre visibles; recodifica)."""
    style = escape_filter_value(f"FontName={font},FontSize={size}")
    graph = f"subtitles={escape_filter_value(str(subs))}:force_style={style}"
    args = ["-i", str(source), "-vf", graph, *_video_encode()]
    args += ["-c:a", "copy"] if probe.has_audio else []
    args += [*_faststart(output), str(output)]
    return _plan("subtitles", args, output, probe.duration, [source, subs])


def build_extract_subtitles(
    source: Path, output: Path, probe: ProbeInfo, track: int = 0
) -> EditPlan:
    args = ["-i", str(source), "-map", f"0:s:{track}", str(output)]
    return _plan("subtitles", args, output, probe.duration, [source])


# ------------------------------------------------------------ 10. marca de agua

#: Posiciones (expresiones de overlay/drawtext con un margen de 10 px).
POSITIONS: dict[str, tuple[str, str]] = {
    "top_left": ("10", "10"),
    "top_right": ("W-w-10", "10"),
    "bottom_left": ("10", "H-h-10"),
    "bottom_right": ("W-w-10", "H-h-10"),
    "center": ("(W-w)/2", "(H-h)/2"),
}
DEFAULT_FONT = Path("C:/Windows/Fonts/arial.ttf")


def build_image_watermark(
    source: Path,
    image: Path,
    output: Path,
    probe: ProbeInfo,
    position: str = "bottom_right",
    opacity: float = 0.8,
    scale: float = 0.2,
) -> EditPlan:
    """Superpone una imagen; ``scale`` es su ancho respecto al del vídeo."""
    x, y = POSITIONS[position]
    graph = (
        f"[1:v][0:v]scale2ref=w=iw*{scale:g}:h=ow/mdar[wm][base];"
        f"[wm]format=rgba,colorchannelmixer=aa={opacity:g}[wm2];"
        f"[base][wm2]overlay={x}:{y}[v]"
    )
    args = ["-i", str(source), "-i", str(image), "-filter_complex", graph, "-map", "[v]"]
    args += ["-map", "0:a?", *_video_encode(), "-c:a", "copy", *_faststart(output), str(output)]
    return _plan("watermark", args, output, probe.duration, [source, image])


def build_text_watermark(
    source: Path,
    output: Path,
    probe: ProbeInfo,
    text: str,
    position: str = "bottom_right",
    opacity: float = 0.8,
    size: int = 32,
    font_file: Path = DEFAULT_FONT,
) -> EditPlan:
    x, y = POSITIONS[position]
    x, y = x.replace("w", "tw").replace("W", "w"), y.replace("h", "th").replace("H", "h")
    graph = (
        f"drawtext=fontfile={escape_filter_value(str(font_file))}:"
        f"text={escape_filter_value(text)}:fontsize={size}:"
        f"fontcolor=white@{opacity:g}:borderw=2:bordercolor=black@{opacity:g}:x={x}:y={y}:"
        "expansion=none"
    )
    args = ["-i", str(source), "-vf", graph, *_video_encode()]
    args += ["-c:a", "copy"] if probe.has_audio else []
    args += [*_faststart(output), str(output)]
    return _plan("watermark", args, output, probe.duration, [source])


# --------------------------------------------------------------- 11. GIF / WebP


def build_animation(
    source: Path,
    output: Path,
    start: float,
    end: float,
    fps: int = 12,
    width: int = 480,
) -> EditPlan:
    """GIF con paleta optimizada o WebP animado (según la extensión de ``output``)."""
    if end <= start:
        raise ValueError("end must be after start")
    base = f"fps={fps},scale={width}:-1:flags=lanczos"
    args = ["-ss", _ts(start), "-to", _ts(end), "-i", str(source)]
    if output.suffix.lower() == ".webp":
        args += ["-vf", base, "-c:v", "libwebp", "-loop", "0", "-q:v", "70", "-an", str(output)]
    else:
        graph = f"{base},split[a][b];[a]palettegen=stats_mode=diff[p];[b][p]paletteuse=dither=bayer"
        args += ["-filter_complex", graph, "-loop", "0", str(output)]
    return _plan("animation", args, output, end - start, [source])


# ------------------------------------------------------------------ 12. capturas


def build_snapshot(source: Path, output: Path, at: float) -> EditPlan:
    args = ["-ss", _ts(at), "-i", str(source), "-frames:v", "1", "-update", "1", str(output)]
    return _plan("snapshot", args, output, None, [source])


def build_snapshots_every(
    source: Path, folder: Path, probe: ProbeInfo, every: float, stem: str
) -> EditPlan:
    """Un fotograma cada ``every`` segundos en ``folder`` (``stem_0001.png``…)."""
    if every <= 0:
        raise ValueError("interval must be positive")
    pattern = folder / f"{stem}_%04d.png"
    args = ["-i", str(source), "-vf", f"fps=1/{every:g}", "-fps_mode", "vfr", str(pattern)]
    return _plan("snapshot", args, folder, probe.duration, [source])


# ------------------------------------------------------- 13. metadatos y carátula

METADATA_FIELDS: tuple[str, ...] = ("title", "artist", "album", "date", "genre", "comment")


def build_metadata(
    source: Path,
    output: Path,
    probe: ProbeInfo,
    tags: Mapping[str, str],
    cover: Path | None = None,
) -> EditPlan:
    """Cambia etiquetas sin recodificar y, opcionalmente, la carátula (archivos de audio)."""
    args = ["-i", str(source)]
    inputs = [source]
    if cover is not None:
        args += ["-i", str(cover), "-map", "0:a", "-map", "1:v", "-disposition:v:0", "attached_pic"]
        inputs.append(cover)
    else:
        args += ["-map", "0"]
    args += ["-c", "copy"]
    for key, value in tags.items():
        args += ["-metadata", f"{key}={value}"]
    if output.suffix.lower() == ".mp3":
        args += ["-id3v2_version", "3"]
    args.append(str(output))
    return _plan("metadata", args, output, probe.duration, inputs)


# ------------------------------------------------------- previsualización y proxy

PREVIEW_SECONDS = 10.0


def preview_plan(
    plan: EditPlan, start: float, output: Path, length: float = PREVIEW_SECONDS
) -> EditPlan | None:
    """Versión corta de un plan (de ``start``, ``length`` segundos) para comprobar el resultado.

    Solo para planes de una pasada que producen vídeo o audio; ``None`` si no se puede.
    """
    if len(plan.passes) != 1 or plan.tool in ("snapshot", "concat"):
        return None
    args = list(plan.passes[0])
    try:
        first_input = args.index("-i")
    except ValueError:
        return None
    # Si el plan ya recorta con -ss/-to delante de la entrada, se previsualiza ese tramo.
    args[-1] = str(output)
    if "-ss" in args[:first_input]:
        return replace(plan, passes=(tuple(args),), output=output, temp_files=(), cpu_fallback=())
    args[first_input:first_input] = ["-ss", _ts(max(0.0, start)), "-t", f"{length:g}"]
    return replace(
        plan, passes=(tuple(args),), output=output, duration=length, temp_files=(), cpu_fallback=()
    )


def build_proxy(source: Path, output: Path, probe: ProbeInfo) -> EditPlan:
    """Copia ligera (H.264 480p) que QtMultimedia siempre puede reproducir."""
    args = ["-i", str(source)]
    if probe.has_video:
        args += ["-vf", "scale=-2:480", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28"]
        args += ["-pix_fmt", "yuv420p"]
    if probe.has_audio:
        args += audio_codec_args("aac", 128)
    args += [*_faststart(output), str(output)]
    return _plan("proxy", args, output, probe.duration, [source])


# ------------------------------------------------------- aceleración por hardware

#: Codificadores por hardware de H.264 y H.265 de cada fabricante.
HW_ENCODERS: dict[str, dict[str, str]] = {
    "nvenc": {"libx264": "h264_nvenc", "libx265": "hevc_nvenc"},
    "qsv": {"libx264": "h264_qsv", "libx265": "hevc_qsv"},
    "amf": {"libx264": "h264_amf", "libx265": "hevc_amf"},
}
_ENCODER_LINE = re.compile(r"^\s*V\S*\s+(\S+)", re.M)


def parse_encoders(text: str) -> set[str]:
    """Nombres de codificadores de vídeo de ``ffmpeg -encoders``."""
    return set(_ENCODER_LINE.findall(text))


def listed_hw(encoders: set[str]) -> list[str]:
    """Fabricantes cuyo codificador H.264 aparece en la lista (aún sin probar)."""
    return [hw for hw, mapping in HW_ENCODERS.items() if mapping["libx264"] in encoders]


def hw_test_args(hw: str) -> list[str]:
    """Prueba rápida: codifica medio segundo sintético y lo descarta."""
    encoder = HW_ENCODERS[hw]["libx264"]
    return [
        "-hide_banner", "-nostdin", "-v", "error", "-f", "lavfi", "-i",
        "color=c=black:s=256x256:d=0.5", "-c:v", encoder, "-f", "null", "-",
    ]  # fmt: skip


def _hw_quality(hw: str, crf: str) -> list[str]:
    if hw == "nvenc":
        return ["-cq", crf]
    if hw == "qsv":
        return ["-global_quality", crf]
    return ["-rc", "cqp", "-qp_i", crf, "-qp_p", crf]


def apply_hw(plan: EditPlan, hw: str) -> EditPlan:
    """Cambia libx264/libx265 por el codificador por hardware, conservando la vía por CPU.

    Las pasadas dobles (``-pass``) no se tocan: los codificadores por hardware no las admiten.
    """
    mapping = HW_ENCODERS.get(hw)
    if mapping is None or any("-pass" in p for p in plan.passes):
        return plan
    changed = False
    new_passes: list[tuple[str, ...]] = []
    for args in plan.passes:
        out: list[str] = []
        i = 0
        while i < len(args):
            arg = args[i]
            if arg == "-c:v" and i + 1 < len(args) and args[i + 1] in mapping:
                out += ["-c:v", mapping[args[i + 1]]]
                changed = True
                i += 2
                continue
            if changed and arg == "-crf" and i + 1 < len(args):
                out += _hw_quality(hw, args[i + 1])
                i += 2
                continue
            if changed and arg == "-preset" and i + 1 < len(args):
                i += 2  # los presets de x264 no valen para el hardware
                continue
            out.append(arg)
            i += 1
        new_passes.append(tuple(out))
    if not changed:
        return plan
    return replace(plan, passes=tuple(new_passes), cpu_fallback=plan.passes)
