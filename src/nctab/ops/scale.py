"""OP-SCL — scale linear coordinates about a point (goal.md §6.2)."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from nctab.core.format import Rounding, replace_value
from nctab.core.model import Line, LineKind, Program, Token, Word
from nctab.core.state import LineState, g_int, iter_states
from nctab.errors import ProgramError
from nctab.geom.transform import scale_value
from nctab.ops.base import OpResult, Range
from nctab.profiles.loader import Profile

LINEAR_AXES = ("X", "Y", "Z", "U", "V", "W")
_CENTER_FOR_AXIS = {"X": "I", "Y": "J", "Z": "K"}
_HOME_CODES = frozenset({28, 30, 53})


@dataclass(frozen=True, slots=True)
class ScaleSpec:
    factor: Decimal
    about: dict[str, Decimal] = field(default_factory=dict)
    """Centre of scaling per axis; missing axes scale about 0."""
    axes: tuple[str, ...] = LINEAR_AXES
    also_feed: bool = False
    digits: int | None = None
    rounding: Rounding = "HALF_UP"
    range: Range = field(default_factory=Range)


def scale(program: Program, spec: ScaleSpec, profile: Profile) -> OpResult:
    if spec.factor <= 0:
        raise ProgramError("scale factor must be positive (use `mirror` to flip)")
    result = OpResult(program=program)
    if spec.factor == 1:
        return result

    axes = tuple(a.upper() for a in spec.axes if a.upper() in profile.axes)
    about = {a.upper(): v for a, v in spec.about.items()}
    selected = spec.range.select(program, profile)
    new_lines: list[Line] = []

    for ls in iter_states(program, profile):
        line = ls.line
        if line.index not in selected or line.kind is not LineKind.MOTION:
            if line.index in selected and spec.also_feed and line.has(profile.feed):
                new_line = _scale_feed_only(line, spec, profile, result)
                new_lines.append(new_line)
                if new_line is not line:
                    result.changed.append(line.index)
                continue
            new_lines.append(line)
            continue
        if any(w.addr == "G" and g_int(w) in _HOME_CODES for w in line.words):
            result.warn("G28/G30/G53 blocks were left untouched")
            new_lines.append(line)
            continue
        new_line = _scale_line(ls, axes, about, spec, profile, result)
        if new_line is not line:
            result.changed.append(line.index)
        new_lines.append(new_line)

    result.program = program.with_lines(new_lines)
    return result


def _scale_feed_only(line: Line, spec: ScaleSpec, profile: Profile, result: OpResult) -> Line:
    tokens: list[Token] = list(line.tokens)
    changed = False
    for idx, t in enumerate(tokens):
        if isinstance(t, Word) and t.addr == profile.feed and t.is_numeric:
            new = replace_value(
                t, t.number * spec.factor, digits=spec.digits, rounding=spec.rounding
            )
            if new.text != t.text:
                tokens[idx] = new
                changed = True
                result.matches += 1
    return line.with_tokens(tuple(tokens)) if changed else line


def _scale_line(
    ls: LineState,
    axes: tuple[str, ...],
    about: dict[str, Decimal],
    spec: ScaleSpec,
    profile: Profile,
    result: OpResult,
) -> Line:
    line, state = ls.line, ls.state
    f = spec.factor
    tokens: list[Token] = list(line.tokens)
    changed = False
    centers = {_CENTER_FOR_AXIS[a]: a for a in axes if a in _CENTER_FOR_AXIS}

    for idx, t in enumerate(tokens):
        if not isinstance(t, Word):
            continue
        a = t.addr
        new_v: Decimal | None = None
        if a in axes:
            if not t.is_numeric:
                result.warn(f"line {line.index + 1}: macro value {t.text} was not scaled")
                continue
            c = about.get(a, Decimal(0))
            new_v = scale_value(t.number, f, c) if state.absolute else t.number * f
        elif a in centers and state.is_arc and t.is_numeric:
            if profile.arc_center_absolute:
                new_v = scale_value(t.number, f, about.get(centers[a], Decimal(0)))
            else:
                new_v = t.number * f
        elif a == "R" and t.is_numeric and profile.arc_r:
            if state.is_arc:
                new_v = t.number * f  # radius
            elif state.in_canned_cycle and "Z" in axes:
                new_v = scale_value(t.number, f, about.get("Z", Decimal(0)))  # retract level
        elif a == profile.feed and spec.also_feed and t.is_numeric:
            new_v = t.number * f
        if new_v is None:
            continue
        new = replace_value(t, new_v, digits=spec.digits, rounding=spec.rounding)
        if new.text != t.text:
            tokens[idx] = new
            changed = True
            result.matches += 1

    if state.in_canned_cycle and line.has("Q"):
        result.warn("canned-cycle Q (peck depth) was not scaled")
    return line.with_tokens(tuple(tokens)) if changed else line
