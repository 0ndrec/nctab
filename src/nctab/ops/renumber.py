"""OP-REN — renumber or strip block numbers (goal.md §6.2)."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from nctab.core.model import Line, LineKind, Program, Text, Token, Word
from nctab.core.parse import parse_line
from nctab.errors import ProgramError
from nctab.ops.base import OpResult, Range
from nctab.profiles.loader import Profile


@dataclass(frozen=True, slots=True)
class RenumberSpec:
    start: int = 10
    step: int = 10
    width: int = 0
    """Minimum digits, zero-padded: ``width=4`` → ``N0010``. 0 = no padding."""
    number_comments: bool = False
    """Also give block numbers to comment-only lines."""
    strip: bool = False
    """Remove block numbers instead of renumbering."""
    range: Range = field(default_factory=Range)


def _is_text(tok: Token | None, *kinds: str) -> bool:
    return isinstance(tok, Text) and tok.kind in kinds


def _eligible(line: Line, spec: RenumberSpec) -> bool:
    if line.kind in (LineKind.BLANK, LineKind.HEADER):
        return False
    if line.kind is LineKind.COMMENT:
        return spec.number_comments or line.block_number is not None
    return True


def _strip_n(tokens: tuple[Token, ...], block_addr: str) -> tuple[Token, ...]:
    out: list[Token] = list(tokens)
    for idx, t in enumerate(out):
        if isinstance(t, Word) and t.addr == block_addr:
            del out[idx]
            # swallow one adjacent separator so "N10 G01" → "G01", "/N10 G01" → "/G01"
            if idx < len(out) and _is_text(out[idx], "space"):
                del out[idx]
            elif idx > 0 and _is_text(out[idx - 1], "space"):
                del out[idx - 1]
            break
    return tuple(out)


def _set_n(tokens: tuple[Token, ...], word: Word) -> tuple[Token, ...]:
    out = list(tokens)
    for idx, t in enumerate(out):
        if isinstance(t, Word) and t.addr == word.addr:
            out[idx] = word
            return tuple(out)
    # insert after leading whitespace and block-skip marker
    pos = 0
    while pos < len(out) and _is_text(out[pos], "space", "skip"):
        pos += 1
    sep: list[Token] = []
    if pos < len(out) and not _is_text(out[pos], "space"):
        sep = [Text("space", " ")]
    return (*out[:pos], word, *sep, *out[pos:])


def renumber(program: Program, spec: RenumberSpec, profile: Profile) -> OpResult:
    if spec.step <= 0 and not spec.strip:
        raise ProgramError("renumber step must be positive")

    selected = spec.range.select(program, profile)
    n_addr = profile.block_number
    result = OpResult(program=program)
    new_lines: list[Line] = []
    num = spec.start

    for line in program.lines:
        if line.index not in selected or not _eligible(line, spec):
            new_lines.append(line)
            continue

        if spec.strip:
            if line.word(n_addr) is None:
                new_lines.append(line)
                continue
            tokens = _strip_n(line.tokens, n_addr)
        else:
            text = f"{n_addr}{num:0{spec.width}d}"
            tokens = _set_n(line.tokens, Word(n_addr, Decimal(num), text))
            num += spec.step

        raw = "".join(t.text for t in tokens)
        if raw == line.raw:
            new_lines.append(line)
            continue
        new_line, _ = parse_line(raw, line.eol, line.index, profile)
        new_lines.append(new_line)
        result.changed.append(line.index)
        result.matches += 1

    if any(
        _is_text(t, "macro") and "GOTO" in t.text.upper()
        for line in program.lines
        for t in line.tokens
    ):
        result.warn("program contains GOTO: jump targets were not updated")

    result.program = program.with_lines(new_lines)
    return result
