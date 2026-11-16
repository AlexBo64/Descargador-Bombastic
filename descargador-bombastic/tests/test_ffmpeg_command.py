import os
from pathlib import Path

import pytest

from bombastic.core import ffmpeg_command as fc
from bombastic.core.ffmpeg_progress import FfmpegProgressParser
from bombastic.core.formatting import format_timecode, parse_timecode
from bombastic.core.media_probe import ProbeError, ProbeInfo, StreamInfo, parse_probe
from bombastic.core.output_paths import enough_space, safe_output

SRC = Path("C:/Vídeos/mi clip ñ's.mkv")
OUT = Path("C:/Vídeos/salida ñ.mp4")
C = list(fc.COMMON)


def probe(
    video: bool = True, audio: bool = True, duration: float | None = 10.0, **video_kw: object
) -> ProbeInfo:
    streams: list[StreamInfo] = []
    if video:
        values: dict[str, object] = {"width": 640, "height": 360, "fps": 30.0}
        values.update(video_kw)
        streams.append(StreamInfo(0, "video", str(values.pop("codec", "h264")), **values))  # type: ignore[arg-type]
    if audio:
        streams.append(StreamInfo(1, "audio", "aac", sample_rate=48000, channels=2))
    return ProbeInfo("mp4", duration, 1000, 800000, tuple(streams))


def test_timecodes() -> None:
    assert format_timecode(3723.0456) == "01:02:03.046"
    assert format_timecode(None) == ""
    assert parse_timecode("01:02:03.046") == pytest.approx(3723.046)
    assert parse_timecode("1:15") == 75
    assert parse_timecode("75,5") == 75.5
    for bad in ("", "a", "1:75", "-3", "1:2:3:4"):
        assert parse_timecode(bad) is None


def test_convert_video() -> None:
    plan = fc.build_convert(SRC, OUT, probe(), fc.ConvertOptions(preset="slow", crf=20))
    assert plan.passes == (
        (*C, "-i", str(SRC), "-c:v", "libx264", "-crf", "20", "-preset", "slow", "-pix_fmt",
         "yuv420p", "-c:a", "aac", "-b:a", "192k", "-sn", "-movflags", "+faststart", str(OUT)),
    )  # fmt: skip
    assert (plan.duration, plan.inputs, plan.tool) == (10.0, (SRC,), "convert")


def test_convert_variants() -> None:
    vp9 = fc.ConvertOptions("webm", "vp9", "opus", crf=31)
    args = fc.build_convert(SRC, OUT, probe(), vp9).passes[0]
    assert args[8:14] == ("-c:v", "libvpx-vp9", "-crf", "31", "-b:v", "0")
    bitrate = fc.ConvertOptions("mkv", "h265", "copy", quality_mode="bitrate", video_kbps=2500)
    args = fc.build_convert(SRC, Path("x.mkv"), probe(), bitrate).passes[0]
    assert "-b:v" in args and "2500k" in args and "-crf" not in args
    assert args[-3:-1] == ("-c:s", "copy") and "-movflags" not in args
    copy = fc.build_convert(SRC, OUT, probe(), fc.ConvertOptions("mp4", "copy", "copy"))
    assert copy.passes[0][len(C) : len(C) + 6] == ("-i", str(SRC), "-c:v", "copy", "-c:a", "copy")
    audio = fc.build_convert(SRC, Path("x.mp3"), probe(), fc.ConvertOptions("mp3", "h264", "copy"))
    assert audio.passes[0][len(C) + 2 :] == ("-vn", "-c:a", "libmp3lame", "-b:a", "192k", "x.mp3")
    m4a = fc.build_convert(SRC, Path("x.m4a"), probe(), fc.ConvertOptions("m4a", "h264", "copy"))
    assert m4a.passes[0][len(C) + 3 : len(C) + 5] == ("-c:a", "copy")
    wav = fc.build_convert(SRC, Path("x.wav"), probe(), fc.ConvertOptions("wav", "h264", "copy"))
    assert "pcm_s16le" in wav.passes[0]
    # Sin vídeo no se añaden opciones de vídeo.
    assert (
        "-c:v" not in fc.build_convert(SRC, OUT, probe(video=False), fc.ConvertOptions()).passes[0]
    )


