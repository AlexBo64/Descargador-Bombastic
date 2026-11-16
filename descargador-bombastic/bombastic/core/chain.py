"""Acciones encadenadas: al terminar una descarga, una tarea de edición se mete sola en la cola.

La acción viaja dentro de ``DownloadOptions.chain`` como JSON, así se guarda con la cola, con
los perfiles y con el historial sin tablas aparte.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject

from bombastic.core import ffmpeg_command as fc
from bombastic.core import ffmpeg_tools as ft
from bombastic.core.download_manager import DownloadManager, ItemState
from bombastic.core.edit_manager import EditManager
from bombastic.core.formatting import parse_timecode
from bombastic.core.media_probe import ProbeInfo
from bombastic.core.media_prober import MediaProber
from bombastic.core.output_paths import safe_output
from bombastic.core.recipes import RecipeError, RecipeStore, build_expert_plan

log = logging.getLogger(__name__)

CHAIN_KINDS: tuple[str, ...] = (
    "none",
    "convert",
    "trim",
    "compress",
    "normalize",
    "extract_audio",
    "resize",
    "recipe",
)


#: Valores típicos de cada acción para el desplegable (se puede escribir otro).
_SUGGESTIONS: dict[str, tuple[str, ...]] = {
    "convert": fc.CONTAINERS,
    "compress": ("8", "10", "25", "50", "100", "500"),
    "normalize": ("-14", "-16", "-23"),
    "extract_audio": tuple(ft.EXTRACT_FORMATS),
    "resize": ("2160", "1440", "1080", "720", "480", "360"),
}


def chain_suggestions(kind: str, recipes: RecipeStore | None = None) -> list[str]:
    """Opciones del desplegable de valor para una acción (las recetas, si es ``recipe``)."""
    if kind == "recipe":
        return [recipe.name for recipe in recipes.all()] if recipes is not None else []
    return list(_SUGGESTIONS.get(kind, ()))


@dataclass(frozen=True)
class ChainAction:
    #: Uno de :data:`CHAIN_KINDS`.
    kind: str = "none"
    #: Parámetro: contenedor, ``inicio-fin``, MB, LUFS, formato de audio, alto o receta.
    value: str = ""
    #: Borrar el archivo descargado cuando la edición termine bien.
    delete_original: bool = False

    @property
    def active(self) -> bool:
        return self.kind != "none"

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False) if self.active else ""

    @classmethod
    def from_json(cls, text: str) -> ChainAction:
        try:
            data: Any = json.loads(text) if text else {}
        except ValueError:
            return cls()
        if not isinstance(data, dict) or data.get("kind") not in CHAIN_KINDS:
            return cls()
        return cls(
            kind=str(data["kind"]),
            value=str(data.get("value") or ""),
            delete_original=data.get("delete_original") is True,
        )


class ChainError(ValueError):
    """El valor de la acción no sirve para este archivo."""


def _trim_range(value: str) -> tuple[float, float]:
    start_text, sep, end_text = value.partition("-")
    # "00:01:00-00:02:00": el guion separa; los tiempos no llevan guiones.
    start, end = parse_timecode(start_text), parse_timecode(end_text) if sep else None
    if start is None or end is None or end <= start:
        raise ChainError(value)
    return start, end


def build_chain_plan(
    action: ChainAction, source: Path, probe: ProbeInfo, recipes: RecipeStore | None = None
) -> fc.EditPlan:
    """Plan de edición de la acción para un archivo descargado."""
    kind, value = action.kind, action.value.strip()
    try:
        if kind == "convert":
            container = value.lower().lstrip(".") or "mp4"
            if container not in fc.CONTAINERS:
                raise ChainError(value)
            options = fc.ConvertOptions(container=container)
            return fc.build_convert(source, safe_output(source, container), probe, options)
        if kind == "trim":
            start, end = _trim_range(value)
            output = safe_output(source, source.suffix.lstrip(".") or "mp4")
            return fc.build_trim(source, output, probe, start, end, precise=True)
        if kind == "compress":
            target = float(value.replace(",", "."))
            log_file = source.with_name(f".{source.stem}-2pass")
            output = safe_output(source, "mp4")
            return fc.build_compress_size(source, output, probe, target, log_file)
        if kind == "normalize":
            lufs = float(value.replace(",", ".")) if value else -16.0
            ext = "mp4" if probe.has_video else source.suffix.lstrip(".") or "m4a"
            return ft.build_normalize(source, safe_output(source, ext), probe, lufs)
        if kind == "extract_audio":
            fmt = value.lower() or "mp3"
            if fmt not in ft.EXTRACT_FORMATS:
                raise ChainError(value)
            return ft.build_extract_audio(source, safe_output(source, fmt), probe, fmt)
        if kind == "resize":
            height = int(value)
            filters = ft.transform_filters(0, height)
            return ft.build_transform(source, safe_output(source, "mp4"), probe, filters)
        if kind == "recipe":
            recipe = recipes.by_name(value) if recipes is not None else None
            if recipe is None:
                raise ChainError(value)
            output = safe_output(source, recipe.output_ext)
            duration = probe.duration
            return build_expert_plan(recipe.command, [source], output, duration, recipe.params)
    except (ValueError, RecipeError) as exc:
        raise ChainError(value) from exc
    raise ChainError(kind)


class ChainRunner(QObject):
    """Vigila las descargas y, al completarse una con acción, encola la edición."""

    def __init__(
        self,
        downloads: DownloadManager,
        edits: EditManager,
        prober: MediaProber,
        recipes: RecipeStore | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._downloads = downloads
        self._edits = edits
        self._prober = prober
        self._recipes = recipes
        #: Descargas ya encadenadas (para no repetir si la tarjeta se refresca).
        self._done: set[int] = set()
        #: Archivo en espera de ffprobe → (acción, título, id de descarga).
        self._waiting: dict[str, tuple[ChainAction, str, int]] = {}
        #: Tarea de edición → archivo original que se borra al terminar bien.
        self._delete_after: dict[int, Path] = {}
        #: Tarea de edición → id de descarga (para enlazar en el historial).
        self.task_download: dict[int, int] = {}
        downloads.item_changed.connect(self._on_item_changed)
        prober.probed.connect(self._on_probed)
        prober.failed.connect(lambda path, _reason: self._waiting.pop(path, None))
        edits.task_completed.connect(self._on_task_completed)

    def queue_files(self, action: ChainAction, files: list[Path]) -> None:
        """Aplica una acción a archivos sueltos (menú contextual o ``--action``)."""
        for file in files:
            if file.is_file():
                self._waiting[str(file)] = (action, file.name, 0)
                self._prober.probe(file)

    def _on_item_changed(self, item_id: int) -> None:
        item = self._downloads.item(item_id)
        if item is None or item.options is None:
            return
        if item.state is not ItemState.COMPLETED:
            # Si se vuelve a descargar, se vuelve a encadenar.
            self._done.discard(item_id)
            return
        if item_id in self._done:
            return
        action = ChainAction.from_json(item.options.chain)
        if not action.active:
            return
        self._done.add(item_id)
        for file in item.files:
            if file.is_file():
                self._waiting[str(file)] = (action, item.title, item_id)
                self._prober.probe(file)

    def _on_probed(self, path: str, probe: ProbeInfo) -> None:
        waiting = self._waiting.pop(path, None)
        if waiting is None:
            return
        action, title, item_id = waiting
        source = Path(path)
        try:
            plan = build_chain_plan(action, source, probe, self._recipes)
        except ChainError:
            log.warning("Chained action %s does not fit %s", action, source)
            return
        task_id = self._edits.add(f"{title} → {plan.tool}", plan)
        if item_id:
            self.task_download[task_id] = item_id
        if action.delete_original:
            self._delete_after[task_id] = source

    def _on_task_completed(self, task_id: int) -> None:
        original = self._delete_after.pop(task_id, None)
        if original is not None:
            try:
                original.unlink(missing_ok=True)
            except OSError:
                log.warning("Could not delete the original %s", original)
