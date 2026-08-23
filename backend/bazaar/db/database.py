"""SQLite access. Thin, explicit, and Postgres-portable.

Design choices that matter:
  * foreign_keys and the UNIQUE constraints are enforced by the engine, so the
    replay and double-charge defenses cannot be bypassed by an application bug.
  * money is always INTEGER paise; no float ever touches a monetary column.
  * connections use Row factory so callers read columns by name.
"""
from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from bazaar.config import SCHEMA_PATH, settings


def connect(db_path: str | None = None, *, check_same_thread: bool = True) -> sqlite3.Connection:
    """Open a connection with foreign keys on and Row access.

    The API passes check_same_thread=False because FastAPI serves requests from a
    threadpool; access there is serialized with a lock in the API layer.
    """
    path = db_path or settings.db_path
    conn = sqlite3.connect(path, check_same_thread=check_same_thread)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db(db_path: str | None = None, *, drop: bool = False) -> str:
    """Create the schema. Returns the resolved db path.

    With drop=True, remove any existing file first (a clean, reproducible DB).
    """
    path = db_path or settings.db_path
    if drop:
        p = Path(path)
        if p.exists():
            p.unlink()
    schema_sql = Path(SCHEMA_PATH).read_text(encoding="utf-8")
    conn = connect(path)
    try:
        conn.executescript(schema_sql)
        conn.commit()
    finally:
        conn.close()
    return path


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Run a block inside a single DB transaction, rolling back on error."""
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def table_names(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    return [r["name"] for r in rows]
