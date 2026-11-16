import pytest
from PySide6.QtWidgets import QApplication

from bombastic.ui.theme import PALETTES, ThemeManager, build_stylesheet, load_icon, resolve_theme


def test_resolve_theme() -> None:
    assert resolve_theme("dark", system_is_dark=False) == "dark"
    assert resolve_theme("light", system_is_dark=True) == "light"
    assert resolve_theme("system", system_is_dark=True) == "dark"
    assert resolve_theme("system", system_is_dark=False) == "light"


def test_palettes_define_the_same_tokens() -> None:
    assert set(PALETTES["dark"]) == set(PALETTES["light"])


@pytest.mark.parametrize("theme", sorted(PALETTES))
def test_stylesheet_has_no_unresolved_tokens(theme: str) -> None:
    qss = build_stylesheet(theme)
    assert "{{" not in qss
    assert PALETTES[theme]["bg"] in qss


def test_theme_manager_applies_and_signals(qapp: QApplication) -> None:
    manager = ThemeManager(qapp)
    seen: list[str] = []
    manager.changed.connect(seen.append)
    manager.apply("dark")
    manager.apply("dark")  # sin cambio: no vuelve a emitir
    manager.apply("light")
    assert seen == ["dark", "light"]
    assert manager.mode == "light"
    assert PALETTES["light"]["bg"] in qapp.styleSheet()
    manager.apply("system")
    assert manager.effective in PALETTES
    qapp.setStyleSheet("")


def test_load_icon(qapp: QApplication) -> None:
    assert not load_icon("downloads", "#ff0000").isNull()
