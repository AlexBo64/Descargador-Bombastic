import re

import pytest
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from bombastic.ui.theme import (
    PALETTES,
    AuroraBackground,
    ThemeManager,
    build_stylesheet,
    load_icon,
    resolve_theme,
)


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


def test_clickable_widgets_get_a_pointing_hand(qapp: QApplication, qtbot: QtBot) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QComboBox, QLabel, QPushButton, QTabBar, QVBoxLayout, QWidget

    manager = ThemeManager(qapp)
    manager.apply("dark")
    host = QWidget()
    qtbot.addWidget(host)
    layout = QVBoxLayout(host)
    button, combo, tabs, label = QPushButton("x"), QComboBox(), QTabBar(), QLabel("y")
    custom = QPushButton("z")
    custom.setCursor(Qt.CursorShape.WaitCursor)  # un cursor puesto a mano se respeta
    for widget in (button, combo, tabs, label, custom):
        layout.addWidget(widget)
    host.show()
    hand = Qt.CursorShape.PointingHandCursor
    assert button.cursor().shape() == hand
    assert combo.cursor().shape() == hand
    assert tabs.cursor().shape() == hand
    assert label.cursor().shape() != hand
    assert custom.cursor().shape() == Qt.CursorShape.WaitCursor
    qapp.setStyleSheet("")


def test_aurora_background_paints_both_themes(qapp: QApplication, qtbot: QtBot) -> None:
    background = AuroraBackground(PALETTES["dark"])
    qtbot.addWidget(background)
    background.resize(200, 120)
    dark = background.grab().toImage().pixelColor(100, 60)
    background.set_palette(PALETTES["light"])
    light = background.grab().toImage().pixelColor(100, 60)
    assert dark.lightness() < 80 < light.lightness()


def test_nav_and_stylesheet_resources(qapp: QApplication, qtbot: QtBot) -> None:
    from pathlib import Path

    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QListWidget

    qss = build_stylesheet("light")
    for icon in re.findall(r"url\(([^)]+)\)", qss):
        assert Path(icon).is_file(), icon
    ThemeManager(qapp)  # instala el filtro del cursor
    nav = QListWidget()
    nav.setObjectName("Nav")
    qtbot.addWidget(nav)
    nav.show()
    assert nav.viewport().cursor().shape() == Qt.CursorShape.PointingHandCursor


def test_wheel_only_changes_values_after_clicking(qapp: QApplication, qtbot: QtBot) -> None:
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtWidgets import QScrollArea, QSpinBox, QVBoxLayout, QWidget

    ThemeManager(qapp)
    area = QScrollArea()
    qtbot.addWidget(area)
    content = QWidget()
    layout = QVBoxLayout(content)
    spin = QSpinBox()
    spin.setRange(0, 100)
    spin.setValue(24)
    layout.addWidget(spin)
    layout.addSpacing(2000)  # contenido más alto que el área: hay scroll
    area.setWidget(content)
    area.resize(300, 200)
    area.show()
    assert spin.focusPolicy() == Qt.FocusPolicy.StrongFocus

    def wheel_down() -> None:
        event = QWheelEvent(
            QPointF(5, 5), QPointF(spin.mapToGlobal(QPoint(5, 5))), QPoint(0, 0), QPoint(0, -120),
            Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase,
            False,
        )  # fmt: skip
        QApplication.sendEvent(spin, event)

    # Sin pinchar: el valor no cambia y la página se desplaza.
    wheel_down()
    assert spin.value() == 24
    assert area.verticalScrollBar().value() > 0
    assert not spin.hasFocus()

    # Tras pinchar (foco), la rueda cambia el valor.
    spin.setFocus()
    qtbot.waitUntil(spin.hasFocus)
    wheel_down()
    assert spin.value() == 23
