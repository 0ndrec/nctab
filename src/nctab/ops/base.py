"""Shared operation plumbing (goal.md §6.2, §10).

Every operation is a pure function ``apply(program, spec, profile) -> OpResult``.
The input ``Program`` is never mutated; changed lines are new objects and their
indices are recorded so the TUI can build undo entries and highlight changes.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from dataclasses import replace as _replace
from typing import Literal

from nctab.core.model import Line, LineKind, Program
from nctab.core.state import g_int
from nctab.errors import ProgramError
from nctab.profiles.loader import Profile

Rounding = Literal["HALF_UP", "HALF_EVEN"]


@dataclass(slots=True)
class OpResult:
    program: Program
    changed: list[int] = field(default_factory=list)  # line indices (0-based)
    warnings: list[str] = field(default_factory=list)
    matches: int = 0  # words / tokens touched

    @property
    def changed_lines(self) -> int:
        return len(self.changed)

    def warn(self, message: str) -> None:
        if message not in self.warnings:
            self.warnings.append(message)


# --------------------------------------------------------------------------- range

_RANGE_LINES = re.compile(r"^(\d+)?\s*[-:]\s*(\d+)?$")
_RANGE_BLOCKS = re.compile(r"^N(\d+)?\s*[-:]\s*N?(\d+)?$", re.IGNORECASE)
_RANGE_TOOL = re.compile(r"^T(\d+)$", re.IGNORECASE)
_RANGE_SINGLE_LINE = re.compile(r"^(\d+)$")
_RANGE_SINGLE_BLOCK = re.compile(r"^N(\d+)$", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class Range:
    """Which lines an operation touches.

    * ``lines``: 1-based inclusive ``(start, end)``; ``None`` = open end
    * ``blocks``: N-number inclusive ``(start, end)``
    * ``tool``: from the block that selects ``T<tool>`` up to (not including)
      the next tool selection
    """

    lines: tuple[int | None, int | None] | None = None
    blocks: tuple[int | None, int | None] | None = None
    tool: int | None = None

    @classmethod
    def all(cls) -> Range:
        return cls()

    @classmethod
    def parse(cls, text: str | None) -> Range:
        """``"all"`` · ``"10-200"`` · ``"50-"`` · ``"N100-N500"`` · ``"T12"`` · ``"120"``."""
        if text is None or text.strip().lower() in ("", "all", "*"):
            return cls()
        t = text.strip()
        if m := _RANGE_SINGLE_LINE.match(t):
            n = int(m.group(1))
            return cls(lines=(n, n))
        if m := _RANGE_SINGLE_BLOCK.match(t):
            n = int(m.group(1))
            return cls(blocks=(n, n))
        if m := _RANGE_TOOL.match(t):
            return cls(tool=int(m.group(1)))
        if m := _RANGE_BLOCKS.match(t):
            a, b = m.groups()
            return cls(blocks=(int(a) if a else None, int(b) if b else None))
        if m := _RANGE_LINES.match(t):
            a, b = m.groups()
            return cls(lines=(int(a) if a else None, int(b) if b else None))
        raise ProgramError(
            f"cannot parse range {text!r}; expected e.g. 10-200, N100-N500, T12 or all"
        )

    @property
    def is_all(self) -> bool:
        return self.lines is None and self.blocks is None and self.tool is None

    def select(self, program: Program, profile: Profile) -> set[int]:
        """0-based indices of lines inside the range."""
        n = len(program.lines)
        if self.is_all:
            return set(range(n))
        if self.lines is not None:
            a, b = self.lines
            lo = (a or 1) - 1
            hi = (b or n) - 1
            return set(range(max(lo, 0), min(hi, n - 1) + 1))
        if self.blocks is not None:
            a, b = self.blocks
            out: set[int] = set()
            inside = a is None
            for line in program.lines:
                bn = line.block_number
                if bn is not None and a is not None and bn >= a:
                    inside = True
                if inside and bn is not None and b is not None and bn > b:
                    break
                if inside:
                    out.add(line.index)
            return out
        assert self.tool is not None
        out = set()
        inside = False
        for line in program.lines:
            t = line.word(profile.tool_word)
            if t is not None:
                code = g_int(t)
                if code is not None:
                    if inside and code != self.tool:
                        break
                    if code == self.tool:
                        inside = True
            if inside:
                out.add(line.index)
        if not out:
            raise ProgramError(f"tool T{self.tool} not found in program")
        return out


# --------------------------------------------------------------------------- helpers


def map_lines(
    program: Program,
    indices: Iterable[int],
    fn: Callable[[Line], Line | None],
    *,
    skip_kinds: frozenset[LineKind] = frozenset(
        {LineKind.BLANK, LineKind.COMMENT, LineKind.HEADER}
    ),
) -> OpResult:
    """Apply ``fn`` to each selected line. ``fn`` returns a new line or ``None`` for no change."""
    wanted = set(indices)
    new_lines: list[Line] = []
    result = OpResult(program=program)
    for line in program.lines:
        if line.index in wanted and line.kind not in skip_kinds:
            out = fn(line)
            if out is not None and out is not line:
                result.changed.append(line.index)
                new_lines.append(out)
                continue
        new_lines.append(line)
    result.program = program.with_lines(new_lines)
    return result


def reindex(lines: list[Line]) -> list[Line]:
    """Renumber ``Line.index`` after lines were inserted or deleted."""
    return [ln if ln.index == i else _replace(ln, index=i) for i, ln in enumerate(lines)]
