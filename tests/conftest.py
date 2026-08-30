"""Shared pytest fixtures."""
from __future__ import annotations

import sqlite3
from collections.abc import Iterator

import pytest

from bazaar.db.database import connect, init_db


@pytest.fixture()
def db(tmp_path) -> Iterator[sqlite3.Connection]:
    """A fresh, schema-initialized SQLite database in a temp dir."""
    path = str(tmp_path / "test.db")
    init_db(path, drop=True)
    conn = connect(path)
    try:
        yield conn
    finally:
        conn.close()
