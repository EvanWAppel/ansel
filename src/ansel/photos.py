"""Photos library access: reads via osxphotos, writes via the photoscript AppleScript bridge.

Writes go through photoscript (AppleScript) rather than touching the Photos
database directly, so edits are treated as user edits and sync with iCloud.
"""

from __future__ import annotations

import subprocess
import time
from collections.abc import Sequence
from pathlib import Path

import osxphotos
import photoscript
from AppKit import NSApplicationActivateIgnoringOtherApps, NSWorkspace

DELETION_ALBUM = "Marked for Deletion"

# Extensions opened in QuickTime Player (which can autoplay) instead of Quick Look.
VIDEO_SUFFIXES = {".mov", ".mp4", ".m4v", ".avi", ".mpg", ".mpeg", ".mkv", ".3gp"}


def load_library() -> list[osxphotos.PhotoInfo]:
    """Load all photos from the system Photos library (slow on large libraries)."""
    return osxphotos.PhotosDB().photos()


def display_path(photo: osxphotos.PhotoInfo) -> Path | None:
    """Return a viewable file path for a photo.

    Falls back to the largest local derivative when the original is not on
    disk (iCloud "Optimize Storage"). Returns None if nothing is available
    locally.
    """
    if photo.path:
        return Path(photo.path)
    if photo.path_derivatives:
        return Path(photo.path_derivatives[0])
    return None


def is_video(path: Path) -> bool:
    """Return True if the path looks like a video, based on its file extension."""
    return path.suffix.lower() in VIDEO_SUFFIXES


class Preview:
    """A live preview window, closed when advancing to the next photo.

    Quick Look previews are a child process; QuickTime playback is a document
    in the (persistent) QuickTime Player app. ``close`` handles both.
    """

    def __init__(
        self, *, process: subprocess.Popen[bytes] | None = None, quicktime: bool = False
    ) -> None:
        self._process = process
        self._quicktime = quicktime

    def close(self) -> None:
        """Close the preview window. Never raises — a stale preview must not end the session."""
        if self._process is not None:
            self._process.terminate()
        if self._quicktime:
            _osascript(
                'tell application "QuickTime Player"\n'
                "    if (count documents) > 0 then close front document saving no\n"
                "end tell"
            )


def _osascript(script: str) -> None:
    """Run an AppleScript snippet, swallowing failures (a flaky preview is non-fatal)."""
    subprocess.run(
        ["osascript", "-e", script],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )


def _applescript_str(text: str) -> str:
    """Quote a string as an AppleScript string literal."""
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _open_quicktime(path: Path) -> Preview:
    """Open a video in QuickTime Player and start playback immediately."""
    _osascript(
        'tell application "QuickTime Player"\n'
        f"    set theDoc to open POSIX file {_applescript_str(str(path))}\n"
        "    play theDoc\n"
        "end tell"
    )
    return Preview(quicktime=True)


def _open_quick_look(path: Path) -> Preview:
    """Open a still image in a non-blocking Quick Look preview window."""
    proc = subprocess.Popen(
        ["qlmanage", "-p", str(path)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return Preview(process=proc)


def open_preview(path: Path) -> Preview:
    """Open a photo or video for viewing, then return focus to the terminal.

    Videos autoplay in QuickTime Player; still images open in a floating Quick
    Look window. Either window steals focus when it appears, so once it is up
    this re-activates whatever app was frontmost (the terminal) — letting you
    type the caption without clicking back.
    """
    front = NSWorkspace.sharedWorkspace().frontmostApplication()
    preview = _open_quicktime(path) if is_video(path) else _open_quick_look(path)
    if front is not None:
        # The viewer window can be slow to appear; if it shows up after a single
        # re-activation it keeps focus, so wait and re-activate twice.
        for delay in (0.8, 0.8):
            time.sleep(delay)
            front.activateWithOptions_(NSApplicationActivateIgnoringOtherApps)
    return preview


def write_metadata(uuid: str, caption: str | None, keywords: Sequence[str]) -> None:
    """Write a caption and merge keywords onto a photo via the AppleScript bridge.

    Keywords are merged with (not replacing) any existing keywords. Raises on
    AppleScript bridge failures; callers should catch and log rather than crash.
    """
    photo = photoscript.Photo(uuid)
    if caption:
        photo.description = caption
    if keywords:
        existing = set(photo.keywords or [])
        photo.keywords = sorted(existing | set(keywords))


def mark_for_deletion(uuid: str) -> None:
    """Add a photo to the deletion album, creating the album if needed.

    Photos' AppleScript interface can't delete media items, so deletion is a
    two-step flow: ansel collects candidates in one album, and the user
    batch-deletes the album's contents inside Photos. Raises on bridge
    failures; callers should catch and log.
    """
    library = photoscript.PhotosLibrary()
    album = library.album(DELETION_ALBUM) or library.create_album(DELETION_ALBUM)
    album.add([photoscript.Photo(uuid)])
