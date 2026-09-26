"""OP-FEED — scale and clamp feed (F) and spindle speed (S) words (goal.md §6.2)."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from nctab.core.format import Rounding, replace_value
from nctab.core.model import Line, Program, Token, Word
from nctab.errors import ProgramError
from nctab.ops.base import OpResult, Range, map_lines
from nctab.profiles.loader import Profile


@dataclass(frozen=True, slots=True)
class FeedsSpec:
    f_scale: Decimal | None = None
    f_min: Decimal | None = None
    f_max: Decimal | None = None
    s_scale: Decimal | None = None
    s_min: Decimal | None = None
    s_max: Decimal | None = None
    digits: int | None = None
    rounding: Rounding = "HALF_UP"
    range: Range = field(default_factory=Range)

    @property
    def is_noop(self) -> bool:
        return all(
            v is None
            for v in (self.f_scale, self.f_min, self.f_max, self.s_scale, self.s_min, self.s_max)
        )


def _adjust(v: Decimal, scale: Decimal | None, lo: Decimal | None, hi: Decimal | None) -> Decimal:
    if scale is not None:
        v = v * scale
    if lo is not None and v < lo:
        v = lo
    if hi is not None and v > hi:
        v = hi
    return v


def feeds(program: Program, spec: FeedsSpec, profile: Profile) -> OpResult:
    if spec.is_noop:
        return OpResult(program=program)
    for name, v in (("f_scale", spec.f_scale), ("s_scale", spec.s_scale)):
        if v is not None and v <= 0:
            raise ProgramError(f"{name} must be positive")

    f_addr, s_addr = profile.feed, profile.spindle
    do_f = any(v is not None for v in (spec.f_scale, spec.f_min, spec.f_max))
    do_s = any(v is not None for v in (spec.s_scale, spec.s_min, spec.s_max))
    matches = 0

    def fn(line: Line) -> Line | None:
        nonlocal matches
        tokens: list[Token] = list(line.tokens)
        changed = False
        for idx, t in enumerate(tokens):
            if not isinstance(t, Word) or not t.is_numeric:
                continue
            if do_f and t.addr == f_addr:
                new_v = _adjust(t.number, spec.f_scale, spec.f_min, spec.f_max)
            elif do_s and t.addr == s_addr:
                new_v = _adjust(t.number, spec.s_scale, spec.s_min, spec.s_max)
            else:
                continue
            # feeds/speeds are whole numbers on most controls unless the source had decimals
            digits = spec.digits if spec.digits is not None else _digits_like(t)
            new = replace_value(t, new_v, digits=digits, rounding=spec.rounding)
            if new.text != t.text:
                tokens[idx] = new
                changed = True
                matches += 1
        return line.with_tokens(tuple(tokens)) if changed else None

    result = map_lines(program, spec.range.select(program, profile), fn)
    result.matches = matches
    return result


def _digits_like(word: Word) -> int:
    """Fractional digits of the source text (``F180`` → 0, ``F12.5`` → 1)."""
    text = word.value_text.strip()
    if "." in text:
        return len(text.split(".", 1)[1])
    return 0
