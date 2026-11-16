from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget
from pytestqt.qtbot import QtBot

from bombastic.ui.effects import (
    ExplodeOverlay,
    explode_and_remove,
    fade_out_and_remove,
    pulse,
    sync_order,
)

TIMEOUT = 5000


def _host(qtbot: QtBot) -> tuple[QWidget, QVBoxLayout, list[QLabel]]:
    host = QWidget()
    qtbot.addWidget(host)
    layout = QVBoxLayout(host)
    labels = [QLabel(f"tarjeta {n}") for n in range(3)]
    for label in labels:
        label.setMinimumHeight(40)
        layout.addWidget(label)
    host.resize(400, 300)
    host.show()
    qtbot.waitExposed(host)
    return host, layout, labels


def test_explode_then_collapse_then_done(qtbot: QtBot) -> None:
    _host_widget, _layout, labels = _host(qtbot)
    done: list[bool] = []
    overlay = explode_and_remove(labels[1], lambda: done.append(True))
    assert isinstance(overlay, ExplodeOverlay)
    assert len(overlay.tiles) == 14 * 4
    assert not labels[1].isEnabled()  # no se puede pulsar mientras desaparece
    assert done == []  # no es instantáneo
    qtbot.waitUntil(lambda: overlay.progress > 0.3, timeout=TIMEOUT)
    qtbot.waitUntil(lambda: done == [True], timeout=TIMEOUT)
    assert labels[1].maximumHeight() == 0


def test_hidden_widgets_are_removed_at_once(qtbot: QtBot) -> None:
    _host_widget, _layout, labels = _host(qtbot)
    labels[0].hide()
    done: list[str] = []
    assert explode_and_remove(labels[0], lambda: done.append("explode")) is None
    fade_out_and_remove(labels[0], lambda: done.append("fade"))
    assert done == ["explode", "fade"]


def test_fade_out_and_pulse(qtbot: QtBot) -> None:
    _host_widget, _layout, labels = _host(qtbot)
    done: list[bool] = []
    fade_out_and_remove(labels[2], lambda: done.append(True))
    assert done == []
    qtbot.waitUntil(lambda: done == [True], timeout=TIMEOUT)
    pulse(labels[0])
    assert labels[0].graphicsEffect() is not None
    qtbot.waitUntil(lambda: labels[0].graphicsEffect() is None, timeout=TIMEOUT)


def test_sync_order_ignores_widgets_being_removed(qtbot: QtBot) -> None:
    _host_widget, layout, labels = _host(qtbot)
    a, ghost, b = labels
    # La tarjeta del medio se está quitando: el orden de las demás ya es el correcto.
    sync_order(layout, [a, b], first=0)
    assert [layout.indexOf(w) for w in (a, ghost, b)] == [0, 1, 2]
    sync_order(layout, [b, a], first=0)
    assert layout.indexOf(b) < layout.indexOf(a)
