"""CLI tests via Click's CliRunner: temp DB, and the library loader patched out."""

import csv
import io
import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

from ansel import cli, db


@pytest.fixture
def db_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "cli.db"
    monkeypatch.setattr(cli, "DB_PATH", path)
    return path


@pytest.fixture
def library(monkeypatch: pytest.MonkeyPatch) -> list[SimpleNamespace]:
    photos = [
        SimpleNamespace(uuid="a", date=datetime(2024, 5, 3)),
        SimpleNamespace(uuid="b", date=datetime(2024, 6, 9)),
    ]

    def fake_load(month: str | None) -> list[SimpleNamespace]:
        cli.click.echo(cli.LOADING_MESSAGE, err=True)
        return photos

    monkeypatch.setattr(cli, "_load_photos", fake_load)
    return photos


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def test_export_csv_to_stdout(db_path: Path, runner: CliRunner) -> None:
    db.record(db.connect(db_path), "a", "done", caption="A dog", keywords=["dog"])
    result = runner.invoke(cli.main, ["export", "--csv"])
    assert result.exit_code == 0, result.output
    parsed = list(csv.reader(io.StringIO(result.stdout)))
    assert parsed[0] == ["uuid", "status", "caption", "keywords", "error", "reviewed_at"]
    assert parsed[1][:4] == ["a", "done", "A dog", "dog"]


def test_export_csv_to_file(db_path: Path, runner: CliRunner, tmp_path: Path) -> None:
    db.record(db.connect(db_path), "a", "skipped")
    out = tmp_path / "out.csv"
    result = runner.invoke(cli.main, ["export", "--csv", str(out)])
    assert result.exit_code == 0, result.output
    assert result.stdout == ""
    assert out.read_text(encoding="utf-8").splitlines()[1].startswith("a,skipped,")


def test_export_requires_a_format(db_path: Path, runner: CliRunner) -> None:
    result = runner.invoke(cli.main, ["export"])
    assert result.exit_code != 0
    assert "--csv" in result.output


def test_stats_json_is_pure_json_on_stdout(
    db_path: Path, library: list[SimpleNamespace], runner: CliRunner
) -> None:
    db.record(db.connect(db_path), "a", "done")
    result = runner.invoke(cli.main, ["stats", "--json"])
    assert result.exit_code == 0, result.output
    stats = json.loads(result.stdout)
    assert stats["total"] == 2
    assert stats["remaining"] == 1
    assert stats["overall"]["done"] == 1
    assert list(stats["months"]) == ["2024-05", "2024-06"]
    assert cli.LOADING_MESSAGE in result.stderr


def test_stats_text_output_unchanged(
    db_path: Path, library: list[SimpleNamespace], runner: CliRunner
) -> None:
    db.record(db.connect(db_path), "b", "delete")
    result = runner.invoke(cli.main, ["stats"])
    assert result.exit_code == 0, result.output
    assert result.stdout == (
        "\nTotal photos: 2\n"
        "  done: 0   skipped: 0   to-delete: 1   errors: 0   remaining: 1\n"
        "\nMonth        Total    Done  Skipped  Delete  Errors    Left\n"
        "2024-05          1       0        0       0       0       1\n"
        "2024-06          1       0        0       1       0       0\n"
    )


def test_load_photos_sorts_undated_last(monkeypatch: pytest.MonkeyPatch) -> None:
    from ansel import photos

    library = [
        SimpleNamespace(uuid="none", date=None),
        SimpleNamespace(uuid="june", date=datetime(2024, 6, 9)),
        SimpleNamespace(uuid="may", date=datetime(2024, 5, 3)),
    ]
    monkeypatch.setattr(photos, "load_library", lambda: list(library))
    assert [p.uuid for p in cli._load_photos(None)] == ["may", "june", "none"]


def test_export_csv_dash_and_unicode_roundtrip(db_path: Path, runner: CliRunner) -> None:
    caption = 'Café "noon",\nsecond line'
    db.record(db.connect(db_path), "a", "done", caption=caption, keywords=["été"])
    result = runner.invoke(cli.main, ["export", "--csv", "-"])
    assert result.exit_code == 0, result.output
    parsed = list(csv.reader(io.StringIO(result.stdout)))
    assert parsed[1][2:4] == [caption, "été"]


def test_errors_lists_fix_raw_message_and_redo(db_path: Path, runner: CliRunner) -> None:
    conn = db.connect(db_path)
    db.record(
        conn, "u-perm", "error", error="Not authorized to send Apple events to Photos. (-1743)"
    )
    db.record(conn, "u-odd", "error", error="bridge hiccup")
    db.record(conn, "u-gone", "error", error="Invalid photo id: u-gone")
    conn.execute("INSERT INTO reviews VALUES ('u-none', 'error', NULL, NULL, NULL, '2026-01-01')")
    conn.commit()
    db.record(conn, "u-done", "done")

    result = runner.invoke(cli.main, ["errors"])

    assert result.exit_code == 0, result.output
    out = result.stdout
    assert "4 photo(s) with errors" in out
    assert "may be for photos you've since deleted" in out
    assert "u-done" not in out
    assert "Privacy & Security → Automation" in out
    assert "bridge hiccup" in out
    assert "ansel redo u-perm" in out
    assert "ansel redo u-odd" in out
    assert "ansel redo u-gone" in out
    assert "error: (no message)" in out
    assert "None" not in out


def test_errors_when_none(db_path: Path, runner: CliRunner) -> None:
    result = runner.invoke(cli.main, ["errors"])
    assert result.exit_code == 0, result.output
    assert "No errors" in result.stdout


def test_stats_points_at_errors_command_when_any(
    db_path: Path, library: list[SimpleNamespace], runner: CliRunner
) -> None:
    db.record(db.connect(db_path), "a", "error", error="x")
    result = runner.invoke(cli.main, ["stats"])
    assert result.exit_code == 0, result.output
    assert result.stdout.endswith("\n1 photo(s) hit errors — run `ansel errors` for fixes.\n")


def test_stats_json_has_no_errors_hint(
    db_path: Path, library: list[SimpleNamespace], runner: CliRunner
) -> None:
    db.record(db.connect(db_path), "a", "error", error="x")
    result = runner.invoke(cli.main, ["stats", "--json"])
    assert json.loads(result.stdout)["overall"]["error"] == 1
