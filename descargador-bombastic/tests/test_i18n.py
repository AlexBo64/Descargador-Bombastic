import json
import re
from pathlib import Path

import pytest

from bombastic.core import i18n
from bombastic.core.download_manager import ItemState
from bombastic.core.paths import resources_dir
from bombastic.core.settings import LANGUAGES, PAGES, THEMES
from bombastic.core.ytdlp_command import MP3_QUALITIES, Preset
from bombastic.core.ytdlp_runner import (
    ERROR_BAD_INFO,
    ERROR_EXIT_CODE,
    ERROR_MISSING,
    ERROR_START_FAILED,
    ERROR_TIMEOUT,
    ERROR_YTDLP,
)

CATALOGS = resources_dir() / "i18n"
PLACEHOLDER = re.compile(r"\{(\w+)\}")


def test_all_languages_have_a_catalog() -> None:
    assert i18n.Translator(CATALOGS).available() == sorted(LANGUAGES)


def test_catalogs_have_same_keys_and_placeholders() -> None:
    translator = i18n.Translator(CATALOGS)
    reference = translator.catalog("es")
    for language in LANGUAGES:
        catalog = translator.catalog(language)
        assert set(catalog) == set(reference), f"claves distintas en {language}"
        for key, text in catalog.items():
            assert text.strip(), f"texto vacío: {language}/{key}"
            assert set(PLACEHOLDER.findall(text)) == set(PLACEHOLDER.findall(reference[key])), key


def test_keys_built_dynamically_exist() -> None:
    catalog = i18n.Translator(CATALOGS).catalog("es")
    for page in PAGES:
        assert f"nav.{page}" in catalog
        assert f"page.{page}.subtitle" in catalog
    for theme in THEMES:
        assert f"settings.theme.{theme}" in catalog
    for language in LANGUAGES:
        assert f"settings.language.{language}" in catalog
    for preset in Preset:
        assert f"downloads.preset.{preset.value}" in catalog
    for quality in MP3_QUALITIES:
        assert f"downloads.mp3_quality.{quality}" in catalog
    for state in ItemState:
        assert f"downloads.status.{state.value}" in catalog
    for code in (
        ERROR_YTDLP,
        ERROR_EXIT_CODE,
        ERROR_START_FAILED,
        ERROR_TIMEOUT,
        ERROR_BAD_INFO,
        ERROR_MISSING,
    ):
        assert f"downloads.error.{code}" in catalog


def test_translate_switch_and_format() -> None:
    translator = i18n.Translator(CATALOGS)
    assert translator.t("nav.queue") == "Cola"
    translator.set_language("en")
    assert translator.t("nav.queue") == "Queue"
    assert translator.t("app.version", version="1.2.3") == "Version 1.2.3"


def test_fallback_language_and_missing_key(tmp_path: Path) -> None:
    (tmp_path / "es.json").write_text(json.dumps({"a": "uno", "b": "dos {n}"}), encoding="utf-8")
    (tmp_path / "en.json").write_text(json.dumps({"a": "one"}), encoding="utf-8")
    (tmp_path / "roto.json").write_text("{", encoding="utf-8")
    translator = i18n.Translator(tmp_path)
    translator.set_language("en")
    assert translator.t("a") == "one"
    assert translator.t("b", n=2) == "dos 2"  # respaldo en español
    assert translator.t("b") == "dos {n}"  # sin parámetros no se formatea
    assert translator.t("b", otro=1) == "dos {n}"  # parámetros incorrectos: no lanza
    assert translator.t("no.existe") == "no.existe"
    assert "roto" not in translator.available()


def test_unknown_language_falls_back() -> None:
    translator = i18n.Translator(CATALOGS)
    translator.set_language("xx")
    assert translator.language == "es"


def test_listeners_are_notified_only_on_change() -> None:
    translator = i18n.Translator(CATALOGS)
    seen: list[str] = []
    unsubscribe = translator.subscribe(seen.append)
    translator.set_language("es")  # sin cambio
    translator.set_language("en")
    unsubscribe()
    translator.set_language("es")
    assert seen == ["en"]


def test_global_tr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(i18n, "_active", None)
    assert i18n.tr("nav.queue") == "nav.queue"
    i18n.install(i18n.Translator(CATALOGS))
    assert i18n.tr("nav.queue") == "Cola"
