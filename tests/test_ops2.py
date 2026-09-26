"""strip, case, scale, mirror, rotate."""

from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from nctab.core.parse import parse_text
from nctab.errors import ProgramError
from nctab.ops.base import Range
from nctab.ops.case import CaseSpec, change_case
from nctab.ops.mirror import MirrorSpec, mirror
from nctab.ops.rotate import RotateSpec, rotate
from nctab.ops.scale import ScaleSpec, scale
from nctab.ops.strip import StripSpec, strip
from nctab.profiles.loader import Profile, load_profile
from tests.conftest import GOLDEN_DIR

D = Decimal
POCKET = GOLDEN_DIR / "pocket.nc"


def P(text: str, profile: Profile):
    return parse_text(text, profile)


def values(program):
    """Per line: ``{address: value}``. Rotation may *add* a coordinate word that was
    modal in the source, so comparisons restrict themselves to the original's addresses."""
    return [{w.addr: w.value for w in ln.words} for ln in program.lines]


def same_values(a, b, tol=None):
    """True when every word of ``a`` has the same value in ``b`` (within ``tol``)."""
    assert len(a) == len(b)
    for la, lb in zip(a, b, strict=True):
        for addr, va in la.items():
            vb = lb.get(addr)
            loose = tol is not None and isinstance(va, Decimal) and isinstance(vb, Decimal)
            if abs(va - vb) > tol if loose else va != vb:
                return False
    return True


# --------------------------------------------------------------------------- strip


def test_strip_n_and_comments(fanuc: Profile) -> None:
    prog = P("%\nN10 G01 X1. (cut) ; end\nN20 (only)\n\n/N30 M08\nN40   G00\n%\n", fanuc)
    res = strip(prog, StripSpec(block_numbers=True), fanuc)
    assert res.program.text == "%\nG01 X1. (cut) ; end\n(only)\n\n/M08\nG00\n%\n"
    res = strip(prog, StripSpec(comments=True), fanuc)
    assert res.program.text == "%\nN10 G01 X1.\nN20\n\n/N30 M08\nN40   G00\n%\n"
    res = strip(prog, StripSpec(block_numbers=True, comments=True, blank=True), fanuc)
    assert res.program.text == "%\nG01 X1.\n/M08\nG00\n%\n"
    assert [ln.index for ln in res.program.lines] == [0, 1, 2, 3, 4]


def test_strip_skip(fanuc: Profile) -> None:
    prog = P("N10 X1.\n/N20 X2.\n/3 N30 X3.\n", fanuc)
    assert (
        strip(prog, StripSpec(skip_marks=True), fanuc).program.text == "N10 X1.\nN20 X2.\nN30 X3.\n"
    )
    res = strip(prog, StripSpec(skipped_blocks=True), fanuc)
    assert res.program.text == "N10 X1.\n"
    assert res.changed == [1, 2]


def test_strip_spaces(fanuc: Profile) -> None:
    prog = P("  N10 G01 X 12.5 Y-3. (A B)\n", fanuc)
    res = strip(prog, StripSpec(spaces=True), fanuc)
    assert res.program.text == "N10G01X12.5Y-3.(A B)\n"
    assert res.program.lines[0].word("X").value == D("12.5")


def test_strip_noop_and_range(fanuc: Profile) -> None:
    prog = P("N10 X1.\nN20 X2.\n", fanuc)
    assert strip(prog, StripSpec(), fanuc).changed == []
    res = strip(prog, StripSpec(block_numbers=True, range=Range.parse("2-2")), fanuc)
    assert res.program.text == "N10 X1.\nX2.\n"


# --------------------------------------------------------------------------- case


def test_case(fanuc: Profile) -> None:
    prog = P("n10 g01 x1. (Keep Me) ; And me\nif[#1eq1]goto20\n", fanuc)
    res = change_case(prog, CaseSpec("upper"), fanuc)
    assert res.program.text == "N10 G01 X1. (Keep Me) ; And me\nIF[#1EQ1]GOTO20\n"
    back = change_case(res.program, CaseSpec("lower"), fanuc)
    assert back.program.text == prog.text
    assert change_case(res.program, CaseSpec("upper"), fanuc).changed == []


