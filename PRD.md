# ansel

A CLI for incrementally captioning and tagging a macOS Photos library, designed
for short sessions spread over months. Progress is tracked in a local SQLite
database keyed by photo UUID (stable across launches), so you can quit at any
time — including Ctrl-C — and pick up exactly where you left off.

Reads go through [osxphotos](https://github.com/RhetTbull/osxphotos); writes go
through [photoscript](https://github.com/RhetTbull/PhotoScript)'s AppleScript
bridge, so captions and keywords are treated as real edits and sync with iCloud.

## Setup

Requires macOS, Python 3.12+, and [uv](https://docs.astral.sh/uv/).

```sh
uv sync
```

### macOS permissions on first run

- **Photos automation access** — the first time a caption is written, macOS
  asks to allow your terminal to control Photos. Approve it, or every write
  fails. (Manage later in System Settings → Privacy & Security → Automation.)
- **Full Disk Access** — osxphotos reads the Photos library database directly;
  if loading fails with a permissions error, grant your terminal app Full Disk
  Access in System Settings → Privacy & Security → Full Disk Access.
- Photos should be open (photoscript will launch it otherwise), and the first
  library load on a big library can take a minute.

## Usage

```sh
uv run ansel review                # review all unreviewed photos, oldest first
uv run ansel chunk --month 2024-05 # review just one month — a natural finish line
uv run ansel random [--count 20]   # a random batch from any period (see below)
uv run ansel stats                 # progress totals + per-month breakdown
uv run ansel redo <uuid>           # clear a photo's status to review it again
```

### The review loop

For each photo, ansel opens a preview and shows the filename, date, albums, and
any existing caption/keywords, then prompts. Still images open in a floating
Quick Look window (`qlmanage -p`); videos autoplay in QuickTime Player. In both
cases focus is handed back to whichever app was frontmost (the terminal) once
the preview window appears, so captions and keywords can be typed without
clicking back.

- **Caption** — type one, or leave blank to skip the photo, `d` to mark it for
  deletion, or `q` to quit cleanly. Progress is committed after every photo,
  so quitting (or Ctrl-C) never loses work. (A caption that is literally just
  `d` or `q` isn't possible — anything longer works.)
- **Keywords** — comma-separated; single-letter shortcuts from `config.toml`
  mix freely with freeform entries. With the default config, `g, beach day, t`
  becomes `guitar, beach day, travel`. Keywords are merged with any the photo
  already has.

Photos whose originals aren't on disk (iCloud "Optimize Storage") fall back to
a local derivative for preview; if nothing is available locally, ansel says so
and you can caption blind or skip.

### Random sessions

`ansel random` pulls a random batch (default 20, `--count` to change) from the
whole library — no month-picking required. Eligibility differs from
`review`/`chunk` in one way: photos **skipped more than a week ago come back**,
so in a random session a skip means "not now, ask me again later" rather than
"never". Captioned (`done`), marked-for-deletion, and errored photos never
resurface. `review` and `chunk` still treat skips as permanent.

### Deleting photos

Photos' AppleScript interface can't delete media items, so `d` instead adds
the photo to a **"Marked for Deletion"** album (created automatically) and
records status `delete`. Every so often, open that album in Photos, select
all (⌘A), and delete — that's the only step macOS allows ansel to hand you.
Deleting photos from the album in Photos sends them to Recently Deleted as
usual.

If an AppleScript write fails, the photo is logged with status `error` (with
the message) instead of crashing the session; retry it later with
`ansel redo <uuid>`. Photos with status `error` are excluded from future
sessions until you `redo` them.

## Config

`config.toml` is created with example shortcuts on first run:

```toml
[shortcuts]
g = "guitar"
f = "food"
t = "travel"
```

Edit freely; keys aren't limited to single letters.

## Files

- `photo_review.db` — SQLite progress database (UUID, status, caption,
  keywords, error, timestamp). Delete it to start over.
- `config.toml` — keyword shortcuts.

## Development

```sh
uv run pytest        # pure-logic tests only — they never touch your Photos library
uv run ruff check .
```
