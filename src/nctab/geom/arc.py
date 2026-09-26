"""Arc geometry: centres, radii, sweep and length (goal.md §6.1, §11).

Conventions (Fanuc): ``I J K`` are the centre offset *from the arc start
point*; ``R`` is the radius, negative ``R`` selects the arc larger than 180°.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal

from nctab.geom.transform import quantize

TWO_PI = 2 * math.pi


@dataclass(frozen=True, slots=True)
class Arc:
    """A circular arc in a 2-D plane. All values in plane coordinates."""

    sx: Decimal
    sy: Decimal
    ex: Decimal
    ey: Decimal
    cx: Decimal
    cy: Decimal
    cw: bool  # G02

    @property
    def radius(self) -> Decimal:
        dx, dy = self.sx - self.cx, self.sy - self.cy
        return (dx * dx + dy * dy).sqrt()

    def sweep(self) -> float:
        """Swept angle in radians, always positive (0 < sweep <= 2π)."""
        a0 = math.atan2(float(self.sy - self.cy), float(self.sx - self.cx))
        a1 = math.atan2(float(self.ey - self.cy), float(self.ex - self.cx))
        d = a0 - a1 if self.cw else a1 - a0
        d %= TWO_PI
        if d < 1e-12:  # full circle when start == end
            d = TWO_PI
        return d

    def length(self, *, digits: int = 4) -> Decimal:
        return quantize(Decimal(repr(float(self.radius) * self.sweep())), digits)


def center_from_ijk(sx: Decimal, sy: Decimal, i: Decimal, j: Decimal) -> tuple[Decimal, Decimal]:
    return sx + i, sy + j


def ijk_from_center(sx: Decimal, sy: Decimal, cx: Decimal, cy: Decimal) -> tuple[Decimal, Decimal]:
    return cx - sx, cy - sy


def center_from_r(
    sx: Decimal,
    sy: Decimal,
    ex: Decimal,
    ey: Decimal,
    r: Decimal,
    cw: bool,
    *,
    digits: int = 4,
) -> tuple[Decimal, Decimal] | None:
    """Centre of the arc defined by endpoints and signed radius.

    Returns ``None`` when the chord is longer than ``2|R|`` (no such arc).
    """
    fsx, fsy, fex, fey = float(sx), float(sy), float(ex), float(ey)
    mx, my = (fsx + fex) / 2, (fsy + fey) / 2
    dx, dy = fex - fsx, fey - fsy
    chord2 = dx * dx + dy * dy
    if chord2 == 0:
        return None
    rr = float(abs(r))
    h2 = rr * rr - chord2 / 4
    if h2 < -1e-9:
        return None
    h = math.sqrt(max(h2, 0.0))
    chord = math.sqrt(chord2)
    # unit normal to the chord, pointing left of travel direction
    nx, ny = -dy / chord, dx / chord
    # for CW with positive R (minor arc) the centre is to the right of travel
    sign = -1.0 if cw else 1.0
    if r < 0:
        sign = -sign
    cx = mx + sign * h * nx
    cy = my + sign * h * ny
    return quantize(Decimal(repr(cx)), digits), quantize(Decimal(repr(cy)), digits)


def radius_mismatch(
    sx: Decimal, sy: Decimal, ex: Decimal, ey: Decimal, cx: Decimal, cy: Decimal
) -> Decimal:
    """|r_start - r_end| — non-zero means IJK and endpoints disagree."""
    r0 = ((sx - cx) ** 2 + (sy - cy) ** 2).sqrt()
    r1 = ((ex - cx) ** 2 + (ey - cy) ** 2).sqrt()
    return abs(r0 - r1)
