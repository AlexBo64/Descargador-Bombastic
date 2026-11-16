from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from bombastic.context import AppContext
from bombastic.core import ffmpeg_command as fc
from bombastic.core import ffmpeg_tools as ft
from bombastic.core.edit_manager import EditManager, EditState
from bombastic.core.hwaccel import HwProbe
from bombastic.core.media_probe import ProbeInfo, StreamInfo
from bombastic.core.ytdlp_runner import Launcher
from bombastic.ui.editor_page import EditorPage
from bombastic.ui.settings_page import SettingsPage

TIMEOUT = 20_000
SRC = Path("C:/v/clip ñ.mp4")
OUT = Path("C:/v/out.mp4")
C = len(fc.COMMON)
VIDEO = StreamInfo(0, "video", "h264", 640, 360, 30.0)
AUDIO = StreamInfo(1, "audio", "aac", sample_rate=48000, channels=2)
PROBE = ProbeInfo("mp4", 10.0, 1, 1, (VIDEO, AUDIO))
AUDIO_ONLY = ProbeInfo("mp3", 10.0, 1, 1, (AUDIO,))


def test_transform_filters_and_plan() -> None:
    assert ft.transform_filters() == []
    assert ft.transform_filters(1280, 0, (100, 50, 4, 8), 90, True, True) == [
        "crop=100:50:4:8",
        "scale=1280:-2",
        "transpose=1",
        "hflip",
        "vflip",
    ]
    assert ft.transform_filters(rotate=180) == ["transpose=1", "transpose=1"]
    assert ft.transform_filters(rotate=270) == ["transpose=2"]
    plan = ft.build_transform(SRC, OUT, PROBE, ["hflip"])
    assert plan.passes[0][C : C + 4] == ("-i", str(SRC), "-vf", "hflip")
    with pytest.raises(ValueError):
        ft.build_transform(SRC, OUT, PROBE, [])


def test_speed() -> None:
    assert ft.atempo_chain(1.5) == ["atempo=1.5"]
    assert ft.atempo_chain(4) == ["atempo=2.0", "atempo=2"]
    assert ft.atempo_chain(5) == ["atempo=2.0", "atempo=2.0", "atempo=1.25"]
    assert ft.atempo_chain(0.25) == ["atempo=0.5", "atempo=0.5"]
    plan = ft.build_speed(SRC, OUT, PROBE, 4)
    args = plan.passes[0]
    assert args[args.index("-filter:v") + 1] == "setpts=PTS/4"
    assert args[args.index("-filter:a") + 1] == "atempo=2.0,atempo=2"
    assert plan.duration == 2.5
    assert "-filter:v" not in ft.build_speed(SRC, OUT, AUDIO_ONLY, 2).passes[0]
    for bad in (0, 1, -2):
        with pytest.raises(ValueError):
            ft.build_speed(SRC, OUT, PROBE, bad)


def test_audio_tools() -> None:
    extract = ft.build_extract_audio(SRC, Path("a.mp3"), PROBE, "mp3").passes[0]
    assert extract[C:] == ("-i", str(SRC), "-vn", "-c:a", "libmp3lame", "-q:a", "2", "a.mp3")
    remove = ft.build_remove_audio(SRC, OUT, PROBE).passes[0]
    assert remove[C:] == ("-i", str(SRC), "-map", "0", "-map", "-0:a", "-c", "copy", str(OUT))
    replace = ft.build_replace_audio(SRC, Path("n.wav"), OUT, PROBE)
    assert replace.inputs == (SRC, Path("n.wav"))
    assert "-shortest" in replace.passes[0]
    assert ft.audio_filters(PROBE, -3, 1.5, 2) == [
        "volume=-3dB",
        "afade=t=in:st=0:d=1.5",
        "afade=t=out:st=8.000:d=2",
    ]
    with pytest.raises(ValueError):
        ft.audio_filters(ProbeInfo("x", None, 1, 1, ()), fade_out=1)
    adjust = ft.build_audio_adjust(SRC, Path("x.wav"), AUDIO_ONLY, [], 1, 44100).passes[0]
    assert adjust[C:] == ("-i", str(SRC), "-ac", "1", "-ar", "44100", "-c:a", "pcm_s16le", "x.wav")
    video_adjust = ft.build_audio_adjust(SRC, OUT, PROBE, ["volume=2dB"]).passes[0]
    assert "-c:v" in video_adjust and "copy" in video_adjust
    with pytest.raises(ValueError):
        ft.build_audio_adjust(SRC, OUT, PROBE, [])


