"""Tests for the SQLite progress store (uses a temp database, never the Photos library)."""

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from ansel import db

WEEK = timedelta(days=7)


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    return db.connect(tmp_path / "test.db")


def test_record_and_reviewed_uuids(conn: sqlite3.Connection) -> None:
    db.record(conn, "uuid-1", "done", caption="A dog", keywords=["dog", "park"])
    db.record(conn, "uuid-2", "skipped")
    db.record(conn, "uuid-3", "error", error="bridge timeout")
    assert db.reviewed_uuids(conn) == {"uuid-1", "uuid-2", "uuid-3"}


def test_record_overwrites_existing(conn: sqlite3.Connection) -> None:
    db.record(conn, "uuid-1", "skipped")
    db.record(conn, "uuid-1", "done", caption="Second pass")
    assert db.all_statuses(conn) == {"uuid-1": "done"}


def test_clear(conn: sqlite3.Connection) -> None:
    db.record(conn, "uuid-1", "done")
    assert db.clear(conn, "uuid-1") is True
    assert db.clear(conn, "uuid-1") is False
    assert db.reviewed_uuids(conn) == set()


def test_status_counts(conn: sqlite3.Connection) -> None:
    db.record(conn, "a", "done")
    db.record(conn, "b", "done")
    db.record(conn, "c", "skipped")
    assert db.status_counts(conn) == {"done": 2, "skipped": 1}


def test_excluded_uuids_without_window_excludes_everything(conn: sqlite3.Connection) -> None:
    db.record(conn, "a", "done")
    db.record(conn, "b", "skipped")
    assert db.excluded_uuids(conn) == {"a", "b"}


def test_excluded_uuids_resurfaces_old_skips(conn: sqlite3.Connection) -> None:
    db.record(conn, "old-skip", "skipped")
    db.record(conn, "captioned", "done")
    db.record(conn, "marked", "delete")
    db.record(conn, "failed", "error")
    next_week = datetime.now(UTC) + timedelta(days=8)
    excluded = db.excluded_uuids(conn, resurface_skips_after=WEEK, now=next_week)
    assert excluded == {"captioned", "marked", "failed"}


def test_excluded_uuids_keeps_recent_skips(conn: sqlite3.Connection) -> None:
    db.record(conn, "recent-skip", "skipped")
    excluded = db.excluded_uuids(conn, resurface_skips_after=WEEK)
    assert excluded == {"recent-skip"}


def test_invalid_status_rejected(conn: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        db.record(conn, "a", "bogus")


def test_delete_status_accepted(conn: sqlite3.Connection) -> None:
    db.record(conn, "a", "delete")
    assert db.all_statuses(conn) == {"a": "delete"}


def test_migration_from_old_check_constraint(tmp_path: Path) -> None:
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.execute(
        "CREATE TABLE reviews ("
        " uuid TEXT PRIMARY KEY,"
        " status TEXT NOT NULL CHECK (status IN ('done', 'skipped', 'error')),"
        " caption TEXT, keywords TEXT, error TEXT, reviewed_at TEXT NOT NULL)"
    )
    old.execute(
        "INSERT INTO reviews VALUES ('uuid-1', 'done', 'A dog', NULL, NULL, '2026-01-01')"
    )
    old.commit()
    old.close()

    conn = db.connect(path)
    assert db.all_statuses(conn) == {"uuid-1": "done"}
    db.record(conn, "uuid-2", "delete")
    assert db.all_statuses(conn) == {"uuid-1": "done", "uuid-2": "delete"}


def test_commit_survives_new_connection(tmp_path: Path) -> None:
    path = tmp_path / "test.db"
    conn = db.connect(path)
    db.record(conn, "uuid-1", "done")
    conn.close()
    reopened = db.connect(path)
    assert db.reviewed_uuids(reopened) == {"uuid-1"}
