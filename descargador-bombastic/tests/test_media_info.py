import json

import pytest

from bombastic.core.media_info import MediaInfoError, parse_media_info

URL = "https://example.com/v"


def test_parse_video() -> None:
    data = {
        "_type": "video",
        "id": "jNQXAC9IVRw",
        "title": "  Me at the zoo ñ ",
        "channel": "jawed",
        "uploader": "otro",
        "duration": 19,
        "thumbnail": "https://i.example/vi/x/hqdefault.jpg?sqp=abc",
        "webpage_url": "https://www.youtube.com/watch?v=jNQXAC9IVRw",
        "extractor_key": "Youtube",
        "live_status": "not_live",
    }
    info = parse_media_info(json.dumps(data), URL)
    assert info.title == "Me at the zoo ñ"
    assert info.channel == "jawed"
    assert info.duration == 19.0
    assert info.thumbnail_url == "https://i.example/vi/x/hqdefault.jpg?sqp=abc"
    assert info.url == "https://www.youtube.com/watch?v=jNQXAC9IVRw"
    assert info.media_id == "jNQXAC9IVRw"
    assert not info.is_playlist
    assert info.entry_count is None
    assert not info.is_live
    assert info.extractor == "Youtube"


def test_parse_playlist_uses_count_and_first_entry_thumbnail() -> None:
    data = {
        "_type": "playlist",
        "id": "PL1",
        "title": "Mi lista",
        "uploader": "Alguien",
        "entries": [
            {"id": "a", "thumbnails": [{"url": "https://i.example/a/small.webp"}]},
            {"id": "b", "thumbnails": [{"url": "https://i.example/b.jpg"}]},
        ],
    }
    info = parse_media_info(json.dumps(data), URL)
    assert info.is_playlist
    assert info.entry_count == 2
    assert info.duration is None
    assert info.channel == "Alguien"
    assert info.thumbnail_url == "https://i.example/a/small.webp"
    assert info.url == URL

    data["playlist_count"] = 57
    assert parse_media_info(json.dumps(data), URL).entry_count == 57


def test_thumbnail_prefers_jpeg_over_webp() -> None:
    data = {
        "id": "x",
        "title": "t",
        "thumbnail": "https://i.example/max.webp",
        "thumbnails": [
            {"url": "https://i.example/low.jpg"},
            {"url": "https://i.example/high.jpg"},
            {"url": "https://i.example/max.webp"},
            "basura",
        ],
    }
    assert parse_media_info(json.dumps(data), URL).thumbnail_url == "https://i.example/high.jpg"
    del data["thumbnails"]
    assert parse_media_info(json.dumps(data), URL).thumbnail_url == "https://i.example/max.webp"


def test_missing_fields_get_safe_defaults() -> None:
    info = parse_media_info('{"id": 42, "duration": "raro", "is_live": true}', URL)
    assert info.title == URL
    assert info.media_id == "42"
    assert info.channel == ""
    assert info.duration is None
    assert info.thumbnail_url == ""
    assert info.is_live


def test_json_is_found_among_other_lines() -> None:
    output = 'WARNING: aviso\n{"id": "a", "title": "Con aviso"}\n\n'
    assert parse_media_info(output, URL).title == "Con aviso"


@pytest.mark.parametrize("output", ["", "no es json", "[1, 2]", "{roto", "null"])
def test_invalid_output_raises(output: str) -> None:
    with pytest.raises(MediaInfoError):
        parse_media_info(output, URL)
