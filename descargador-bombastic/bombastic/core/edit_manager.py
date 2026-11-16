"""Cola de edición: ejecuta los planes de ffmpeg con progreso real y la guarda en SQLite.

Igual que la cola de descargas, pero sin reanudar a medias: pausar o cancelar una edición
borra la salida incompleta, y al reanudar empieza de nuevo.
"""

from __future__ import annotations

import json
import logging
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from enum import StrEnum
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QProcess, Signal

from bombastic.core.db import Database, now_iso
from bombastic.core.ffmpeg_command import EditPlan
from bombastic.core.ffmpeg_progress import FfmpegProgressParser
from bombastic.core.ffmpeg_tools import fill_analysis
from bombastic.core.output_paths import enough_space
from bombastic.core.process_control import kill_process_tree
from bombastic.core.ytdlp_runner import Launcher, describe

log = logging.getLogger(__name__)

_LOG_LINES = 200
_SHUTDOWN_WAIT_MS = 3000

# Códigos de error (la interfaz los traduce con ``editor.error.<código>``).
ERROR_FFMPEG = "ffmpeg"  # ffmpeg ha fallado: el detalle es su último mensaje
ERROR_MISSING = "ffmpeg_missing"
ERROR_NO_SPACE = "no_space"
ERROR_START_FAILED = "start_failed"
ERROR_ANALYSIS = "analysis"  # la primera pasada no ha dado las medidas esperadas


class EditState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


EDIT_FINISHED = frozenset({EditState.COMPLETED, EditState.FAILED, EditState.CANCELLED})


@dataclass
class EditTask:
    task_id: int
    title: str
    plan: EditPlan
    state: EditState = EditState.QUEUED
    position: float = 0.0
    #: De 0 a 1, o ``None`` si no se sabe la duración.
    fraction: float | None = None
    speed: float | None = None
    error_code: str = ""
    error_detail: str = ""
    log: list[str] = field(default_factory=list)
    created_at: str = ""

    @property
    def commands(self) -> list[str]:
        return [describe(("ffmpeg", list(p))) for p in self.plan.passes]


def plan_to_dict(plan: EditPlan) -> dict[str, Any]:
    return {
        "tool": plan.tool,
        "passes": [list(p) for p in plan.passes],
        "output": str(plan.output),
        "duration": plan.duration,
        "inputs": [str(p) for p in plan.inputs],
        "temp_files": [str(p) for p in plan.temp_files],
        "analysis": plan.analysis,
        "cpu_fallback": [list(p) for p in plan.cpu_fallback],
    }


def plan_from_dict(data: Any) -> EditPlan | None:
    try:
        duration = data.get("duration")
        return EditPlan(
            tool=str(data["tool"]),
            passes=tuple(tuple(str(a) for a in p) for p in data["passes"]),
            output=Path(data["output"]),
            duration=float(duration) if isinstance(duration, (int, float)) else None,
            inputs=tuple(Path(p) for p in data.get("inputs", [])),
            temp_files=tuple(Path(p) for p in data.get("temp_files", [])),
            analysis=str(data.get("analysis", "")),
            cpu_fallback=tuple(tuple(str(a) for a in p) for p in data.get("cpu_fallback", [])),
        )
    except (AttributeError, KeyError, TypeError, ValueError):
        return None


