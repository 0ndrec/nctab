"""OP-MIR — mirror across an axis (goal.md §6.2, §11).

Mirroring flips handedness, so besides negating the coordinate and its arc
centre offset it swaps G02↔G03 and G41↔G42. Blocks that inherit an arc
direction modally from *outside* the range get an explicit G word so the
result stays correct when only a section is mirrored.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from nctab.core.format import Rounding, replace_value
from nctab.core.model import Line, LineKind, Program, Text, Token, Word
from nctab.core.state import g_int, iter_states
from nctab.errors import ProgramError
from nctab.geom.transform import mirror_value
from nctab.ops.base import OpResult, Range
from nctab.profiles.loader import Profile

_CENTER_FOR_AXIS = {"X": "I", "Y": "J", "Z": "K"}
_HOME_CODES = frozenset({28, 30, 53})
_SWAP = {2: 3, 3: 2, 41: 42, 42: 41}


@dataclass(frozen=True, slots=True)
class MirrorSpec:
    axis: str
    about: Decimal = Decimal(0)
    digits: int | None = None
    rounding: Rounding = "HALF_UP"
    range: Range = field(default_factory=Range)


def _swap_g(word: Word, code: int) -> Word:
    """``G02``→``G03`` keeping zero padding; ``G2``→``G3``."""
    new = _SWAP[code]
    src = word.value_text.strip()
    pad = len(src.split(".", 1)[0])
    return Word("G", Decimal(new), word.text[0] + str(new).zfill(pad))


def _is_text(tok: Token | None, *kinds: str) -> bool:
    return isinstance(tok, Text) and tok.kind in kinds


def _at(tokens: list[Token], pos: int) -> Token | None:
    return tokens[pos] if 0 <= pos < len(tokens) else None


def _insert_g(tokens: list[Token], code: int, block_addr: str) -> list[Token]:
    """Insert an explicit ``Gnn`` after the block number (or leading skip/space)."""
    pos = 0
    while _is_text(_at(tokens, pos), "space", "skip"):
        pos += 1
    here = _at(tokens, pos)
    if isinstance(here, Word) and here.addr == block_addr:
        pos += 1
        if _is_text(_at(tokens, pos), "space"):
            pos += 1
    word = Word("G", Decimal(code), f"G{code:02d}")
    sep: list[Token] = [] if isinstance(_at(tokens, pos), Text) else [Text("space", " ")]
    return [*tokens[:pos], word, *sep, *tokens[pos:]]


def mirror(program: Program, spec: MirrorSpec, profile: Profile) -> OpResult:
    axis = spec.axis.upper()
    if axis not in profile.axes:
        raise ProgramError(f"axis {axis!r} not in profile {profile.id}")
    center_addr = _CENTER_FOR_AXIS.get(axis)
    selected = spec.range.select(program, profile)
    result = OpResult(program=program)
    new_lines: list[Line] = []
    prev_in_range = False

    for ls in iter_states(program, profile):
        line, state = ls.line, ls.state
        in_range = line.index in selected and line.kind not in (
            LineKind.BLANK,
            LineKind.COMMENT,
            LineKind.HEADER,
        )
        explicit_g = {g_int(w) for w in line.words if w.addr == "G"}

        if not in_range:
            # first block after the range that still inherits a (now flipped) arc direction
            if (
                prev_in_range
                and state.is_arc
                and line.kind is LineKind.MOTION
                and not (explicit_g & {2, 3})
            ):
                assert state.motion is not None
                tokens = _insert_g(list(line.tokens), state.motion, profile.block_number)
                new_lines.append(line.with_tokens(tuple(tokens)))
                result.changed.append(line.index)
                result.warn(
                    f"line {line.index + 1}: explicit G{state.motion:02d} added "
                    "after mirrored range"
                )
            else:
                new_lines.append(line)
            prev_in_range = False
            continue

        if any(g in _HOME_CODES for g in explicit_g):
            result.warn("G28/G30/G53 blocks were left untouched")
            new_lines.append(line)
            prev_in_range = True
            continue

        tokens: list[Token] = list(line.tokens)
        changed = False
        in_plane = axis in state.plane

        # arc inherited from before the range → make it explicit (swapped)
        if (
            not prev_in_range
            and state.is_arc
            and line.kind is LineKind.MOTION
            and in_plane
            and not (explicit_g & {2, 3})
        ):
            assert state.motion is not None
            # insert the ORIGINAL code: the swap loop below flips it like a written word
            tokens = _insert_g(tokens, state.motion, profile.block_number)
            changed = True
            result.warn(
                f"line {line.index + 1}: range starts inside a modal arc; explicit G word added"
            )

        for idx, t in enumerate(tokens):
            if not isinstance(t, Word):
                continue
            if t.addr == "G":
                code = g_int(t)
                if (code in (2, 3) and in_plane) or code in (41, 42):
                    assert code is not None
                    tokens[idx] = _swap_g(t, code)
                    changed = True
                    result.matches += 1
                continue
            new_v: Decimal | None = None
            if t.addr == axis:
                if not t.is_numeric:
                    result.warn(f"line {line.index + 1}: macro value {t.text} was not mirrored")
                    continue
                new_v = mirror_value(t.number, spec.about) if state.absolute else -t.number
            elif center_addr and t.addr == center_addr and state.is_arc and t.is_numeric:
                new_v = (
                    mirror_value(t.number, spec.about) if profile.arc_center_absolute else -t.number
                )
            if new_v is None:
                continue
            new = replace_value(t, new_v, digits=spec.digits, rounding=spec.rounding)
            if new.text != t.text:
                tokens[idx] = new
                changed = True
                result.matches += 1

        if changed:
            new_lines.append(line.with_tokens(tuple(tokens)))
            result.changed.append(line.index)
        else:
            new_lines.append(line)
        prev_in_range = True

    result.program = program.with_lines(new_lines)
    return result
