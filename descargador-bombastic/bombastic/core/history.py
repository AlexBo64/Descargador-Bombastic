"""Historial de descargas y perfiles de opciones, en SQLite."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Signal

from bombastic.core.db import Database, now_iso
from bombastic.core.download_manager import DownloadManager, ItemState
from bombastic.core.ytdlp_command import DownloadOptions, options_from_dict, options_to_dict

HISTORY_RESULTS: tuple[str, ...] = ("completed", "failed")


@dataclass
class HistoryEntry:
    entry_id: int
    created_at: str
    title: str
    url: str
    files: list[Path]
    size: int | None
    profile: str
    #: ``completed`` o ``failed``.
    result: str
    error: str
    options: DownloadOptions | None
    #: Archivo resultante de la acción encadenada, si la hubo.
    edit_output: str = ""


class HistoryStore:
    def __init__(self, db: Database | None) -> None:
        self._db = db if db is not None else Database(None)

    def add(
        self,
        title: str,
        url: str,
        files: list[Path],
        result: str,
        error: str = "",
        options: DownloadOptions | None = None,
    ) -> int:
        size = 0
        for file in files:
            try:
                size += file.stat().st_size
            except OSError:
                continue
        cursor = self._db.execute(
            "INSERT INTO history (created_at, title, url, files, size, profile, result, error,"
            " options) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                now_iso(),
                title,
                url,
                json.dumps([str(f) for f in files], ensure_ascii=False),
                size or None,
                options.profile if options is not None else "",
                result,
                error,
                json.dumps(options_to_dict(options)) if options is not None else None,
            ),
        )
        return int(cursor.lastrowid or 0)

    def set_edit_output(self, entry_id: int, output: Path) -> None:
        self._db.execute("UPDATE history SET edit_output = ? WHERE id = ?", (str(output), entry_id))

    def search(self, text: str = "", result: str = "") -> list[HistoryEntry]:
        """Lo más reciente primero. ``text`` busca en el título y en el enlace."""
        sql = "SELECT * FROM history WHERE 1 = 1"
        params: list[Any] = []
        if text.strip():
            sql += " AND (title LIKE ? ESCAPE '\\' OR url LIKE ? ESCAPE '\\')"
            needle = "%" + re.sub(r"([%_\\])", r"\\\1", text.strip()) + "%"
            params += [needle, needle]
        if result in HISTORY_RESULTS:
            sql += " AND result = ?"
            params.append(result)
        sql += " ORDER BY id DESC"
        return [self._entry(row) for row in self._db.query(sql, params)]

    def get(self, entry_id: int) -> HistoryEntry | None:
        rows = self._db.query("SELECT * FROM history WHERE id = ?", (entry_id,))
        return self._entry(rows[0]) if rows else None

    def delete(self, entry_ids: list[int]) -> None:
        self._db.executemany("DELETE FROM history WHERE id = ?", [(i,) for i in entry_ids])

    def clear(self) -> None:
        self._db.execute("DELETE FROM history")

    @staticmethod
    def _entry(row: Any) -> HistoryEntry:
        try:
            files = [Path(f) for f in json.loads(row["files"]) if isinstance(f, str)]
        except (ValueError, TypeError):
            files = []
        try:
            options = options_from_dict(json.loads(row["options"])) if row["options"] else None
        except ValueError:
            options = None
        return HistoryEntry(
            entry_id=int(row["id"]),
            created_at=row["created_at"],
            title=row["title"],
            url=row["url"],
            files=files,
            size=row["size"],
            profile=row["profile"],
            result=row["result"],
            error=row["error"],
            options=options,
            edit_output=row["edit_output"],
        )


class HistoryRecorder(QObject):
    """Apunta en el historial cada descarga que termina (bien o con error)."""

    #: Se ha añadido una entrada (para refrescar la página de historial).
    recorded = Signal(int)

    def __init__(
        self, downloads: DownloadManager, store: HistoryStore, parent: QObject | None = None
    ) -> None:
        super().__init__(parent)
        self._downloads = downloads
        self._store = store
        #: Último estado visto de cada descarga: solo se apunta al cambiar a terminado.
        self._last: dict[int, ItemState] = {}
        #: Descarga → entrada del historial (para enlazar la edición encadenada).
        self.entry_for: dict[int, int] = {}
        downloads.item_changed.connect(self._on_changed)

    def _on_changed(self, item_id: int) -> None:
        item = self._downloads.item(item_id)
        if item is None:
            return
        previous = self._last.get(item_id)
        self._last[item_id] = item.state
        if item.state == previous or item.state not in (ItemState.COMPLETED, ItemState.FAILED):
            return
        result = "completed" if item.state is ItemState.COMPLETED else "failed"
        error = f"{item.error_code}: {item.error_detail}" if item.error_code else ""
        entry_id = self._store.add(item.title, item.url, item.files, result, error, item.options)
        self.entry_for[item_id] = entry_id
        self.recorded.emit(entry_id)


# -------------------------------------------------------------------- perfiles

#: Ajustes que guarda un perfil (los de las opciones de descarga).
PROFILE_FIELDS: tuple[str, ...] = (
    "download_preset",
    "mp3_quality",
    "embed_subs",
    "embed_extras",
    "download_dir",
    "advanced_options",
    "extra_args",
    "cookies_mode",
    "cookies_browser",
    "cookies_profile",
    "cookies_file",
    "chain_action",
)


@dataclass
class Profile:
    name: str
    values: dict[str, Any] = field(default_factory=dict)
    is_default: bool = False
    profile_id: int = 0

    def to_json(self) -> dict[str, Any]:
        return {"name": self.name, "values": self.values, "is_default": self.is_default}


class ProfileError(ValueError):
    pass


class ProfileStore:
    def __init__(self, db: Database | None) -> None:
        self._db = db if db is not None else Database(None)

    def all(self) -> list[Profile]:
        rows = self._db.query("SELECT * FROM profiles ORDER BY name COLLATE NOCASE")
        return [self._profile(row) for row in rows]

    def get(self, profile_id: int) -> Profile | None:
        return next((p for p in self.all() if p.profile_id == profile_id), None)

    def by_name(self, name: str) -> Profile | None:
        return next((p for p in self.all() if p.name.lower() == name.lower()), None)

    def default(self) -> Profile | None:
        return next((p for p in self.all() if p.is_default), None)

    def save(self, profile: Profile) -> Profile:
        taken = {p.name.lower() for p in self.all() if p.profile_id != profile.profile_id}
        base = re.sub(r" \(\d+\)$", "", profile.name.strip() or "?")
        name, counter = profile.name.strip() or "?", 2
        while name.lower() in taken:
            name = f"{base} ({counter})"
            counter += 1
        profile.name = name
        data = json.dumps(profile.values, ensure_ascii=False)
        if profile.is_default:
            self._db.execute("UPDATE profiles SET is_default = 0")
        if profile.profile_id:
            self._db.execute(
                "UPDATE profiles SET name = ?, data = ?, is_default = ? WHERE id = ?",
                (name, data, int(profile.is_default), profile.profile_id),
            )
        else:
            cursor = self._db.execute(
                "INSERT INTO profiles (name, data, is_default, created_at) VALUES (?, ?, ?, ?)",
                (name, data, int(profile.is_default), now_iso()),
            )
            profile.profile_id = int(cursor.lastrowid or 0)
        return profile

    def set_default(self, profile_id: int | None) -> None:
        self._db.execute("UPDATE profiles SET is_default = (id = ?)", (profile_id or 0,))

    def delete(self, profile_id: int) -> None:
        self._db.execute("DELETE FROM profiles WHERE id = ?", (profile_id,))

    def export_json(self, profiles: list[Profile]) -> str:
        return json.dumps(
            {"profiles": [p.to_json() for p in profiles]}, ensure_ascii=False, indent=2
        )

    def import_json(self, text: str) -> list[Profile]:
        try:
            data = json.loads(text)
        except ValueError as exc:
            raise ProfileError(str(exc)) from exc
        items = data.get("profiles") if isinstance(data, dict) else None
        if not isinstance(items, list):
            raise ProfileError("no profiles")
        result: list[Profile] = []
        for item in items:
            if not isinstance(item, dict) or not isinstance(item.get("name"), str):
                raise ProfileError("bad profile")
            values: dict[str, Any] = item["values"] if isinstance(item.get("values"), dict) else {}
            clean = {k: v for k, v in values.items() if k in PROFILE_FIELDS}
            result.append(self.save(Profile(item["name"], clean)))
        return result

    @staticmethod
    def _profile(row: Any) -> Profile:
        try:
            values = json.loads(row["data"])
        except ValueError:
            values = {}
        return Profile(
            name=row["name"],
            values=values if isinstance(values, dict) else {},
            is_default=bool(row["is_default"]),
            profile_id=int(row["id"]),
        )
