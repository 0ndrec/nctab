"""2-D point transforms on ``Decimal`` coordinates (goal.md §11, PLAN rule 3).

Every function takes and returns ``Decimal``. Rotation by a multiple of 90°
is exact (coordinate swaps and sign flips). Any other angle goes through
``math.sin``/``math.cos`` and is quantised once, to ``digits`` fractional
digits, before returning — the only place ``float`` touches coordinates.
"""

from __future__ import annotations

import math
from decimal import ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal
from typing import Literal

Rounding = Literal["HALF_UP", "HALF_EVEN"]
_ROUNDING = {"HALF_UP": ROUND_HALF_UP, "HALF_EVEN": ROUND_HALF_EVEN}

ZERO = Decimal(0)


def quantize(value: Decimal, digits: int, rounding: Rounding = "HALF_UP") -> Decimal:
    return value.quantize(Decimal(1).scaleb(-digits), rounding=_ROUNDING[rounding])


def _from_float(x: float, digits: int, rounding: Rounding) -> Decimal:
    # repr() gives the shortest string that round-trips; quantise from there
    return quantize(Decimal(repr(x)), digits, rounding)


def normalize_angle(deg: Decimal) -> Decimal:
    """Reduce to [0, 360)."""
    d = deg % Decimal(360)
    return d if d >= 0 else d + Decimal(360)


def is_right_angle(deg: Decimal) -> bool:
    return normalize_angle(deg) % Decimal(90) == 0


def rotate_point(
    x: Decimal,
    y: Decimal,
    deg: Decimal,
    cx: Decimal = ZERO,
    cy: Decimal = ZERO,
    *,
    digits: int = 3,
    rounding: Rounding = "HALF_UP",
) -> tuple[Decimal, Decimal]:
    """Rotate ``(x, y)`` counter-clockwise by ``deg`` degrees about ``(cx, cy)``."""
    dx, dy = x - cx, y - cy
    a = normalize_angle(deg)
    if a == 0:
        return x, y
    if a == 90:
        return cx - dy, cy + dx
    if a == 180:
        return cx - dx, cy - dy
    if a == 270:
        return cx + dy, cy - dx
    rad = math.radians(float(a))
    c, s = math.cos(rad), math.sin(rad)
    fx, fy = float(dx), float(dy)
    rx = _from_float(fx * c - fy * s, digits, rounding)
    ry = _from_float(fx * s + fy * c, digits, rounding)
    return cx + rx, cy + ry


def rotate_vector(
    dx: Decimal, dy: Decimal, deg: Decimal, *, digits: int = 3, rounding: Rounding = "HALF_UP"
) -> tuple[Decimal, Decimal]:
    """Rotate a direction/offset vector (no centre)."""
    return rotate_point(dx, dy, deg, digits=digits, rounding=rounding)


def mirror_value(v: Decimal, about: Decimal = ZERO) -> Decimal:
    """Reflect a coordinate across ``about``: ``2*about - v``."""
    return about + about - v


def scale_value(v: Decimal, factor: Decimal, about: Decimal = ZERO) -> Decimal:
    return about + (v - about) * factor


def distance(dx: Decimal, dy: Decimal, dz: Decimal = ZERO, *, digits: int = 4) -> Decimal:
    """Euclidean length, quantised."""
    return quantize((dx * dx + dy * dy + dz * dz).sqrt(), digits)
