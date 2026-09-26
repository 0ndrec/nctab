"""CLI: stats path block, tools, check exit codes, diff."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from nctab.cli import main
from tests.conftest import GOLDEN_DIR

POCKET = GOLDEN_DIR / "pocket.nc"
BROKEN = GOLDEN_DIR / "broken.nc"


def run(*args: str, capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    code = main(list(args))
    out, err = capsys.readouterr()
    return code, out, err


# --------------------------------------------------------------------------- stats


def test_stats_path_block(capsys) -> None:
    code, out, _ = run("stats", str(POCKET), capsys=capsys)
    assert code == 0
    assert "Rapid G00" in out and "Cutting total" in out
    _, out, _ = run("stats", str(POCKET), "--no-path", capsys=capsys)
    assert "Rapid G00" not in out


def test_stats_path_json(capsys) -> None:
    _, out, _ = run("stats", str(POCKET), "--json", capsys=capsys)
    data = json.loads(out)["path"]
    assert float(data["cutting"]) > 0
    assert float(data["total"]) == float(data["rapid"]) + float(data["feed"]) + float(data["arc"])


# --------------------------------------------------------------------------- tools


def test_tools_table(capsys) -> None:
    code, out, _ = run("tools", str(POCKET), capsys=capsys)
    assert code == 0
    assert "T1" in out and "T12" in out and "ROUGH" in out


def test_tools_json(capsys) -> None:
    code, out, _ = run("tools", str(POCKET), "--json", capsys=capsys)
    assert code == 0
    data = json.loads(out)
    assert [t["tool"] for t in data["tools"]] == [1, 12]
    assert data["tools"][0]["first_line"] == 10


def test_tools_none(tmp_path: Path, capsys) -> None:
    f = tmp_path / "n.nc"
    f.write_text("G00 X1.\n", encoding="utf-8")
    code, _, err = run("tools", str(f), capsys=capsys)
    assert code == 0 and "no tool words" in err


# --------------------------------------------------------------------------- check


def test_check_clean_exits_zero(capsys) -> None:
    code, _, err = run("check", str(POCKET), capsys=capsys)
    assert code == 0 and "no problems found" in err


def test_check_errors_exit_two(capsys) -> None:
    code, out, err = run("check", str(BROKEN), capsys=capsys)
    assert code == 2
    assert "unclosed-comment" in out and "arc-r-and-ijk" in out
    assert "errors" in err


def test_check_unclosed_bracket_exits_two(tmp_path: Path, capsys) -> None:
    """goal.md §16.6: an unclosed comment must give exit code 2."""
    f = tmp_path / "c.nc"
    f.write_text("%\nN10 (oops\nN20 M30\n%\n", encoding="utf-8")
    code, out, _ = run("check", str(f), capsys=capsys)
    assert code == 2 and "unclosed-comment" in out


def test_check_strict_promotes_warnings(tmp_path: Path, capsys) -> None:
    f = tmp_path / "w.nc"
    f.write_text("%\nN10 G00 X1.\nN20 M30\n%\n", encoding="utf-8")
    code, _, _ = run("check", str(f), capsys=capsys)
    assert code == 0
    code, _, _ = run("check", str(f), "--strict", capsys=capsys)
    assert code == 0  # this file has no warnings either
    code, _, _ = run("check", str(POCKET), "--strict", capsys=capsys)
    assert code == 0


def test_check_json(capsys) -> None:
    code, out, _ = run("check", str(BROKEN), "--json", capsys=capsys)
    assert code == 2
    data = json.loads(out)
    assert data["schema_version"] == 1 and data["errors"] > 0
    assert {d["code"] for d in data["diagnostics"]} >= {"unclosed-comment", "arc-no-center"}


def test_check_rules_listing(capsys) -> None:
    code, out, _ = run("check", str(POCKET), "--rules", capsys=capsys)
    assert code == 0
    assert "arc-radius-mismatch" in out and "missing-program-end" in out


def test_check_arc_tolerance(tmp_path: Path, capsys) -> None:
    f = tmp_path / "arc.nc"
    f.write_text(
        "%\nF1\nS1 M03\nG90 G00 X0 Y0\nG02 X10.001 Y0. I5. J0.\nM30\n%\n", encoding="utf-8"
    )
    code, _, _ = run("check", str(f), capsys=capsys)
    assert code == 0
    code, out, _ = run("check", str(f), "--arc-tolerance", "0.0001", capsys=capsys)
    assert code == 2 and "arc-radius-mismatch" in out


# --------------------------------------------------------------------------- diff


@pytest.fixture
def renumbered(tmp_path: Path, capsys) -> Path:
    dst = tmp_path / "renum.nc"
    shutil.copy(POCKET, dst)
    main(["renumber", str(dst), "--start", "1000", "--step", "1", "-i", "-q"])
    capsys.readouterr()
    return dst


def test_diff_identical(capsys) -> None:
    code, _, err = run("diff", str(POCKET), str(POCKET), capsys=capsys)
    assert code == 0 and "identical" in err


def test_diff_differs_exits_one(renumbered: Path, capsys) -> None:
    code, out, err = run("diff", str(POCKET), str(renumbered), capsys=capsys)
    assert code == 1
    assert "-N10 G21" in out and "+N1000 G21" in out
    assert "changed" in err


def test_diff_ignore_n(renumbered: Path, capsys) -> None:
    """goal.md §16.5: diff ignores block numbers when asked."""
    code, out, err = run("diff", str(POCKET), str(renumbered), "--ignore-n", capsys=capsys)
    assert code == 0 and out == "" and "identical" in err


def test_diff_normalize_all(tmp_path: Path, capsys) -> None:
    a = tmp_path / "a.nc"
    b = tmp_path / "b.nc"
    a.write_text("N10 G01 X1.500 (cut)\nN20 M30\n", encoding="utf-8")
    b.write_text("n999   g1   x01.5   ; different comment\n\nn1000 m30\n", encoding="utf-8")
    code, _, _ = run("diff", str(a), str(b), capsys=capsys)
    assert code == 1
    code, _, err = run("diff", str(a), str(b), "--normalize-all", capsys=capsys)
    assert code == 0 and "identical" in err


def test_diff_json(renumbered: Path, capsys) -> None:
    code, out, _ = run("diff", str(POCKET), str(renumbered), "--json", capsys=capsys)
    assert code == 1
    data = json.loads(out)
    assert data["identical"] is False and data["changed"] > 0
    assert data["hunks"][0]["kind"] == "replace"


def test_diff_side_by_side(renumbered: Path, capsys) -> None:
    code, out, _ = run("diff", str(POCKET), str(renumbered), "--side-by-side", capsys=capsys)
    assert code == 1
    assert "N10 G21" in out and "N1000 G21" in out


def test_diff_missing_file_exits_three(tmp_path: Path, capsys) -> None:
    code, _, err = run("diff", str(POCKET), str(tmp_path / "nope.nc"), capsys=capsys)
    assert code == 3 and "cannot read" in err


# --------------------------------------------------------------------------- snippets


def test_snippets_list(capsys) -> None:
    code, out, _ = run("snippets", capsys=capsys)
    assert code == 0
    assert "tool-change" in out and "Drilling cycle G81" in out


def test_snippets_list_json(capsys) -> None:
    code, out, _ = run("snippets", "--json", capsys=capsys)
    assert code == 0
    data = json.loads(out)
    ids = {s["id"] for s in data}
    assert "tool-change" in ids
    entry = next(s for s in data if s["id"] == "tool-change")
    assert [f["name"] for f in entry["fields"]] == ["T", "S"]


def test_snippets_follow_the_profile(capsys) -> None:
    code, out, _ = run("snippets", "-p", "fanuc-turn", capsys=capsys)
    assert code == 0
    assert "turn-header" in out and "drill-cycle" not in out


def test_snippets_render(capsys) -> None:
    code, out, _ = run("snippets", "tool-change", "--set", "T=7", "--set", "S=4500", capsys=capsys)
    assert code == 0
    assert "T7 M06" in out and "S4500 M03" in out


def test_snippets_render_uses_defaults(capsys) -> None:
    code, out, _ = run("snippets", "drill-cycle", capsys=capsys)
    assert code == 0 and "Z-10. R2. F150" in out


def test_snippets_bad_set_syntax(capsys) -> None:
    code, _, err = run("snippets", "tool-change", "--set", "T7", capsys=capsys)
    assert code == 1 and "NAME=VALUE" in err


def test_snippets_out_of_range(capsys) -> None:
    code, _, err = run("snippets", "tool-change", "--set", "T=999", capsys=capsys)
    assert code == 1 and "at most 99" in err


def test_snippets_unknown_id(capsys) -> None:
    code, _, err = run("snippets", "nope", capsys=capsys)
    assert code == 1 and "unknown snippet" in err
