"""The interactive review loop."""

from __future__ import annotations

from sqlite3 import Connection
from typing import TYPE_CHECKING

import click

from ansel import db
from ansel.config import Config, expand_keywords
from ansel.photos import (
    DELETION_ALBUM,
    Preview,
    display_path,
    mark_for_deletion,
    open_preview,
    write_metadata,
)

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
    the session. Ctrl-C exits cleanly; everything already answered is
    committed.
    """
    total = len(photos)
    viewer: Preview | None = None
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
                    click.echo(
                        f"  ! marking failed ({exc}) — logged as error;"
                        f" run 'ansel redo {photo.uuid}' to retry later"
                    )
                    continue
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
                click.echo(
                    f"  ! write failed ({exc}) — logged as error;"
                    f" run 'ansel redo {photo.uuid}' to retry later"
                )
                continue

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
