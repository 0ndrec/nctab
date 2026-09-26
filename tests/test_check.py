from __future__ import annotations

from decimal import Decimal

import pytest

from nctab.check import CheckReport, check_program, rule_codes
from nctab.core.parse import parse_text
from nctab.profiles.loader import Profile, load_profile
from tests.conftest import GOLDEN_DIR

D = Decimal
POCKET = GOLDEN_DIR / "pocket.nc"
BROKEN = GOLDEN_DIR / "broken.nc"


def codes(text: str, profile: Profile, **kw) -> list[str]:
    return [d.code for d in check_program(parse_text(text, profile), profile, **kw)]


def test_clean_program_has_no_diagnostics(fanuc: Profile) -> None:
    prog = parse_text(POCKET.read_text(), fanuc)
    assert check_program(prog, fanuc) == []


def test_broken_program_report(fanuc: Profile) -> None:
    prog = parse_text(BROKEN.read_text(), fanuc)
    report = CheckReport.build(
        check_program(prog, fanuc), profile=fanuc.id, lines=len(prog), file=str(BROKEN)
    )
    found = {d.code for d in report.diagnostics}
    assert found == {
        "unclosed-comment",
        "missing-delimiter",
        "missing-program-end",
        "comp-without-offset",
        "length-comp-without-offset",
        "feed-missing",
        "cutting-without-spindle",
        "speed-without-spindle",
        "arc-r-and-ijk",
        "arc-no-center",
        "arc-r-too-small",
        "duplicate-address",
        "unknown-code",
        "cycle-without-cancel",
        "incremental-not-restored",
    }
    assert report.errors == 6
    assert report.ok is False
    # diagnostics are sorted by line, then severity
    assert [d.line for d in report.diagnostics] == sorted(d.line for d in report.diagnostics)
    assert report.diagnostics[0].line == 0  # whole-program findings first


def test_report_schema_is_stable(fanuc: Profile) -> None:
    prog = parse_text(BROKEN.read_text(), fanuc)
    report = CheckReport.build(check_program(prog, fanuc), profile=fanuc.id, lines=len(prog))
    data = report.model_dump()
    assert set(data) == {
        "schema_version",
        "file",
        "profile",
        "lines",
        "diagnostics",
        "errors",
        "warnings",
        "infos",
    }
    assert data["schema_version"] == 1
    assert set(data["diagnostics"][0]) == {
        "line",
        "severity",
        "code",
        "message",
        "block",
        "text",
    }


# --------------------------------------------------------------------------- individual rules


def test_duplicate_address(fanuc: Profile) -> None:
    assert "duplicate-address" in codes("N10 G01 X1. X2. F100\n", fanuc)
    assert "duplicate-address" not in codes("N10 G01 G90 X1. F100\n", fanuc)  # G/M exempt
    assert "duplicate-address" not in codes("N10 G01 X1. (X2.) F100\n", fanuc)


def test_unknown_code(fanuc: Profile) -> None:
    assert "unknown-code" in codes("N10 G77\n", fanuc)
    assert "unknown-code" not in codes("N10 G01 G1 M8 M08\n", fanuc)  # padded or not


def test_comp_rules(fanuc: Profile) -> None:
    assert "comp-without-offset" in codes("G41 X1.\n", fanuc)
    assert "comp-without-offset" not in codes("G41 D1 X1.\n", fanuc)
    assert "comp-without-offset" not in codes("D1\nG41 X1.\n", fanuc)  # D already modal
    assert "length-comp-without-offset" in codes("G43 Z1.\n", fanuc)
    assert "length-comp-without-offset" not in codes("G43 H1 Z1.\n", fanuc)


def test_spindle_rules(fanuc: Profile) -> None:
    assert "cutting-without-spindle" in codes("G01 X1. F100\n", fanuc)
    assert "cutting-without-spindle" not in codes("S1000 M03\nG01 X1. F100\n", fanuc)
    assert "cutting-without-spindle" not in codes("G00 X1.\n", fanuc)  # rapid does not cut
    assert "speed-without-spindle" in codes("S1000\nG00 X1.\n", fanuc)
    assert "speed-without-spindle" not in codes("S1000 M03\n", fanuc)


