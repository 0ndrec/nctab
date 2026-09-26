"""The NC editor widget (goal.md §5.2, §6.6).

Built on Textual's ``TextArea``, which virtualises rendering, so a 50 000-line
program costs no more than the visible rows. Highlighting rides on the
documented ``get_line`` hook rather than tree-sitter, because the project's own
tokeniser already knows the dialect.

Navigation the shop asked for. The editor is always in insert mode, so a bare
``]`` has to insert a bracket; navigation therefore lives on keys a terminal
delivers reliably and that never collide with typing:

* ``Ctrl+F`` search, ``F3`` / ``Shift+F3`` next and previous match, every match drawn
* ``Ctrl+G`` jump to a line number or an ``N`` block number
* ``F4`` / ``Shift+F4`` next and previous tool change
* ``F5`` / ``Shift+F5`` next and previous motion-mode change
* ``Ctrl+B`` then a letter sets a bookmark, ``Ctrl+J`` then a letter jumps to it
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from rich.style import Style
from rich.text import Text as RichText
from textual.message import Message
from textual.widgets import TextArea

from nctab.core.model import Program
from nctab.core.parse import parse_text
from nctab.core.state import g_int
from nctab.ops.find import Match
from nctab.profiles.loader import Profile
from nctab.tui import highlight as hl
from nctab.tui.search import SearchState

_STYLES: dict[str, Style] = {
    hl.COMMENT: Style(color="#6a9955", italic=True),
    hl.BLOCK_NUMBER: Style(color="#858585"),
    hl.MOTION: Style(color="#4ec9b0", bold=True),
    hl.PREP: Style(color="#569cd6"),
    hl.MCODE: Style(color="#c586c0"),
    hl.AXIS: Style(color="#dcdcaa"),
    hl.CENTER: Style(color="#d7ba7d"),
    hl.FEED: Style(color="#ce9178"),
    hl.TOOL: Style(color="#9cdcfe", bold=True),
    hl.MACRO: Style(color="#b5cea8"),
    hl.SKIP: Style(color="#808080", italic=True),
    hl.PERCENT: Style(color="#569cd6", bold=True),
    hl.ERROR: Style(color="#f44747", underline=True),
    hl.WORD: Style(color="#d4d4d4"),
}

_MATCH = Style(bgcolor="#515c6a")
_CURRENT_MATCH = Style(bgcolor="#c08040", color="#000000", bold=True)
_BOOKMARK_KEY = re.compile(r"^[a-z]$")


@dataclass(frozen=True, slots=True)
class ToolStop:
    line: int
    tool: int | None
    label: str


class NcEditor(TextArea):
    """A ``TextArea`` that knows NC syntax, search matches and program structure."""

    class CursorMoved(Message):
        """The cursor landed on a new line."""

        def __init__(self, line: int, column: int) -> None:
            super().__init__()
            self.line = line
            self.column = column

    class SearchMoved(Message):
        """The selected search match changed."""

        def __init__(self, state: SearchState) -> None:
            super().__init__()
            self.state = state

    class PromptKey(Message):
        """A one-key prompt (bookmark set or jump) received its letter."""

        def __init__(self, purpose: str, character: str) -> None:
            super().__init__()
            self.purpose = purpose
            self.character = character

    def __init__(self, profile: Profile, text: str = "", **kwargs) -> None:
        kwargs.setdefault("show_line_numbers", True)
        kwargs.setdefault("soft_wrap", False)
        kwargs.setdefault("tab_behavior", "indent")
        super().__init__(text, **kwargs)
        self.profile = profile
        self.highlighter = hl.Highlighter(profile)
        self.search = SearchState()
        self.bookmarks: dict[str, int] = {}
        self._program: Program | None = None
        self._program_text: str | None = None
        self._pending_prefix: str | None = None

    # -- program ------------------------------------------------------------

    def set_profile(self, profile: Profile) -> None:
        self.profile = profile
        self.highlighter.set_profile(profile)
        self._program = None
        self.refresh()

    @property
    def program(self) -> Program:
        """The parsed document, re-parsed only when the text actually changed."""
        text = self.text
        if self._program is None or self._program_text != text:
            self._program = parse_text(text, self.profile)
            self._program_text = text
        return self._program

    def invalidate_program(self) -> None:
        self._program = None
        self._program_text = None

    def load_program(self, text: str) -> None:
        self.load_text(text)
        self.invalidate_program()
        self.search.clear()
        self.bookmarks.clear()

    # -- rendering ----------------------------------------------------------

    def get_line(self, line_index: int) -> RichText:
        """Apply NC highlighting and search marks. Documented TextArea hook."""
        line = super().get_line(line_index)
        plain = line.plain
        if not plain:
            return line
        for start, end, name in self.highlighter.spans(plain):
            style = _STYLES.get(name)
            if style is not None:
                line.stylize(style, start, end)
        if self.search.active:
            current = self.search.current
            for m in self.search.matches_on(line_index):
                is_current = current is not None and (m.line, m.col) == (current.line, current.col)
                line.stylize(_CURRENT_MATCH if is_current else _MATCH, m.col, m.col + m.length)
        return line

    # -- navigation ---------------------------------------------------------

    def goto_line(self, line: int, column: int = 0, *, one_based: bool = True) -> None:
        """Move the cursor to a line and scroll it into view."""
        index = max(0, (line - 1) if one_based else line)
        index = min(index, self.document.line_count - 1)
        column = min(column, len(self.document.get_line(index)))
        self.move_cursor((index, column))
        self.scroll_cursor_visible(center=True)
        self.post_message(self.CursorMoved(index, column))

    def goto_block(self, number: int) -> bool:
        """Jump to the block with this N number. False when there is none."""
        for line in self.program.lines:
            if line.block_number == number:
                self.goto_line(line.index, one_based=False)
                return True
        return False

    def goto_match(self, match: Match) -> None:
        self.goto_line(match.line, match.col, one_based=False)
        self.selection = self._selection_for(match)
        self.refresh()
        self.post_message(self.SearchMoved(self.search))

    def _selection_for(self, match: Match):
        from textual.widgets.text_area import Selection

        return Selection((match.line, match.col), (match.line, match.col + match.length))

    # -- tool / mode stops --------------------------------------------------

    def tool_stops(self) -> list[ToolStop]:
        """Lines that change the tool, in order."""
        out: list[ToolStop] = []
        t_addr = self.profile.tool_word
        last: int | None = None
        for line in self.program.lines:
            word = line.word(t_addr)
            if word is None:
                continue
            tool = g_int(word)
            if tool is not None and tool == last:
                continue
            last = tool
            label = (line.comment or line.raw).strip()
            out.append(ToolStop(line.index, tool, label))
        return out

    def mode_stops(self) -> list[int]:
        """Lines where an explicit motion G word appears."""
        out: list[int] = []
        for line in self.program.lines:
            for w in line.words:
                if w.addr == "G" and g_int(w) in (0, 1, 2, 3):
                    out.append(line.index)
                    break
        return out

    def _jump(self, stops: list[int], forward: bool) -> bool:
        if not stops:
            return False
        here = self.cursor_location[0]
        candidates = [s for s in stops if s > here] if forward else [s for s in stops if s < here]
        if not candidates:
            target = stops[0] if forward else stops[-1]  # wrap
        else:
            target = candidates[0] if forward else candidates[-1]
        self.goto_line(target, one_based=False)
        return True

    def next_tool(self) -> bool:
        return self._jump([s.line for s in self.tool_stops()], forward=True)

    def prev_tool(self) -> bool:
        return self._jump([s.line for s in self.tool_stops()], forward=False)

    def next_mode(self) -> bool:
        return self._jump(self.mode_stops(), forward=True)

    def prev_mode(self) -> bool:
        return self._jump(self.mode_stops(), forward=False)

    # -- search -------------------------------------------------------------

    def find_next(self) -> Match | None:
        row, col = self.cursor_location
        match = self.search.next(from_line=row, from_col=col + 1)
        if match is not None:
            self.goto_match(match)
        return match

    def find_prev(self) -> Match | None:
        row, col = self.cursor_location
        match = self.search.prev(from_line=row, from_col=col)
        if match is not None:
            self.goto_match(match)
        return match

    def action_find_next(self) -> None:
        self.find_next()

    def action_find_prev(self) -> None:
        self.find_prev()

    # -- bookmarks ----------------------------------------------------------

    def set_bookmark(self, key: str) -> bool:
        if not _BOOKMARK_KEY.match(key):
            return False
        self.bookmarks[key] = self.cursor_location[0]
        return True

    def goto_bookmark(self, key: str) -> bool:
        line = self.bookmarks.get(key)
        if line is None:
            return False
        self.goto_line(min(line, self.document.line_count - 1), one_based=False)
        return True

    # -- one-key prompts (bookmarks) ---------------------------------------

    def await_key(self, purpose: str) -> None:
        """Swallow the next keystroke and use it for ``purpose`` ("mark" or "jump")."""
        self._pending_prefix = purpose

    @property
    def pending_prefix(self) -> str | None:
        return self._pending_prefix

    def clear_prefix(self) -> None:
        self._pending_prefix = None

    def take_key(self, character: str | None) -> tuple[str, str] | None:
        """Consume a keystroke for a pending prompt. Returns ``(purpose, letter)``."""
        purpose, self._pending_prefix = self._pending_prefix, None
        if purpose is None or not character:
            return None
        return purpose, character

    async def _on_key(self, event) -> None:
        """Intercept the keystroke a bookmark prompt is waiting for."""
        if self._pending_prefix is not None:
            event.prevent_default()
            event.stop()
            self.post_message(self.PromptKey(self._pending_prefix, event.character or ""))
            self._pending_prefix = None
            return
        await super()._on_key(event)