def test_can_copy() -> None:
    assert fc.can_copy(probe(), "mp4")
    assert fc.can_copy(probe(codec="vp9"), "mkv")
    assert not fc.can_copy(probe(codec="vp9"), "mp4")
    assert not fc.can_copy(probe(), "webm")
    assert not fc.can_copy(probe(), "mp3")


def test_trim_fast_and_precise() -> None:
    fast = fc.build_trim(SRC, OUT, probe(), 1.5, 4.25, precise=False)
    assert fast.passes[0][len(C) :] == (
        "-ss", "00:00:01.500", "-to", "00:00:04.250", "-i", str(SRC), "-map", "0", "-c", "copy",
        "-avoid_negative_ts", "make_zero", "-movflags", "+faststart", str(OUT),
    )  # fmt: skip
    assert fast.duration == pytest.approx(2.75)
    precise = fc.build_trim(SRC, OUT, probe(video=False), 0, 2, precise=True).passes[0]
    assert precise[len(C) : len(C) + 6] == (
        "-i",
        str(SRC),
        "-ss",
        "00:00:00.000",
        "-to",
        "00:00:02.000",
    )
    assert "-c:v" not in precise and "aac" in precise
    with pytest.raises(ValueError):
        fc.build_trim(SRC, OUT, probe(), 3, 3, precise=False)


def test_segment_helpers() -> None:
    assert fc.normalize_segments([(5, 7), (1, 3), (2, 4), (9, 20), (8, 8)], 10) == [
        (1, 4),
        (5, 7),
        (9, 10),
    ]
    assert fc.invert_segments([(2, 3), (5, 6)], 10) == [(0, 2), (3, 5), (6, 10)]
    assert fc.invert_segments([(0, 10)], 10) == []


def test_build_segments() -> None:
    plan = fc.build_segments(SRC, OUT, probe(), [(1, 2), (4, 6)], remove=False)
    args = plan.passes[0]
    graph = args[args.index("-filter_complex") + 1]
    assert graph == (
        "[0:v]trim=start=1.000:end=2.000,setpts=PTS-STARTPTS[v0];"
        "[0:a]atrim=start=1.000:end=2.000,asetpts=PTS-STARTPTS[a0];"
        "[0:v]trim=start=4.000:end=6.000,setpts=PTS-STARTPTS[v1];"
        "[0:a]atrim=start=4.000:end=6.000,asetpts=PTS-STARTPTS[a1];"
        "[v0][a0][v1][a1]concat=n=2:v=1:a=1[v][a]"
    )
    assert plan.duration == 3
    removed = fc.build_segments(SRC, OUT, probe(video=False), [(0, 4)], remove=True)
    graph = removed.passes[0][removed.passes[0].index("-filter_complex") + 1]
    assert graph.endswith("[a0]concat=n=1:v=0:a=1[a]")
    assert removed.duration == 6
    with pytest.raises(ValueError):
        fc.build_segments(SRC, OUT, probe(), [(0, 10)], remove=True)


def test_concat_demuxer_and_filter(tmp_path: Path) -> None:
    a, b = Path("C:/a ñ.mp4"), Path("C:/b's.mp4")
    assert (
        fc.concat_list_text([a, b])
        == f"file '{a}'\nfile '{str(b).replace(chr(39), chr(39) + chr(92) + chr(39) + chr(39))}'\n"
    )
    listing = tmp_path / "lista.txt"
    demux = fc.build_concat([a, b], OUT, [probe(), probe(duration=5)], listing)
    assert demux.passes[0][len(C) :] == (
        "-f", "concat", "-safe", "0", "-i", str(listing), "-map", "0", "-c", "copy",
        "-movflags", "+faststart", str(OUT),
    )  # fmt: skip
    assert demux.duration == 15 and demux.temp_files == (listing,)

    recode = fc.build_concat([a, b], OUT, [probe(), probe(width=1920, height=1080)], listing)
    args = recode.passes[0]
    assert args.count("-i") == 2
    graph = args[args.index("-filter_complex") + 1]
    assert "[1:v]scale=640:360:force_original_aspect_ratio=decrease" in graph
    assert graph.endswith("[v0][a0][v1][a1]concat=n=2:v=1:a=1[v][a]")
    assert recode.temp_files == ()
    assert fc.build_concat([a, b], OUT, [probe(duration=None), probe()], listing).duration is None
    assert not fc.concat_compatible([probe()])
    with pytest.raises(ValueError):
        fc.build_concat([a], OUT, [probe()], listing)


