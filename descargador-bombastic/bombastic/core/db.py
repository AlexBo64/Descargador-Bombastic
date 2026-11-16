"""Base de datos SQLite de la aplicación (cola, ediciones, recetas, historial y perfiles).

El esquema se versiona con ``PRAGMA user_version``: cada elemento de :data:`MIGRATIONS` lleva
la base de datos de la versión ``n`` a la ``n + 1``. Nunca se edita una migración ya publicada;
los cambios se añaden como migraciones nuevas al final.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import time
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

MIGRATIONS: tuple[str, ...] = (
    # 1 — Fase 2: cola de descargas.
    """
    CREATE TABLE downloads (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        url TEXT NOT NULL,
        position REAL NOT NULL,
        state TEXT NOT NULL,
        info TEXT,
        options TEXT,
        playlist_items TEXT NOT NULL DEFAULT '',
        files TEXT NOT NULL DEFAULT '[]',
        error_code TEXT NOT NULL DEFAULT '',
        error_detail TEXT NOT NULL DEFAULT '',
        command TEXT NOT NULL DEFAULT '',
        log TEXT NOT NULL DEFAULT '',
        attempts INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE INDEX downloads_position ON downloads(position);
    """,
)

SCHEMA_VERSION = len(MIGRATIONS)


def now_iso() -> str:
    """Fecha y hora local en formato ISO, con segundos."""
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def migrate(conn: sqlite3.Connection, migrations: Sequence[str] = MIGRATIONS) -> int:
    """Aplica las migraciones pendientes. Devuelve la versión final."""
    current = int(conn.execute("PRAGMA user_version").fetchone()[0])
    if current > len(migrations):
        log.warning(
            "Database schema %s is newer than this app (%s); using it as is",
            current,
            len(migrations),
        )
        return current
    for version in range(current, len(migrations)):
        log.info("Migrating database to schema %s", version + 1)
        conn.executescript(
            f"BEGIN;\n{migrations[version]}\nPRAGMA user_version = {version + 1};\nCOMMIT;"
        )
    return max(current, len(migrations))


class Database:
    """Conexión única a la base de datos. Las escrituras se confirman al momento.

    Se usa solo desde el hilo de la interfaz; las operaciones son pequeñas y rápidas.
    Con ``path=None`` la base de datos vive en memoria (tests).
    """

    def __init__(self, path: Path | None) -> None:
        self.path = path
        self.conn = self._open()

    def _connect(self) -> sqlite3.Connection:
        target = ":memory:" if self.path is None else str(self.path)
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(target, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        if self.path is not None:
            conn.execute("PRAGMA journal_mode = WAL")
        return conn

    def _open(self) -> sqlite3.Connection:
        try:
            conn = self._connect()
            conn.execute("PRAGMA quick_check").fetchone()
            migrate(conn)
            return conn
        except sqlite3.DatabaseError:
            if self.path is None:
                raise
            log.exception("Database %s is damaged; starting a new one", self.path)
            self._set_aside_damaged()
            conn = self._connect()
            migrate(conn)
            return conn

    def _set_aside_damaged(self) -> None:
        assert self.path is not None
        stamp = time.strftime("%Y%m%d-%H%M%S")
        for suffix in ("", "-wal", "-shm"):
            source = Path(str(self.path) + suffix)
            if source.exists():
                try:
                    os.replace(source, Path(f"{self.path}.damaged-{stamp}{suffix}"))
                except OSError:
                    log.exception("Could not move damaged database file %s", source)

    @property
    def version(self) -> int:
        return int(self.conn.execute("PRAGMA user_version").fetchone()[0])

    def execute(self, sql: str, params: Sequence[Any] | dict[str, Any] = ()) -> sqlite3.Cursor:
        return self.conn.execute(sql, params)

    def executemany(self, sql: str, rows: Iterable[Sequence[Any]]) -> None:
        self.conn.execute("BEGIN")
        try:
            self.conn.executemany(sql, rows)
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise
        self.conn.execute("COMMIT")

    def query(self, sql: str, params: Sequence[Any] | dict[str, Any] = ()) -> list[sqlite3.Row]:
        return list(self.conn.execute(sql, params).fetchall())

    def close(self) -> None:
        self.conn.close()
