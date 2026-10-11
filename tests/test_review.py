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


@pytest.fixture
def scripted_confirms(monkeypatch: pytest.MonkeyPatch):
    """Install a queue of answers for ``click.confirm``; returns the questions asked.

    An unexpected confirm (empty queue) fails the test instead of reading stdin.
    """

    def install(answers: list[bool | BaseException]) -> list[str]:
        queue = list(answers)
        asked: list[str] = []

        def fake_confirm(text: str, *_args: object, default: bool = False, **_kw: object) -> bool:
            asked.append(text)
            assert default is False, "keep-going must default to stopping"
            assert queue, f"unexpected confirm: {text!r}"
            answer = queue.pop(0)
            if isinstance(answer, BaseException):
                raise answer
            return answer

        monkeypatch.setattr(click, "confirm", fake_confirm)
        return asked

    return install


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


def test_write_failure_leads_with_the_fix(
    conn,
    config,
    spy_photos,
    scripted_prompts,
    scripted_confirms,
    capsys: pytest.CaptureFixture[str],
) -> None:
    raw = (
        "run_script 'photoSetDescription' failed:"
        " Not authorized to send Apple events to Photos. (-1743)"
    )
    spy_photos.write_error = RuntimeError(raw)
    scripted_prompts(["caption one", ""])
    scripted_confirms([])

    review.run_session([FakePhoto("uuid-1")], conn, config)

    out = capsys.readouterr().out
    assert "Privacy & Security → Automation" in out
    assert raw in out
    assert out.index("Automation") < out.index(raw)
    assert "ansel redo uuid-1" in out
    # The DB keeps the raw message untouched, for `redo` diagnosis and the mac app.
    assert db.all_statuses(conn) == {"uuid-1": "error"}
    assert conn.execute("SELECT error FROM reviews").fetchone() == (raw,)


def test_not_found_on_write_still_suggests_redo(
    conn, config, spy_photos, scripted_prompts, capsys: pytest.CaptureFixture[str]
) -> None:
    # The usual write-path failure: photoscript's existence check swallows the real
    # error (often a missing Automation permission) and reports "Invalid photo id".
    spy_photos.write_error = ValueError("Invalid photo id: uuid-1")
    scripted_prompts(["caption one", ""])

    review.run_session([FakePhoto("uuid-1")], conn, config)

    out = capsys.readouterr().out
    assert "may have been deleted" in out
    assert "Automation" in out
    assert "ansel redo uuid-1" in out


def test_unknown_failure_keeps_original_message(
    conn, config, spy_photos, scripted_prompts, capsys: pytest.CaptureFixture[str]
) -> None:
    spy_photos.write_error = RuntimeError("bridge timeout")
    scripted_prompts(["caption one", ""])

    review.run_session([FakePhoto("uuid-1")], conn, config)

    out = capsys.readouterr().out
    assert "write failed (bridge timeout)" in out
    assert "ansel redo uuid-1" in out


PERMISSION_ERROR = "Not authorized to send Apple events to Photos. (-1743)"
NOT_RUNNING_ERROR = "Photos got an error: Application isn't running. (-600)"


def test_permission_failure_asks_and_stops_on_no(
    conn, config, spy_photos, scripted_prompts, scripted_confirms, capsys
) -> None:
    spy_photos.write_error = RuntimeError(PERMISSION_ERROR)
    scripted_prompts(["caption one", ""])  # photo 2 is never prompted
    asked = scripted_confirms([False])

    review.run_session([FakePhoto("uuid-1"), FakePhoto("uuid-2")], conn, config)

    assert asked == ["  Photos isn't accepting changes — keep going?"]
    assert db.all_statuses(conn) == {"uuid-1": "error"}
    out = capsys.readouterr().out
    assert "Stopping — progress saved." in out
    assert "`ansel errors` to see what to redo" in out
    assert "All photos in this session reviewed" not in out
    # The preview of the photo that failed is closed on the way out.
    assert [preview.closed for _, preview in spy_photos.calls["opened"]] == [True]


def test_not_running_failure_asks_and_continues_on_yes(
    conn, config, spy_photos, scripted_prompts, scripted_confirms
) -> None:
    spy_photos.mark_error = RuntimeError(NOT_RUNNING_ERROR)
    scripted_prompts(["d", ""])
    asked = scripted_confirms([True])

    review.run_session([FakePhoto("uuid-1"), FakePhoto("uuid-2")], conn, config)

    assert len(asked) == 1
    assert db.all_statuses(conn) == {"uuid-1": "error", "uuid-2": "skipped"}