# --------------------------------------------------------------------------- scale


def test_scale_basic(fanuc: Profile) -> None:
    prog = P(
        "G90 G01 X10. Y-4. Z2. A90. F100\nG02 X20. Y0. I5. J0.\nG03 X0 Y0 R10.\nG91 X1.\n", fanuc
    )
    res = scale(prog, ScaleSpec(D(2)), fanuc)
    assert res.program.text == (
        "G90 G01 X20. Y-8. Z4. A90. F100\nG02 X40. Y0. I10. J0.\nG03 X0 Y0 R20.\nG91 X2.\n"
    )


def test_scale_about_and_feed(fanuc: Profile) -> None:
    prog = P("G01 X10. Y10. F100\n", fanuc)
    res = scale(prog, ScaleSpec(D("0.5"), about={"X": D(10), "Y": D(0)}, also_feed=True), fanuc)
    assert res.program.text == "G01 X10. Y5. F50\n"


def test_scale_cycle_r_and_warnings(fanuc: Profile) -> None:
    prog = P("G81 X0 Y0 Z-10. R2. Q3. F100\nG28 G91 Z0\n", fanuc)
    res = scale(prog, ScaleSpec(D(2)), fanuc)
    assert res.program.text.splitlines()[0] == "G81 X0 Y0 Z-20. R4. Q3. F100"
    assert any("Q" in w for w in res.warnings) and any("G28" in w for w in res.warnings)


def test_scale_errors_and_identity(fanuc: Profile) -> None:
    prog = P("X1.", fanuc)
    with pytest.raises(ProgramError):
        scale(prog, ScaleSpec(D(0)), fanuc)
    with pytest.raises(ProgramError):
        scale(prog, ScaleSpec(D(-1)), fanuc)
    assert scale(prog, ScaleSpec(D(1)), fanuc).changed == []


# --------------------------------------------------------------------------- mirror


def test_mirror_x(fanuc: Profile) -> None:
    prog = P(
        "G90 G41 D1 X10. Y5.\nG02 X20. Y15. I10. J0.\nG3 X0 Y0 R-5.\nG91 X1.\nG40 G42\n", fanuc
    )
    res = mirror(prog, MirrorSpec("X"), fanuc)
    assert res.program.text == (
        "G90 G42 D1 X-10. Y5.\nG03 X-20. Y15. I-10. J0.\nG2 X0 Y0 R-5.\nG91 X-1.\nG40 G41\n"
    )


def test_mirror_about_and_z_out_of_plane(fanuc: Profile) -> None:
    prog = P("G17 G02 X10. Z-1. I5. J0.\n", fanuc)
    res = mirror(prog, MirrorSpec("Z", about=D(-5)), fanuc)
    # Z is not in the XY plane: no G02→G03 swap, only Z (and K, absent) change
    assert res.program.text == "G17 G02 X10. Z-9. I5. J0.\n"


def test_mirror_twice_identity(fanuc: Profile) -> None:
    prog = P(POCKET.read_text(), fanuc)
    once = mirror(prog, MirrorSpec("Y", about=D(3)), fanuc)
    twice = mirror(once.program, MirrorSpec("Y", about=D(3)), fanuc)
    assert twice.program.text == prog.text


def test_mirror_partial_range_makes_modal_arcs_explicit(fanuc: Profile) -> None:
    prog = P(
        "N10 G02 X10. Y0. I5. J0.\nN20 X0. Y0. I-5. J0.\nN30 X10. Y0. I5. J0.\nN40 G01 X0\n", fanuc
    )
    res = mirror(prog, MirrorSpec("X", range=Range.parse("N20")), fanuc)
    lines = res.program.text.splitlines()
    assert lines[0] == "N10 G02 X10. Y0. I5. J0."
    assert lines[1] == "N20 G03 X0. Y0. I5. J0."  # explicit swapped direction
    assert lines[2] == "N30 G02 X10. Y0. I5. J0."  # restored explicitly after the range
    assert lines[3] == "N40 G01 X0"
    assert len(res.warnings) == 2


