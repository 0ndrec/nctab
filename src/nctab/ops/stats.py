"""``stats``: program overview (goal.md §6.3).

Stage 0: counts, per-axis min/max, G/M histogram, tools, feeds, speeds.
Path-length estimates arrive with the modal-state engine in stage 1.
"""

from __future__ import annotations

from collections import Counter
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from nctab.core.model import LineKind, Program, Word
from nctab.ops.path import compute_path
from nctab.profiles.loader import Profile


class AxisRange(BaseModel):
    model_config = ConfigDict(frozen=True)

    min: Decimal
    max: Decimal

    @property
    def span(self) -> Decimal:
        return self.max - self.min


class PathStats(BaseModel):
    """Geometric path estimate. Not a cycle time: no kinematics, no acceleration."""

    model_config = ConfigDict(frozen=True)

    rapid: Decimal
    feed: Decimal
    arc: Decimal
    cutting: Decimal
    total: Decimal
    segments: int
    skipped: int


class Stats(BaseModel):
    """JSON-stable report. Field additions are allowed; renames are not."""

    model_config = ConfigDict(frozen=True)

    schema_version: int = 1
    file: str | None = None
    profile: str
    lines: int
    blocks: int = Field(description="lines that carry at least one word")
    motion_blocks: int
    comment_lines: int
    blank_lines: int
    skipped_blocks: int
    axes: dict[str, AxisRange]
    gcodes: dict[str, int]
    mcodes: dict[str, int]
    tools: list[int]
    path: PathStats | None = None
    feeds: list[Decimal]
    speeds: list[Decimal]
    parse_issues: int


def _code_key(word: Word) -> str | None:
    """``G1`` / ``G01`` → ``G01``; ``G54.1`` → ``G54.1``; macro values → ``None``."""
    if not isinstance(word.value, Decimal):
        return None
    v = word.value
    if v == v.to_integral_value():
        return f"{word.addr}{int(v):02d}"
    return f"{word.addr}{v.normalize():f}"


def compute_stats(
    program: Program, profile: Profile, *, file: str | None = None, path: bool = True
) -> Stats:
    axes: dict[str, list[Decimal]] = {}
    g: Counter[str] = Counter()
    m: Counter[str] = Counter()
    tools: set[int] = set()
    feeds: set[Decimal] = set()
    speeds: set[Decimal] = set()
    blocks = motion = comments = blanks = skipped = 0
    axis_set = set(profile.axes)

    for line in program.lines:
        if line.kind is LineKind.BLANK:
            blanks += 1
            continue
        if line.kind is LineKind.COMMENT:
            comments += 1
            continue
        words = line.words
        if not words:
            continue
        blocks += 1
        if line.skipped:
            skipped += 1
        if line.kind is LineKind.MOTION:
            motion += 1
        for w in words:
            if not isinstance(w.value, Decimal):
                continue
            a = w.addr
            if a in axis_set:
                axes.setdefault(a, []).append(w.value)
            elif a == "G":
                key = _code_key(w)
                if key:
                    g[key] += 1
            elif a == "M":
                key = _code_key(w)
                if key:
                    m[key] += 1
            elif a == profile.tool_word:
                if w.value == w.value.to_integral_value():
                    tools.add(int(w.value))
            elif a == profile.feed:
                feeds.add(w.value)
            elif a == profile.spindle:
                speeds.add(w.value)

    path_stats: PathStats | None = None
    if path:
        p = compute_path(program, profile)
        path_stats = PathStats(
            rapid=p.rapid,
            feed=p.feed,
            arc=p.arc,
            cutting=p.cutting,
            total=p.total,
            segments=p.segments,
            skipped=p.skipped,
        )

    return Stats(
        file=file,
        profile=profile.id,
        lines=len(program.lines),
        blocks=blocks,
        motion_blocks=motion,
        comment_lines=comments,
        blank_lines=blanks,
        skipped_blocks=skipped,
        axes={a: AxisRange(min=min(v), max=max(v)) for a, v in sorted(axes.items())},
        gcodes=dict(sorted(g.items())),
        mcodes=dict(sorted(m.items())),
        tools=sorted(tools),
        path=path_stats,
        feeds=sorted(feeds),
        speeds=sorted(speeds),
        parse_issues=len(program.issues),
    )
