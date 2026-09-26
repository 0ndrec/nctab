from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from nctab.core.parse import parse_text
from nctab.errors import ProgramError
from nctab.ops.addr_math import MathSpec, addr_math
from nctab.ops.base import Range
from nctab.ops.feeds import FeedsSpec, feeds
from nctab.ops.renumber import RenumberSpec, renumber
from nctab.ops.shift import ShiftSpec, shift
from nctab.profiles.loader import Profile, load_profile
from tests.conftest import GOLDEN_DIR

D = Decimal
POCKET = GOLDEN_DIR / "pocket.nc"


def P(text: str, profile: Profile):
    return parse_text(text, profile)


# --------------------------------------------------------------------------- Range


def test_range_parse() -> None:
    assert Range.parse(None).is_all and Range.parse("all").is_all
    assert Range.parse("10-200").lines == (10, 200)
    assert Range.parse("50-").lines == (50, None)
    assert Range.parse("-50").lines == (None, 50)
    assert Range.parse("120").lines == (120, 120)
    assert Range.parse("N100-N500").blocks == (100, 500)
    assert Range.parse("n100-500").blocks == (100, 500)
    assert Range.parse("N120").blocks == (120, 120)
    assert Range.parse("T12").tool == 12
    with pytest.raises(ProgramError):
        Range.parse("garbage")


def test_range_select(fanuc: Profile) -> None:
    prog = P("N10 T1 M06\nN20 X1.\nN30 T12 M06\nN40 X2.\nN50 X3.\nN60 T1 M06\nN70 X4.", fanuc)
    assert Range.parse("2-3").select(prog, fanuc) == {1, 2}
    assert Range.parse("N30-N50").select(prog, fanuc) == {2, 3, 4}
    assert Range.parse("N50-").select(prog, fanuc) == {4, 5, 6}
    assert Range(tool=12).select(prog, fanuc) == {2, 3, 4}
    assert Range(tool=1).select(prog, fanuc) == {0, 1}  # first occurrence, until next tool
    with pytest.raises(ProgramError, match="T99"):
        Range(tool=99).select(prog, fanuc)


# --------------------------------------------------------------------------- renumber


def test_renumber_basic(fanuc: Profile) -> None:
    prog = P("%\nO0001\n(HEAD)\nN5 G90\nG01 X1.\n\n/G00 Z5.\nN999 M30\n%\n", fanuc)
    res = renumber(prog, RenumberSpec(start=10, step=10), fanuc)
    assert (
        res.program.text == "%\nO0001\n(HEAD)\nN10 G90\nN20 G01 X1.\n\n/N30 G00 Z5.\nN40 M30\n%\n"
    )
    assert res.changed == [3, 4, 6, 7]


def test_renumber_width_and_indent(fanuc: Profile) -> None:
    prog = P("  G01 X1.\nN7   G00\n", fanuc)
    res = renumber(prog, RenumberSpec(start=10, step=5, width=4), fanuc)
    assert res.program.text == "  N0010 G01 X1.\nN0015   G00\n"


def test_renumber_comment_lines(fanuc: Profile) -> None:
    prog = P("(A)\nN10 (B)\nG01\n", fanuc)
    res = renumber(prog, RenumberSpec(), fanuc)
    assert res.program.text == "(A)\nN10 (B)\nN20 G01\n"
    res = renumber(prog, RenumberSpec(number_comments=True), fanuc)
    assert res.program.text == "N10 (A)\nN20 (B)\nN30 G01\n"


def test_renumber_ignores_n_in_comment(fanuc: Profile) -> None:
    prog = P("G01 (N999 keep)\n", fanuc)
    res = renumber(prog, RenumberSpec(), fanuc)
    assert res.program.text == "N10 G01 (N999 keep)\n"


def test_renumber_strip(fanuc: Profile) -> None:
    prog = P("N10 G01 X1.\n/N20 G00\nN30\nG02 N40 X1.\n", fanuc)
    res = renumber(prog, RenumberSpec(strip=True), fanuc)
    assert res.program.text == "G01 X1.\n/G00\n\nG02 X1.\n"


