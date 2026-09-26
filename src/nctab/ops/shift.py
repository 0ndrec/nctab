"""OP-SHIFT — translate absolute coordinates (goal.md §6.2, §11)."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from nctab.core.format import Rounding, replace_value
from nctab.core.model import Line, LineKind, Program, Token, Word
from nctab.core.state import LineState, g_int, iter_states
from nctab.ops.base import OpResult, Range
from nctab.profiles.loader import Profile

_HOME_CODES = frozenset({28, 30, 53})
_CENTER_FOR_AXIS = {"X": "I", "Y": "J", "Z": "K"}


@dataclass(frozen=True, slots=True)
class ShiftSpec:
    deltas: dict[str, Decimal]
    """Axis → offset, e.g. ``{"Z": Decimal("-0.02")}``. Zero deltas are ignored."""
    also_incremental: bool = False
    """Also add the offset to words in G91 blocks (changes geometry — rarely wanted)."""
    digits: int | None = None
    rounding: Rounding = "HALF_UP"
    range: Range = field(default_factory=Range)


def _is_home_line(line: Line) -> bool:
    return any(w.addr == "G" and g_int(w) in _HOME_CODES for w in line.words)


def shift(program: Program, spec: ShiftSpec, profile: Profile) -> OpResult:
    deltas = {a.upper(): d for a, d in spec.deltas.items() if d != 0}
    result = OpResult(program=program)
    if not deltas:
        return result

    unknown = [a for a in deltas if a not in profile.axes]
    if unknown:
        result.warn(f"axes not in profile {profile.id}: {', '.join(unknown)}")

    selected = spec.range.select(program, profile)
    new_lines: list[Line] = []

    for ls in iter_states(program, profile):
        line = ls.line
        if line.index not in selected or line.kind is not LineKind.MOTION:
            new_lines.append(line)
            continue
        if _is_home_line(line):
            result.warn("G28/G30/G53 blocks were left untouched")
            new_lines.append(line)
            continue
        if ls.state.incremental and not spec.also_incremental:
            new_lines.append(line)
            continue

        new_line = _shift_line(ls, deltas, spec, profile, result)
        if new_line is not line:
            result.changed.append(line.index)
        new_lines.append(new_line)

    result.program = program.with_lines(new_lines)
    return result


def _shift_line(
    ls: LineState,
    deltas: dict[str, Decimal],
    spec: ShiftSpec,
    profile: Profile,
    result: OpResult,
) -> Line:
    line = ls.line
    state = ls.state
    tokens: list[Token] = list(line.tokens)
    changed = False

    # canned-cycle R is an absolute Z level → moves with Z
    cycle_r = state.in_canned_cycle and "Z" in deltas and profile.arc_r
    # arc centres move only when the dialect stores them as absolute coordinates
    center_axes = (
        {_CENTER_FOR_AXIS[a]: d for a, d in deltas.items() if a in _CENTER_FOR_AXIS}
        if state.is_arc and profile.arc_center_absolute
        else {}
    )

    for idx, t in enumerate(tokens):
        if not isinstance(t, Word):
            continue
        delta: Decimal | None = None
        if t.addr in deltas:
            delta = deltas[t.addr]
        elif t.addr in center_axes:
            delta = center_axes[t.addr]
        elif cycle_r and t.addr == "R":
            delta = deltas["Z"]
        if delta is None:
            continue
        if not t.is_numeric:
            result.warn(f"line {line.index + 1}: macro value {t.text} was not shifted")
            continue
        new = replace_value(t, t.number + delta, digits=spec.digits, rounding=spec.rounding)
        if new.text != t.text:
            tokens[idx] = new
            changed = True
            result.matches += 1

    return line.with_tokens(tuple(tokens)) if changed else line
