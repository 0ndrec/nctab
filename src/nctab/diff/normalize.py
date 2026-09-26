"""NC-aware normalisation for comparison (goal.md §6.4).

``normalize`` renders each line into the form the comparison should see. The
returned list is index-aligned with ``program.lines``, so a hunk found in the
normalised text maps straight back to real line numbers.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from nctab.core.model import Line, Program, Word
from nctab.profiles.loader import Profile


@dataclass(frozen=True, slots=True)
class DiffOptions:
    ignore_block_numbers: bool = False
    ignore_whitespace: bool = False
    ignore_comments: bool = False
    ignore_leading_zeros: bool = False
    """Compare numbers by value: ``X010.500`` == ``X10.5``."""
    ignore_case: bool = False
    ignore_blank_lines: bool = False

    @property
    def is_exact(self) -> bool:
        return not any(
            (
                self.ignore_block_numbers,
                self.ignore_whitespace,
                self.ignore_comments,
                self.ignore_leading_zeros,
                self.ignore_case,
                self.ignore_blank_lines,
            )
        )


def _number_text(value: Decimal | str) -> str:
    """Canonical rendering so ``X010.500``, ``X10.5`` and ``X+10.5`` compare equal."""
    if isinstance(value, Decimal):
        return f"{value.normalize():f}"  # :f expands 1E+2 back to 100
    return value


def normalize_line(line: Line, profile: Profile, opts: DiffOptions) -> str:
    if opts.is_exact:
        return line.raw

    parts: list[str] = []
    for t in line.tokens:
        if isinstance(t, Word):
            if opts.ignore_block_numbers and t.addr == profile.block_number:
                continue
            if opts.ignore_leading_zeros:
                parts.append(t.addr + _number_text(t.value))
            else:
                parts.append(t.text.upper() if opts.ignore_case else t.text)
            continue
        if t.kind == "comment":
            if opts.ignore_comments:
                continue
            parts.append(t.text.upper() if opts.ignore_case else t.text)
            continue
        if t.kind == "space":
            if not opts.ignore_whitespace:
                parts.append(t.text)
            continue
        parts.append(t.text.upper() if opts.ignore_case else t.text)

    out = "".join(parts)
    out = "".join(out.split()) if opts.ignore_whitespace else out.rstrip()
    return out.upper() if opts.ignore_case and not opts.ignore_leading_zeros else out


def normalize(program: Program, profile: Profile, opts: DiffOptions) -> list[str]:
    """One normalised string per source line, index-aligned with ``program.lines``."""
    return [normalize_line(ln, profile, opts) for ln in program.lines]


def comparable(
    program: Program, profile: Profile, opts: DiffOptions
) -> tuple[list[str], list[int]]:
    """Normalised lines with blank lines optionally dropped, plus their original indices."""
    lines = normalize(program, profile, opts)
    if not opts.ignore_blank_lines:
        return lines, list(range(len(lines)))
    keep = [i for i, s in enumerate(lines) if s.strip()]
    return [lines[i] for i in keep], keep
