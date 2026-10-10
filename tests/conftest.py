"""Shared fixtures. Every database is a temp file; nothing touches the Photos library."""

import sqlite3
from pathlib import Path

import pytest

from ansel import db


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    return db.connect(tmp_path / "test.db")
