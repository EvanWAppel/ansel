# ansel — task backlog

Polish and hardening items, roughly ordered by value-to-effort. Nothing here
blocks daily use — the review loop, resume, and stats all work today. See
[`PRD.md`](./PRD.md) for scope and [`README.md`](./README.md) for usage.

Development is TDD: write a failing test, make it pass, refactor. Pure-logic
tests never touch the Photos library; the AppleScript bridge and preview
machinery are mocked (see `tests/test_review.py` for the pattern).

## P1 — scale

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

## P2 — nice-to-haves

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
- ✅ Actionable bridge errors — `report.classify_bridge_error()` maps raw
  AppleScript failures (by error number: −1743 automation permission, −600
  Photos not running / −128 launch gave up, −1712 timeout — matched only as the
  trailing ScriptError code; plus photoscript's "Invalid photo id", which is
  ambiguous because its existence check swallows every AppleScript failure) to
  a fix. The review loop leads with the fix, then the raw
  message; the DB still stores only the raw message (classified at display
  time, so old rows benefit and the mac app's schema is untouched). Lives in
  `report`, not `photos`, so it stays importable without osxphotos/AppKit.
- ✅ `ansel errors` lists error-status photos with fix, raw message, and a
  `redo` hint (always — it's also how to clear rows for deleted photos);
  `stats` points at it when any exist.
