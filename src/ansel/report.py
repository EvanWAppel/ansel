"""Pure reporting helpers: stats aggregation, CSV export, bridge-error advice.

Nothing here touches the Photos library or the database directly, so both
renderers (text and JSON) and the exporter are unit-testable with plain data.
"""

from __future__ import annotations

import csv
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
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


@dataclass(frozen=True)
class BridgeAdvice:
    """What to do about a failed AppleScript-bridge call (always followed by `ansel redo`)."""

    kind: str
    fix: str


def _trailing_code(*codes: int) -> re.Pattern[str]:
    """Match an AppleScript error number where py-applescript's ScriptError puts it.

    ScriptError text is ``<message> (<number>)[ app='…'][ range=a-b]``. Anchoring on
    that suffix keeps a number quoted back from an argument (e.g. a caption)
    from deciding the classification.
    """
    alternatives = "|".join(str(code) for code in codes)
    return re.compile(rf"\((?:{alternatives})\)(?: app='[^']*')?(?: range=\d+-\d+)?$")


_PERMISSION_FIX = (
    "Your terminal isn't allowed to control Photos. Turn it on in System Settings"
    " → Privacy & Security → Automation (enable Photos under your terminal app)."
)

# Checked in order; the AppleScript error number is stable across macOS languages.
_BRIDGE_RULES: tuple[tuple[re.Pattern[str], BridgeAdvice], ...] = (
    (_trailing_code(-1743), BridgeAdvice("permission", _PERMISSION_FIX)),
    (
        # -600: Photos isn't running. -128: photoscript launched Photos itself and
        # gave up waiting for it to respond.
        _trailing_code(-600, -128),
        BridgeAdvice(
            "not-running",
            "Photos wasn't running or didn't respond. Open Photos (with your library"
            " loaded) and retry.",
        ),
    ),
    (
        _trailing_code(-1712),
        BridgeAdvice(
            "timeout",
            "Photos took too long to respond — it may be busy (iCloud sync, an import)."
            " Retry once it settles.",
        ),
    ),
    (
        # photoscript's photoExists check returns false on *any* AppleScript failure,
        # so this does not reliably mean the photo was deleted.
        re.compile(r"^Invalid photo id:"),
        BridgeAdvice(
            "not-found",
            "Photos couldn't find or reach this photo. It may have been deleted — or"
            " your terminal lacks the Automation permission for Photos (System Settings"
            " → Privacy & Security → Automation), or Photos was busy. Check both, then"
            " retry.",
        ),
    ),
)


def classify_bridge_error(message: str) -> BridgeAdvice | None:
    """Map a raw bridge error message to actionable advice, or None if unrecognised."""
    for pattern, advice in _BRIDGE_RULES:
        if pattern.search(message):
            return advice
    return None
