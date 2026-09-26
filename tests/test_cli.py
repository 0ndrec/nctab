from __future__ import annotations

import ast
import io
import json
from contextlib import redirect_stderr, redirect_stdout
from decimal import Decimal
from pathlib import Path

import pytest

from nctab import cli
from nctab.cli import main
from tests.conftest import GOLDEN_DIR

POCKET = GOLDEN_DIR / "pocket.nc"


def run(*args: str, capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    code = main(list(args))
    out, err = capsys.readouterr()
    return code, out, err


def test_stats_table(capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = run("stats", str(POCKET), capsys=capsys)
    assert code == 0
    assert "pocket.nc" in out
    assert "fanuc-mill" in out
    assert "T1 T12" in out
    assert "G02" in out


def test_stats_json(capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = run("stats", str(POCKET), "--json", capsys=capsys)
    assert code == 0
    data = json.loads(out)
    assert data["schema_version"] == 1
    assert data["profile"] == "fanuc-mill"
    assert data["lines"] == POCKET.read_text().count("\n")
    assert Decimal(data["axes"]["X"]["min"]) == Decimal("-30")
    assert Decimal(data["axes"]["X"]["max"]) == Decimal("30")
    assert Decimal(data["axes"]["Z"]["min"]) == Decimal("-3.02")
    assert data["tools"] == [1, 12]
    assert data["gcodes"]["G02"] == 7
    assert data["gcodes"]["G03"] == 1
    assert data["mcodes"]["M06"] == 2
    assert data["skipped_blocks"] == 1
    assert data["parse_issues"] == 0
    assert [Decimal(f) for f in data["feeds"]] == [Decimal(v) for v in (200, 300, 600, 900)]


def test_stats_profile_flag(capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = run("stats", str(POCKET), "--json", "-p", "generic-iso", capsys=capsys)
    assert code == 0
    assert json.loads(out)["profile"] == "generic-iso"


def test_stats_missing_file_exit_3(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, _, err = run("stats", str(tmp_path / "nope.nc"), capsys=capsys)
    assert code == 3
    assert "cannot read" in err


def test_unknown_profile_exit_2(capsys: pytest.CaptureFixture[str]) -> None:
    code, _, err = run("stats", str(POCKET), "-p", "nope", capsys=capsys)
    assert code == 2
    assert "unknown profile" in err


def test_bare_file_argument_opens_the_editor(monkeypatch: pytest.MonkeyPatch) -> None:
    """`nctab FILE` is the same as `nctab edit FILE` (goal.md section 5.1)."""
    opened: list[object] = []
    monkeypatch.setattr("nctab.app.run", lambda **kw: opened.append(kw))
    assert main([str(POCKET)]) == 0
    assert opened and opened[0]["path"] == POCKET


def test_edit_missing_file_exits_3(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("nctab.app.run", lambda **kw: None)
    code, _, err = run("edit", str(tmp_path / "nope.nc"), capsys=capsys)
    assert code == 3
    assert "cannot read" in err


def test_profiles_command(capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = run("profiles", capsys=capsys)
    assert code == 0
    assert "fanuc-mill" in out
    assert "generic-iso" in out


def test_help(capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = run("--help", capsys=capsys)
    assert code == 0
    assert "stats" in out
    assert "--profile" in out


# --------------------------------------------------------------------------- portability


def test_help_text_is_ascii() -> None:
    """Shop-floor Windows consoles run a legacy code page.

    rich raises UnicodeEncodeError rather than printing when a character is
    outside it, so `nctab mirror --help` once crashed on an arrow in its
    docstring. Command help and printed output must stay ASCII.
    """
    source = Path(cli.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    module_doc = ast.get_docstring(tree)
    offenders: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        if node.value == module_doc:
            continue
        bad = {c for c in node.value if ord(c) > 127}
        if bad:
            codes = " ".join(f"U+{ord(c):04X}" for c in sorted(bad))
            offenders.append(f"line {node.lineno}: {codes}")
    assert offenders == []


@pytest.mark.parametrize(
    "args",
    [["--help"], ["mirror", "--help"], ["rotate", "--help"], ["replace", "--help"]],
)
def test_help_survives_a_legacy_codepage(args: list[str], tmp_path: Path) -> None:
    """The same check end to end: render help into a cp1252 stream."""
    out = io.TextIOWrapper(io.BytesIO(), encoding="cp1252", errors="strict")
    err = io.TextIOWrapper(io.BytesIO(), encoding="cp1252", errors="strict")
    with redirect_stdout(out), redirect_stderr(err):
        code = cli.main(args)
    assert code == 0
