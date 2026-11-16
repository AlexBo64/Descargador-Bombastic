import json
from pathlib import Path

from bombastic.core.settings import MIN_WINDOW_WIDTH, Settings, SettingsStore


def test_missing_file_gives_defaults(tmp_path: Path) -> None:
    assert SettingsStore(tmp_path / "settings.json").load() == Settings()


def test_roundtrip_with_unicode_path(tmp_path: Path) -> None:
    store = SettingsStore(tmp_path / "nested" / "settings.json")
    settings = Settings(language="en", theme="light", download_dir="C:\\Vídeos ñ\\música")
    store.save(settings)
    assert store.load() == settings
    assert not list(store.path.parent.glob("*.tmp"))
    # Se guarda en UTF-8 legible, sin escapes \u.
    assert "Vídeos ñ" in store.path.read_text(encoding="utf-8")


def test_corrupt_file_gives_defaults_and_keeps_backup(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text("{ esto no es json", encoding="utf-8")
    assert SettingsStore(path).load() == Settings()
    assert (tmp_path / "settings.json.bak").is_file()


def test_non_object_root_gives_defaults(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")
    assert SettingsStore(path).load() == Settings()


def test_invalid_values_are_sanitized(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps(
            {
                "language": "klingon",
                "theme": "rosa",
                "last_page": "nope",
                "window_width": 5,
                "window_maximized": 1,  # tipo incorrecto: se ignora
                "future_option": True,  # clave desconocida: se ignora
            }
        ),
        encoding="utf-8",
    )
    settings = SettingsStore(path).load()
    assert settings.language == "es"
    assert settings.theme == "system"
    assert settings.last_page == "downloads"
    assert settings.window_width == MIN_WINDOW_WIDTH
    assert settings.window_maximized is False


def test_partial_file_keeps_other_defaults(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text('{"theme": "dark"}', encoding="utf-8")
    settings = SettingsStore(path).load()
    assert settings.theme == "dark"
    assert settings.language == "es"
