# ansel — task backlog

Polish and hardening items, roughly ordered by value-to-effort. Nothing here
blocks daily use — the review loop, resume, and stats all work today. See
[`PRD.md`](./PRD.md) for scope and [`README.md`](./README.md) for usage.

Development is TDD: write a failing test, make it pass, refactor. Pure-logic
tests never touch the Photos library; the AppleScript bridge and preview
machinery are mocked (see `tests/test_review.py` for the pattern).

## P1 — error ergonomics

- **Better AppleScript error messages.** Bridge failures currently surface the
  raw exception string (`write_metadata` / `mark_for_deletion` → status
  `error`). Map the common cases to actionable guidance:
  - automation permission not granted → point at System Settings → Privacy &
    Security → Automation.
  - Photos not running / library not open → tell the user to open Photos.
  - photo no longer exists (deleted since load) → suggest `redo` is not needed;
    it will drop out on next load.
  Keep the raw message too (for `redo` diagnosis), but lead with the fix. Add a
  `photos.classify_bridge_error(exc) -> str` pure function and test it against
  representative message strings.
- **Surface `error`-status photos in `stats`** with their messages, or add
  `ansel errors` to list them, so failures aren't invisible until the next
  session.

## P2 — scale

- **10k+ library profiling.** `_load_photos` loads the whole library and sorts
  in memory on every command (`review`, `chunk`, `stats`, `random`). Profile
  against a large library and measure: `PhotosDB()` construction, `.photos()`
  materialization, and the per-command filter/sort. Consider:
  - caching the loaded library within a single process (stats already loads it
    once — fine — but confirm no double-load paths creep in).
  - narrowing the osxphotos query for `chunk --month` instead of loading all
    then filtering, if osxphotos supports a date-bounded query.
  - a progress indicator during the initial load (currently a single "this can
    take a moment" line).

## P3 — nice-to-haves

- **Undo the last action** — an `ansel undo` that reverts the most recent
  `record`/write within a session (caption written to Photos can't be un-written
  via the bridge easily; scope this carefully).
- **Configurable DB/config paths** via env vars or flags, so ansel can run
  against more than one library.
- **Keyword suggestions** — surface the most-used keywords at the prompt.

---

## Done

- ✅ Fixed the broken `.venv` (shebangs pinned to an old absolute path); project
  now pins Python 3.12 via `.python-version` and `uv sync` rebuilds cleanly.
- ✅ Added `tests/test_review.py` — integration coverage for the full
  `run_session()` loop (caption + keywords, skip, delete, quit, bridge-write
  and mark-for-deletion errors, preview open/close, missing-original preview).
- ✅ `ansel export --csv [PATH]` — dumps the progress DB (`db.COLUMNS`, oldest
  review first) as CSV; stdout when no path is given.
- ✅ `ansel stats --json` (renamed from the planned `--stats-json`) — stats
  aggregation moved into a pure `report.build_stats()` shared by the text and
  JSON renderers. The "Loading Photos library…" line now goes to stderr so
  stdout stays machine-readable.