def test_loudnorm_two_passes() -> None:
    plan = ft.build_normalize(SRC, OUT, PROBE, -14)
    first, second = plan.passes
    assert plan.analysis == "loudnorm"
    assert "loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json" in first
    assert first[-3:] == ("-f", "null", "-")
    log = (
        'ruido\n{\n "input_i" : "-21.75", "input_tp" : "-18.06", "input_lra" : "0.00",\n'
        ' "input_thresh" : "-31.75", "target_offset" : "-0.05"\n}\n'
    )
    measured = ft.loudnorm_measurements(log)
    assert measured == (
        "measured_I=-21.75:measured_TP=-18.06:measured_LRA=0:measured_thresh=-31.75:offset=-0.05"
    )
    filled = ft.fill_analysis([second], "loudnorm", log)
    assert filled is not None
    assert f"loudnorm=I=-14:TP=-1.5:LRA=11:{measured}:linear=true" in filled[0]
    assert ft.fill_analysis([second], "loudnorm", "sin medidas") is None
    assert ft.fill_analysis([("a",)], "", "") == [["a"]]


def test_filter_escaping_subtitles_and_text() -> None:
    assert ft.escape_filter_value(r"C:\Subs\a'b.srt") == r"C\\:/Subs/a\\\'b.srt"
    assert ft.escape_filter_value("a,b;[c]") == r"a\,b\;\[c\]"
    burn = ft.build_burn_subtitles(SRC, Path("C:/s.srt"), OUT, PROBE, "Arial", 30).passes[0]
    graph = burn[burn.index("-vf") + 1]
    assert graph == r"subtitles=C\\:/s.srt:force_style=FontName=Arial\,FontSize=30"
    soft = ft.build_embed_subtitles(SRC, Path("s.srt"), OUT, PROBE).passes[0]
    assert soft[-5:] == ("-c:s", "mov_text", "-movflags", "+faststart", str(OUT))
    assert "srt" in ft.build_embed_subtitles(SRC, Path("s.srt"), Path("o.mkv"), PROBE).passes[0]
    text = ft.build_text_watermark(SRC, OUT, PROBE, "Hola: 'ñ'", "bottom_right").passes[0]
    graph = text[text.index("-vf") + 1]
    assert r"text=Hola\\: \\\'ñ\\\'" in graph
    assert "x=w-tw-10:y=h-th-10" in graph and graph.endswith("expansion=none")
    image = ft.build_image_watermark(SRC, Path("l.png"), OUT, PROBE, "center", 0.5, 0.25)
    graph = image.passes[0][image.passes[0].index("-filter_complex") + 1]
    assert "scale2ref=w=iw*0.25" in graph and "aa=0.5" in graph
    assert graph.endswith("overlay=(W-w)/2:(H-h)/2[v]")


def test_animation_snapshots_metadata() -> None:
    gif = ft.build_animation(SRC, Path("a.gif"), 1, 3.5, 10, 320).passes[0]
    assert gif[C : C + 6] == ("-ss", "00:00:01.000", "-to", "00:00:03.500", "-i", str(SRC))
    assert "palettegen" in gif[gif.index("-filter_complex") + 1]
    webp = ft.build_animation(SRC, Path("a.webp"), 0, 2).passes[0]
    assert "libwebp" in webp and "-filter_complex" not in webp
    with pytest.raises(ValueError):
        ft.build_animation(SRC, Path("a.gif"), 2, 2)
    snap = ft.build_snapshot(SRC, Path("s.png"), 2.5).passes[0]
    assert snap[C:] == (
        "-ss",
        "00:00:02.500",
        "-i",
        str(SRC),
        "-frames:v",
        "1",
        "-update",
        "1",
        "s.png",
    )
    every = ft.build_snapshots_every(SRC, Path("C:/caps"), PROBE, 5, "clip")
    assert every.passes[0][-1] == str(Path("C:/caps/clip_%04d.png"))
    assert "fps=1/5" in every.passes[0]
    meta = ft.build_metadata(SRC, Path("o.mp3"), AUDIO_ONLY, {"title": "T ñ"}, Path("c.jpg"))
    args = meta.passes[0]
    assert args[C + 4 : C + 10] == (
        "-map",
        "0:a",
        "-map",
        "1:v",
        "-disposition:v:0",
        "attached_pic",
    )
    assert "title=T ñ" in args and args[-3:] == ("-id3v2_version", "3", "o.mp3")


