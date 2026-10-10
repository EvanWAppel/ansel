"""Command-line interface: review, random, chunk, stats, export, redo."""

from __future__ import annotations

import json
import random as random_module
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, TextIO

import click

from ansel import db, report
from ansel.config import ensure_config, load_config
from ansel.review import run_session

if TYPE_CHECKING:
    import osxphotos

DB_PATH = Path("photo_review.db")
CONFIG_PATH = Path("config.toml")

SKIP_RESURFACE_WINDOW = timedelta(days=7)

_MONTH_RE = re.compile(r"\d{4}-\d{2}")

# Goes to stderr so machine-readable stdout (e.g. ``stats --json``) stays clean.
LOADING_MESSAGE = "Loading Photos library (this can take a moment)…"


def _load_photos(month: str | None) -> list[osxphotos.PhotoInfo]:
    """Load the Photos library, optionally filtered to one YYYY-MM month, sorted by date.

    Undated photos sort last.
    """
    from ansel.photos import load_library  # deferred: importing osxphotos is slow

    click.echo(LOADING_MESSAGE, err=True)
    photos = load_library()
    if month is not None:
        photos = [p for p in photos if p.date and report.month_key(p.date) == month]
    photos.sort(key=lambda p: (p.date is None, p.date or datetime.min))
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
@click.option("--json", "as_json", is_flag=True, help="Emit the stats as one JSON object.")
def stats(as_json: bool) -> None:
    """Show overall progress and a per-month breakdown."""
    conn = db.connect(DB_PATH)
    summary = report.build_stats(_load_photos(None), db.all_statuses(conn))
    if as_json:
        click.echo(json.dumps(summary, indent=2))
        return

    overall = summary["overall"]
    click.echo(f"\nTotal photos: {summary['total']}")
    click.echo(
        f"  done: {overall['done']}   skipped: {overall['skipped']}"
        f"   to-delete: {overall['delete']}   errors: {overall['error']}"
        f"   remaining: {summary['remaining']}"
    )
    click.echo(
        f"\n{'Month':<10}{'Total':>8}{'Done':>8}{'Skipped':>9}"
        f"{'Delete':>8}{'Errors':>8}{'Left':>8}"
    )
    for key, b in summary["months"].items():
        click.echo(
            f"{key:<10}{b['total']:>8}{b['done']:>8}{b['skipped']:>9}"
            f"{b['delete']:>8}{b['error']:>8}{b['remaining']:>8}"
        )


@main.command()
@click.option(
    "--csv",
    "csv_out",
    is_flag=False,
    flag_value="-",
    default=None,
    type=click.File("w", encoding="utf-8"),
    metavar="[PATH]",
    help="Write the progress DB as CSV to PATH (stdout if PATH is omitted).",
)
def export(csv_out: TextIO | None) -> None:
    """Export the progress DB for spreadsheet review or backup."""
    if csv_out is None:
        raise click.UsageError("choose an export format, e.g. --csv [PATH]")
    report.write_csv(db.rows(db.connect(DB_PATH)), csv_out)


@main.command()
@click.argument("uuid")
def redo(uuid: str) -> None:
    """Clear a photo's review status so it comes up for review again."""
    conn = db.connect(DB_PATH)
    if db.clear(conn, uuid):
        click.echo(f"Cleared {uuid} — it will come up in the next review session.")
    else:
        raise click.ClickException(f"no review record found for {uuid}")
