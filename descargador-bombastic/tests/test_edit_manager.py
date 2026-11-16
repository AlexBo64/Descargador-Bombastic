import sqlite3
from pathlib import Path

from pytestqt.qtbot import QtBot

from bombastic.core import ffmpeg_command as fc
from bombastic.core.db import MIGRATIONS, Database, migrate
from bombastic.core.edit_manager import (
    ERROR_FFMPEG,
    ERROR_MISSING,
    ERROR_NO_SPACE,
    EditManager,
    EditState,
    plan_from_dict,
    plan_to_dict,
)
from bombastic.core.media_probe import ProbeInfo, StreamInfo
from bombastic.core.ytdlp_runner import Launcher

TIMEOUT = 20_000
PROBE = ProbeInfo(
    "mp4",
    10.0,
    1000,
    1,
    (StreamInfo(0, "video", "h264", 640, 360, 30.0), StreamInfo(1, "audio", "aac")),
)


def _plan(tmp_path: Path, name: str = "entrada ñ.mp4", out: str = "salida ñ.mp4") -> fc.EditPlan:
    source = tmp_path / name
    source.write_bytes(b"x")
    return fc.build_convert(source, tmp_path / out, PROBE, fc.ConvertOptions())


def _wait(qtbot: QtBot, manager: EditManager, task_id: int, state: EditState) -> None:
    qtbot.waitUntil(
        lambda: (task := manager.task(task_id)) is not None and task.state is state,
        timeout=TIMEOUT,
    )


def test_task_runs_with_real_progress(qtbot: QtBot, fake_ffmpeg: Launcher, tmp_path: Path) -> None:
    manager = EditManager(fake_ffmpeg)
    fractions: list[float | None] = []
    manager.task_changed.connect(
        lambda i: fractions.append(t.fraction) if (t := manager.task(i)) else None
    )
    with qtbot.waitSignal(manager.task_completed, timeout=TIMEOUT) as done:
        task_id = manager.add("Convertir", _plan(tmp_path))
    assert done.args == [task_id]
    task = manager.task(task_id)
    assert task is not None
    assert task.state is EditState.COMPLETED and task.fraction == 1.0
    assert task.plan.output.read_bytes() == b"resultado completo"
    # Progreso real calculado con out_time frente a la duración (2 s de 10 → 0,2…).
    assert 0.2 in fractions and 0.6 in fractions
    assert task.speed == 2.5
    assert task.commands[0].startswith("ffmpeg -hide_banner")


def test_two_passes_report_overall_progress(
    qtbot: QtBot, fake_ffmpeg: Launcher, tmp_path: Path
) -> None:
    manager = EditManager(fake_ffmpeg)
    source = tmp_path / "e.mp4"
    source.write_bytes(b"x")
    log = tmp_path / "2pass"
    Path(f"{log}-0.log").write_text("log")
    plan = fc.build_compress_size(source, tmp_path / "s.mp4", PROBE, 1, log)
    seen: list[float] = []
    manager.task_changed.connect(
        lambda i: (
            seen.append(t.fraction)  # type: ignore[arg-type]
            if (t := manager.task(i)) and t.fraction is not None
            else None
        )
    )
    task_id = manager.add("Comprimir", plan)
    _wait(qtbot, manager, task_id, EditState.COMPLETED)
    # La primera pasada llega a 0,5 y la segunda empieza desde ahí.
    assert 0.1 in seen and 0.6 in seen
    assert max(f for f in seen[: seen.index(0.6)]) <= 0.5
    assert not Path(f"{log}-0.log").exists()


def test_failure_removes_partial_output(
    qtbot: QtBot, fake_ffmpeg: Launcher, tmp_path: Path
) -> None:
    manager = EditManager(fake_ffmpeg)
    task_id = manager.add("x", _plan(tmp_path, out="fail.mp4"))
    _wait(qtbot, manager, task_id, EditState.FAILED)
    task = manager.task(task_id)
    assert task is not None
    assert task.error_code == ERROR_FFMPEG
    assert task.error_detail == "Conversion failed!"
    assert "[libx264] Error de prueba ñ" in task.log
    assert not (tmp_path / "fail.mp4").exists()