def test_single_unrecognised_failure_does_not_ask(
    conn, config, spy_photos, scripted_prompts, scripted_confirms
) -> None:
    spy_photos.write_error = RuntimeError("bridge hiccup")
    scripted_prompts(["caption one", "", ""])
    asked = scripted_confirms([])

    review.run_session([FakePhoto("uuid-1"), FakePhoto("uuid-2")], conn, config)

    assert asked == []


def test_two_failures_in_a_row_ask_even_when_ambiguous(
    conn, config, spy_photos, scripted_prompts, scripted_confirms
) -> None:
    # On the write path a missing permission surfaces as "Invalid photo id".
    spy_photos.write_error = ValueError("Invalid photo id: x")
    scripted_prompts(["one", "", "two", ""])
    asked = scripted_confirms([False])

    photos = [FakePhoto("uuid-1"), FakePhoto("uuid-2"), FakePhoto("uuid-3")]
    review.run_session(photos, conn, config)

    assert len(asked) == 1
    assert db.all_statuses(conn) == {"uuid-1": "error", "uuid-2": "error"}


def test_skip_between_failures_does_not_reset_the_streak(
    conn, config, spy_photos, scripted_prompts, scripted_confirms
) -> None:
    spy_photos.write_error = RuntimeError("bridge hiccup")
    scripted_prompts(["one", "", "", "two", ""])
    asked = scripted_confirms([False])

    photos = [FakePhoto(f"uuid-{n}") for n in range(1, 5)]
    review.run_session(photos, conn, config)

    assert len(asked) == 1


def test_success_resets_the_streak(
    conn, config, spy_photos, scripted_prompts, scripted_confirms, monkeypatch
) -> None:
    outcomes = [RuntimeError("bridge hiccup"), None, RuntimeError("bridge hiccup")]

    def flaky_write(uuid: str, caption: str | None, keywords: list[str]) -> None:
        error = outcomes.pop(0)
        if error is not None:
            raise error

    monkeypatch.setattr(review, "write_metadata", flaky_write)
    scripted_prompts(["one", "", "two", "", "three", ""])
    asked = scripted_confirms([])

    photos = [FakePhoto("uuid-1"), FakePhoto("uuid-2"), FakePhoto("uuid-3")]
    review.run_session(photos, conn, config)

    assert asked == []
    assert db.all_statuses(conn)["uuid-2"] == "done"


def test_answering_yes_resets_the_streak(
    conn, config, spy_photos, scripted_prompts, scripted_confirms
) -> None:
    spy_photos.write_error = RuntimeError("bridge hiccup")
    scripted_prompts(["one", "", "two", "", "three", ""])
    asked = scripted_confirms([True])  # asked after #2 only; #3 starts a new streak

    photos = [FakePhoto("uuid-1"), FakePhoto("uuid-2"), FakePhoto("uuid-3")]
    review.run_session(photos, conn, config)

    assert len(asked) == 1
    assert len(db.all_statuses(conn)) == 3


def test_no_keep_going_prompt_after_the_last_photo(
    conn, config, spy_photos, scripted_prompts, scripted_confirms, capsys
) -> None:
    spy_photos.write_error = RuntimeError(PERMISSION_ERROR)
    scripted_prompts(["one", "", "two", ""])
    asked = scripted_confirms([True])  # asked after photo 1 only

    review.run_session([FakePhoto("uuid-1"), FakePhoto("uuid-2")], conn, config)

    assert len(asked) == 1
    assert db.all_statuses(conn) == {"uuid-1": "error", "uuid-2": "error"}
    out = capsys.readouterr().out
    assert "All photos in this session reviewed" not in out
    assert "Session finished — 2 photo(s) failed to save" in out


def test_streak_spans_mark_and_write_failures(
    conn, config, spy_photos, scripted_prompts, scripted_confirms
) -> None:
    spy_photos.mark_error = RuntimeError("bridge hiccup")
    spy_photos.write_error = RuntimeError("bridge hiccup")
    scripted_prompts(["d", "two", ""])
    asked = scripted_confirms([False])

    photos = [FakePhoto("uuid-1"), FakePhoto("uuid-2"), FakePhoto("uuid-3")]
    review.run_session(photos, conn, config)

    assert len(asked) == 1
    assert db.all_statuses(conn) == {"uuid-1": "error", "uuid-2": "error"}


def test_ctrl_c_at_keep_going_prompt_exits_cleanly(
    conn, config, spy_photos, scripted_prompts, scripted_confirms, capsys
) -> None:
    spy_photos.write_error = RuntimeError(PERMISSION_ERROR)
    scripted_prompts(["one", ""])
    scripted_confirms([click.exceptions.Abort()])

    review.run_session([FakePhoto("uuid-1"), FakePhoto("uuid-2")], conn, config)

    assert db.all_statuses(conn) == {"uuid-1": "error"}
    assert "Interrupted — progress saved." in capsys.readouterr().out
