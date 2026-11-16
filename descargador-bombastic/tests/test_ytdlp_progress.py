from pathlib import Path

import pytest

from bombastic.core.ytdlp_progress import (
    DOWNLOAD_TEMPLATE,
    FILE_TEMPLATE,
    POSTPROCESS_TEMPLATE,
    DownloadProgress,
    ErrorLine,
    FileReady,
    FormatsSelected,
    PlaylistItem,
    PostprocessProgress,
    ProgressTracker,
    parse_line,
)

# Líneas reales de yt-dlp 2026.08.19 con las plantillas de la app.
REAL_DOWNLOADING = (
    'BMBPROG {"status":"downloading","d":7168,"t":433081,"te":NA,"s":1783730.1140314448,'
    '"e":0,"i":NA,"n":NA,"fi":NA,"fc":NA}'
)
REAL_FINISHED = (
    'BMBPROG {"status":"finished","d":433081,"t":433081,"te":NA,"s":692454.921390633,'
    '"e":NA,"i":NA,"n":NA,"fi":NA,"fc":NA}'
)


def test_templates_use_the_prefixes_the_parser_expects() -> None:
    assert DOWNLOAD_TEMPLATE.startswith("download:BMBPROG {")
    assert POSTPROCESS_TEMPLATE.startswith("postprocess:BMBPP {")
    assert FILE_TEMPLATE == "after_move:BMBFILE %(filepath)j"


def test_parse_real_progress_lines_with_na() -> None:
    event = parse_line(REAL_DOWNLOADING)
    assert event == DownloadProgress(
        status="downloading", downloaded=7168, total=433081, speed=1783730.1140314448, eta=0
    )
    assert isinstance(event, DownloadProgress)
    assert event.fraction == pytest.approx(7168 / 433081)

    finished = parse_line(REAL_FINISHED + "\r")
    assert isinstance(finished, DownloadProgress)
    assert finished.status == "finished"
    assert finished.eta is None
    assert finished.fraction == 1.0


def test_parse_progress_everything_unknown() -> None:
    event = parse_line(
        'BMBPROG {"status":"downloading","d":NA,"t":NA,"te":NA,"s":NA,"e":NA,'
        '"i":NA,"n":NA,"fi":NA,"fc":NA}'
    )
    assert event == DownloadProgress(status="downloading")
    assert isinstance(event, DownloadProgress)
    assert event.fraction is None


def test_parse_progress_estimate_fragments_and_playlist() -> None:
    event = parse_line(
        'BMBPROG {"status":"downloading","d":500,"t":NA,"te":2000.5,"s":"12.5","e":7,'
        '"i":2,"n":10,"fi":3,"fc":12}'
    )
    assert isinstance(event, DownloadProgress)
    assert event.total == 2000.5
    assert event.speed == 12.5
    assert (event.item_index, event.item_count) == (2, 10)
    assert event.fraction == pytest.approx(500 / 2000.5)

    only_fragments = parse_line(
        'BMBPROG {"status":"downloading","d":500,"t":NA,"te":NA,"s":NA,"e":NA,'
        '"i":NA,"n":NA,"fi":3,"fc":12}'
    )
    assert isinstance(only_fragments, DownloadProgress)
    assert only_fragments.fraction == pytest.approx(0.25)


def test_fraction_is_clamped() -> None:
    assert DownloadProgress("downloading", downloaded=300, total=100).fraction == 1.0
    assert DownloadProgress("downloading", downloaded=5, total=0).fraction is None


def test_parse_postprocess_file_formats_item_and_error() -> None:
    assert parse_line('BMBPP {"status":"started","pp":"Merger"}') == PostprocessProgress(
        "started", "Merger"
    )
    assert parse_line('BMBPP {"status":NA,"pp":NA}') == PostprocessProgress("", "")
    assert parse_line(
        'BMBFILE "C:\\\\Users\\\\Alex\\\\Me at the zoo \\u00f1 [abc].mp4"'
    ) == FileReady(Path("C:\\Users\\Alex\\Me at the zoo ñ [abc].mp4"))
    assert parse_line("[info] jNQXAC9IVRw: Downloading 1 format(s): 133+140") == FormatsSelected(2)
    assert parse_line("[info] abc: Downloading 1 format(s): 18") == FormatsSelected(1)
    assert parse_line("[download] Downloading item 3 of 12") == PlaylistItem(3, 12)
    assert parse_line("ERROR: [youtube] abc: This video is unavailable") == ErrorLine(
        "[youtube] abc: This video is unavailable"
    )


