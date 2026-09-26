from __future__ import annotations

from decimal import Decimal

from nctab.core.parse import parse_text
from nctab.diff import DiffOptions, build_report, diff_programs, normalize_line, unified
from nctab.ops.shift import ShiftSpec, shift
from nctab.profiles.loader import Profile
from tests.conftest import GOLDEN_DIR

POCKET = GOLDEN_DIR / "pocket.nc"


def P(text: str, profile: Profile):
    return parse_text(text, profile)


# --------------------------------------------------------------------------- normalisation


def norm(text: str, profile: Profile, **kw) -> str:
    return normalize_line(P(text, profile).lines[0], profile, DiffOptions(**kw))


def test_exact_normalisation_is_the_raw_line(fanuc: Profile) -> None:
    line = "N10  g01   X01.500 (c) ; t"
    assert norm(line, fanuc) == line


def test_ignore_block_numbers(fanuc: Profile) -> None:
    assert norm("N10 G01 X1.", fanuc, ignore_block_numbers=True) == " G01 X1."
    assert norm("G01 (N10) X1.", fanuc, ignore_block_numbers=True) == "G01 (N10) X1."


def test_ignore_whitespace(fanuc: Profile) -> None:
    assert norm("  N10   G01  X1. ", fanuc, ignore_whitespace=True) == "N10G01X1."


def test_ignore_comments(fanuc: Profile) -> None:
    assert norm("N10 G01 (cut) X1. ; end", fanuc, ignore_comments=True) == "N10 G01  X1."


def test_ignore_leading_zeros(fanuc: Profile) -> None:
    o = {"ignore_leading_zeros": True}
    assert norm("X010.500", fanuc, **o) == norm("X10.5", fanuc, **o)
    assert norm("X+10.5", fanuc, **o) == norm("X10.5", fanuc, **o)
    assert norm("G01", fanuc, **o) == norm("G1", fanuc, **o)
    assert norm("X100", fanuc, **o) == "X100"  # not 1E+2


def test_ignore_case(fanuc: Profile) -> None:
    assert norm("n10 g01 x1. (c)", fanuc, ignore_case=True) == "N10 G01 X1. (C)"


# --------------------------------------------------------------------------- comparison


def test_identical(fanuc: Profile) -> None:
    a = P(POCKET.read_text(), fanuc)
    result = diff_programs(a, P(POCKET.read_text(), fanuc), fanuc)
    assert result.identical
    assert result.hunks == []
    assert unified(a, a, fanuc) == ""


def test_renumbering_is_a_difference_unless_ignored(fanuc: Profile) -> None:
    a = P("N10 G01 X1.\nN20 M30\n", fanuc)
    b = P("N1000 G01 X1.\nN1010 M30\n", fanuc)
    assert not diff_programs(a, b, fanuc).identical
    assert diff_programs(a, b, fanuc, DiffOptions(ignore_block_numbers=True)).identical


def test_hunk_positions_map_to_original_lines(fanuc: Profile) -> None:
    a = P("N10 X1.\nN20 X2.\nN30 X3.\n", fanuc)
    b = P("N10 X1.\nN20 X9.\nN25 X8.\nN30 X3.\n", fanuc)
    result = diff_programs(a, b, fanuc)
    assert [(h.kind, h.a_start, h.a_len, h.b_start, h.b_len) for h in result.hunks] == [
        ("replace", 2, 1, 2, 2)
    ]
    assert result.hunks[0].a_lines == ["N20 X2."]
    assert result.hunks[0].b_lines == ["N20 X9.", "N25 X8."]


def test_insert_and_delete(fanuc: Profile) -> None:
    a = P("X1.\nX2.\n", fanuc)
    b = P("X1.\nX1.5\nX2.\n", fanuc)
    ins = diff_programs(a, b, fanuc).hunks
    assert [(h.kind, h.a_start, h.a_len, h.b_start, h.b_len) for h in ins] == [
        ("insert", 2, 0, 2, 1)
    ]
    dele = diff_programs(b, a, fanuc).hunks
    assert [(h.kind, h.a_start, h.a_len, h.b_start, h.b_len) for h in dele] == [
        ("delete", 2, 1, 2, 0)
    ]


def test_rows_cover_every_line(fanuc: Profile) -> None:
    a = P("X1.\nX2.\nX3.\n", fanuc)
    b = P("X1.\nX9.\n", fanuc)
    rows = diff_programs(a, b, fanuc).rows
    assert [r.kind for r in rows] == ["equal", "replace", "replace"]
    assert [(r.left_line, r.right_line) for r in rows] == [(1, 1), (2, 2), (3, None)]
    assert rows[2].right is None


def test_blank_lines_ignored(fanuc: Profile) -> None:
    a = P("X1.\n\n\nX2.\n", fanuc)
    b = P("X1.\nX2.\n", fanuc)
    assert not diff_programs(a, b, fanuc).identical
    assert diff_programs(a, b, fanuc, DiffOptions(ignore_blank_lines=True)).identical


def test_normalised_diff_shows_original_text(fanuc: Profile) -> None:
    a = P("N10 G01 X1.\nN20 M30\n", fanuc)
    b = P("N1000 G01 X1.\nN1010 G01 Y2.\nN1020 M30\n", fanuc)
    opts = DiffOptions(ignore_block_numbers=True)
    text = unified(a, b, fanuc, opts, a_name="a.nc", b_name="b.nc")
    assert "+N1010 G01 Y2." in text  # the real line, not the normalised one
    assert "-N10 G01 X1." not in text  # unchanged apart from its number
    assert text.startswith("--- a.nc\n+++ b.nc\n")


def test_report(fanuc: Profile) -> None:
    a = P("X1.\nX2.\nX3.\n", fanuc)
    b = P("X1.\nX9.\nX3.\nX4.\n", fanuc)
    report = build_report(a, b, fanuc, a_name="a.nc", b_name="b.nc")
    assert report.schema_version == 1
    assert report.identical is False
    assert (report.added, report.removed, report.changed) == (1, 0, 1)
    assert report.a == "a.nc" and report.b == "b.nc"
    assert set(report.model_dump()) == {
        "schema_version",
        "a",
        "b",
        "profile",
        "identical",
        "hunks",
        "added",
        "removed",
        "changed",
    }


def test_shift_diff_is_one_hunk_per_changed_line(fanuc: Profile) -> None:
    a = P(POCKET.read_text(), fanuc)
    b = shift(a, ShiftSpec({"Z": Decimal("-0.02")}), fanuc).program
    result = diff_programs(a, b, fanuc)
    # consecutive changed lines merge into one hunk, so compare the lines they cover
    covered = {n for h in result.hunks for n in range(h.a_start, h.a_start + h.a_len)}
    expected = {ln + 1 for ln in shift(a, ShiftSpec({"Z": Decimal("-0.02")}), fanuc).changed}
    assert covered == expected
    assert all(h.kind == "replace" for h in result.hunks)