def test_cancel_pause_and_concurrency(qtbot: QtBot, fake_ffmpeg: Launcher, tmp_path: Path) -> None:
    manager = EditManager(fake_ffmpeg, max_concurrent=1)
    slow = manager.add("lento", _plan(tmp_path, "slow.mp4", "s.mp4"))
    waiting = manager.add("espera", _plan(tmp_path, "a.mp4", "a_out.mp4"))
    assert manager.task(slow).state is EditState.RUNNING  # type: ignore[union-attr]
    assert manager.task(waiting).state is EditState.QUEUED  # type: ignore[union-attr]
    qtbot.waitUntil((tmp_path / "s.mp4").exists, timeout=TIMEOUT)
    manager.pause(slow)
    _wait(qtbot, manager, slow, EditState.PAUSED)
    assert not (tmp_path / "s.mp4").exists()
    _wait(qtbot, manager, waiting, EditState.COMPLETED)

    manager.resume(slow)
    _wait(qtbot, manager, slow, EditState.RUNNING)
    manager.cancel(slow)
    _wait(qtbot, manager, slow, EditState.CANCELLED)
    assert not (tmp_path / "s.mp4").exists()
    manager.remove(waiting)
    assert [t.task_id for t in manager.tasks()] == [slow]
    assert not manager.busy


def test_missing_ffmpeg_and_no_space(qtbot: QtBot, tmp_path: Path) -> None:
    manager = EditManager(lambda _args: None)
    task_id = manager.add("x", _plan(tmp_path))
    _wait(qtbot, manager, task_id, EditState.FAILED)
    assert manager.task(task_id).error_code == ERROR_MISSING  # type: ignore[union-attr]
    manager.space_check = lambda _plan: False
    other = manager.add("y", _plan(tmp_path, out="otra.mp4"))
    assert manager.task(other).error_code == ERROR_NO_SPACE  # type: ignore[union-attr]


def test_queue_is_saved_and_restored(qtbot: QtBot, fake_ffmpeg: Launcher, tmp_path: Path) -> None:
    db = Database(tmp_path / "db.sqlite3")
    manager = EditManager(fake_ffmpeg, db=db, max_concurrent=1)
    done = manager.add("hecho", _plan(tmp_path))
    _wait(qtbot, manager, done, EditState.COMPLETED)
    slow = manager.add("lento", _plan(tmp_path, "slow.mp4", "s.mp4"))
    pending = manager.add("pendiente", _plan(tmp_path, "b.mp4", "b_out.mp4"))
    manager.move(pending, -1)
    manager.shutdown()
    db.close()

    db = Database(tmp_path / "db.sqlite3")
    restored = EditManager(fake_ffmpeg, db=db)
    restored.restore()
    tasks = restored.tasks()
    assert [t.task_id for t in tasks] == [done, pending, slow]
    assert [t.state for t in tasks] == [EditState.COMPLETED, EditState.PAUSED, EditState.PAUSED]
    assert tasks[1].plan == plan_from_dict(plan_to_dict(tasks[1].plan))
    assert tasks[1].plan.output == tmp_path / "b_out.mp4"
    assert restored.add("nueva", _plan(tmp_path, out="n.mp4")) > slow
    restored.shutdown()
    db.close()


def test_migration_from_schema_1_keeps_downloads(tmp_path: Path) -> None:
    path = tmp_path / "vieja.sqlite3"
    conn = sqlite3.connect(path, isolation_level=None)
    migrate(conn, MIGRATIONS[:1])
    conn.execute(
        "INSERT INTO downloads (url, position, state, created_at, updated_at)"
        " VALUES ('u', 1, 'completed', 'a', 'b')"
    )
    conn.close()
    db = Database(path)
    assert db.version == len(MIGRATIONS)
    assert db.query("SELECT url FROM downloads")[0]["url"] == "u"
    assert db.query("SELECT COUNT(*) AS n FROM edits")[0]["n"] == 0
    db.close()
