"""Pure reporting helpers: stats aggregation and CSV export.

Nothing here touches the Photos library or the database directly, so both
renderers (text and JSON) and the exporter are unit-testable with plain data.
"""

from __future__ import annotations

import csv
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from typing import Any, Protocol, TextIO

from ansel import db


class Dated(Protocol):
    """The two attributes of ``osxphotos.PhotoInfo`` that stats needs."""

    @property
    def uuid(self) -> str: ...

    @property
    def date(self) -> datetime | None: ...


def month_key(date: datetime | None) -> str:
    return f"{date.year:04d}-{date.month:02d}" if date else "unknown"


def build_stats(photos: Iterable[Dated], statuses: Mapping[str, str]) -> dict[str, Any]:
    """Aggregate overall and per-month status counts for the photos in the library.

    Statuses recorded for photos no longer in the library are ignored. Months
    are sorted chronologically, with undated photos last under "unknown".
    """
    overall = dict.fromkeys(db.STATUSES, 0)
    months: dict[str, dict[str, int]] = {}
    total = 0
    for photo in photos:
        total += 1
        bucket = months.setdefault(
            month_key(photo.date), {"total": 0, **dict.fromkeys(db.STATUSES, 0)}
        )
        bucket["total"] += 1
        status = statuses.get(photo.uuid)
        if status in overall:
            overall[status] += 1
            bucket[status] += 1

    for bucket in months.values():
        bucket["remaining"] = bucket["total"] - sum(bucket[s] for s in db.STATUSES)

    return {
        "total": total,
        "remaining": total - sum(overall.values()),
        "overall": overall,
        # "unknown" sorts after every "YYYY-MM" key, so a plain sort is chronological.
        "months": {key: months[key] for key in sorted(months)},
    }


def write_csv(rows: Iterable[Sequence[str | None]], out: TextIO) -> None:
    """Write review records (in ``db.COLUMNS`` order) as CSV with a header row."""
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(db.COLUMNS)
    writer.writerows(rows)
