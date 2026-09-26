"""Unified and side-by-side diff over normalised NC text (goal.md §6.4)."""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict

from nctab.core.model import Program
from nctab.diff.normalize import DiffOptions, comparable
from nctab.profiles.loader import Profile

OpKind = Literal["equal", "replace", "delete", "insert"]


@dataclass(frozen=True, slots=True)
class Row:
    """One side-by-side row. ``None`` means the side has no line here."""

    kind: OpKind
    left_line: int | None  # 1-based original line number
    right_line: int | None
    left: str | None  # original raw text
    right: str | None


class Hunk(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: OpKind
    a_start: int
    """1-based line number in A; for a pure insert, the line it comes after."""
    a_len: int
    b_start: int
    b_len: int
    a_lines: list[str] = []
    b_lines: list[str] = []


class DiffReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: int = 1
    a: str | None = None
    b: str | None = None
    profile: str
    identical: bool
    hunks: list[Hunk]
    added: int
    removed: int
    changed: int


@dataclass(slots=True)
class DiffResult:
    hunks: list[Hunk] = field(default_factory=list)
    rows: list[Row] = field(default_factory=list)

    @property
    def identical(self) -> bool:
        return not self.hunks

    def counts(self) -> tuple[int, int, int]:
        added = sum(h.b_len for h in self.hunks if h.kind == "insert")
        removed = sum(h.a_len for h in self.hunks if h.kind == "delete")
        changed = sum(max(h.a_len, h.b_len) for h in self.hunks if h.kind == "replace")
        return added, removed, changed


def diff_programs(
    a: Program, b: Program, profile: Profile, opts: DiffOptions | None = None
) -> DiffResult:
    opts = opts or DiffOptions()
    a_norm, a_map = comparable(a, profile, opts)
    b_norm, b_map = comparable(b, profile, opts)
    matcher = difflib.SequenceMatcher(a=a_norm, b=b_norm, autojunk=False)
    result = DiffResult()

    for kind, i1, i2, j1, j2 in matcher.get_opcodes():
        a_idx = a_map[i1:i2]
        b_idx = b_map[j1:j2]
        a_raw = [a.lines[i].raw for i in a_idx]
        b_raw = [b.lines[i].raw for i in b_idx]

        if kind == "equal":
            for ai, bi in zip(a_idx, b_idx, strict=True):
                result.rows.append(Row("equal", ai + 1, bi + 1, a.lines[ai].raw, b.lines[bi].raw))
            continue

        result.hunks.append(
            Hunk(
                kind=kind,  # type: ignore[arg-type]
                a_start=(a_idx[0] + 1) if a_idx else (a_map[i1 - 1] + 2 if i1 else 1),
                a_len=len(a_idx),
                b_start=(b_idx[0] + 1) if b_idx else (b_map[j1 - 1] + 2 if j1 else 1),
                b_len=len(b_idx),
                a_lines=a_raw,
                b_lines=b_raw,
            )
        )
        for n in range(max(len(a_idx), len(b_idx))):
            ai = a_idx[n] if n < len(a_idx) else None
            bi = b_idx[n] if n < len(b_idx) else None
            result.rows.append(
                Row(
                    kind,  # type: ignore[arg-type]
                    None if ai is None else ai + 1,
                    None if bi is None else bi + 1,
                    None if ai is None else a.lines[ai].raw,
                    None if bi is None else b.lines[bi].raw,
                )
            )
    return result


def unified(
    a: Program,
    b: Program,
    profile: Profile,
    opts: DiffOptions | None = None,
    *,
    a_name: str = "a",
    b_name: str = "b",
    context: int = 3,
) -> str:
    """Unified diff of the *original* text, aligned by the normalised comparison."""
    opts = opts or DiffOptions()
    a_norm, a_map = comparable(a, profile, opts)
    b_norm, b_map = comparable(b, profile, opts)
    a_show = [a.lines[i].raw + "\n" for i in a_map]
    b_show = [b.lines[i].raw + "\n" for i in b_map]
    matcher = difflib.SequenceMatcher(a=a_norm, b=b_norm, autojunk=False)

    out: list[str] = []
    groups = list(matcher.get_grouped_opcodes(context))
    if not groups:
        return ""
    out.append(f"--- {a_name}\n")
    out.append(f"+++ {b_name}\n")
    for group in groups:
        i1, i2 = group[0][1], group[-1][2]
        j1, j2 = group[0][3], group[-1][4]
        a_first = (a_map[i1] + 1) if i1 < len(a_map) else len(a.lines)
        b_first = (b_map[j1] + 1) if j1 < len(b_map) else len(b.lines)
        out.append(f"@@ -{a_first},{i2 - i1} +{b_first},{j2 - j1} @@\n")
        for kind, k1, k2, l1, l2 in group:
            if kind == "equal":
                out.extend(" " + s for s in a_show[k1:k2])
                continue
            out.extend("-" + s for s in a_show[k1:k2])
            out.extend("+" + s for s in b_show[l1:l2])
    return "".join(out)


def build_report(
    a: Program,
    b: Program,
    profile: Profile,
    opts: DiffOptions | None = None,
    *,
    a_name: str | None = None,
    b_name: str | None = None,
) -> DiffReport:
    result = diff_programs(a, b, profile, opts)
    added, removed, changed = result.counts()
    return DiffReport(
        a=a_name,
        b=b_name,
        profile=profile.id,
        identical=result.identical,
        hunks=result.hunks,
        added=added,
        removed=removed,
        changed=changed,
    )
