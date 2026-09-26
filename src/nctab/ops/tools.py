"""``tools``: what each tool in the program is and does (goal.md §6.3)."""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from nctab.core.model import Program
from nctab.core.state import g_int, iter_states
from nctab.profiles.loader import Profile


class ToolUse(BaseModel):
    model_config = ConfigDict(frozen=True)

    tool: int
    first_line: int
    """1-based line of the block that selects the tool."""
    last_line: int
    """1-based line of the last block before the next tool selection."""
    first_block: int | None = None
    blocks: int = 0
    """Number of blocks with words in this tool's section."""
    d: list[int] = []
    h: list[int] = []
    speeds: list[Decimal] = []
    feeds: list[Decimal] = []
    comment: str | None = None
    """Nearest comment on or just before the tool-change block — the tool's name."""


class ToolsReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: int = 1
    file: str | None = None
    profile: str
    tools: list[ToolUse]


def _nearby_comment(program: Program, index: int, look_back: int = 3) -> str | None:
    """Comment on the tool-change line, else the closest one just above it."""
    own = program.lines[index].comment
    if own:
        return own.strip()
    for i in range(index - 1, max(index - 1 - look_back, -1), -1):
        c = program.lines[i].comment
        if c and not program.lines[i].words:
            return c.strip()
    return None


def collect_tools(program: Program, profile: Profile, *, file: str | None = None) -> ToolsReport:
    t_addr = profile.tool_word
    uses: list[dict] = []
    current: dict | None = None

    for ls in iter_states(program, profile):
        line = ls.line
        w = line.word(t_addr)
        code = g_int(w) if w is not None else None
        if code is not None and (current is None or current["tool"] != code):
            current = {
                "tool": code,
                "first_line": line.index + 1,
                "last_line": line.index + 1,
                "first_block": line.block_number,
                "blocks": 0,
                "d": [],
                "h": [],
                "speeds": [],
                "feeds": [],
                "comment": _nearby_comment(program, line.index),
            }
            uses.append(current)
        if current is None:
            continue
        current["last_line"] = line.index + 1
        if not line.words:
            continue
        current["blocks"] += 1
        for key, addr in (("d", profile.radius_comp), ("h", profile.length_comp)):
            word = line.word(addr)
            v = g_int(word) if word is not None else None
            if v is not None and v not in current[key]:
                current[key].append(v)
        for key, addr in (("speeds", profile.spindle), ("feeds", profile.feed)):
            word = line.word(addr)
            if word is not None and word.is_numeric and word.number not in current[key]:
                current[key].append(word.number)

    return ToolsReport(
        file=file,
        profile=profile.id,
        tools=[ToolUse(**u) for u in uses],
    )
