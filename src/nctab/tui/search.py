"""Search state shared by the editor and the find/replace dialogs (PLAN.md §1.4a).

Holds the current query, its matches, and which one is selected. The editor
draws every match and highlights the current one; ``next``/``prev`` wrap around
and report their position so the status bar can show ``3/17``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from nctab.core.model import Program
from nctab.ops.find import Match, Query, find
from nctab.profiles.loader import Profile


@dataclass(slots=True)
class SearchState:
    query: Query | None = None
    matches: list[Match] = field(default_factory=list)
    index: int = -1
    """Position in ``matches``; -1 when nothing is selected yet."""

    @property
    def active(self) -> bool:
        return bool(self.matches)

    @property
    def count(self) -> int:
        return len(self.matches)

    @property
    def current(self) -> Match | None:
        if 0 <= self.index < len(self.matches):
            return self.matches[self.index]
        return None

    @property
    def position(self) -> str:
        """``"3/17"`` for the status bar, or ``"0/0"`` when nothing matched."""
        return f"{self.index + 1 if self.index >= 0 else 0}/{self.count}"

    def clear(self) -> None:
        self.query = None
        self.matches = []
        self.index = -1

    def run(self, program: Program, profile: Profile, query: Query) -> int:
        """Search and select nothing yet. Returns the number of matches."""
        self.query = query
        self.matches = find(program, profile, query)
        self.index = -1
        return len(self.matches)

    def refresh(self, program: Program, profile: Profile) -> None:
        """Re-run the current query after an edit, keeping the position if possible."""
        if self.query is None:
            return
        anchor = self.current
        self.matches = find(program, profile, self.query)
        if anchor is None or not self.matches:
            self.index = -1 if not self.matches else 0
            return
        # settle on the first match at or after where we were
        for i, m in enumerate(self.matches):
            if (m.line, m.col) >= (anchor.line, anchor.col):
                self.index = i
                return
        self.index = len(self.matches) - 1

    def next(self, *, from_line: int = 0, from_col: int = 0) -> Match | None:
        """Select the next match, wrapping around. Starts after ``(from_line, from_col)``."""
        if not self.matches:
            return None
        if self.index < 0:
            for i, m in enumerate(self.matches):
                if (m.line, m.col) >= (from_line, from_col):
                    self.index = i
                    return m
            self.index = 0
            return self.matches[0]
        self.index = (self.index + 1) % len(self.matches)
        return self.matches[self.index]

    def prev(self, *, from_line: int = 0, from_col: int = 0) -> Match | None:
        """Select the previous match, wrapping around."""
        if not self.matches:
            return None
        if self.index < 0:
            for i in range(len(self.matches) - 1, -1, -1):
                m = self.matches[i]
                if (m.line, m.col) < (from_line, from_col):
                    self.index = i
                    return m
            self.index = len(self.matches) - 1
            return self.matches[self.index]
        self.index = (self.index - 1) % len(self.matches)
        return self.matches[self.index]

    def matches_on(self, line: int) -> list[Match]:
        return [m for m in self.matches if m.line == line]
