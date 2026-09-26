"""NC syntax highlighting (goal.md §6.6).

There is no tree-sitter grammar for G-code, and the project already has a
tokeniser that knows the dialect, so highlights come straight from it. A span is
``(start, end, name)`` in character offsets, and ``name`` is looked up in the
editor's style table.

Spans are computed per line and cached by the exact line text, so scrolling a
50 000-line program re-highlights only what enters the viewport.
"""

from __future__ import annotations

from decimal import Decimal

from nctab.core.model import Line, Text, Word
from nctab.core.parse import parse_line
from nctab.profiles.loader import Profile

Span = tuple[int, int, str]

# style names, resolved against the theme in editor.py
COMMENT = "nc-comment"
BLOCK_NUMBER = "nc-block-number"
MOTION = "nc-motion"  # G00-G03
PREP = "nc-prep"  # other G
MCODE = "nc-mcode"
AXIS = "nc-axis"
CENTER = "nc-center"  # I J K R
FEED = "nc-feed"  # F S
TOOL = "nc-tool"  # T D H
MACRO = "nc-macro"
SKIP = "nc-skip"
PERCENT = "nc-percent"
ERROR = "nc-error"
WORD = "nc-word"  # anything else

_MOTION_CODES = frozenset({0, 1, 2, 3})
_CENTER_ADDRS = frozenset({"I", "J", "K", "R"})


def _word_style(word: Word, profile: Profile) -> str:
    addr = word.addr
    if addr == profile.block_number:
        return BLOCK_NUMBER
    if addr == "G":
        if isinstance(word.value, Decimal) and word.value == word.value.to_integral_value():
            return MOTION if int(word.value) in _MOTION_CODES else PREP
        return PREP
    if addr == "M":
        return MCODE
    if addr in profile.axes:
        return AXIS
    if addr in _CENTER_ADDRS:
        return CENTER
    if addr in (profile.feed, profile.spindle):
        return FEED
    if addr in (profile.tool_word, profile.radius_comp, profile.length_comp):
        return TOOL
    if not word.is_numeric:
        return MACRO
    return WORD


_TEXT_STYLE = {
    "comment": COMMENT,
    "macro": MACRO,
    "skip": SKIP,
    "percent": PERCENT,
    "other": ERROR,
}


def line_spans(line: Line, profile: Profile) -> list[Span]:
    """Highlight spans for an already-parsed line."""
    spans: list[Span] = []
    pos = 0
    for token in line.tokens:
        width = len(token.text)
        if width:
            if isinstance(token, Word):
                spans.append((pos, pos + width, _word_style(token, profile)))
            elif isinstance(token, Text) and token.kind != "space":
                style = _TEXT_STYLE.get(token.kind)
                if style:
                    spans.append((pos, pos + width, style))
        pos += width
    return spans


class Highlighter:
    """Caches spans per line text, so repeated renders of a viewport are cheap."""

    def __init__(self, profile: Profile, max_entries: int = 4096) -> None:
        self.profile = profile
        self._cache: dict[str, list[Span]] = {}
        self._max = max_entries

    def set_profile(self, profile: Profile) -> None:
        if profile is not self.profile:
            self.profile = profile
            self._cache.clear()

    def spans(self, text: str) -> list[Span]:
        cached = self._cache.get(text)
        if cached is not None:
            return cached
        line, _ = parse_line(text, "", 0, self.profile)
        spans = line_spans(line, self.profile)
        if len(self._cache) >= self._max:
            self._cache.clear()
        self._cache[text] = spans
        return spans