def test_preview_plan_and_proxy() -> None:
    plan = ft.build_speed(SRC, OUT, PROBE, 2)
    preview = ft.preview_plan(plan, 3, Path("p.mp4"), 4)
    assert preview is not None
    args = preview.passes[0]
    assert args[C : C + 6] == ("-ss", "00:00:03.000", "-t", "4", "-i", str(SRC))
    assert args[-1] == "p.mp4" and preview.duration == 4
    trim = fc.build_trim(SRC, OUT, PROBE, 1, 2, precise=False)
    short = ft.preview_plan(trim, 9, Path("p.mp4"))
    assert short is not None
    assert short.passes[0][C : C + 2] == ("-ss", "00:00:01.000") and short.passes[0][-1] == "p.mp4"
    two = fc.build_compress_size(SRC, OUT, PROBE, 5, Path("log"))
    assert ft.preview_plan(two, 0, Path("p.mp4")) is None
    assert ft.preview_plan(ft.build_snapshot(SRC, Path("s.png"), 1), 0, Path("p.png")) is None
    proxy = ft.build_proxy(SRC, Path("x.mp4"), PROBE).passes[0]
    assert "scale=-2:480" in proxy and "ultrafast" in proxy


def test_hardware_acceleration() -> None:
    encoders = ft.parse_encoders(" V....D libx264  x\n V..... h264_qsv  y\n A....D aac  z\n")
    assert encoders == {"libx264", "h264_qsv"}
    assert ft.listed_hw(encoders) == ["qsv"]
    plan = fc.build_compress_crf(SRC, OUT, PROBE, 26)
    nvenc = ft.apply_hw(plan, "nvenc")
    args = nvenc.passes[0]
    assert "h264_nvenc" in args and "libx264" not in args
    assert args[args.index("-cq") + 1] == "26" and "-crf" not in args and "-preset" not in args
    assert nvenc.cpu_fallback == plan.passes
    amf = ft.apply_hw(plan, "amf").passes[0]
    assert amf[amf.index("-rc") : amf.index("-rc") + 6] == (
        "-rc",
        "cqp",
        "-qp_i",
        "26",
        "-qp_p",
        "26",
    )
    two = fc.build_compress_size(SRC, OUT, PROBE, 5, Path("log"))
    assert ft.apply_hw(two, "nvenc") is two
    copy = fc.build_convert(SRC, OUT, PROBE, fc.ConvertOptions("mkv", "copy", "copy"))
    assert ft.apply_hw(copy, "qsv") is copy
    assert ft.hw_test_args("amf")[-5:] == ["-c:v", "h264_amf", "-f", "null", "-"]


def _src(tmp_path: Path, name: str = "e.mp4") -> Path:
    path = tmp_path / name
    path.write_bytes(b"x")
    return path


def test_loudnorm_runs_with_measured_values(
    qtbot: QtBot, fake_ffmpeg: Launcher, tmp_path: Path
) -> None:
    manager = EditManager(fake_ffmpeg)
    plan = ft.build_normalize(_src(tmp_path), tmp_path / "n.mp4", PROBE)
    task_id = manager.add("normalizar", plan)
    qtbot.waitUntil(
        lambda: manager.task(task_id).state is EditState.COMPLETED,  # type: ignore[union-attr]
        timeout=TIMEOUT,
    )
    assert (tmp_path / "n.mp4").read_bytes() == b"resultado completo"