def test_compress() -> None:
    crf = fc.build_compress_crf(SRC, OUT, probe(), 30).passes[0]
    assert crf[len(C) + 2 : len(C) + 6] == ("-c:v", "libx264", "-crf", "30")
    assert fc.target_video_kbps(10, 60, 128) == 1242
    assert fc.target_video_kbps(1, 3600, 128) == 100  # nunca menos de 100 kbps
    log = Path("C:/tmp/2pass")
    plan = fc.build_compress_size(SRC, OUT, probe(), 10, log)
    first, second = plan.passes
    assert ("-pass", "1", "-passlogfile", str(log), "-an", "-f") == first[-8:-2]
    assert first[-2:] == ("null", os.devnull)
    assert "-an" in first and "2" in second and second[-1] == str(OUT)
    kbps = f"{fc.target_video_kbps(10, 10, 128)}k"
    assert kbps in first and kbps in second
    assert plan.temp_files == (Path(f"{log}-0.log"), Path(f"{log}-0.log.mbtree"))
    with pytest.raises(ValueError):
        fc.build_compress_size(SRC, OUT, probe(duration=None), 10, log)


def test_progress_parser() -> None:
    parser = FfmpegProgressParser()
    lines = ["frame=10", "out_time_us=2500000", "speed=1.5x", "progress=continue"]
    results = [parser.feed(line) for line in lines]
    assert results[:3] == [None, None, None]
    assert results[3] is not None
    assert (results[3].out_time, results[3].speed, results[3].ended) == (2.5, 1.5, False)
    for line in ("out_time_us=N/A", "out_time=00:01:02.500000", "speed=N/A"):
        parser.feed(line)
    end = parser.feed("progress=end")
    assert end is not None and (end.out_time, end.speed, end.ended) == (62.5, None, True)
    assert parser.feed("basura") is None


def test_parse_probe() -> None:
    output = """{"streams": [
        {"index": 0, "codec_type": "video", "codec_name": "h264", "width": 1280, "height": 720,
         "avg_frame_rate": "30000/1001"},
        {"index": 1, "codec_type": "audio", "codec_name": "opus", "sample_rate": "48000",
         "channels": 2, "tags": {"language": "spa"}},
        {"index": 2, "codec_type": "video", "codec_name": "mjpeg",
         "disposition": {"attached_pic": 1}}
      ], "format": {"format_name": "matroska,webm", "duration": "12.5", "size": "999",
                    "bit_rate": "N/A"}}"""
    info = parse_probe(output)
    assert (info.container, info.duration, info.size, info.bitrate) == (
        "matroska,webm",
        12.5,
        999,
        None,
    )
    video = info.first("video")
    assert video is not None and video.fps == 29.97 and video.width == 1280
    audio = info.first("audio")
    assert audio is not None and (audio.language, audio.channels) == ("spa", 2)
    assert info.streams[2].attached_pic
    only_cover = ProbeInfo("mp3", 3, 1, 1, (info.streams[2],))
    assert not only_cover.has_video
    for bad in ("no json", "[]", '{"streams": []}'):
        with pytest.raises(ProbeError):
            parse_probe(bad)


def test_safe_output_and_space(tmp_path: Path) -> None:
    source = tmp_path / "vídeo ñ.mp4"
    source.write_bytes(b"x")
    first = safe_output(source, "mp4")
    assert first == tmp_path / "vídeo ñ_editado.mp4"
    first.write_bytes(b"x")
    assert safe_output(source, ".mp4") == tmp_path / "vídeo ñ_editado (1).mp4"
    (tmp_path / "vídeo ñ_editado (1).mp4").write_bytes(b"x")
    assert safe_output(source, "mp4").name == "vídeo ñ_editado (2).mp4"
    assert safe_output(source, "mp4", suffix="").name == "vídeo ñ (1).mp4"
    assert enough_space(tmp_path / "no" / "existe", 1)
    assert not enough_space(tmp_path, 10**18)
