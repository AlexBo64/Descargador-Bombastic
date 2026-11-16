import subprocess
import sys
from pathlib import Path

import pytest
from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QDropEvent, QIcon
from pytestqt.qtbot import QtBot

from bombastic.context import AppContext
from bombastic.core.cli import AppCommand, command_args, parse_command
from bombastic.core.ytdlp_runner import Launcher
from bombastic.platform_win import context_menu
from bombastic.platform_win.single_instance import InstanceServer, send_to_running, server_name
from bombastic.platform_win.tray import Tray
from bombastic.ui.main_window import MainWindow

TIMEOUT = 20_000


def test_parse_command() -> None:
    assert parse_command([]).empty
    command = parse_command(
        ["--download", "https://e.com/a", "https://e.com/b", "--edit", "C:/v ñ.mp4"]
    )
    assert command.download == ["https://e.com/a", "https://e.com/b"]
    assert command.edit == [Path("C:/v ñ.mp4")]
    action = parse_command(["--action", "recipe:Mi receta", "a.mp4", "b.mkv"])
    assert (action.action, action.action_files) == (
        "recipe:Mi receta",
        [Path("a.mp4"), Path("b.mkv")],
    )
    # Archivos sueltos ("Abrir con…") van al editor; lo desconocido se ignora.
    loose = parse_command(["x.mp4", "y.mp3", "--rara"])
    assert loose.edit == [Path("x.mp4"), Path("y.mp3")]
    assert parse_command(command_args(command)) == command
    assert parse_command(command_args(action)) == action
    assert command_args(AppCommand()) == []


def test_single_instance_forwards_arguments(qtbot: QtBot, tmp_path: Path) -> None:
    name = server_name(str(tmp_path))
    assert name != server_name("otra carpeta")
    assert not send_to_running(name, ["--edit", "x"])  # aún no hay nadie escuchando
    server = InstanceServer(name)
    assert server.listening
    # La otra instancia es otro proceso (en el mismo hilo la tubería no se vaciaría).
    code = (
        "import sys; from PySide6.QtCore import QCoreApplication; app = QCoreApplication([]);"
        "from bombastic.platform_win.single_instance import send_to_running;"
        f"sys.exit(0 if send_to_running({name!r}, ['--download', 'https://e.com/ñ']) else 1)"
    )
    with qtbot.waitSignal(server.message_received, timeout=TIMEOUT) as blocker:
        child = subprocess.Popen([sys.executable, "-c", code], cwd=Path(__file__).parents[1])
    assert blocker.args == [["--download", "https://e.com/ñ"]]
    assert child.wait(timeout=20) == 0
    # Una segunda instancia del servidor con el mismo nombre se recupera de un socket viejo.
    server.deleteLater()


def test_context_menu_entries() -> None:
    labels = {
        "menu": "Descargador Bombastic",
        "edit": "Editar",
        "convert_mp4": "MP4",
        "extract_mp3": "MP3",
        "compress": "Comprimir…",
        "recipe": "Receta: {name}",
    }
    entries = context_menu.registry_entries('"C:\\App\\DB.exe"', labels, ['Mi "receta"'])
    per_ext = len(entries) // len(context_menu.MEDIA_EXTENSIONS)
    assert per_ext == 2 + 2 * 5
    base = r"Software\Classes\SystemFileAssociations\.mp4\shell\DescargadorBombastic"
    values = {(k, n): v for k, n, v in entries}
    assert values[(base, "MUIVerb")] == "Descargador Bombastic"
    assert values[(base, "SubCommands")] == ""
    assert values[(rf"{base}\shell\1_edit\command", "")] == '"C:\\App\\DB.exe" --edit "%1"'
    assert values[(rf"{base}\shell\5_recipe", "")] == "Receta: Mi receta"
    assert values[(rf"{base}\shell\5_recipe\command", "")] == (
        '"C:\\App\\DB.exe" --action "recipe:Mi receta" "%1"'
    )
    assert "-m bombastic" in context_menu.launch_command()
    assert {".mp4", ".mkv", ".mp3", ".flac", ".opus"} <= set(context_menu.MEDIA_EXTENSIONS)


def test_tray_notifications(qtbot: QtBot, translator: object) -> None:
    tray = Tray(QIcon())
    tray.set_progress("2 descargas · 40 %")
    assert tray.icon.toolTip() == "Descargador Bombastic\n2 descargas · 40 %"
    clicked: list[bool] = []
    tray.notify("Hecho", "vídeo.mp4", lambda: clicked.append(True))
    tray.icon.messageClicked.emit()
    assert clicked == [True]
    with qtbot.waitSignal(tray.show_requested):
        tray.icon.messageClicked.emit()  # sin acción pendiente: muestra la ventana
    with qtbot.waitSignal(tray.quit_requested):
        tray.menu.actions()[-1].trigger()
    tray.deleteLater()


@pytest.fixture
def window(
    qtbot: QtBot, ctx: AppContext, fake_launcher: Launcher, monkeypatch: pytest.MonkeyPatch
) -> MainWindow:
    import bombastic.ui.downloads_page as downloads_module

    monkeypatch.setattr(downloads_module, "default_launcher", lambda _paths: fake_launcher)
    main = MainWindow(ctx)
    qtbot.addWidget(main)
    return main


def _drop(window: MainWindow, mime: QMimeData) -> None:
    event = QDropEvent(
        QPointF(QPoint(10, 10)), Qt.DropAction.CopyAction, mime,
        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
    )  # fmt: skip
    window.dropEvent(event)


def test_drop_links_txt_and_media(window: MainWindow, tmp_path: Path) -> None:
    listing = tmp_path / "enlaces.txt"
    listing.write_text("https://example.com/v1\nhttps://example.com/v2\n", encoding="utf-8")
    mime = QMimeData()
    mime.setUrls([QUrl("https://example.com/v3"), QUrl.fromLocalFile(str(listing))])
    _drop(window, mime)
    assert window.current_page() == "downloads"
    assert len(window.downloads_page.cards) == 3

    video = tmp_path / "clip.mkv"
    video.write_bytes(b"x")
    media = QMimeData()
    media.setUrls([QUrl.fromLocalFile(str(video))])
    _drop(window, media)
    assert window.current_page() == "editor"

    text = QMimeData()
    text.setText("mira https://example.com/v4")
    _drop(window, text)
    assert len(window.downloads_page.cards) == 4


def test_commands_from_other_instances(window: MainWindow, tmp_path: Path) -> None:
    window.handle_args(["--download", "https://example.com/otro"])
    assert window.current_page() == "downloads"
    assert len(window.downloads_page.cards) == 1
    video = tmp_path / "a.mp4"
    video.write_bytes(b"x")
    window.handle_args(["--action", "compress", str(video)])
    assert window.current_page() == "editor"
    assert window.editor_page.tools.currentIndex() == 4
    window.handle_args(["--action", "convert_mp4", str(video)])
    assert window.current_page() == "queue"
    window.handle_args(["--action", "desconocida", str(video)])
    assert window.current_page() == "queue"


def test_close_to_tray(window: MainWindow, ctx: AppContext) -> None:
    window.tray = Tray(QIcon(), window)
    ctx.settings.minimize_to_tray = True
    window.show()
    assert not window.close()
    assert not window.isVisible()
    window.bring_to_front()
    assert window.isVisible()
    window._quitting = True
    assert window.close()
