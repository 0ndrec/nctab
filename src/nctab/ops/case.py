"""OP-CASE — upper/lower-case the code, never the comments (goal.md §6.2)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from nctab.core.model import Line, Program, Text, Token, Word
from nctab.ops.base import OpResult, Range, map_lines
from nctab.profiles.loader import Profile

Case = Literal["upper", "lower"]


@dataclass(frozen=True, slots=True)
class CaseSpec:
    case: Case = "upper"
    range: Range = field(default_factory=Range)


def change_case(program: Program, spec: CaseSpec, profile: Profile) -> OpResult:
    conv = str.upper if spec.case == "upper" else str.lower
    matches = 0

    def fn(line: Line) -> Line | None:
        nonlocal matches
        tokens: list[Token] = list(line.tokens)
        changed = False
        for idx, t in enumerate(tokens):
            if isinstance(t, Word):
                new_text = conv(t.text)
                if new_text != t.text:
                    tokens[idx] = Word(t.addr, t.value, new_text)
                    changed = True
                    matches += 1
            elif isinstance(t, Text) and t.kind == "macro":
                new_text = conv(t.text)
                if new_text != t.text:
                    tokens[idx] = Text("macro", new_text)
                    changed = True
                    matches += 1
        return line.with_tokens(tuple(tokens)) if changed else None

    result = map_lines(program, spec.range.select(program, profile), fn)
    result.matches = matches
    return result