def test_mirror_errors(fanuc: Profile) -> None:
    with pytest.raises(ProgramError):
        mirror(P("X1.", fanuc), MirrorSpec("Q"), fanuc)


# --------------------------------------------------------------------------- rotate


def test_rotate_90_exact(fanuc: Profile) -> None:
    prog = P("G90 G01 X10. Y2.\nG02 X0. Y12. I-10. J0.\nG91 X1. Y0.\n", fanuc)
    res = rotate(prog, RotateSpec(D(90)), fanuc)
    assert res.program.text == "G90 G01 X-2. Y10.\nG02 X-12. Y0. I0. J-10.\nG91 X0. Y1.\n"


def test_rotate_about_center_and_missing_axis(fanuc: Profile) -> None:
    prog = P("G90 G00 X10. Y0.\nG01 X20.\nY5.\n", fanuc)
    res = rotate(prog, RotateSpec(D(90), cx=D(10), cy=D(0)), fanuc)
    # third block: X is modal (20), so the rotated point is (5, 10) and X is written out
    assert res.program.text == "G90 G00 X10. Y0.\nG01 X10. Y10.\nY10. X5.\n"


def test_rotate_unknown_modal_position_skipped(fanuc: Profile) -> None:
    prog = P("G90 G01 X20.\n", fanuc)
    res = rotate(prog, RotateSpec(D(90)), fanuc)
    assert res.changed == [] and any("unknown" in w for w in res.warnings)


def test_rotate_arbitrary_angle_quantised(fanuc: Profile) -> None:
    prog = P("G90 G01 X10. Y0.\n", fanuc)
    res = rotate(prog, RotateSpec(D(30)), fanuc)
    # profile digits = 3, but a trailing zero is dropped unless the source had one
    assert res.program.text == "G90 G01 X8.66 Y5.\n"
    res = rotate(prog, RotateSpec(D(30), digits=1), fanuc)
    assert res.program.text == "G90 G01 X8.7 Y5.\n"


def test_rotate_plane_refused(fanuc: Profile) -> None:
    prog = P("G18 G01 X1. Z1.\n", fanuc)
    with pytest.raises(ProgramError, match="G18"):
        rotate(prog, RotateSpec(D(90)), fanuc)
    res = rotate(prog, RotateSpec(D(90), force=True), fanuc)
    assert res.program.text == "G18 G01 X1. Z-1.\n"  # Z→X is CCW: (z,x)=(1,1) → (-1,1)


def test_rotate_noop_and_warnings(fanuc: Profile) -> None:
    prog = P("G68 X0 Y0 R45.\nG01 X1. Y1.\nG28 G91 Z0\n", fanuc)
    assert rotate(prog, RotateSpec(D(360)), fanuc).changed == []
    res = rotate(prog, RotateSpec(D(180)), fanuc)
    assert any("G68" in w for w in res.warnings)
    assert res.program.text.splitlines()[1] == "G01 X-1. Y-1."


def test_rotate_360_by_quarters_is_identity(fanuc: Profile) -> None:
    prog = P(POCKET.read_text(), fanuc)
    cur = prog
    for _ in range(4):
        cur = rotate(cur, RotateSpec(D(90), cx=D(3), cy=D(-2)), fanuc).program
    assert same_values(values(prog), values(cur))


@settings(max_examples=20, deadline=None)
@given(st.decimals(min_value=-359, max_value=359, places=1, allow_nan=False, allow_infinity=False))
def test_rotate_there_and_back_within_tolerance(deg: Decimal) -> None:
    fanuc = load_profile("fanuc-mill")
    prog = parse_text(POCKET.read_text(), fanuc)
    there = rotate(prog, RotateSpec(deg, digits=4), fanuc).program
    back = rotate(there, RotateSpec(-deg, digits=4), fanuc).program
    assert same_values(values(prog), values(back), tol=D("0.001"))
