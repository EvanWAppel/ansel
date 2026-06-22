# ansel

Incrementally caption and tag your macOS Photos library from the terminal,
in short sessions spread over months. Progress lives in a local SQLite
database keyed by photo UUID, so you can quit at any time — including
Ctrl-C — and pick up exactly where you left off.

Reads go through [osxphotos](https://github.com/RhetTbull/osxphotos); writes
go through [photoscript](https://github.com/RhetTbull/PhotoScript)'s
AppleScript bridge, so captions and keywords are real Photos edits that sync
with iCloud.

## Setup

Requires macOS, Python 3.12+, and [uv](https://docs.astral.sh/uv/).

```sh
cd ~/Documents/ansel
uv sync
```

**Permissions to expect on first run:**

- **Full Disk Access** — osxphotos reads the Photos library database
  directly. If loading fails with `Operation not permitted`, add your
  terminal app in System Settings → Privacy & Security → Full Disk Access,
  then fully quit and relaunch the terminal.
- **Photos automation** — the first write triggers a prompt asking to let
  your terminal control Photos. Approve it.

Run commands with `uv run ansel …`, or `source .venv/bin/activate` once per
shell and call `ansel …` directly. Either way, run from the project
directory — `config.toml` and `photo_review.db` live here.

## Commands

```sh
ansel review                # everything unreviewed, oldest first
ansel chunk --month 2024-05 # one month only — a natural finish line
ansel random --count 20     # a random batch from any period
ansel stats                 # progress totals + per-month breakdown
ansel redo <uuid>           # clear one photo's status to review it again
```

## A review session

For each photo, ansel opens a preview — still images in a floating Quick Look
window, videos autoplaying in QuickTime Player — then returns focus to the
terminal so you can type without clicking back. It prints the filename, date,
albums, and any existing caption/keywords, then prompts twice:

**1. Caption** — your options:

| Input        | Effect                                                  |
| ------------ | ------------------------------------------------------- |
| any text     | becomes the photo's caption; keywords prompt follows    |
| blank        | skip this photo                                         |
| `d`          | mark for deletion (see below)                           |
| `q`          | quit the session; everything answered so far is saved   |

**2. Keywords** — comma-separated. Tokens matching a shortcut in
`config.toml` expand to the full keyword; anything else passes through
freeform, and the two mix freely:

```
Keywords (shortcuts + freeform, comma-separated): g, t, beach house
→ guitar, travel, beach house
```

Keywords are merged with any the photo already has, never replaced. Progress
commits after every photo, so interrupting never loses work.

Photos whose originals aren't on disk (iCloud "Optimize Storage") preview
from a local derivative when one exists; otherwise ansel says so and you can
caption blind or skip. (A video that hasn't been downloaded may only have a
still-image derivative locally, so it previews as an image rather than
playing.)

### Skipping: permanent vs. "ask me later"

In `review` and `chunk`, a skipped photo never comes up again (use
`ansel redo <uuid>` to bring one back). In `random` sessions, skips
resurface after a week — there, a skip just means "not now."

### Deleting photos

Photos' AppleScript interface can't delete media items, so `d` adds the
photo to a **"Marked for Deletion"** album instead. Every so often, open
that album in Photos, select all (⌘A), and delete — they go to Recently
Deleted as usual.

### When a write fails

AppleScript bridge calls occasionally fail. The photo is logged with status
`error` (message included) instead of crashing your session, and it's
excluded from future sessions until you `ansel redo <uuid>` it.

## Config

`config.toml` is created with example shortcuts on first run; edit freely.
Keys aren't limited to single letters.

```toml
[shortcuts]
g = "guitar"
f = "food"
t = "travel"
```

## Files

- `photo_review.db` — SQLite progress (UUID, status, caption, keywords,
  error, timestamp). Delete it to start over from scratch.
- `config.toml` — keyword shortcuts.
- `PRD.md` — design notes and product spec.

## Development

```sh
uv run pytest        # pure-logic tests only — they never touch your Photos library
uv run ruff check .
```