def test_renumber_idempotent_and_range(fanuc: Profile) -> None:
    prog = P(POCKET.read_text(), fanuc)
    once = renumber(prog, RenumberSpec(), fanuc)
    twice = renumber(once.program, RenumberSpec(), fanuc)
    assert twice.changed == []
    assert twice.program.text == once.program.text
    # only T12 section, starting at 1000
    part = renumber(prog, RenumberSpec(start=1000, step=1, range=Range(tool=12)), fanuc)
    lines = part.program.text.splitlines()
    assert lines[32] == "N1000 T12 M06"
    assert lines[31] == "N250 G90"  # untouched before
    assert part.program.text.count("\n") == prog.text.count("\n")


def test_renumber_goto_warning(fanuc: Profile) -> None:
    prog = P("N10 IF[#1EQ1]GOTO30\nN20 X1.\nN30 M30\n", fanuc)
    res = renumber(prog, RenumberSpec(start=100), fanuc)
    assert any("GOTO" in w for w in res.warnings)


def test_renumber_bad_step(fanuc: Profile) -> None:
    with pytest.raises(ProgramError):
        renumber(P("X1.", fanuc), RenumberSpec(step=0), fanuc)


# --------------------------------------------------------------------------- shift


def test_shift_absolute_only(fanuc: Profile) -> None:
    prog = P("G90 G01 X10. Y5. Z-1.\nG91 X1.\nG90 Z-2.5 F100\n", fanuc)
    res = shift(prog, ShiftSpec({"X": D("0.5"), "Z": D("-0.02")}), fanuc)
    assert res.program.text == "G90 G01 X10.5 Y5. Z-1.02\nG91 X1.\nG90 Z-2.52 F100\n"
    assert res.changed == [0, 2]
    assert res.matches == 3


def test_shift_also_incremental(fanuc: Profile) -> None:
    prog = P("G91 X1.\n", fanuc)
    res = shift(prog, ShiftSpec({"X": D(1)}, also_incremental=True), fanuc)
    assert res.program.text == "G91 X2.\n"


def test_shift_preserves_number_style(fanuc: Profile) -> None:
    prog = P("G01 X-0.0130 Y12 Z.5\n", fanuc)
    res = shift(prog, ShiftSpec({"X": D("0.02"), "Y": D("1"), "Z": D("-1")}), fanuc)
    assert res.program.text == "G01 X0.0070 Y13 Z-.5\n"


def test_shift_zero_is_noop(fanuc: Profile) -> None:
    prog = P(POCKET.read_text(), fanuc)
    res = shift(prog, ShiftSpec({"X": D(0)}), fanuc)
    assert res.changed == [] and res.program.text == prog.text


def test_shift_skips_home_and_comments(fanuc: Profile) -> None:
    prog = P("G28 G91 Z0\nG90 G53 Z0\n(Z1.)\nG00 Z5.\n", fanuc)
    res = shift(prog, ShiftSpec({"Z": D(1)}), fanuc)
    assert res.program.text == "G28 G91 Z0\nG90 G53 Z0\n(Z1.)\nG00 Z6.\n"
    assert any("G28" in w for w in res.warnings)


def test_shift_ijk_not_moved_for_incremental_centres(fanuc: Profile) -> None:
    prog = P("G02 X10. Y0. I5. J0.\n", fanuc)
    res = shift(prog, ShiftSpec({"X": D(1)}), fanuc)
    assert res.program.text == "G02 X11. Y0. I5. J0.\n"


def test_shift_ijk_moved_for_absolute_centres(tmp_path: Path) -> None:
    f = tmp_path / "abs.toml"
    f.write_text('id="abs"\nlabel="abs"\narc_center_absolute=true\n', encoding="utf-8")
    prof = load_profile(str(f))
    prog = P("G17 G02 X10. Y0. I5. J0. K1.\n", prof)
    res = shift(prog, ShiftSpec({"X": D(1), "Z": D(2)}), prof)
    assert res.program.text == "G17 G02 X11. Y0. I6. J0. K3.\n"


def test_shift_canned_cycle_r_follows_z(fanuc: Profile) -> None:
    prog = P("G81 X0 Y0 Z-5. R2. F100\nG80\nG02 X1. Y1. R2.\n", fanuc)
    res = shift(prog, ShiftSpec({"Z": D(1)}), fanuc)
    assert res.program.text == "G81 X0 Y0 Z-4. R3. F100\nG80\nG02 X1. Y1. R2.\n"


