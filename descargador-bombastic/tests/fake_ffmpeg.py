"""ffmpeg y ffprobe falsos para los tests: imitan su salida sin binarios reales.

``python fake_ffmpeg.py <argumentos>``. Con ``-show_format`` se comporta como ffprobe y, si
no, como ffmpeg. Palabras en los nombres de archivo:

- ``audio``: (ffprobe) el archivo solo tiene audio.
- ``broken``: (ffprobe) no se puede leer.
- ``big``: (ffprobe) vídeo de 1920x1080 en vez de 640x360.
- ``fail``: (ffmpeg) la salida falla tras escribir parte del archivo.
- ``slow``: (ffmpeg) la entrada no termina nunca (para cancelar).

Además: ``-encoders`` lista NVENC y QSV; codificar con ``h264_qsv`` o ``h264_nvenc`` falla
(para probar la detección y la vuelta a CPU); ``print_format=json`` escribe las medidas
de loudnorm en stderr como el ffmpeg real.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path


def out(text: str, stream: str = "stdout") -> None:
    target = sys.stdout if stream == "stdout" else sys.stderr
    target.buffer.write((text + "\n").encode("utf-8"))
    target.buffer.flush()


def probe(path: str) -> int:
    name = Path(path).name
    if "broken" in name:
        out(f"{path}: Invalid data found when processing input", "stderr")
        return 1
    streams: list[dict[str, object]] = []
    if "audio" not in name:
        width, height = (1920, 1080) if "big" in name else (640, 360)
        streams.append(
            {
                "index": 0,
                "codec_type": "video",
                "codec_name": "h264",
                "width": width,
                "height": height,
                "avg_frame_rate": "30000/1001",
            }
        )
    streams.append(
        {
            "index": len(streams),
            "codec_type": "audio",
            "codec_name": "aac",
            "sample_rate": "48000",
            "channels": 2,
            "tags": {"language": "spa"},
        }
    )
    data = {
        "streams": streams,
        "format": {
            "format_name": "mov,mp4,m4a,3gp,3g2,mj2",
            "duration": "10.000000",
            "size": "1000000",
            "bit_rate": "800000",
        },
    }
    out(json.dumps(data))
    return 0


ENCODERS = """Encoders:
 V..... = Video
 ------
 V....D libx264              libx264 H.264 / AVC
 V....D h264_nvenc           NVIDIA NVENC H.264 encoder (codec h264)
 V..... h264_qsv             H.264 (Intel Quick Sync Video acceleration) (codec h264)
 A....D aac                  AAC (Advanced Audio Coding)"""

LOUDNORM = """{
	"input_i" : "-21.75",
	"input_tp" : "-18.06",
	"input_lra" : "0.00",
	"input_thresh" : "-31.75",
	"output_i" : "-15.95",
	"target_offset" : "-0.05"
}"""


def ffmpeg(args: list[str]) -> int:
    if "-encoders" in args:
        out(ENCODERS)
        return 0
    if "-filters" in args:
        out("Filters:\n  T.. = Timeline support\n  ------")
        out(" TS scale             V->V       Scale the input video size.")
        out(" .. atempo            A->A       Adjust audio tempo.")
        return 0
    if "h264_qsv" in args or ("h264_nvenc" in args and "-cq" in args):
        out("Cannot load the hardware encoder", "stderr")
        return 1
    if any("print_format=json" in a for a in args):
        out("[Parsed_loudnorm_0 @ 0000] ", "stderr")
        out(LOUDNORM, "stderr")
    output = args[-1]
    inputs = [args[i + 1] for i, a in enumerate(args) if a == "-i"]
    slow = any("slow" in Path(i).name for i in inputs)
    writing = output.lower() not in ("nul", "/dev/null")
    if writing:
        Path(output).write_bytes(b"parcial")
    for step in range(1, 6):
        if slow:
            step = 1
            time.sleep(0.05)
        out(f"frame={step * 10}")
        out(f"out_time_us={step * 2_000_000}")
        out(f"out_time=00:00:{step * 2:02d}.000000")
        out("speed=2.5x")
        out("progress=continue")
        if "fail" in Path(output).name and step == 2:
            out("[libx264] Error de prueba ñ", "stderr")
            out("Conversion failed!", "stderr")
            return 1
        while slow:
            time.sleep(0.05)
            out("out_time_us=1000000")
            out("progress=continue")
    out("out_time_us=10000000")
    out("progress=end")
    if writing:
        Path(output).write_bytes(b"resultado completo")
    return 0


def main(argv: list[str]) -> int:
    if "-show_format" in argv:
        return probe(argv[-1])
    return ffmpeg(argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
