from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from nctab.geom.arc import Arc, center_from_ijk, center_from_r, ijk_from_center, radius_mismatch
from nctab.geom.transform import (
    distance,
    is_right_angle,
    mirror_value,
    normalize_angle,
    rotate_point,
    scale_value,
)

D = Decimal
coords = st.decimals(
    min_value=-1000, max_value=1000, places=3, allow_nan=False, allow_infinity=False
)


@pytest.mark.parametrize(
    ("deg", "expected"),
    [
        (D(0), (D("10"), D("2"))),
        (D(90), (D("-2"), D("10"))),
        (D(180), (D("-10"), D("-2"))),
        (D(270), (D("2"), D("-10"))),
        (D(360), (D("10"), D("2"))),
        (D(-90), (D("2"), D("-10"))),
    ],
)
def test_right_angles_are_exact(deg: Decimal, expected: tuple[Decimal, Decimal]) -> None:
    assert rotate_point(D(10), D(2), deg) == expected


def test_rotate_about_center() -> None:
    assert rotate_point(D(5), D(5), D(90), D(5), D(0)) == (D(0), D(0))
    assert rotate_point(D(10), D(0), D(90), D(5), D(0)) == (D(5), D(5))


def test_arbitrary_angle_is_quantised() -> None:
    x, y = rotate_point(D(10), D(0), D(30), digits=3)
    assert x == D("8.660") and y == D("5.000")
    x, y = rotate_point(D(10), D(0), D(45), digits=4)
    assert x == D("7.0711") and y == D("7.0711")


@given(coords, coords, st.integers(0, 3))
def test_right_angle_rotations_preserve_distance_exactly(x: Decimal, y: Decimal, k: int) -> None:
    rx, ry = rotate_point(x, y, D(90 * k))
    assert rx * rx + ry * ry == x * x + y * y


@given(coords, coords, st.decimals(min_value=-720, max_value=720, places=2, allow_nan=False))
def test_rotate_360_identity(x: Decimal, y: Decimal, deg: Decimal) -> None:
    rx, ry = rotate_point(x, y, D(360))
    assert (rx, ry) == (x, y)
    assert normalize_angle(deg) >= 0 and normalize_angle(deg) < 360


@given(coords, coords, st.decimals(min_value=-359, max_value=359, places=1, allow_nan=False))
def test_arbitrary_rotation_preserves_distance_within_quantum(
    x: Decimal, y: Decimal, deg: Decimal
) -> None:
    rx, ry = rotate_point(x, y, deg, digits=4)
    before = (x * x + y * y).sqrt()
    after = (rx * rx + ry * ry).sqrt()
    assert abs(before - after) <= D("0.0002")


def test_is_right_angle() -> None:
    assert is_right_angle(D(90)) and is_right_angle(D(-270)) and is_right_angle(D(0))
    assert not is_right_angle(D("90.1"))


@given(coords, coords)
def test_mirror_twice_identity(v: Decimal, about: Decimal) -> None:
    assert mirror_value(mirror_value(v, about), about) == v


def test_scale() -> None:
    assert scale_value(D(10), D("1.5"), D(2)) == D("14.0")


def test_distance() -> None:
    assert distance(D(3), D(4)) == D("5.0000")
    assert distance(D(1), D(1), D(1), digits=3) == D("1.732")


# --------------------------------------------------------------------------- arcs


def test_ijk_roundtrip() -> None:
    cx, cy = center_from_ijk(D(10), D(0), D(-10), D(0))
    assert (cx, cy) == (D(0), D(0))
    assert ijk_from_center(D(10), D(0), cx, cy) == (D(-10), D(0))


def test_quarter_circle_length_and_sweep() -> None:
    arc = Arc(D(10), D(0), D(0), D(10), D(0), D(0), cw=False)
    assert arc.radius == D(10)
    assert abs(arc.sweep() - 1.5707963) < 1e-6
    assert arc.length(digits=3) == D("15.708")
    cw = Arc(D(10), D(0), D(0), D(10), D(0), D(0), cw=True)
    assert cw.length(digits=3) == D("47.124")  # the long way round


def test_full_circle() -> None:
    arc = Arc(D(10), D(0), D(10), D(0), D(0), D(0), cw=True)
    assert arc.length(digits=2) == D("62.83")


def test_center_from_r() -> None:
    # quarter arc from (10,0) to (0,10), R10 CCW: centre at origin
    c = center_from_r(D(10), D(0), D(0), D(10), D(10), cw=False)
    assert c == (D("0.0000"), D("0.0000"))
    # same endpoints CW: centre on the other side
    c = center_from_r(D(10), D(0), D(0), D(10), D(10), cw=True)
    assert c == (D("10.0000"), D("10.0000"))
    # negative R flips to the big arc → other centre
    c = center_from_r(D(10), D(0), D(0), D(10), D(-10), cw=False)
    assert c == (D("10.0000"), D("10.0000"))
    # chord longer than diameter
    assert center_from_r(D(0), D(0), D(30), D(0), D(10), cw=False) is None


def test_radius_mismatch() -> None:
    assert radius_mismatch(D(10), D(0), D(0), D(10), D(0), D(0)) == 0
    assert radius_mismatch(D(10), D(0), D(0), D(11), D(0), D(0)) == 1
