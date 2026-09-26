# Decisions

An append-only log of the design choices that had a real trade-off — what was
chosen, what was rejected, and why. Newest last.

## Writes go through AppleScript, not the Photos database directly

**Chose:** Write captions and keywords via the Photos AppleScript interface
(`photoscript` in the CLI, a direct `osascript` bridge in the macOS app).
**Rejected:** Editing the Photos SQLite database (`Photos.sqlite`) in place.

Reads are cheap and safe to do directly (that's what `osxphotos` and PhotoKit
do), but writing to the Photos database out-of-band risks corrupting the library
and does not trigger the iCloud sync machinery — edits would be invisible to
other devices and could be clobbered. AppleScript is the only interface Apple
sanctions for setting `description` and `keywords`, so edits are treated as real
user edits and sync normally. The cost is that AppleScript is slow and
occasionally fails; that's handled by committing after every photo and recording
failures as an `error` status instead of crashing the session.

## Progress lives in SQLite, keyed by photo UUID

**Chose:** A local SQLite table `(uuid, status, caption, keywords, error,
reviewed_at)`. **Rejected:** A JSON/flat-file log, or no persistence (re-scan
each run).

The whole point of the tool is *incremental* review over months, so resumability
is the core feature, not an add-on. Photo UUIDs are stable across launches and
across the CLI/app boundary, which makes them a natural primary key. SQLite gives
per-photo commits (so Ctrl-C never loses work) and cheap set queries
("everything unreviewed, oldest first") without loading the whole library into
memory. A flat file would force a full rewrite per commit and make the "skipped
more than a week ago comes back" query awkward.

## Two front-ends (CLI + native app) share one schema, not one codebase

**Chose:** Keep the Python CLI, and add a SwiftUI/PhotoKit app that reuses the
*same* `photo_review.db` schema so progress migrates between them. Pure logic in
the app lives in a UI-free `AnselCore` Swift package. **Rejected:** Rewriting the
CLI away, or sharing code across the language boundary (e.g. embedding Python).

The CLI was already working and battle-tested against a real library; throwing it
away to chase a GUI would have discarded months of accumulated progress and a
known-good write path. Making the app schema-compatible instead means the app is
an *incremental* rewrite — you can move to it (via "Import progress…") without
losing history, and both front-ends stay useful. Sharing a schema rather than a
binary keeps each side idiomatic (Click + osxphotos on one side, PhotoKit +
Swift on the other) at the cost of porting the pure logic once — which is exactly
what `AnselCore` and its 40-check runner exist to keep honest.

## macOS app builds without Xcode

**Chose:** A `build.sh` that compiles the SwiftUI + PhotoKit app with the Command
Line Tools `swiftc` and ad-hoc code-signs it; XcodeGen and a full Xcode project
are optional. **Rejected:** Requiring Xcode + a checked-in `.xcodeproj`.

A committed `.xcodeproj` is noisy in diffs and easy to let drift; requiring Xcode
raises the barrier to build and review. Compiling with the CLT toolchain keeps
the repo small (the project is generated, not stored) and makes CI able to verify
the pure logic (`swift run ansel-core-check`) without an Xcode setup step. The
trade-off is that `build.sh` reimplements a little of what Xcode does for free
(bundle assembly, signing), which is acceptable for a personal/local app.
