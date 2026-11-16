import pytest

from bombastic.core.formatting import format_bytes, format_duration, format_speed
from bombastic.core.urls import extract_urls


def test_extract_urls_from_lines_and_spaces() -> None:
    text = "https://a.example/v1\n  http://b.example/v2?x=1&y=2   https://a.example/v1\n\n"
    assert extract_urls(text) == ["https://a.example/v1", "http://b.example/v2?x=1&y=2"]


def test_extract_urls_strips_surrounding_punctuation() -> None:
    assert extract_urls("Mira (https://a.example/v1), y <https://b.example/v2>.") == [
        "https://a.example/v1",
        "https://b.example/v2",
    ]


def test_extract_urls_accepts_links_without_scheme() -> None:
    assert extract_urls("youtu.be/abc www.example.com/watch?v=1") == [
        "https://youtu.be/abc",
        "https://www.example.com/watch?v=1",
    ]


@pytest.mark.parametrize("text", ["", "   \n ", "hola mundo", "archivo.txt", "https://", "1/2"])
def test_extract_urls_ignores_everything_else(text: str) -> None:
    assert extract_urls(text) == []


@pytest.mark.parametrize(
    ("size", "expected"),
    [
        (None, ""),
        (-1, ""),
        (0, "0 B"),
        (1023, "1023 B"),
        (1536, "1.5 KB"),
        (5 * 1024**2, "5.0 MB"),
        (3.25 * 1024**3, "3.2 GB"),
        (2 * 1024**5, "2048.0 TB"),
    ],
)
def test_format_bytes(size: float | None, expected: str) -> None:
    assert format_bytes(size) == expected


def test_format_speed() -> None:
    assert format_speed(2048) == "2.0 KB/s"
    assert format_speed(None) == ""


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [(None, ""), (-5, ""), (0, "0:00"), (19, "0:19"), (75.4, "1:15"), (3723, "1:02:03")],
)
def test_format_duration(seconds: float | None, expected: str) -> None:
    assert format_duration(seconds) == expected
