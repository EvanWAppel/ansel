"""Tests for config loading and keyword shortcut expansion (no Photos library access)."""

from pathlib import Path

from ansel.config import ensure_config, expand_keywords, load_config

SHORTCUTS = {"g": "guitar", "f": "food", "t": "travel"}


def test_expand_shortcuts() -> None:
    assert expand_keywords("g, f", SHORTCUTS) == ["guitar", "food"]


def test_expand_mixed_shortcuts_and_freeform() -> None:
    assert expand_keywords("g, beach day, t", SHORTCUTS) == ["guitar", "beach day", "travel"]


def test_expand_dedupes_preserving_order() -> None:
    assert expand_keywords("g, guitar, g", SHORTCUTS) == ["guitar"]


def test_expand_ignores_blank_tokens() -> None:
    assert expand_keywords(" , g,, ", SHORTCUTS) == ["guitar"]
    assert expand_keywords("", SHORTCUTS) == []


def test_ensure_config_creates_default(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    ensure_config(path)
    assert path.exists()
    config = load_config(path)
    assert config.shortcuts["g"] == "guitar"


def test_ensure_config_does_not_overwrite(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text('[shortcuts]\nx = "xylophone"\n')
    ensure_config(path)
    assert load_config(path).shortcuts == {"x": "xylophone"}
