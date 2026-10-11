"""The interactive review loop."""

from __future__ import annotations

from sqlite3 import Connection
from typing import TYPE_CHECKING

import click

from ansel import db, report
from ansel.config import Config, expand_keywords
from ansel.photos import (
    DELETION_ALBUM,
    Preview,
    display_path,
    mark_for_deletion,
    open_preview,
    write_metadata,
)

# Failures that will hit every remaining photo until the user fixes something.
SYSTEMIC_KINDS = frozenset({"permission", "not-running"})
# Bridge failures in a row (skips don't count either way) before asking to stop;
# catches a systemic cause that surfaced ambiguously (e.g. "Invalid photo id").
FAILURE_STREAK_LIMIT = 2


if TYPE_CHECKING:
    import osxphotos


def describe(photo: osxphotos.PhotoInfo) -> str:
    """Format a photo's filename, date, albums, and existing metadata for display."""
    date = photo.date.strftime("%Y-%m-%d %H:%M") if photo.date else "unknown date"
    albums = ", ".join(photo.albums) if photo.albums else "—"
    caption = photo.description or "—"
    keywords = ", ".join(photo.keywords) if photo.keywords else "—"
    return (
        f"{photo.original_filename} — {date}\n"
        f"  Albums:   {albums}\n"
        f"  Caption:  {caption}\n"
        f"  Keywords: {keywords}"
    )


def run_session(photos: list[osxphotos.PhotoInfo], conn: Connection, config: Config) -> None:
    """Review photos one at a time, committing progress to SQLite after each.

    For every photo: open a Quick Look preview, show existing metadata, prompt
    for a caption (blank skips, 'd' marks for deletion, 'q' quits cleanly) and
    keywords (shortcuts and freeform mixed), then write via photoscript.
    AppleScript failures are logged with status 'error' instead of crashing
    the session; after one that looks systemic (or several in a row) the user
    is asked whether to keep going. Ctrl-C exits cleanly; everything already
    answered is committed.
    """
    total = len(photos)
    viewer: Preview | None = None
    streak = 0  # consecutive bridge failures
    try:
        for i, photo in enumerate(photos, start=1):
            click.echo(f"\n[{i}/{total}] {describe(photo)}")

            if viewer is not None:
                viewer.close()
                viewer = None
            path = display_path(photo)
            if path is None:
                click.echo(
                    "  (preview unavailable — original not on disk;"
                    " download it in Photos or skip)"
                )
            else:
                viewer = open_preview(path)

            caption = click.prompt(
                "Caption (blank=skip, d=delete, q=quit)", default="", show_default=False
            ).strip()
            if caption.lower() == "q":
                click.echo("Quitting — progress saved.")
                return
            if caption.lower() == "d":
                try:
                    mark_for_deletion(photo.uuid)
                except Exception as exc:  # AppleScript bridge calls can fail in many ways
                    db.record(conn, photo.uuid, "error", error=str(exc))
                    streak += 1
                    advice = _report_bridge_failure("marking", photo.uuid, exc)
                    if should_ask_to_stop(advice, streak):
                        if not _keep_going():
                            return
                        streak = 0
                    continue
                streak = 0
                db.record(conn, photo.uuid, "delete")
                click.echo(f"  ✗ added to “{DELETION_ALBUM}” album — batch-delete it in Photos")
                continue
            if not caption:
                db.record(conn, photo.uuid, "skipped")
                click.echo("  · skipped")
                continue

            raw = click.prompt(
                "Keywords (shortcuts + freeform, comma-separated)",
                default="",
                show_default=False,
            )
            keywords = expand_keywords(raw, config.shortcuts)

            try:
                write_metadata(photo.uuid, caption, keywords)
            except Exception as exc:  # AppleScript bridge calls can fail in many ways
                db.record(
                    conn, photo.uuid, "error", caption=caption, keywords=keywords, error=str(exc)
                )
                streak += 1
                advice = _report_bridge_failure("write", photo.uuid, exc)
                if should_ask_to_stop(advice, streak):
                    if not _keep_going():
                        return
                    streak = 0
                continue

            streak = 0
            db.record(conn, photo.uuid, "done", caption=caption, keywords=keywords)
            if keywords:
                click.echo(f"  ✓ saved ({', '.join(keywords)})")
            else:
                click.echo("  ✓ saved")
        click.echo("\nAll photos in this session reviewed 🎉")
    except (KeyboardInterrupt, click.exceptions.Abort):
        click.echo("\nInterrupted — progress saved.")
    finally:
        if viewer is not None:
            viewer.close()


def should_ask_to_stop(advice: report.BridgeAdvice | None, streak: int) -> bool:
    """Whether a bridge failure suggests the rest of the session will fail too."""
    systemic = advice is not None and advice.kind in SYSTEMIC_KINDS
    return systemic or streak >= FAILURE_STREAK_LIMIT


def _keep_going() -> bool:
    """Ask whether to continue after repeated/systemic failures; say so if stopping."""
    if click.confirm("  Writes to Photos are failing — keep going?", default=False):
        return True
    click.echo("Stopping — progress saved. Fix the cause above, then `ansel errors`.")
    return False


def _report_bridge_failure(action: str, uuid: str, exc: Exception) -> report.BridgeAdvice | None:
    """Tell the user a bridge call failed, leading with the fix when it's recognised."""
    redo = f"run 'ansel redo {uuid}' to retry later"
    advice = report.classify_bridge_error(str(exc))
    if advice is None:
        click.echo(f"  ! {action} failed ({exc}) — logged as error; {redo}")
        return None
    click.echo(f"  ! {action} failed — {advice.fix}")
    click.echo(f"    original error: {exc}")
    click.echo(f"    logged as error; {redo}")
    return advice
