"""Thin connection manager around sqlite3.

Isolated from the repository so that connection lifecycle (pragmas,
schema migrations) is a single, testable concern.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from pathlib import Path

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS detections (
    id TEXT PRIMARY KEY,
    detector_id TEXT NOT NULL,
    player_name TEXT NOT NULL,
    player_uuid TEXT NOT NULL,
    world TEXT NOT NULL,
    dimension TEXT NOT NULL,
    x REAL NOT NULL,
    y REAL NOT NULL,
    z REAL NOT NULL,
    confidence_score REAL NOT NULL,
    confidence_level INTEGER NOT NULL,
    reason TEXT NOT NULL,
    metadata TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_detections_player ON detections (player_name);
CREATE INDEX IF NOT EXISTS idx_detections_detector ON detections (detector_id);
CREATE INDEX IF NOT EXISTS idx_detections_created_at ON detections (created_at DESC);
"""


class Database:
    """Owns a single sqlite3 connection for the whole plugin lifetime.

    A lock guards every statement: Endstone plugins are not guaranteed
    to be free of cross-thread scheduler calls, and sqlite3 connections
    are not safe to share across threads without one.
    """

    def __init__(self, db_path: Path, logger: logging.Logger | None = None):
        self._path = db_path
        self._logger = logger or logging.getLogger("antidupe.db")
        self._lock = threading.RLock()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._configure()
        self._migrate()

    def _configure(self) -> None:
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL;")
            self._conn.execute("PRAGMA synchronous=NORMAL;")
            self._conn.execute("PRAGMA foreign_keys=ON;")

    def _migrate(self) -> None:
        with self._lock, self._conn:
            self._conn.executescript(_SCHEMA)
            row = self._conn.execute(
                "SELECT value FROM schema_meta WHERE key = 'version'"
            ).fetchone()
            if row is None:
                self._conn.execute(
                    "INSERT INTO schema_meta (key, value) VALUES ('version', ?)",
                    (str(SCHEMA_VERSION),),
                )

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            return self._conn.execute(sql, params)

    def executemany(self, sql: str, seq_of_params) -> sqlite3.Cursor:
        with self._lock:
            return self._conn.executemany(sql, seq_of_params)

    def commit(self) -> None:
        with self._lock:
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.commit()
            finally:
                self._conn.close()
