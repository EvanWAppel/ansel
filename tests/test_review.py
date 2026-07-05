"""Integration tests for the interactive review loop.

These exercise the full ``run_session()`` flow against a real (temp) SQLite
progress database, with the two external worlds mocked out:

- **osxphotos** — photos are lightweight ``FakePhoto`` stand-ins carrying just
  the attributes ``run_session`` reads (uuid, filename, date, albums,
  description, keywords).
- **photoscript** — the AppleScript-bridge calls (``write_metadata``,
  ``mark_for_deletion``) and the preview machinery (``display_path``,
  ``open_preview``) are patched on the ``ansel.review`` module, so nothing
  touches the Photos library or spawns a window.

Keyboard answers are scripted by replacing ``click.prompt`` with a queue: each
call pops the next answer, mirroring the real caption-then-keywords prompt
order.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import click
import pytest

from ansel import db, review
from ansel.config import Config


@dataclass
class FakePhoto:
    """A stand-in for ``osxphotos.PhotoInfo`` exposing only what the loop reads."""

    uuid: str
    original_filename: str = "IMG_0001.jpg"
    date: datetime | None = field(default_factory=lambda: datetime(2024, 5, 1, 12, 0))
    albums: list[str] = field(default_factory=list)
    description: str | None = None
    keywords: list[str] = field(default_factory=list)


class FakePreview:
    """Stand-in for ``photos.Preview`` — records whether it was closed."""

    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def conn(tmp_path: Path):
    return db.connect(tmp_path / "review.db")


@pytest.fixture
def config() -> Config:
    return Config(shortcuts={"g": "guitar", "t": "travel"})


@pytest.fixture
def scripted_prompts(monkeypatch: pytest.MonkeyPatch):
    """Return a callable that installs a queue of answers for ``click.prompt``.

    ``run_session`` calls ``click.prompt`` once for the caption and (only when a
    caption was entered) once more for keywords, so answers are consumed in that
    order.
    """

    def install(answers: list[str]) -> list[str]:
        queue = list(answers)

        def fake_prompt(*_args: object, **_kwargs: object) -> str:
            return queue.pop(0)

        monkeypatch.setattr(click, "prompt", fake_prompt)
        return queue

    return install


@pytest.fixture
def spy_photos(monkeypatch: pytest.MonkeyPatch):
    """Patch the photoscript/preview surface on ``ansel.review`` and record calls.

    By default previews are available (a ``FakePreview`` is opened) and the
    bridge writes succeed. Individual tests can override the recorded behaviour
    via the returned namespace.
    """

    calls: dict[str, list] = {"write": [], "delete": [], "opened": []}

    def fake_display_path(_photo: FakePhoto) -> Path | None:
        return spy.display_path_result

    def fake_open_preview(path: Path) -> FakePreview:
        preview = FakePreview()
        calls["opened"].append((path, preview))
        return preview

    def fake_write_metadata(uuid: str, caption: str | None, keywords: list[str]) -> None:
        calls["write"].append((uuid, caption, list(keywords)))
        if spy.write_error is not None:
            raise spy.write_error

    def fake_mark_for_deletion(uuid: str) -> None:
        calls["delete"].append(uuid)
        if spy.mark_error is not None:
            raise spy.mark_error

    spy = SimpleNamespace(
        calls=calls,
        display_path_result=Path("/tmp/fake.jpg"),
        write_error=None,
        mark_error=None,
    )
    monkeypatch.setattr(review, "display_path", fake_display_path)
    monkeypatch.setattr(review, "open_preview", fake_open_preview)
    monkeypatch.setattr(review, "write_metadata", fake_write_metadata)
    monkeypatch.setattr(review, "mark_for_deletion", fake_mark_for_deletion)
    return spy


def test_caption_and_keywords_saved(conn, config, spy_photos, scripted_prompts) -> None:
    scripted_prompts(["A dog at the park", "g, park"])
    photos = [FakePhoto("uuid-1")]

    review.run_session(photos, conn, config)

    # Shortcut 'g' expanded to 'guitar'; freeform 'park' passed through.
    assert spy_photos.calls["write"] == [("uuid-1", "A dog at the park", ["guitar", "park"])]
    assert db.all_statuses(conn) == {"uuid-1": "done"}
    row = conn.execute(
        "SELECT caption, keywords FROM reviews WHERE uuid = 'uuid-1'"
    ).fetchone()
    assert row == ("A dog at the park", "guitar, park")


def test_blank_caption_skips(conn, config, spy_photos, scripted_prompts) -> None:
    scripted_prompts([""])
    photos = [FakePhoto("uuid-1")]

    review.run_session(photos, conn, config)

    assert db.all_statuses(conn) == {"uuid-1": "skipped"}
    assert spy_photos.calls["write"] == []  # never reached the keyword prompt


def test_d_marks_for_deletion(conn, config, spy_photos, scripted_prompts) -> None:
    scripted_prompts(["d"])
    photos = [FakePhoto("uuid-1")]

    review.run_session(photos, conn, config)

    assert spy_photos.calls["delete"] == ["uuid-1"]
    assert spy_photos.calls["write"] == []
    assert db.all_statuses(conn) == {"uuid-1": "delete"}


def test_q_quits_without_touching_later_photos(conn, config, spy_photos, scripted_prompts) -> None:
    scripted_prompts(["q"])
    photos = [FakePhoto("uuid-1"), FakePhoto("uuid-2")]

    review.run_session(photos, conn, config)

    # Quit before recording anything; the second photo is never reached.
    assert db.all_statuses(conn) == {}
    assert spy_photos.calls["write"] == []


def test_write_failure_logged_as_error_and_loop_continues(
    conn, config, spy_photos, scripted_prompts
) -> None:
    spy_photos.write_error = RuntimeError("bridge timeout")
    # Photo 1's write fails; photo 2 is skipped — proving the loop survived.
    scripted_prompts(["caption one", "g", ""])
    photos = [FakePhoto("uuid-1"), FakePhoto("uuid-2")]

    review.run_session(photos, conn, config)

    assert db.all_statuses(conn) == {"uuid-1": "error", "uuid-2": "skipped"}
    row = conn.execute(
        "SELECT caption, keywords, error FROM reviews WHERE uuid = 'uuid-1'"
    ).fetchone()
    assert row == ("caption one", "guitar", "bridge timeout")


def test_mark_for_deletion_failure_logged_as_error(
    conn, config, spy_photos, scripted_prompts
) -> None:
    spy_photos.mark_error = RuntimeError("no album access")
    scripted_prompts(["d"])
    photos = [FakePhoto("uuid-1")]

    review.run_session(photos, conn, config)

    row = conn.execute(
        "SELECT status, error FROM reviews WHERE uuid = 'uuid-1'"
    ).fetchone()
    assert row == ("error", "no album access")


def test_full_loop_mixes_caption_delete_skip(
    conn, config, spy_photos, scripted_prompts
) -> None:
    """One session over four photos exercising every outcome in sequence."""
    scripted_prompts(
        [
            "a sunset",  # photo 1 caption
            "t, beach",  # photo 1 keywords
            "d",  # photo 2 → delete
            "",  # photo 3 → skip
            "just a caption",  # photo 4 caption
            "",  # photo 4 keywords (none)
        ]
    )
    photos = [FakePhoto(f"uuid-{n}") for n in range(1, 5)]

    review.run_session(photos, conn, config)

    assert db.all_statuses(conn) == {
        "uuid-1": "done",
        "uuid-2": "delete",
        "uuid-3": "skipped",
        "uuid-4": "done",
    }
    assert spy_photos.calls["write"] == [
        ("uuid-1", "a sunset", ["travel", "beach"]),
        ("uuid-4", "just a caption", []),
    ]
    assert spy_photos.calls["delete"] == ["uuid-2"]


def test_preview_opened_and_closed_between_photos(
    conn, config, spy_photos, scripted_prompts
) -> None:
    scripted_prompts(["", ""])
    photos = [FakePhoto("uuid-1"), FakePhoto("uuid-2")]

    review.run_session(photos, conn, config)

    # A preview was opened for each photo, and the first was closed when
    # advancing to the second (the last is closed in the finally block).
    opened = [preview for _path, preview in spy_photos.calls["opened"]]
    assert len(opened) == 2
    assert all(preview.closed for preview in opened)


def test_missing_original_skips_preview(conn, config, spy_photos, scripted_prompts) -> None:
    spy_photos.display_path_result = None  # nothing available locally
    scripted_prompts([""])
    photos = [FakePhoto("uuid-1")]

    review.run_session(photos, conn, config)

    # No preview opened when there's no viewable path, but review still proceeds.
    assert spy_photos.calls["opened"] == []
    assert db.all_statuses(conn) == {"uuid-1": "skipped"}
