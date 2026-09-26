"""OP-STRIP — remove block numbers, comments, blank lines, skip marks, spaces (goal.md §6.2)."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field

from nctab.core.model import Line, Program, Text, Token, Word
from nctab.core.parse import parse_line
from nctab.ops.base import OpResult, Range, reindex
from nctab.profiles.loader import Profile

_WS = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class StripSpec:
    block_numbers: bool = False
    comments: bool = False
    blank: bool = False
    """Delete lines that are (or become) empty."""
    skip_marks: bool = False
    """Remove the leading ``/`` so skipped blocks become active."""
    skipped_blocks: bool = False
    """Delete ``/`` blocks entirely."""
    spaces: bool = False
    """Remove whitespace between words (comments keep theirs)."""
    range: Range = field(default_factory=Range)

    @property
    def is_noop(self) -> bool:
        return not any(
            (
                self.block_numbers,
                self.comments,
                self.blank,
                self.skip_marks,
                self.skipped_blocks,
                self.spaces,
            )
        )


def strip(program: Program, spec: StripSpec, profile: Profile) -> OpResult:
    result = OpResult(program=program)
    if spec.is_noop:
        return result
    selected = spec.range.select(program, profile)
    out: list[Line] = []

    for line in program.lines:
        if line.index not in selected:
            out.append(line)
            continue
        if spec.skipped_blocks and line.skipped:
            result.changed.append(line.index)
            continue

        tokens = list(line.tokens)
        if spec.block_numbers:
            tokens = _drop(tokens, lambda t: isinstance(t, Word) and t.addr == profile.block_number)
        if spec.comments:
            tokens = _drop(tokens, lambda t: _is(t, "comment"))
        if spec.skip_marks:
            tokens = _drop(tokens, lambda t: _is(t, "skip"))
        if spec.spaces:
            tokens = [
                Word(t.addr, t.value, _WS.sub("", t.text)) if isinstance(t, Word) else t
                for t in tokens
                if not (isinstance(t, Text) and t.kind == "space")
            ]

        raw = "".join(t.text for t in tokens)
        if spec.blank and raw.strip() == "":
            result.changed.append(line.index)
            continue
        if raw == line.raw:
            out.append(line)
            continue
        new_line, _ = parse_line(raw, line.eol, line.index, profile)
        out.append(new_line)
        result.changed.append(line.index)
        result.matches += 1

    result.program = program.with_lines(reindex(out))
    return result


def _is(tok: Token, kind: str) -> bool:
    return isinstance(tok, Text) and tok.kind == kind


def _drop(tokens: list[Token], match: Callable[[Token], bool]) -> list[Token]:
    """Remove matching tokens together with one adjacent separator each.

    Without this a removed ``N10`` would leave ``" G01 X1."`` with a stray leading
    space. The separator after the token is preferred; if there is none (the token
    ended the line) the one before it goes instead.
    """
    out: list[Token] = []
    i = 0
    while i < len(tokens):
        t = tokens[i]
        if not match(t):
            out.append(t)
            i += 1
            continue
        nxt = tokens[i + 1] if i + 1 < len(tokens) else None
        if nxt is not None and _is(nxt, "space"):
            i += 2  # drop the token and the separator that followed it
            continue
        if out and _is(out[-1], "space"):
            out.pop()
        i += 1
    return out
