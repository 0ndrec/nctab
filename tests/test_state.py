from __future__ import annotations

from decimal import Decimal

from nctab.core.parse import parse_text
from nctab.core.state import states
from nctab.profiles.loader import Profile

D = Decimal


def run(text: str, fanuc: Profile):
    return states(parse_text(text, fanuc), fanuc)


def test_defaults(fanuc: Profile) -> None:
    (s,) = run("N10", fanuc)
    st = s.state
    assert st.absolute and st.plane == "XY" and st.motion is None
    assert st.tool is None and st.spindle == "off" and st.coolant is False


def test_g_words_apply_to_own_block(fanuc: Profile) -> None:
    a, b, c = run("G90 X10.\nG91 X5.\nG90 G01 X1. Y2.", fanuc)
    assert a.state.absolute and a.state.pos("X") == D(10)
    assert b.state.incremental and b.state.pos("X") == D(15)
    assert c.state.absolute and c.state.pos("X") == D(1) and c.state.pos("Y") == D(2)
    assert c.state.start["X"] == D(15)


def test_incremental_from_unknown_stays_unknown(fanuc: Profile) -> None:
    (s,) = run("G91 X5.", fanuc)
    assert s.state.pos("X") is None


def test_motion_modal(fanuc: Profile) -> None:
    a, b, c = run("G01 X1.\nX2.\nG00 X3.", fanuc)
    assert a.state.motion == 1 and b.state.motion == 1 and c.state.motion == 0
    assert b.is_motion


def test_planes_and_comp(fanuc: Profile) -> None:
    a, b = run("G18 G41 D5\nG19 G40", fanuc)
    assert a.state.plane == "ZX" and a.state.plane_code == 18
    assert a.state.comp == 41 and a.state.d == 5
    assert b.state.plane == "YZ" and b.state.comp == 40


def test_tool_spindle_coolant_feed(fanuc: Profile) -> None:
    a, b, c = run("T12 M06\nS4500 M03 F300 H12\nM05 M09", fanuc)
    assert a.state.tool == 12
    assert b.state.speed == D(4500) and b.state.spindle == "cw" and b.state.feed == D(300)
    assert b.state.h == 12
    assert c.state.spindle == "off"


def test_spindle_direction_and_stops(fanuc: Profile) -> None:
    lines = run("M04\nM19\nM03\nM30\nM03\nM02", fanuc)
    assert [ls.state.spindle for ls in lines] == ["ccw", "off", "cw", "off", "cw", "off"]


def test_coolant(fanuc: Profile) -> None:
    a, b = run("M08\nM09", fanuc)
    assert a.state.coolant is True and b.state.coolant is False


def test_home_return_makes_position_unknown(fanuc: Profile) -> None:
    a, b = run("G90 G00 Z50.\nG28 G91 Z0", fanuc)
    assert a.state.pos("Z") == D(50)
    assert b.state.pos("Z") is None


def test_arc_and_canned_cycle_flags(fanuc: Profile) -> None:
    a, b, c = run("G02 X1. Y1. I1. J0.\nG81 Z-5. R2. F100\nG80", fanuc)
    assert a.state.is_arc
    assert b.state.in_canned_cycle and b.state.motion == 81
    assert c.state.motion is None


def test_units_and_feed_mode(fanuc: Profile) -> None:
    a, b = run("G20 G95\nG21 G94", fanuc)
    assert a.state.units == "inch" and a.state.feed_mode == 95
    assert b.state.units == "mm" and b.state.feed_mode == 94


def test_comments_do_not_change_state(fanuc: Profile) -> None:
    a, b = run("G91\n(G90 in a comment)", fanuc)
    assert a.state.incremental and b.state.incremental


def test_macro_axis_value_unknown(fanuc: Profile) -> None:
    (s,) = run("G90 X#100", fanuc)
    assert s.state.pos("X") is None
