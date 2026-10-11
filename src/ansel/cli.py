"""Command-line interface: review, random, chunk, stats, errors, export, redo."""

from __future__ import annotations

import json
import random as random_module
import re
from dataclasses import dataclass
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


@dataclass(frozen=True)
class Paths:
    """Where this invocation keeps its progress DB and config."""

    db: Path
    config: Path


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


def _run_review(paths: Paths, month: str | None) -> None:
    config = load_config(ensure_config(paths.config))
    conn = db.connect(paths.db)
    photos = _load_photos(month)
    seen = db.reviewed_uuids(conn)
    pending = [p for p in photos if p.uuid not in seen]
    if not pending:
        scope = f"for {month} " if month else ""
        click.echo(f"Nothing left to review {scope}🎉")
        return
    click.echo(f"{len(pending)} photo(s) to review. Shortcuts: {config.shortcuts}")
    run_session(pending, conn, config)


_PATH = click.Path(dir_okay=False, path_type=Path)


@click.group()
@click.option(
    "--db",
    "db_path",
    envvar="ANSEL_DB",
    type=_PATH,
    help=f"Progress database. [env: ANSEL_DB; default: ./{DB_PATH}]",
)
@click.option(
    "--config",
    "config_path",
    envvar="ANSEL_CONFIG",
    type=_PATH,
    help=f"Config file (created if missing). [env: ANSEL_CONFIG; default: ./{CONFIG_PATH}]",
)
@click.pass_context
def main(ctx: click.Context, db_path: Path | None, config_path: Path | None) -> None:
    """Incrementally caption and tag your macOS Photos library.

    Reads the library Photos last opened. To work through another library,
    open it in Photos (hold Option while launching) and give it its own --db.
    """
    # Defaults resolve here, not in the option, so tests can patch DB_PATH/CONFIG_PATH.
    # expanduser: a quoted env var like ANSEL_DB="~/x.db" isn't expanded by the shell.
    ctx.obj = Paths(
        db=(db_path or DB_PATH).expanduser(), config=(config_path or CONFIG_PATH).expanduser()
    )


@main.command()
@click.pass_obj
def review(paths: Paths) -> None:
    """Review all unreviewed photos, oldest first."""
    _run_review(paths, None)


@main.command(name="random")
@click.option(
    "--count",
    default=20,
    show_default=True,
    help="How many random photos to pull into the session.",
)
@click.pass_obj
def random_batch(paths: Paths, count: int) -> None:
    """Review a random batch from any period.

    Eligible photos are ones never reviewed, plus ones skipped more than a
    week ago (a skip means "not now, ask me again later"). Captioned,
    marked-for-deletion, and errored photos never resurface.
    """
    config = load_config(ensure_config(paths.config))
    conn = db.connect(paths.db)
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
@click.pass_obj
def chunk(paths: Paths, month: str) -> None:
    """Review only photos from one month, so sessions have a natural finish line."""
    if not _MONTH_RE.fullmatch(month):
        raise click.BadParameter("expected YYYY-MM, e.g. 2024-05", param_hint="--month")
    _run_review(paths, month)


@main.command()
@click.option("--json", "as_json", is_flag=True, help="Emit the stats as one JSON object.")
@click.pass_obj
def stats(paths: Paths, as_json: bool) -> None:
    """Show overall progress and a per-month breakdown."""
    conn = db.connect(paths.db)
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
        f"\n{'Month':<10}{'Total':>8}{'Done':>8}{'Skipped':>9}{'Delete':>8}{'Errors':>8}{'Left':>8}"
    )
    for key, b in summary["months"].items():
        click.echo(
            f"{key:<10}{b['total']:>8}{b['done']:>8}{b['skipped']:>9}"
            f"{b['delete']:>8}{b['error']:>8}{b['remaining']:>8}"
        )
    if overall["error"]:
        click.echo(f"\n{overall['error']} photo(s) hit errors — run `ansel errors` for fixes.")


@main.command()
@click.pass_obj
def errors(paths: Paths) -> None:
    """List photos whose Photos write failed, with how to fix each one."""
    rows = db.error_rows(db.connect(paths.db))
    if not rows:
        click.echo("No errors 🎉")
        return
    click.echo(
        f"{len(rows)} photo(s) with errors (some may be for photos you've since deleted;"
        " `ansel redo` clears any row):"
    )
    for uuid, message, reviewed_at in rows:
        advice = report.classify_bridge_error(message or "")
        click.echo(f"\n{uuid}  ({reviewed_at[:10]})")
        if advice is not None:
            click.echo(f"  fix:   {advice.fix}")
        click.echo(f"  error: {message or '(no message)'}")
        click.echo(f"  retry: ansel redo {uuid}")


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
@click.pass_obj
def export(paths: Paths, csv_out: TextIO | None) -> None:
    """Export the progress DB for spreadsheet review or backup."""
    if csv_out is None:
        raise click.UsageError("choose an export format, e.g. --csv [PATH]")
    report.write_csv(db.rows(db.connect(paths.db)), csv_out)


@main.command()
@click.argument("uuid")
@click.pass_obj
def redo(paths: Paths, uuid: str) -> None:
    """Clear a photo's review status so it comes up for review again."""
    conn = db.connect(paths.db)
    if db.clear(conn, uuid):
        click.echo(f"Cleared {uuid} — it will come up in the next review session.")
    else:
        raise click.ClickException(f"no review record found for {uuid}")
