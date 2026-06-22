"""SQLite progress tracking.

Each reviewed photo gets one row keyed by its Photos UUID (which is stable
across launches and machines), making review sessions resumable. Every write
commits immediately so an interrupted session never loses work.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

STATUSES = ("done", "skipped", "error", "delete")

SCHEMA = """
CREATE TABLE IF NOT EXISTS reviews (
    uuid        TEXT PRIMARY KEY,
    status      TEXT NOT NULL CHECK (status IN ('done', 'skipped', 'error', 'delete')),
    caption     TEXT,
    keywords    TEXT,
    error       TEXT,
    reviewed_at TEXT NOT NULL
);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    """Open (creating if needed) the progress database and ensure the schema is current."""
    conn = sqlite3.connect(db_path)
    conn.execute(SCHEMA)
    _migrate(conn)
    conn.commit()
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    """Rebuild the reviews table if its CHECK constraint predates newer statuses."""
    (table_sql,) = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'reviews'"
    ).fetchone()
    if all(f"'{status}'" in table_sql for status in STATUSES):
        return
    conn.execute("ALTER TABLE reviews RENAME TO reviews_old")
    conn.execute(SCHEMA)
    conn.execute("INSERT INTO reviews SELECT * FROM reviews_old")
    conn.execute("DROP TABLE reviews_old")


def reviewed_uuids(conn: sqlite3.Connection) -> set[str]:
    """Return the UUIDs of all photos with any recorded status (done/skipped/error)."""
    rows = conn.execute("SELECT uuid FROM reviews").fetchall()
    return {row[0] for row in rows}


def excluded_uuids(
    conn: sqlite3.Connection,
    *,
    resurface_skips_after: timedelta | None = None,
    now: datetime | None = None,
) -> set[str]:
    """Return the UUIDs a review session should exclude.

    Without a resurface window this is every recorded UUID. With one, photos
    skipped longer ago than the window become eligible again ("not now, ask
    me later"); done/delete/error records always stay excluded.
    """
    if resurface_skips_after is None:
        return reviewed_uuids(conn)
    cutoff = (now or datetime.now(UTC)) - resurface_skips_after
    rows = conn.execute("SELECT uuid, status, reviewed_at FROM reviews").fetchall()
    return {
        uuid
        for uuid, status, reviewed_at in rows
        if not (status == "skipped" and datetime.fromisoformat(reviewed_at) <= cutoff)
    }


def all_statuses(conn: sqlite3.Connection) -> dict[str, str]:
    """Return a mapping of photo UUID to recorded status."""
    rows = conn.execute("SELECT uuid, status FROM reviews").fetchall()
    return {uuid: status for uuid, status in rows}


def record(
    conn: sqlite3.Connection,
    uuid: str,
    status: str,
    *,
    caption: str | None = None,
    keywords: Sequence[str] | None = None,
    error: str | None = None,
) -> None:
    """Record (or overwrite) a photo's review status and commit immediately."""
    conn.execute(
        "INSERT OR REPLACE INTO reviews (uuid, status, caption, keywords, error, reviewed_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (
            uuid,
            status,
            caption,
            ", ".join(keywords) if keywords else None,
            error,
            datetime.now(UTC).isoformat(),
        ),
    )
    conn.commit()


def clear(conn: sqlite3.Connection, uuid: str) -> bool:
    """Delete a photo's review record so it comes up again. Returns True if a row existed."""
    cursor = conn.execute("DELETE FROM reviews WHERE uuid = ?", (uuid,))
    conn.commit()
    return cursor.rowcount > 0


def status_counts(conn: sqlite3.Connection) -> dict[str, int]:
    """Return counts of recorded statuses, e.g. {'done': 12, 'skipped': 3, 'error': 1}."""
    rows = conn.execute("SELECT status, COUNT(*) FROM reviews GROUP BY status").fetchall()
    return {status: count for status, count in rows}