def _remove(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        log.warning("Could not delete %s", path)


class FfmpegJob(QObject):
    """Ejecuta las pasadas de un plan una tras otra."""

    #: ``(fracción o None, velocidad o None)``.
    progress = Signal(object, object)
    #: ``(estado final, código de error, detalle)``: ``completed``, ``failed`` o ``cancelled``.
    finished = Signal(str, str, str)
    #: Cada línea de la salida de error de ffmpeg (consola del modo experto).
    output_line = Signal(str)

    def __init__(self, plan: EditPlan, launcher: Launcher, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._plan = plan
        self._launcher = launcher
        #: Pasadas pendientes de ejecutar (las siguientes pueden rellenarse con el análisis).
        self._passes = [list(p) for p in plan.passes]
        self._pass_log: list[str] = []
        self._pass = 0
        self._cancelled = False
        self._done = False
        self._parser = FfmpegProgressParser()
        self._stdout = b""
        self._stderr = b""
        self.log_lines: deque[str] = deque(maxlen=_LOG_LINES)
        self._process: QProcess | None = None

    @property
    def running(self) -> bool:
        return (
            self._process is not None and self._process.state() != QProcess.ProcessState.NotRunning
        )

    def start(self) -> None:
        if self._plan.tool == "snapshot" and not self._plan.output.suffix:
            # Capturas cada N segundos: la salida es una carpeta que ffmpeg no crea.
            try:
                self._plan.output.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                self._finish("failed", ERROR_FFMPEG, str(exc))
                return
        self._start_pass()

    def _start_pass(self) -> None:
        launch = self._launcher(self._passes[self._pass])
        self._pass_log = []
        if launch is None:
            self._finish("failed", ERROR_MISSING, "")
            return
        log.info("Running ffmpeg: %s", describe(launch))
        process = QProcess(self)
        process.readyReadStandardOutput.connect(self._read_stdout)
        process.readyReadStandardError.connect(self._read_stderr)
        process.finished.connect(self._on_finished)
        process.errorOccurred.connect(self._on_error)
        self._process = process
        self._parser = FfmpegProgressParser()
        process.start(*launch)

    def cancel(self) -> None:
        if self._done or self._cancelled:
            return
        self._cancelled = True
        if self._process is not None and self.running:
            kill_process_tree(self._process)
        else:
            self._finish("cancelled", "", "")

    def wait(self, msecs: int) -> None:
        if self._process is not None and self.running:
            self._process.waitForFinished(msecs)

    def _lines(self, buffer: bytes) -> tuple[list[str], bytes]:
        *complete, rest = buffer.split(b"\n")
        return [raw.decode("utf-8", errors="replace").rstrip("\r") for raw in complete], rest

    def _read_stdout(self) -> None:
        assert self._process is not None
        self._stdout += bytes(self._process.readAllStandardOutput().data())
        lines, self._stdout = self._lines(self._stdout)
        for line in lines:
            update = self._parser.feed(line)
            if update is None or self._cancelled:
                continue
            fraction = None
            if self._plan.duration and update.out_time is not None:
                within = min(1.0, update.out_time / self._plan.duration)
                fraction = (self._pass + within) / len(self._plan.passes)
            self.progress.emit(fraction, update.speed)

    def _read_stderr(self) -> None:
        assert self._process is not None
        self._stderr += bytes(self._process.readAllStandardError().data())
        lines, self._stderr = self._lines(self._stderr)
        kept = [line for line in lines if line.strip()]
        self.log_lines.extend(kept)
        self._pass_log.extend(kept)
        for line in kept:
            self.output_line.emit(line)

    def _on_error(self, error: QProcess.ProcessError) -> None:
        if error == QProcess.ProcessError.FailedToStart:
            self._finish("failed", ERROR_START_FAILED, "ffmpeg")

    def _on_finished(self, exit_code: int, status: QProcess.ExitStatus) -> None:
        self._read_stdout()
        self._read_stderr()
        if self._stderr.strip():
            rest = self._stderr.decode("utf-8", errors="replace").strip()
            self.log_lines.append(rest)
            self._pass_log.append(rest)
            self._stderr = b""
        if self._cancelled:
            self._finish("cancelled", "", "")
        elif exit_code != 0 or status != QProcess.ExitStatus.NormalExit:
            detail = self.log_lines[-1] if self.log_lines else str(exit_code)
            self._finish("failed", ERROR_FFMPEG, detail)
        elif self._pass + 1 < len(self._passes):
            if self._pass == 0 and self._plan.analysis:
                filled = fill_analysis(
                    self._passes[1:], self._plan.analysis, "\n".join(self._pass_log)
                )
                if filled is None:
                    self._finish("failed", ERROR_ANALYSIS, self._plan.analysis)
                    return
                self._passes[1:] = filled
            self._pass += 1
            self._start_pass()
        else:
            self._finish("completed", "", "")

    def _finish(self, status: str, code: str, detail: str) -> None:
        if self._done:
            return
        self._done = True
        if status != "completed":
            # Un archivo a medias no sirve: se borra para no confundirlo con un resultado.
            _remove(self._plan.output)
        for temp in self._plan.temp_files:
            if status == "completed" or temp.suffix in (".log", ".mbtree"):
                _remove(temp)
        log.info("Edit %s: %s %s", status, self._plan.output, detail)
        self.finished.emit(status, code, detail)


class EditManager(QObject):
    task_added = Signal(int)
    task_changed = Signal(int)
    task_removed = Signal(int)
    #: Una edición ha terminado bien: emite su id (para las acciones encadenadas).
    task_completed = Signal(int)

    def __init__(
        self,
        launcher: Launcher,
        parent: QObject | None = None,
        db: Database | None = None,
        max_concurrent: int = 1,
    ) -> None:
        super().__init__(parent)
        self._launcher = launcher
        self._db = db
        self._tasks: dict[int, EditTask] = {}
        self._jobs: dict[int, FfmpegJob] = {}
        self._pausing: set[int] = set()
        self._closing = False
        self.max_concurrent = max_concurrent
        #: Comprueba si hay espacio para una tarea; los tests lo sustituyen.
        self.space_check: Callable[[EditPlan], bool] = _has_space
        self._next_id = 1
        if db is not None:
            row = db.query("SELECT MAX(id) AS top FROM edits")[0]
            self._next_id = int(row["top"] or 0) + 1

    # ------------------------------------------------------------------ consulta

    @property
    def launcher(self) -> Launcher:
        return self._launcher

    def tasks(self) -> list[EditTask]:
        return sorted(self._tasks.values(), key=lambda task: task.position)

    def task(self, task_id: int) -> EditTask | None:
        return self._tasks.get(task_id)

    @property
    def busy(self) -> bool:
        return any(t.state in (EditState.QUEUED, EditState.RUNNING) for t in self._tasks.values())

    # ------------------------------------------------------------------ acciones

    def add(self, title: str, plan: EditPlan) -> int:
        position = max((t.position for t in self._tasks.values()), default=0.0) + 1
        task = EditTask(self._next_id, title, plan, position=position, created_at=now_iso())
        self._next_id += 1
        self._tasks[task.task_id] = task
        self._save(task)
        self.task_added.emit(task.task_id)
        self._pump()
        return task.task_id

    def cancel(self, task_id: int) -> None:
        task = self._tasks.get(task_id)
        if task is None or task.state in EDIT_FINISHED:
            return
        job = self._jobs.get(task_id)
        if job is not None:
            self._pausing.discard(task_id)
            job.cancel()
            return
        task.state = EditState.CANCELLED
        self._changed(task)

    def pause(self, task_id: int) -> None:
        task = self._tasks.get(task_id)
        if task is None or task.state not in (EditState.QUEUED, EditState.RUNNING):
            return
        job = self._jobs.get(task_id)
        if job is not None:
            self._pausing.add(task_id)
            job.cancel()
            return
        task.state = EditState.PAUSED
        self._changed(task)

    def resume(self, task_id: int) -> None:
        task = self._tasks.get(task_id)
        if task is not None and task.state in (EditState.PAUSED, *EDIT_FINISHED):
            self._enqueue(task)

    retry = resume

    def remove(self, task_id: int) -> None:
        task = self._tasks.pop(task_id, None)
        if task is None:
            return
        job = self._jobs.get(task_id)
        if job is not None:
            job.cancel()
        if self._db is not None:
            self._db.execute("DELETE FROM edits WHERE id = ?", (task_id,))
        self.task_removed.emit(task_id)

    def move(self, task_id: int, offset: int) -> None:
        tasks = self.tasks()
        index = next((i for i, t in enumerate(tasks) if t.task_id == task_id), None)
        if index is None:
            return
        target = max(0, min(len(tasks) - 1, index + offset))
        tasks.insert(target, tasks.pop(index))
        for position, task in enumerate(tasks, start=1):
            if task.position != position:
                task.position = float(position)
                self._changed(task)

    def restore(self) -> None:
        """Carga la cola guardada; lo que estaba pendiente o en marcha queda en pausa."""
        if self._db is None:
            return
        for row in self._db.query("SELECT * FROM edits ORDER BY position"):
            plan = plan_from_dict(_load_json(row["plan"]))
            if plan is None:
                continue
            try:
                state = EditState(row["state"])
            except ValueError:
                state = EditState.FAILED
            if state in (EditState.QUEUED, EditState.RUNNING):
                state = EditState.PAUSED
            task = EditTask(
                task_id=int(row["id"]),
                title=row["title"],
                plan=plan,
                state=state,
                position=float(row["position"]),
                fraction=1.0 if state is EditState.COMPLETED else None,
                error_code=row["error_code"],
                error_detail=row["error_detail"],
                log=row["log"].splitlines(),
                created_at=row["created_at"],
            )
            self._tasks[task.task_id] = task
            self._next_id = max(self._next_id, task.task_id + 1)
            self.task_added.emit(task.task_id)

    def shutdown(self) -> None:
        self._closing = True
        jobs = list(self._jobs.items())
        for task_id, job in jobs:
            self._pausing.add(task_id)
            job.cancel()
        for _task_id, job in jobs:
            job.wait(_SHUTDOWN_WAIT_MS)
        for task in self._tasks.values():
            if task.state is EditState.QUEUED:
                task.state = EditState.PAUSED
                self._save(task)

    # ------------------------------------------------------------------- turnos

    def _enqueue(self, task: EditTask) -> None:
        task.state = EditState.QUEUED
        task.fraction = task.speed = None
        task.error_code = task.error_detail = ""
        self._changed(task)
        self._pump()

    def _pump(self) -> None:
        if self._closing:
            return
        for task in self.tasks():
            if len(self._jobs) >= max(1, self.max_concurrent):
                return
            if task.state is EditState.QUEUED:
                self._launch(task)

    def _launch(self, task: EditTask) -> None:
        if not self.space_check(task.plan):
            task.state = EditState.FAILED
            task.error_code = ERROR_NO_SPACE
            self._changed(task)
            return
        job = FfmpegJob(task.plan, self._launcher, parent=self)
        self._jobs[task.task_id] = job
        task.state = EditState.RUNNING
        task.fraction = 0.0 if task.plan.duration else None
        job.progress.connect(lambda f, s, i=task.task_id: self._on_progress(i, f, s))
        job.finished.connect(lambda st, c, d, i=task.task_id: self._on_finished(i, st, c, d))
        self._changed(task)
        job.start()

    def _on_progress(self, task_id: int, fraction: float | None, speed: float | None) -> None:
        task = self._tasks.get(task_id)
        if task is not None:
            task.fraction = fraction
            # El último bloque (progress=end) no trae velocidad: se conserva la anterior.
            if speed is not None:
                task.speed = speed
            self.task_changed.emit(task_id)

    def _on_finished(self, task_id: int, status: str, code: str, detail: str) -> None:
        job = self._jobs.pop(task_id, None)
        task_log = list(job.log_lines) if job is not None else []
        if job is not None:
            job.deleteLater()
        pausing = task_id in self._pausing
        self._pausing.discard(task_id)
        task = self._tasks.get(task_id)
        if task is not None:
            task.log = task_log
            task.error_code, task.error_detail = code, detail
            if status == "completed":
                task.state, task.fraction = EditState.COMPLETED, 1.0
            elif status == "cancelled":
                task.state = EditState.PAUSED if pausing else EditState.CANCELLED
            elif task.plan.cpu_fallback:
                # La aceleración por hardware ha fallado: se repite por CPU sin preguntar.
                log.warning("Hardware encoding failed for %s; retrying on CPU", task.title)
                task.plan = replace(task.plan, passes=task.plan.cpu_fallback, cpu_fallback=())
                task.state = EditState.QUEUED
                task.error_code = task.error_detail = ""
            else:
                task.state = EditState.FAILED
            self._changed(task)
            if task.state is EditState.COMPLETED:
                self.task_completed.emit(task_id)
        self._pump()

    # ------------------------------------------------------------- persistencia

    def _changed(self, task: EditTask) -> None:
        self._save(task)
        self.task_changed.emit(task.task_id)

    def _save(self, task: EditTask) -> None:
        if self._db is None:
            return
        self._db.execute(
            """
            INSERT INTO edits (id, title, position, state, plan, error_code, error_detail, log,
                created_at, updated_at)
            VALUES (:id, :title, :position, :state, :plan, :error_code, :error_detail, :log,
                :created_at, :updated_at)
            ON CONFLICT(id) DO UPDATE SET position = excluded.position, state = excluded.state,
                plan = excluded.plan,
                error_code = excluded.error_code, error_detail = excluded.error_detail,
                log = excluded.log, updated_at = excluded.updated_at
            """,
            {
                "id": task.task_id,
                "title": task.title,
                "position": task.position,
                "state": task.state.value,
                "plan": json.dumps(plan_to_dict(task.plan)),
                "error_code": task.error_code,
                "error_detail": task.error_detail,
                "log": "\n".join(task.log[-_LOG_LINES:]),
                "created_at": task.created_at or now_iso(),
                "updated_at": now_iso(),
            },
        )


def _has_space(plan: EditPlan) -> bool:
    needed = 0
    for source in plan.inputs:
        try:
            needed += source.stat().st_size
        except OSError:
            continue
    return enough_space(plan.output.parent, needed)


def _load_json(raw: str | None) -> object:
    try:
        return json.loads(raw) if raw else None
    except ValueError:
        return None
