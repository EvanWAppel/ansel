# Ansel — native macOS app

A SwiftUI rewrite of the `ansel` photo-captioning CLI as a real Mac app. Reads
your Photos library through **PhotoKit**; writes captions and keywords through
**AppleScript to Photos.app** (the only interface Apple exposes for those
fields — PhotoKit can set `favorite`/`hidden`/`date`/`location` but not
description or keywords). No Python at runtime.

## Layout

```
macapp/
├── AnselCore/          Swift package — pure logic, no PhotoKit/UI.
│   ├── Sources/AnselCore/       ReviewStatus, PhotoRef, keyword expansion,
│   │                            SessionSelector, buildStats, Config, ProgressStore (SQLite)
│   └── Sources/AnselCoreCheck/  dependency-free check runner (`swift run ansel-core-check`)
└── App/                SwiftUI + PhotoKit + AppleScript app shell.
    ├── project.yml     XcodeGen spec → generates Ansel.xcodeproj
    └── Ansel/          AnselApp, AppModel, ReviewViewModel, PhotoLibrary,
                        PhotosWriter, Views/
```

`AnselCore` is schema-compatible with the CLI's `photo_review.db` — the same
`(uuid, status, caption, keywords, error, reviewed_at)` table — so months of
existing progress carry over (see "Reusing existing progress" below).

## Build & run

Requires **Xcode** (not just Command Line Tools). Once installed:

```sh
# 1. Verify the pure logic (works with Command Line Tools alone):
cd macapp/AnselCore && swift run ansel-core-check

# 2. Generate the Xcode project (one-time; needs `brew install xcodegen`):
cd macapp/App && xcodegen generate

# 3. Open and run:
open Ansel.xcodeproj      # then ⌘R in Xcode
```

No XcodeGen? Create a new **macOS App** target in Xcode, add the `App/Ansel`
folder, add the `AnselCore` package as a local dependency, and copy the
`INFOPLIST_KEY_*` / sandbox settings from `project.yml`.

## Permissions on first run

- **Photos access** — macOS prompts the first time the library loads. Required.
- **Automation (Photos)** — the first caption/keyword save prompts to let Ansel
  control Photos. Required for writes. (System Settings → Privacy & Security →
  Automation to change later.)

The app is built **unsandboxed** for personal/local use, so no Full Disk Access
is needed (PhotoKit handles reads) and AppleScript can reach Photos.

## Data locations

- `~/Library/Application Support/Ansel/photo_review.db` — progress
- `~/Library/Application Support/Ansel/config.json` — keyword shortcuts

### Reusing existing progress

Click **Import progress…** on the start screen and pick the CLI's
`photo_review.db` (e.g. `~/Documents/portfolio/ansel/photo_review.db`). Rows are
merged by UUID — original timestamps are preserved, so an old skip still
resurfaces on schedule. You can import repeatedly; last import wins per photo.

## Review loop

Photo on the left, caption + keyword fields on the right. Keyword shortcuts from
`config.json` expand at entry (`g, beach day, t` → `guitar, beach day, travel`),
merged with any keywords the photo already has. **⌘↩ Save · ⌘→ Skip · ⌘⌫ mark
for deletion.** Deletion adds to a "Marked for Deletion" album you batch-delete
in Photos — Photos' scripting interface can't delete media directly.

## Status

- ✅ `AnselCore` — implemented, 40 checks passing (`swift run ansel-core-check`).
- ✅ App layer — implemented; type-checks against the macOS SDK (Swift 6, macOS 13
  target). Not yet built/run — needs Xcode (tracked in `../BLOCKED.md`).
- ⬜ Once Xcode is in: generate project, run, verify the live PhotoKit read /
  AppleScript write paths against a real library; then convert `AnselCoreCheck`
  into idiomatic `import Testing` suites.
