"""Tool-path length estimate (goal.md §6.3).

A geometric estimate only: straight lines are exact, arcs are measured along
the circle, and everything the modal state cannot resolve (unknown position
after G28, macro coordinates, canned cycles) is skipped and counted separately.
There is no machine kinematics here, so this is not a cycle-time prediction.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from nctab.core.model import Program
from nctab.core.state import LineState, iter_states
from nctab.geom.arc import Arc, center_from_ijk, center_from_r
from nctab.geom.transform import distance
from nctab.profiles.loader import Profile

_CENTER_FOR_AXIS = {"X": "I", "Y": "J", "Z": "K"}


@dataclass(slots=True)
class PathLengths:
    rapid: Decimal = Decimal(0)
    """G00 distance."""
    feed: Decimal = Decimal(0)
    """G01 distance."""
    arc: Decimal = Decimal(0)
    """G02/G03 arc length."""
    skipped: int = 0
    """Motion blocks whose geometry could not be resolved."""
    segments: int = 0
    warnings: list[str] = field(default_factory=list)

    @property
    def cutting(self) -> Decimal:
        return self.feed + self.arc

    @property
    def total(self) -> Decimal:
        return self.rapid + self.feed + self.arc


def _delta(ls: LineState, axis: str) -> Decimal | None:
    """Travel along ``axis`` for this block, or ``None`` when it cannot be known.

    An axis that has never been positioned *and* is not positioned here has simply
    not moved, so it contributes zero rather than making the whole block unmeasurable.
    """
    a, b = ls.state.start.get(axis), ls.state.position.get(axis)
    if a is None and b is None:
        return Decimal(0)
    if a is None or b is None:
        return None
    return b - a


def compute_path(program: Program, profile: Profile, *, digits: int = 3) -> PathLengths:
    out = PathLengths()
    axes = [a for a in ("X", "Y", "Z") if a in profile.axes]

    for ls in iter_states(program, profile):
        state = ls.state
        if not ls.is_motion or state.motion is None:
            continue
        if state.in_canned_cycle:
            out.skipped += 1
            continue

        deltas = {a: _delta(ls, a) for a in axes}
        if any(v is None for v in deltas.values()):
            out.skipped += 1
            continue
        dx, dy, dz = (deltas.get(a) or Decimal(0) for a in ("X", "Y", "Z"))

        if state.motion in (0, 1):
            d = distance(dx, dy, dz, digits=digits)
            if state.motion == 0:
                out.rapid += d
            else:
                out.feed += d
            out.segments += 1
            continue

        length = _arc_length(ls, profile, digits)
        if length is None:
            out.skipped += 1
            continue
        # helical arcs also travel along the plane normal
        normal = {"XY": dz, "ZX": dy, "YZ": dx}.get(state.plane, Decimal(0))
        out.arc += distance(length, normal, digits=digits) if normal else length
        out.segments += 1

    if out.skipped:
        out.warnings.append(
            f"{out.skipped} motion blocks skipped (unknown position or canned cycle)"
        )
    return out


def _arc_length(ls: LineState, profile: Profile, digits: int) -> Decimal | None:
    state = ls.state
    u, v = state.plane[0], state.plane[1]
    su, sv = state.start.get(u), state.start.get(v)
    eu, ev = state.position.get(u), state.position.get(v)
    if None in (su, sv, eu, ev):
        return None
    assert su is not None and sv is not None and eu is not None and ev is not None

    cw = state.motion == 2
    wr = ls.line.word("R")
    if wr is not None and wr.is_numeric:
        center = center_from_r(su, sv, eu, ev, wr.number, cw)
        if center is None:
            return None
        cu, cv = center
    else:
        i_addr, j_addr = _CENTER_FOR_AXIS.get(u), _CENTER_FOR_AXIS.get(v)
        wi = ls.line.word(i_addr) if i_addr else None
        wj = ls.line.word(j_addr) if j_addr else None
        if wi is None and wj is None:
            return None
        if (wi is not None and not wi.is_numeric) or (wj is not None and not wj.is_numeric):
            return None
        i = wi.number if wi is not None else Decimal(0)
        j = wj.number if wj is not None else Decimal(0)
        cu, cv = (i, j) if profile.arc_center_absolute else center_from_ijk(su, sv, i, j)

    return Arc(su, sv, eu, ev, cu, cv, cw).length(digits=digits)
