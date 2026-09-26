"""CLI smoke tests for transforms and find/replace (write safety, exit codes, JSON)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from nctab.cli import main
from tests.conftest import GOLDEN_DIR

POCKET = GOLDEN_DIR / "pocket.nc"


@pytest.fixture
def work(tmp_path: Path) -> Path:
    dst = tmp_path / "pocket.nc"
    shutil.copy(POCKET, dst)
    return dst


def run(*args: str, capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    code = main(list(args))
    out, err = capsys.readouterr()
    return code, out, err


# --------------------------------------------------------------------------- write safety


def test_no_flags_is_dry_run(work: Path, capsys) -> None:
    before = work.read_bytes()
    code, out, err = run("shift", str(work), "--z", "-0.02", capsys=capsys)
    assert code == 0
    assert work.read_bytes() == before
    assert "-N90 G01 Z-3. F300" in out and "+N90 G01 Z-3.02 F300" in out
    assert "dry run" in err


def test_in_place_with_backup(work: Path, capsys) -> None:
    code, out, err = run("shift", str(work), "--z", "-0.02", "-i", "--backup", capsys=capsys)
    assert code == 0
    assert out == ""  # no diff when writing
    assert "written to" in err
    assert "Z-3.02 F300" in work.read_text()
    assert (work.parent / "pocket.nc.bak").read_bytes() == POCKET.read_bytes()


def test_output_file(work: Path, tmp_path: Path, capsys) -> None:
    dst = tmp_path / "out.nc"
    code, _, _ = run("shift", str(work), "--z", "-0.02", "-o", str(dst), capsys=capsys)
    assert code == 0
    assert work.read_bytes() == POCKET.read_bytes()
    assert "Z-3.02 F300" in dst.read_text()


def test_dry_run_beats_in_place(work: Path, capsys) -> None:
    code, out, _ = run("shift", str(work), "--z", "1", "-i", "--dry-run", capsys=capsys)
    assert code == 0
    assert work.read_bytes() == POCKET.read_bytes()
    assert out.startswith("---")


def test_json_result(work: Path, capsys) -> None:
    code, out, _ = run("shift", str(work), "--x", "1", "--json", capsys=capsys)
    assert code == 0
    data = json.loads(out)
    assert data["changed_lines"] > 0 and data["written"] is None and "diff" in data


# --------------------------------------------------------------------------- commands


def test_renumber_cli(work: Path, capsys) -> None:
    code, _, _ = run("renumber", str(work), "--start", "100", "--step", "5", "-i", capsys=capsys)
    assert code == 0
    lines = work.read_text().splitlines()
    assert lines[5] == "N100 G21 G17 G40 G49 G80 G90"
    assert lines[6] == "N105 G28 G91 Z0"
    code, _, _ = run("renumber", str(work), "--strip", "-i", capsys=capsys)
    assert code == 0
    assert not any(ln.startswith("N") for ln in work.read_text().splitlines())


def test_shift_requires_axis(work: Path, capsys) -> None:
    code, _, err = run("shift", str(work), capsys=capsys)
    assert code == 1 and "at least one" in err


def test_shift_bad_number(work: Path, capsys) -> None:
    code, _, err = run("shift", str(work), "--z", "abc", capsys=capsys)
    assert code == 1 and "not a number" in err


def test_math_cli(work: Path, capsys) -> None:
    code, _, _ = run(
        "math", str(work), "--addr", "z", "--op", "add", "--value", "-0.013", "-i", capsys=capsys
    )
    assert code == 0
    assert "Z-3.013 F300" in work.read_text()


def test_feeds_cli(work: Path, capsys) -> None:
    code, _, _ = run("feeds", str(work), "--f-scale", "0.5", "--f-min", "200", "-i", capsys=capsys)
    assert code == 0
    text = work.read_text()
    assert "F450" in text and "F300" in text and "F200" in text  # 900→450, 600→300, 200/300→200
    code, _, err = run("feeds", str(work), capsys=capsys)
    assert code == 1 and "nothing to do" in err


def test_range_option(work: Path, capsys) -> None:
    code, _, _ = run("shift", str(work), "--z", "1", "-r", "T12", "-i", capsys=capsys)
    assert code == 0
    text = work.read_text()
    assert "N90 G01 Z-3. F300" in text  # T1 untouched
    assert "N310 G01 Z-2.02 F200" in text  # T12 shifted
    code, _, err = run("shift", str(work), "--z", "1", "-r", "bogus", capsys=capsys)
    assert code == 1 and "cannot parse range" in err


# --------------------------------------------------------------------------- find / replace


def test_find_hints(work: Path, capsys) -> None:
    code, out, _ = run("find", str(work), "--addr", "F", capsys=capsys)
    assert code == 0
    assert "F300" in out and "F900" in out and "N90" in out
    code, out, _ = run("find", str(work), "--addr", "F", "--json", capsys=capsys)
    hints = json.loads(out)
    assert hints[0]["text"] == "F300" and hints[0]["count"] == 1


def test_find_matches(work: Path, capsys) -> None:
    code, out, err = run("find", str(work), "--addr", "F", "--value", "300", capsys=capsys)
    assert code == 0
    assert "N90" in out and "N100" not in out
    assert "1 matches in 1 lines" in err
    code, out, _ = run("find", str(work), "G41 D", "--json", capsys=capsys)
    ms = json.loads(out)
    assert [m["block"] for m in ms] == [100, 320]
    code, out, _ = run("find", str(work), "--code", "G3", "--json", capsys=capsys)
    assert [m["block"] for m in json.loads(out)] == [340]


def test_find_regex(work: Path, capsys) -> None:
    code, out, _ = run("find", str(work), r"R-?8\.", "--regex", "--json", capsys=capsys)
    assert code == 0 and len(json.loads(out)) == 5
    code, _, err = run("find", str(work), "(", "--regex", capsys=capsys)
    assert code == 1 and "bad regex" in err


def test_replace_cli(work: Path, capsys) -> None:
    code, out, err = run(
        "replace", str(work), "--addr", "F", "--value", "300,900", "--to", "250", capsys=capsys
    )
    assert code == 0 and "+N90 G01 Z-3. F250" in out and "dry run" in err
    code, _, _ = run(
        "replace",
        str(work),
        "--addr",
        "F",
        "--value",
        "300,900",
        "--to",
        "250",
        "-i",
        capsys=capsys,
    )
    assert code == 0
    text = work.read_text()
    assert "F300" not in text and "F900" not in text and text.count("F250") == 2

    code, _, _ = run("replace", str(work), "--code", "M8", "--to", "7", "-i", capsys=capsys)
    assert "M07" in work.read_text() and "M08" not in work.read_text()

    code, _, _ = run(
        "replace", str(work), r"S(\d+)", "--regex", "--to", r"S\g<1>0", "-i", capsys=capsys
    )
    assert "S45000" in work.read_text()


def test_replace_needs_selector(work: Path, capsys) -> None:
    code, _, err = run("replace", str(work), "--to", "1", capsys=capsys)
    assert code == 1 and "query needs" in err


# --------------------------------------------------------------------------- stage 1b


def test_strip_cli(work: Path, capsys) -> None:
    code, _, err = run("strip", str(work), capsys=capsys)
    assert code == 1 and "nothing to do" in err
    code, _, _ = run("strip", str(work), "--n", "--comments", "--blank", "-i", capsys=capsys)
    assert code == 0
    text = work.read_text()
    lines = text.splitlines()
    assert "N10" not in text and "(POST" not in text
    assert lines[0] == "%"  # the program delimiter survives
    assert lines[1] == "O0020"  # O number kept, its comment stripped
    assert lines[2] == "G21 G17 G40 G49 G80 G90"


def test_case_cli(work: Path, capsys) -> None:
    code, _, _ = run("case", str(work), "lower", "-i", capsys=capsys)
    assert code == 0
    text = work.read_text()
    assert "n10 g21 g17" in text
    assert "(POCKET 60X40 R8)" in text  # comments untouched


def test_scale_cli(work: Path, capsys) -> None:
    code, _, _ = run("scale", str(work), "--factor", "2", "-i", capsys=capsys)
    assert code == 0
    text = work.read_text()
    assert "N60 G00 X-40. Y-20." in text
    assert "N120 G02 X-44. Y36. I16. J0." in text
    assert "F900" in text  # feeds untouched without --also-feed


def test_mirror_cli(work: Path, capsys) -> None:
    code, _, _ = run("mirror", str(work), "--axis", "x", "-i", capsys=capsys)
    assert code == 0
    text = work.read_text()
    assert "N60 G00 X20. Y-10." in text
    assert "N110 Y10." in text  # Y is unchanged by an X mirror
    assert "N120 G03 X22. Y18. I-8. J0." in text  # G02→G03, I negated
    assert "N100 G42 D1 X30. F900" in text  # G41→G42


def test_mirror_twice_is_identity_cli(work: Path, capsys) -> None:
    original = work.read_bytes()
    run("mirror", str(work), "--axis", "y", "-i", capsys=capsys)
    run("mirror", str(work), "--axis", "y", "-i", capsys=capsys)
    assert work.read_bytes() == original


def test_rotate_cli(work: Path, capsys) -> None:
    code, _, _ = run("rotate", str(work), "--deg", "90", "-i", capsys=capsys)
    assert code == 0
    text = work.read_text()
    assert "N60 G00 X10. Y-20." in text  # (-20,-10) → (10,-20)
    assert "N120 G02 X-18. Y-22. I0. J8." in text


def test_rotate_plane_refused_cli(tmp_path: Path, capsys) -> None:
    f = tmp_path / "g18.nc"
    f.write_text("N10 G18 G01 X1. Z1.\n", encoding="utf-8")
    code, _, err = run("rotate", str(f), "--deg", "90", capsys=capsys)
    assert code == 1 and "G18" in err
    code, _, _ = run("rotate", str(f), "--deg", "90", "--force", "-i", capsys=capsys)
    assert code == 0 and "Z-1." in f.read_text()