def test_hardware_failure_falls_back_to_cpu(
    qtbot: QtBot, fake_ffmpeg: Launcher, tmp_path: Path
) -> None:
    manager = EditManager(fake_ffmpeg)
    plan = ft.apply_hw(
        fc.build_compress_crf(_src(tmp_path), tmp_path / "c.mp4", PROBE, 28), "nvenc"
    )
    task_id = manager.add("comprimir", plan)
    qtbot.waitUntil(
        lambda: manager.task(task_id).state is EditState.COMPLETED,  # type: ignore[union-attr]
        timeout=TIMEOUT,
    )
    task = manager.task(task_id)
    assert task is not None
    assert task.plan.cpu_fallback == () and "libx264" in task.plan.passes[0]


def test_hw_probe_tests_each_encoder(qtbot: QtBot, fake_ffmpeg: Launcher) -> None:
    probe = HwProbe(fake_ffmpeg)
    with qtbot.waitSignal(probe.finished, timeout=TIMEOUT) as blocker:
        probe.start()
    # QSV aparece en la lista pero su prueba falla.
    assert blocker.args == [["nvenc"]]


def test_settings_page_detects_hw(
    qtbot: QtBot, ctx: AppContext, fake_ffmpeg: Launcher, monkeypatch: pytest.MonkeyPatch
) -> None:
    import bombastic.ui.settings_page as module

    monkeypatch.setattr(module, "tool_launcher", lambda _paths, _tool: fake_ffmpeg)
    page = SettingsPage(ctx)
    qtbot.addWidget(page)
    probe = page.detect_hw()
    with qtbot.waitSignal(probe.finished, timeout=TIMEOUT):
        pass
    assert ctx.settings.hw_available == ["nvenc"]
    assert page.hw_combo.count() == 2
    page.hw_combo.setCurrentIndex(1)
    assert ctx.settings.hw_encoder == "nvenc"


def test_editor_has_all_tools_and_preview(
    qtbot: QtBot, ctx: AppContext, fake_ffmpeg: Launcher, tmp_path: Path
) -> None:
    manager = EditManager(fake_ffmpeg)
    page = EditorPage(ctx, manager, probe_launcher=fake_ffmpeg)
    page.show_preview_dialog = False
    qtbot.addWidget(page)
    assert page.tools.count() == 14
    source = _src(tmp_path, "vid.mp4")
    with qtbot.waitSignal(page.file_opened, timeout=TIMEOUT):
        page.open_file(source)
    page.tools.setCurrentIndex(6)  # velocidad
    with qtbot.waitSignal(page.preview_ready, timeout=TIMEOUT) as blocker:
        page.preview()
    assert Path(blocker.args[0]).name == "preview.mp4"

    page.tools.setCurrentIndex(11)  # capturas
    snapshot = page.forms[11]
    snapshot.mode.setCurrentIndex(1)  # type: ignore[attr-defined]
    plan = page.current_plan()
    assert plan is not None and plan.output.name == "vid_capturas"
    assert not plan.output.exists()  # se crea al ejecutar, no al ver el comando

    page.tools.setCurrentIndex(9)  # marca de agua de texto sin texto
    page.forms[9].kind.setCurrentIndex(1)  # type: ignore[attr-defined]
    assert page.current_plan() is None
    assert page.feedback.text() == "Escribe el texto de la marca de agua."

    ctx.settings.hw_encoder = "nvenc"
    page.tools.setCurrentIndex(4)  # comprimir por CRF
    task_id = page.add_to_queue()
    task = manager.task(task_id or 0)
    assert task is not None and task.plan.cpu_fallback

    # Si el reproductor no puede con el archivo, se genera una copia ligera.
    page.player.playback_failed.emit("códec no soportado")
    qtbot.waitUntil(lambda: "copia ligera" in page.feedback.text(), timeout=TIMEOUT)
    qtbot.waitUntil(lambda: "Vista previa con" in page.feedback.text(), timeout=TIMEOUT)
    assert any((ctx.paths.cache_dir / "proxies").iterdir())
