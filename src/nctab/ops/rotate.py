"""OP-ROT — rotate about a point in the working plane (goal.md §6.2, §11).

v1 supports the G17 (XY) plane. Other planes are refused unless ``force`` is
set, in which case ``plane[0]`` → ``plane[1]`` is treated as the CCW direction.

A block that names only one plane axis (``X10.`` with Y modal) needs the other
coordinate from the modal position; the missing word is inserted. If that
position is unknown (start of program, after G28) the block is skipped with a
warning — check the output.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from nctab.core.format import Rounding, format_decimal, replace_value
from nctab.core.model import Line, LineKind, Program, Text, Token, Word
from nctab.core.state import LineState, g_int, iter_states
from nctab.errors import ProgramError
from nctab.geom.transform import is_right_angle, rotate_point, rotate_vector
from nctab.ops.base import OpResult, Range
from nctab.profiles.loader import Profile

_CENTER_FOR_AXIS = {"X": "I", "Y": "J", "Z": "K"}
_HOME_CODES = frozenset({28, 30, 53})


@dataclass(frozen=True, slots=True)
class RotateSpec:
    deg: Decimal
    cx: Decimal = Decimal(0)
    cy: Decimal = Decimal(0)
    force: bool = False
    digits: int | None = None
    rounding: Rounding = "HALF_UP"
    range: Range = field(default_factory=Range)


def rotate(program: Program, spec: RotateSpec, profile: Profile) -> OpResult:
    result = OpResult(program=program)
    if spec.deg % 360 == 0:
        return result
    exact = is_right_angle(spec.deg)
    digits = spec.digits if spec.digits is not None else (None if exact else profile.digits)
    selected = spec.range.select(program, profile)
    new_lines: list[Line] = []

    if any(w.addr == "G" and g_int(w) == 68 for ln in program.lines for w in ln.words):
        result.warn("program already uses G68 coordinate rotation")

    for ls in iter_states(program, profile):
        line, state = ls.line, ls.state
        if line.index not in selected or line.kind is not LineKind.MOTION:
            new_lines.append(line)
            continue
        if any(w.addr == "G" and g_int(w) in _HOME_CODES for w in line.words):
            result.warn("G28/G30/G53 blocks were left untouched")
            new_lines.append(line)
            continue
        if state.plane_code != 17:
            if not spec.force:
                raise ProgramError(
                    f"line {line.index + 1}: rotation in plane G{state.plane_code} ({state.plane}) "
                    "is not supported in v1; use --force to rotate "
                    f"{state.plane[0]}→{state.plane[1]} anyway"
                )
            result.warn(f"rotating in G{state.plane_code} plane with --force")
        new_line = _rotate_line(ls, spec, digits, profile, result)
        if new_line is not line:
            result.changed.append(line.index)
        new_lines.append(new_line)

    result.program = program.with_lines(new_lines)
    return result


def _rotate_line(
    ls: LineState, spec: RotateSpec, digits: int | None, profile: Profile, result: OpResult
) -> Line:
    line, state = ls.line, ls.state
    u_axis, v_axis = state.plane[0], state.plane[1]
    wu, wv = line.word(u_axis), line.word(v_axis)
    if wu is None and wv is None and not state.is_arc:
        return line
    for w in (wu, wv):
        if w is not None and not w.is_numeric:
            result.warn(f"line {line.index + 1}: macro value {w.text}; block not rotated")
            return line

    tokens: list[Token] = list(line.tokens)
    changed = False
    q = digits if digits is not None else profile.digits

    # --- end point ---------------------------------------------------------
    if wu is not None or wv is not None:
        src = state.start if not state.absolute else state.position
        # coordinate not written on this block: take it from the modal position
        u = wu.number if wu is not None else (Decimal(0) if not state.absolute else src.get(u_axis))
        v = wv.number if wv is not None else (Decimal(0) if not state.absolute else src.get(v_axis))
        if u is None or v is None:
            result.warn(
                f"line {line.index + 1}: modal {u_axis if u is None else v_axis} position unknown; "
                "block not rotated"
            )
            return line
        if state.absolute:
            nu, nv = rotate_point(
                u, v, spec.deg, spec.cx, spec.cy, digits=q, rounding=spec.rounding
            )
        else:
            nu, nv = rotate_vector(u, v, spec.deg, digits=q, rounding=spec.rounding)
        sibling = wu if wu is not None else wv
        assert sibling is not None
        like = sibling.value_text
        tokens, c1 = _set_word(tokens, wu, u_axis, nu, like, digits, spec.rounding, profile)
        tokens, c2 = _set_word(tokens, wv, v_axis, nv, like, digits, spec.rounding, profile)
        changed = changed or c1 or c2
        result.matches += int(c1) + int(c2)

    # --- arc centre offsets --------------------------------------------------
    if state.is_arc:
        i_addr, j_addr = _CENTER_FOR_AXIS.get(u_axis), _CENTER_FOR_AXIS.get(v_axis)
        wi = line.word(i_addr) if i_addr else None
        wj = line.word(j_addr) if j_addr else None
        if (wi is not None or wj is not None) and i_addr and j_addr:
            if any(w is not None and not w.is_numeric for w in (wi, wj)):
                result.warn(f"line {line.index + 1}: macro arc centre; not rotated")
                return line
            i = wi.number if wi is not None else Decimal(0)
            j = wj.number if wj is not None else Decimal(0)
            if profile.arc_center_absolute:
                ni, nj = rotate_point(
                    i, j, spec.deg, spec.cx, spec.cy, digits=q, rounding=spec.rounding
                )
            else:
                ni, nj = rotate_vector(i, j, spec.deg, digits=q, rounding=spec.rounding)
            sibling = wi if wi is not None else wj
            assert sibling is not None
            like = sibling.value_text
            tokens, c1 = _set_word(tokens, wi, i_addr, ni, like, digits, spec.rounding, profile)
            tokens, c2 = _set_word(tokens, wj, j_addr, nj, like, digits, spec.rounding, profile)
            changed = changed or c1 or c2
            result.matches += int(c1) + int(c2)

    return line.with_tokens(tuple(tokens)) if changed else line


def _set_word(
    tokens: list[Token],
    word: Word | None,
    addr: str,
    value: Decimal,
    like: str,
    digits: int | None,
    rounding: Rounding,
    profile: Profile,
) -> tuple[list[Token], bool]:
    """Replace ``word`` with ``value`` or insert a new ``addr`` word after its sibling."""
    if word is not None:
        new = replace_value(word, value, digits=digits, rounding=rounding)
        if new.text == word.text:
            return tokens, False
        return [new if t is word else t for t in tokens], True
    if value == 0:
        return tokens, False  # omitted coordinate stayed zero → keep it omitted
    text = addr + format_decimal(value, like=like, digits=digits, rounding=rounding)
    new_word = Word(addr, value, text)
    # insert after the last axis/centre word so "X.. Y.." order stays natural
    pos = max(
        (
            idx
            for idx, t in enumerate(tokens)
            if isinstance(t, Word) and t.addr in [*profile.axes, "I", "J", "K"]
        ),
        default=None,
    )
    if pos is None:
        pos = max((idx for idx, t in enumerate(tokens) if isinstance(t, Word)), default=-1)
    return [*tokens[: pos + 1], Text("space", " "), new_word, *tokens[pos + 1 :]], True
