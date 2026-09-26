"""OP-MATH — arithmetic on every word of the given addresses (goal.md §6.2).

This is deliberately *not* modal-aware: ``math --addr Z --op add --value -0.013``
adds to every ``Z`` word in range, absolute or incremental. Use ``shift`` for a
geometry-aware translation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal

from nctab.core.format import Rounding, replace_value
from nctab.core.model import Line, Program, Token, Word
from nctab.errors import ProgramError
from nctab.ops.base import OpResult, Range, map_lines
from nctab.profiles.loader import Profile

MathOp = Literal["add", "sub", "mul", "div"]


@dataclass(frozen=True, slots=True)
class MathSpec:
    addrs: tuple[str, ...]
    op: MathOp
    value: Decimal
    digits: int | None = None
    rounding: Rounding = "HALF_UP"
    range: Range = field(default_factory=Range)


def _compute(v: Decimal, op: MathOp, k: Decimal) -> Decimal:
    if op == "add":
        return v + k
    if op == "sub":
        return v - k
    if op == "mul":
        return v * k
    return v / k


def addr_math(program: Program, spec: MathSpec, profile: Profile) -> OpResult:
    if spec.op == "div" and spec.value == 0:
        raise ProgramError("division by zero")
    addrs = frozenset(a.upper() for a in spec.addrs)
    if not addrs:
        raise ProgramError("no addresses given")
    if profile.block_number in addrs:
        raise ProgramError(f"use `renumber` to change {profile.block_number} words")

    matches = 0
    warnings: list[str] = []

    def fn(line: Line) -> Line | None:
        nonlocal matches
        tokens: list[Token] = list(line.tokens)
        changed = False
        for idx, t in enumerate(tokens):
            if not isinstance(t, Word) or t.addr not in addrs:
                continue
            if not t.is_numeric:
                warnings.append(f"line {line.index + 1}: macro value {t.text} skipped")
                continue
            new = replace_value(
                t,
                _compute(t.number, spec.op, spec.value),
                digits=spec.digits,
                rounding=spec.rounding,
            )
            if new.text != t.text:
                tokens[idx] = new
                changed = True
                matches += 1
        return line.with_tokens(tuple(tokens)) if changed else None

    result = map_lines(program, spec.range.select(program, profile), fn)
    result.matches = matches
    for w in warnings:
        result.warn(w)
    return result