def test_feed_missing(fanuc: Profile) -> None:
    assert "feed-missing" in codes("S1 M03\nG01 X1.\n", fanuc)
    assert "feed-missing" not in codes("S1 M03\nG01 X1. F100\n", fanuc)
    assert "feed-missing" not in codes("F100\nG01 X1.\n", fanuc)  # F already modal


def test_incremental_not_restored(fanuc: Profile) -> None:
    assert "incremental-not-restored" in codes("G91 X1.\n", fanuc)
    assert "incremental-not-restored" not in codes("G91 X1.\nG90\n", fanuc)


def test_tool_not_changed(fanuc: Profile) -> None:
    assert "tool-not-changed" in codes("T1\nG00 X1.\n", fanuc)
    assert "tool-not-changed" not in codes("T1 M06\nG00 X1.\n", fanuc)
    assert "tool-not-changed" not in codes("T1\nM06\nG00 X1.\n", fanuc)


def test_program_end_and_delimiter(fanuc: Profile) -> None:
    assert "missing-program-end" in codes("G00 X1.\n", fanuc)
    assert "missing-program-end" not in codes("G00 X1.\nM30\n", fanuc)
    assert "missing-program-end" not in codes("G00 X1.\nM02\n", fanuc)
    assert "missing-delimiter" in codes("M30\n", fanuc)
    assert "missing-delimiter" not in codes("%\nM30\n%\n", fanuc)


def test_cycle_without_cancel(fanuc: Profile) -> None:
    assert "cycle-without-cancel" in codes("G81 X0 Y0 Z-1. R1. F100\nM30\n", fanuc)
    assert "cycle-without-cancel" not in codes("G81 X0 Y0 Z-1. R1. F100\nG80\nM30\n", fanuc)


# --------------------------------------------------------------------------- arcs


def test_arc_rules(fanuc: Profile) -> None:
    head = "F100\nS1 M03\nG90 G00 X0 Y0\n"
    assert "arc-r-and-ijk" in codes(head + "G02 X10. Y0. I5. J0. R5.\n", fanuc)
    assert "arc-no-center" in codes(head + "G02 X10. Y0.\n", fanuc)
    assert "arc-r-full-circle" in codes(head + "G02 X0 Y0 R5.\n", fanuc)
    assert "arc-r-too-small" in codes(head + "G02 X30. Y0. R5.\n", fanuc)
    # a correct semicircle raises nothing
    clean = codes(head + "G02 X10. Y0. I5. J0.\n", fanuc)
    assert not any(c.startswith("arc-") for c in clean)


def test_arc_radius_mismatch_and_tolerance(fanuc: Profile) -> None:
    head = "F100\nS1 M03\nG90 G00 X0 Y0\n"
    bad = head + "G02 X10. Y2. I5. J0.\n"  # end point is not on the circle
    assert "arc-radius-mismatch" in codes(bad, fanuc)
    # a 0.0005 error passes the default 0.001 tolerance but fails a tighter one
    near = head + "G02 X10.001 Y0. I5. J0.\n"
    assert "arc-radius-mismatch" not in codes(near, fanuc)
    assert "arc-radius-mismatch" in codes(near, fanuc, arc_tolerance=D("0.0001"))


def test_arc_with_unknown_start_is_not_flagged(fanuc: Profile) -> None:
    assert "arc-radius-mismatch" not in codes("F1\nS1 M03\nG02 X10. Y0. I5. J0.\n", fanuc)


# --------------------------------------------------------------------------- misc


def test_rule_codes_cover_everything_emitted(fanuc: Profile) -> None:
    prog = parse_text(BROKEN.read_text(), fanuc)
    emitted = {d.code for d in check_program(prog, fanuc)}
    assert emitted <= set(rule_codes())


def test_empty_program(fanuc: Profile) -> None:
    emitted = codes("", fanuc)
    assert "missing-program-end" in emitted
    assert "missing-delimiter" in emitted


@pytest.mark.parametrize("profile_id", ["fanuc-mill", "generic-iso"])
def test_check_runs_on_every_profile(profile_id: str) -> None:
    p = load_profile(profile_id)
    prog = parse_text(POCKET.read_text(), p)
    check_program(prog, p)  # must not raise
