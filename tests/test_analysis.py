"""Tool inventory and path-length estimation."""

from __future__ import annotations

from decimal import Decimal

from nctab.core.parse import parse_text
from nctab.ops.path import compute_path
from nctab.ops.stats import compute_stats
from nctab.ops.tools import collect_tools
from nctab.profiles.loader import Profile
from tests.conftest import GOLDEN_DIR

D = Decimal
POCKET = GOLDEN_DIR / "pocket.nc"


def P(text: str, profile: Profile):
    return parse_text(text, profile)


# --------------------------------------------------------------------------- tools


def test_tools_on_golden(fanuc: Profile) -> None:
    report = collect_tools(P(POCKET.read_text(), fanuc), fanuc, file="pocket.nc")
    assert [t.tool for t in report.tools] == [1, 12]
    t1, t12 = report.tools
    assert t1.first_line == 10 and t1.first_block == 40
    assert t1.d == [1] and t1.h == [1]
    assert t1.speeds == [D(4500)] and t1.feeds == [D(300), D(900)]
    assert t1.comment == "(--- T1 ROUGH ---)"
    assert t12.first_line == 33
    assert t12.feeds == [D(200), D(600)]
    assert t1.last_line < t12.first_line
    assert t1.blocks > 0 and t12.blocks > 0


def test_tools_uses_comment_on_the_same_line(fanuc: Profile) -> None:
    report = collect_tools(P("N10 T5 M06 (FACE MILL 50)\n", fanuc), fanuc)
    assert report.tools[0].comment == "(FACE MILL 50)"


def test_tools_repeated_selection_starts_a_new_section(fanuc: Profile) -> None:
    report = collect_tools(P("T1 M06\nX1.\nT2 M06\nX2.\nT1 M06\nX3.\n", fanuc), fanuc)
    assert [t.tool for t in report.tools] == [1, 2, 1]
    assert [t.first_line for t in report.tools] == [1, 3, 5]


def test_tools_same_tool_repeated_on_consecutive_lines(fanuc: Profile) -> None:
    report = collect_tools(P("T1\nT1 M06\nX1.\n", fanuc), fanuc)
    assert [t.tool for t in report.tools] == [1]


def test_tools_empty(fanuc: Profile) -> None:
    assert collect_tools(P("G00 X1.\n", fanuc), fanuc).tools == []


# --------------------------------------------------------------------------- path


def test_straight_lines(fanuc: Profile) -> None:
    p = compute_path(P("G90 G00 X0 Y0 Z0\nG00 X3. Y4.\nG01 X3. Y4. Z-12. F100\n", fanuc), fanuc)
    assert p.rapid == D("5.000")
    assert p.feed == D("12.000")
    assert p.arc == 0
    # the very first block has no known start position, so it is skipped, not measured
    assert p.segments == 2 and p.skipped == 1
    assert p.total == D("17.000")


def test_incremental_moves(fanuc: Profile) -> None:
    p = compute_path(P("G90 G00 X0 Y0 Z0\nG91 G01 X3. Y4. F100\n", fanuc), fanuc)
    assert p.feed == D("5.000")


def test_quarter_arc(fanuc: Profile) -> None:
    p = compute_path(P("G90 G17 G00 X10. Y0. Z0\nG03 X0 Y10. I-10. J0. F100\n", fanuc), fanuc)
    assert p.arc == D("15.708")  # pi * 10 / 2
    assert p.feed == 0


def test_arc_by_radius(fanuc: Profile) -> None:
    p = compute_path(P("G90 G17 G00 X10. Y0. Z0\nG03 X0 Y10. R10. F100\n", fanuc), fanuc)
    assert p.arc == D("15.708")


def test_helical_arc_includes_the_axis_move(fanuc: Profile) -> None:
    prog = P("G90 G17 G00 X10. Y0. Z0\nG03 X0 Y10. Z-5. I-10. J0. F100\n", fanuc)
    p = compute_path(prog, fanuc)
    assert p.arc > D("15.708")
    assert p.arc == D("16.485")  # sqrt(15.708^2 + 5^2), quantised


def test_unknown_position_is_skipped(fanuc: Profile) -> None:
    p = compute_path(P("G28 G91 Z0\nG90 G01 X10. F100\n", fanuc), fanuc)
    assert p.skipped == 1
    assert p.warnings and "skipped" in p.warnings[0]


def test_canned_cycle_is_skipped(fanuc: Profile) -> None:
    prog = P("G90 G00 X0 Y0 Z0\nG81 X10. Y0 Z-5. R2. F100\nG80\n", fanuc)
    p = compute_path(prog, fanuc)
    assert p.skipped == 2  # the opening block and the cycle
    assert p.feed == 0


def test_macro_coordinate_is_skipped(fanuc: Profile) -> None:
    p = compute_path(P("G90 G00 X0 Y0 Z0\nG01 X#100 F100\n", fanuc), fanuc)
    assert p.skipped == 2  # the opening block and the macro move


def test_bad_arc_is_skipped(fanuc: Profile) -> None:
    p = compute_path(P("G90 G00 X0 Y0 Z0\nG02 X30. Y0 R5. F100\n", fanuc), fanuc)
    assert p.skipped == 2  # the opening block and the impossible arc


def test_golden_path_totals(fanuc: Profile) -> None:
    p = compute_path(P(POCKET.read_text(), fanuc), fanuc)
    assert p.rapid > 0 and p.feed > 0 and p.arc > 0
    assert p.total == p.rapid + p.feed + p.arc
    assert p.cutting == p.feed + p.arc


# --------------------------------------------------------------------------- stats wiring


def test_stats_includes_path(fanuc: Profile) -> None:
    prog = P(POCKET.read_text(), fanuc)
    s = compute_stats(prog, fanuc)
    assert s.path is not None
    assert s.path.total == s.path.rapid + s.path.feed + s.path.arc
    assert compute_stats(prog, fanuc, path=False).path is None


def test_first_block_has_no_known_start(fanuc: Profile) -> None:
    """Machine position is unknown until something sets it, so block 1 is never measured."""
    p = compute_path(P("G90 G00 X100. Y100.\n", fanuc), fanuc)
    assert p.skipped == 1 and p.rapid == 0
    # once a position is established the next move is measured normally
    p = compute_path(P("G90 G00 X100. Y100.\nG00 X100. Y103.\n", fanuc), fanuc)
    assert p.rapid == D("3.000") and p.skipped == 1