def test_shift_macro_warning(fanuc: Profile) -> None:
    prog = P("G01 X#100\n", fanuc)
    res = shift(prog, ShiftSpec({"X": D(1)}), fanuc)
    assert res.changed == [] and res.warnings


def test_shift_range(fanuc: Profile) -> None:
    prog = P("G01 X1.\nX2.\nX3.\n", fanuc)
    res = shift(prog, ShiftSpec({"X": D(10)}, range=Range.parse("2-2")), fanuc)
    assert res.program.text == "G01 X1.\nX12.\nX3.\n"


deltas = st.decimals(min_value=-100, max_value=100, places=3, allow_nan=False, allow_infinity=False)


@settings(max_examples=30, deadline=None)
@given(deltas, deltas)
def test_shift_roundtrip_is_identity(dx: Decimal, dz: Decimal) -> None:
    fanuc = load_profile("fanuc-mill")
    prog = parse_text(POCKET.read_text(), fanuc)
    there = shift(prog, ShiftSpec({"X": dx, "Z": dz}), fanuc)
    back = shift(there.program, ShiftSpec({"X": -dx, "Z": -dz}), fanuc)
    # goal.md §13: coordinates compare as Decimal — preserve-scale may keep extra zeros in text
    assert [[w.value for w in ln.words] for ln in back.program.lines] == [
        [w.value for w in ln.words] for ln in prog.lines
    ]
    assert [ln.comment for ln in back.program.lines] == [ln.comment for ln in prog.lines]


# --------------------------------------------------------------------------- math


def test_math_ops(fanuc: Profile) -> None:
    prog = P("G01 X10. Z-1.5 (X0)\nG91 Z2.\n", fanuc)
    assert addr_math(prog, MathSpec(("Z",), "add", D("-0.013")), fanuc).program.text == (
        "G01 X10. Z-1.513 (X0)\nG91 Z1.987\n"
    )
    assert addr_math(prog, MathSpec(("X", "Z"), "mul", D(2)), fanuc).program.text == (
        "G01 X20. Z-3.0 (X0)\nG91 Z4.\n"
    )
    assert addr_math(prog, MathSpec(("Z",), "div", D(3), digits=3), fanuc).program.text == (
        "G01 X10. Z-0.5 (X0)\nG91 Z0.667\n"
    )
    assert addr_math(prog, MathSpec(("X",), "sub", D(10)), fanuc).program.text == (
        "G01 X0. Z-1.5 (X0)\nG91 Z2.\n"
    )


def test_math_errors(fanuc: Profile) -> None:
    prog = P("X1.", fanuc)
    with pytest.raises(ProgramError):
        addr_math(prog, MathSpec(("X",), "div", D(0)), fanuc)
    with pytest.raises(ProgramError):
        addr_math(prog, MathSpec(("N",), "add", D(1)), fanuc)
    with pytest.raises(ProgramError):
        addr_math(prog, MathSpec((), "add", D(1)), fanuc)


def test_math_macro_skipped(fanuc: Profile) -> None:
    res = addr_math(P("X#1 X2.\n", fanuc), MathSpec(("X",), "add", D(1)), fanuc)
    assert res.program.text == "X#1 X3.\n" and res.warnings


# --------------------------------------------------------------------------- feeds


def test_feeds_scale_and_clamp(fanuc: Profile) -> None:
    prog = P("G01 X1. F300\nF80 S6000\nF12.5\n", fanuc)
    res = feeds(prog, FeedsSpec(f_scale=D("0.9"), f_min=D(80)), fanuc)
    assert res.program.text == "G01 X1. F270\nF80 S6000\nF80\n"
    res = feeds(prog, FeedsSpec(s_scale=D("1.5"), s_max=D(8000)), fanuc)
    assert res.program.text == "G01 X1. F300\nF80 S8000\nF12.5\n"
    res = feeds(prog, FeedsSpec(f_scale=D("0.9"), digits=1), fanuc)
    assert res.program.text == "G01 X1. F270\nF72 S6000\nF11.3\n"


def test_feeds_noop_and_errors(fanuc: Profile) -> None:
    prog = P("F300", fanuc)
    assert feeds(prog, FeedsSpec(), fanuc).changed == []
    with pytest.raises(ProgramError):
        feeds(prog, FeedsSpec(f_scale=D(0)), fanuc)
