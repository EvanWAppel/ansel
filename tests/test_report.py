"""Tests for the pure stats aggregation and CSV export (no Photos library involved)."""

import csv
import io
from datetime import datetime
from types import SimpleNamespace

import pytest

from ansel import db, report


def photo(uuid: str, date: datetime | None) -> SimpleNamespace:
    return SimpleNamespace(uuid=uuid, date=date)


MAY = datetime(2024, 5, 3)
JUNE = datetime(2024, 6, 9)


def test_build_stats_totals_and_months() -> None:
    photos = [photo("a", MAY), photo("b", MAY), photo("c", JUNE), photo("d", None)]
    statuses = {"a": "done", "c": "delete", "d": "error"}
    stats = report.build_stats(photos, statuses)
    assert stats == {
        "total": 4,
        "remaining": 1,
        "overall": {"done": 1, "skipped": 0, "error": 1, "delete": 1},
        "months": {
            "2024-05": {
                "total": 2,
                "done": 1,
                "skipped": 0,
                "error": 0,
                "delete": 0,
                "remaining": 1,
            },
            "2024-06": {
                "total": 1,
                "done": 0,
                "skipped": 0,
                "error": 0,
                "delete": 1,
                "remaining": 0,
            },
            "unknown": {
                "total": 1,
                "done": 0,
                "skipped": 0,
                "error": 1,
                "delete": 0,
                "remaining": 0,
            },
        },
    }


def test_build_stats_months_sorted() -> None:
    photos = [photo("a", JUNE), photo("b", None), photo("c", MAY)]
    assert list(report.build_stats(photos, {})["months"]) == ["2024-05", "2024-06", "unknown"]


def test_build_stats_ignores_statuses_for_photos_not_in_library() -> None:
    stats = report.build_stats([photo("a", MAY)], {"gone": "done"})
    assert stats["overall"]["done"] == 0
    assert stats["remaining"] == 1


def test_build_stats_empty_library() -> None:
    assert report.build_stats([], {}) == {
        "total": 0,
        "remaining": 0,
        "overall": dict.fromkeys(db.STATUSES, 0),
        "months": {},
    }


def test_write_csv_header_and_rows() -> None:
    out = io.StringIO()
    report.write_csv(
        [("uuid-1", "done", "A dog, running", "dog, park", None, "2026-01-01T00:00:00+00:00")],
        out,
    )
    parsed = list(csv.reader(io.StringIO(out.getvalue())))
    assert parsed == [
        ["uuid", "status", "caption", "keywords", "error", "reviewed_at"],
        ["uuid-1", "done", "A dog, running", "dog, park", "", "2026-01-01T00:00:00+00:00"],
    ]


def test_write_csv_empty_still_writes_header() -> None:
    out = io.StringIO()
    report.write_csv([], out)
    assert out.getvalue() == "uuid,status,caption,keywords,error,reviewed_at\n"


# Representative bridge failures: photoscript wraps py-applescript's ScriptError
# (message + " (<errno>)") as AppleScriptError("run_script '<name>' failed: ..."),
# and raises ValueError("Invalid photo id: ...") when its `photoExists` check
# returns false -- which it also does on *any* AppleScript failure (the lookup sits
# in a bare `try ... on error return false`), so that case is ambiguous.
NOT_AUTHORIZED = (
    "run_script 'photoSetDescription' failed: "
    "Not authorized to send Apple events to Photos. (-1743)"
)
NOT_RUNNING = (
    "run_script 'photoExists' failed: Photos got an error: Application isn't running. (-600)"
)
TIMED_OUT = (
    "run_script 'photoSetKeywords' failed: Photos got an error: AppleEvent timed out. (-1712)"
)
NOT_FOUND = "Invalid photo id: 1F2E3D4C-0000-0000-0000-000000000000"
# Real ScriptError text carries trailing app/range details after the number.
NOT_AUTHORIZED_WITH_APP = (
    "run_script 'photosLibraryVersion' failed:"
    " Not authorized to send Apple events to Photos. (-1743) app='Photos'"
)
LAUNCH_GAVE_UP = "run_script 'photoExists' failed: User canceled. (-128)"


@pytest.mark.parametrize(
    ("message", "kind", "needle"),
    [
        (NOT_AUTHORIZED, "permission", "Privacy & Security → Automation"),
        (NOT_AUTHORIZED_WITH_APP, "permission", "Automation"),
        ("execution error: (-1743)", "permission", "Automation"),
        (NOT_RUNNING, "not-running", "Open Photos"),
        (LAUNCH_GAVE_UP, "not-running", "Open Photos"),
        (TIMED_OUT, "timeout", "busy"),
        (NOT_FOUND, "not-found", "may have been deleted"),
    ],
)
def test_classify_bridge_error_known_cases(message: str, kind: str, needle: str) -> None:
    advice = report.classify_bridge_error(message)
    assert advice is not None
    assert advice.kind == kind
    assert needle in advice.fix


def test_not_found_advice_also_points_at_permission_and_photos() -> None:
    # photoExists swallows every failure, so "not found" must not claim deletion.
    advice = report.classify_bridge_error(NOT_FOUND)
    assert advice is not None
    assert "Automation" in advice.fix
    assert "Photos" in advice.fix


def test_classify_ignores_codes_quoted_from_arguments() -> None:
    # A caption echoed back inside the error must not decide the classification.
    message = (
        "run_script 'photoSetDescription' failed:"
        ' Can\'t make "lunch (-600) timed out" into type text. (-1700)'
    )
    assert report.classify_bridge_error(message) is None


@pytest.mark.parametrize("message", ["bridge timeout", "", "something odd (-9999)"])
def test_classify_bridge_error_unknown_returns_none(message: str) -> None:
    assert report.classify_bridge_error(message) is None