@pytest.mark.parametrize(
    "line",
    [
        "",
        "[youtube] Extracting URL: https://example.com",
        "[download] Destination: C:\\vídeos\\algo.f133.mp4",
        "WARNING: algo",
        "BMBPROG",
        "BMBPROG {roto",
        "BMBPROG [1, 2]",
        "BMBPP no es json",
        "BMBFILE NA",
        'BMBFILE ""',
        "BMBFILE {",
        "BMBFILE 42",
    ],
)
def test_parse_line_ignores_what_it_does_not_understand(line: str) -> None:
    assert parse_line(line) is None


def _feed_all(tracker: ProgressTracker, lines: list[str]) -> list[float | None]:
    fractions: list[float | None] = []
    for line in lines:
        event = parse_line(line)
        assert event is not None, line
        snapshot = tracker.feed(event)
        if snapshot is not None:
            fractions.append(snapshot.fraction)
    return fractions


def _progress(status: str, done: int, total: int, index: str = "NA", count: str = "NA") -> str:
    return (
        f'BMBPROG {{"status":"{status}","d":{done},"t":{total},"te":NA,"s":10,"e":1,'
        f'"i":{index},"n":{count},"fi":NA,"fc":NA}}'
    )


def test_tracker_spreads_video_and_audio_over_one_bar() -> None:
    tracker = ProgressTracker()
    fractions = _feed_all(
        tracker,
        [
            "[info] abc: Downloading 1 format(s): 137+140",
            _progress("downloading", 0, 1000),
            _progress("downloading", 500, 1000),
            _progress("finished", 1000, 1000),
            _progress("downloading", 0, 200),
            _progress("downloading", 100, 200),
            _progress("finished", 200, 200),
        ],
    )
    assert fractions == [0.0, 0.25, 0.5, 0.5, 0.75, 1.0]
    assert tracker.snapshot.phase == "downloading"
    assert tracker.snapshot.speed == 10


def test_tracker_never_goes_backwards_with_extra_files() -> None:
    """Miniaturas y subtítulos también informan de progreso: la barra no debe retroceder."""
    tracker = ProgressTracker()
    fractions = _feed_all(
        tracker,
        [
            "[info] abc: Downloading 1 format(s): 18",
            _progress("finished", 50, 50),
            _progress("downloading", 10, 100),
            _progress("finished", 100, 100),
        ],
    )
    assert fractions == [1.0, 1.0, 1.0]


def test_tracker_playlist_progress() -> None:
    tracker = ProgressTracker()
    fractions = _feed_all(
        tracker,
        [
            "[download] Downloading item 1 of 2",
            "[info] a: Downloading 1 format(s): 18",
            _progress("downloading", 500, 1000, "1", "2"),
            _progress("finished", 1000, 1000, "1", "2"),
            "[download] Downloading item 2 of 2",
            "[info] b: Downloading 1 format(s): 137+140",
            _progress("downloading", 500, 1000, "2", "2"),
            _progress("finished", 1000, 1000, "2", "2"),
            _progress("finished", 100, 100, "2", "2"),
        ],
    )
    assert fractions == [0.0, 0.25, 0.5, 0.5, 0.625, 0.75, 1.0]
    assert (tracker.snapshot.item_index, tracker.snapshot.item_count) == (2, 2)


def test_tracker_unknown_total_reports_no_fraction() -> None:
    tracker = ProgressTracker()
    snapshot = tracker.feed(DownloadProgress("downloading", downloaded=4096))
    assert snapshot is not None
    assert snapshot.fraction is None
    assert snapshot.downloaded == 4096


def test_tracker_postprocessing_phase() -> None:
    tracker = ProgressTracker()
    tracker.feed(FormatsSelected(1))
    tracker.feed(DownloadProgress("finished", downloaded=10, total=10))
    snapshot = tracker.feed(PostprocessProgress("started", "Merger"))
    assert snapshot is not None
    assert (snapshot.phase, snapshot.postprocessor, snapshot.fraction) == (
        "processing",
        "Merger",
        1.0,
    )
    # Ni el final de un paso ni el movimiento de archivos cambian lo que se muestra.
    assert tracker.feed(PostprocessProgress("finished", "Merger")) is None
    assert tracker.feed(PostprocessProgress("started", "MoveFiles")) is None
    assert tracker.feed(ErrorLine("x")) is None
    assert tracker.snapshot.phase == "processing"
