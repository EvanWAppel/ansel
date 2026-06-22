"""Command-line interface: review, chunk, stats, redo."""

from __future__ import annotations

import random as random_module
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import click

from ansel import db
from ansel.config import ensure_config, load_config
from ansel.review import run_session

if TYPE_CHECKING:
    import osxphotos

DB_PATH = Path("photo_review.db")
CONFIG_PATH = Path("config.toml")

SKIP_RESURFACE_WINDOW = timedelta(days=7)

_MONTH_RE = re.compile(r"\d{4}-\d{2}")


def _month_key(date: datetime) -> str:
    return f"{date.year:04d}-{date.month:02d}"


def _load_photos(month: str | None) -> list[osxphotos.PhotoInfo]:
    """Load the Photos library, optionally filtered to one YYYY-MM month, sorted by date."""
    from ansel.photos import load_library  # deferred: importing osxphotos is slow

    click.echo("Loading Photos library (this can take a moment)…")
    photos = load_library()
    if month is not None:
        photos = [p for p in photos if p.date and _month_key(p.date) == month]
    photos.sort(key=lambda p: p.date)
    return photos


def _run_review(month: str | None) -> None:
    config = load_config(ensure_config(CONFIG_PATH))
    conn = db.connect(DB_PATH)
    photos = _load_photos(month)
    seen = db.reviewed_uuids(conn)
    pending = [p for p in photos if p.uuid not in seen]
    if not pending:
        scope = f"for {month} " if month else ""
        click.echo(f"Nothing left to review {scope}🎉")
        return
    click.echo(f"{len(pending)} photo(s) to review. Shortcuts: {config.shortcuts}")
    run_session(pending, conn, config)


@click.group()
def main() -> None:
    """Incrementally caption and tag your macOS Photos library."""


@main.command()
def review() -> None:
    """Review all unreviewed photos, oldest first."""
    _run_review(None)


@main.command(name="random")
@click.option(
    "--count",
    default=20,
    show_default=True,
    help="How many random photos to pull into the session.",
)
def random_batch(count: int) -> None:
    """Review a random batch from any period.

    Eligible photos are ones never reviewed, plus ones skipped more than a
    week ago (a skip means "not now, ask me again later"). Captioned,
    marked-for-deletion, and errored photos never resurface.
    """
    config = load_config(ensure_config(CONFIG_PATH))
    conn = db.connect(DB_PATH)
    photos = _load_photos(None)
    excluded = db.excluded_uuids(conn, resurface_skips_after=SKIP_RESURFACE_WINDOW)
    pending = [p for p in photos if p.uuid not in excluded]
    if not pending:
        click.echo("Nothing eligible right now — recent skips resurface after a week 🎉")
        return
    batch = random_module.sample(pending, min(count, len(pending)))
    click.echo(
        f"{len(batch)} random photo(s) this session"
        f" ({len(pending)} eligible). Shortcuts: {config.shortcuts}"
    )
    run_session(batch, conn, config)


@main.command()
@click.option("--month", required=True, help="Restrict the session to one month (YYYY-MM).")
def chunk(month: str) -> None:
    """Review only photos from one month, so sessions have a natural finish line."""
    if not _MONTH_RE.fullmatch(month):
        raise click.BadParameter("expected YYYY-MM, e.g. 2024-05", param_hint="--month")
    _run_review(month)


@main.command()
def stats() -> None:
    """Show overall progress and a per-month breakdown."""
    conn = db.connect(DB_PATH)
    statuses = db.all_statuses(conn)
    photos = _load_photos(None)

    total = len(photos)
    overall = dict.fromkeys(db.STATUSES, 0)
    months: dict[str, dict[str, int]] = {}
    for photo in photos:
        key = _month_key(photo.date) if photo.date else "unknown"
        bucket = months.setdefault(key, {"total": 0, **dict.fromkeys(db.STATUSES, 0)})
        bucket["total"] += 1
        status = statuses.get(photo.uuid)
        if status in overall:
            overall[status] += 1
            bucket[status] += 1

    remaining = total - sum(overall.values())
    click.echo(f"\nTotal photos: {total}")
    click.echo(
        f"  done: {overall['done']}   skipped: {overall['skipped']}"
        f"   to-delete: {overall['delete']}   errors: {overall['error']}"
        f"   remaining: {remaining}"
    )
    click.echo(
        f"\n{'Month':<10}{'Total':>8}{'Done':>8}{'Skipped':>9}"
        f"{'Delete':>8}{'Errors':>8}{'Left':>8}"
    )
    for key in sorted(months):
        b = months[key]
        left = b["total"] - sum(b[s] for s in db.STATUSES)
        click.echo(
            f"{key:<10}{b['total']:>8}{b['done']:>8}{b['skipped']:>9}"
            f"{b['delete']:>8}{b['error']:>8}{left:>8}"
        )


@main.command()
@click.argument("uuid")
def redo(uuid: str) -> None:
    """Clear a photo's review status so it comes up for review again."""
    conn = db.connect(DB_PATH)
    if db.clear(conn, uuid):
        click.echo(f"Cleared {uuid} — it will come up in the next review session.")
    else:
        raise click.ClickException(f"no review record found for {uuid}")
