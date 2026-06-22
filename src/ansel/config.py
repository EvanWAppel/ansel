"""TOML config loading and keyword shortcut expansion."""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_CONFIG = """\
# ansel configuration
#
# Shortcuts are expanded at the keywords prompt. Entry is comma-separated and
# shortcuts mix freely with freeform keywords:
#   "g, f, beach day"  ->  guitar, food, beach day

[shortcuts]
g = "guitar"
f = "food"
t = "travel"
n = "nature"
p = "people"
w = "work"
"""


@dataclass(frozen=True)
class Config:
    """Parsed config: keyword shortcuts keyed by their abbreviation."""

    shortcuts: dict[str, str] = field(default_factory=dict)


def ensure_config(path: Path) -> Path:
    """Create the config file with example shortcuts if it doesn't exist."""
    if not path.exists():
        path.write_text(DEFAULT_CONFIG)
    return path


def load_config(path: Path) -> Config:
    """Load shortcuts from a TOML config file."""
    with path.open("rb") as f:
        data = tomllib.load(f)
    shortcuts = {str(k): str(v) for k, v in data.get("shortcuts", {}).items()}
    return Config(shortcuts=shortcuts)


def expand_keywords(raw: str, shortcuts: Mapping[str, str]) -> list[str]:
    """Split comma-separated keyword entry, expanding shortcuts and deduping in order.

    Tokens that match a shortcut key are replaced by the shortcut's expansion;
    everything else passes through as a freeform keyword.
    """
    keywords: list[str] = []
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        keyword = shortcuts.get(token, token)
        if keyword not in keywords:
            keywords.append(keyword)
    return keywords
