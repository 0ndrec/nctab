"""Inspector: what the current block does, and where the machine is (goal.md §5.2).

Everything shown comes from the profile dictionary and the modal state, never
from a table hard-coded in the widget (goal.md §17).
"""

from __future__ import annotations

from decimal import Decimal

from rich.table import Table
from rich.text import Text as RichText
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Static

from nctab.core.model import Line, Word
from nctab.core.state import LineState, ModalState, Spindle, g_int
from nctab.profiles.loader import Profile

SPINDLE_LABELS: dict[Spindle, str] = {
    "cw": "↻ CW",
    "ccw": "↺ CCW",
    "off": "■ STOP",
}


class SpindleIndicator(Static):
    """Spindle direction in effect on the cursor's line: CW, CCW or stopped.

    The CSS class (``-cw`` / ``-ccw`` / ``-off``) carries the colour, so a theme
    can restyle it.
    """

    def set_state(self, state: ModalState | None) -> None:
        for spindle in SPINDLE_LABELS:
            self.set_class(state is not None and state.spindle == spindle, f"-{spindle}")
        if state is None:
            self.update("")
            return
        text = RichText(f"Spindle {SPINDLE_LABELS[state.spindle]}", end="")
        if state.speed is not None:
            text.append(f"  S{state.speed}")
        self.update(text)


class Inspector(VerticalScroll):
    """Decodes the word under the cursor and the state in effect on its line."""

    def compose(self) -> ComposeResult:
        yield SpindleIndicator(id="inspector-spindle")
        yield Static(id="inspector-word")
        yield Static(id="inspector-state")
        yield Static(id="inspector-position")

    def update(self, profile: Profile, ls: LineState | None, column: int) -> None:
        spindle_panel = self.query_one("#inspector-spindle", SpindleIndicator)
        word_panel = self.query_one("#inspector-word", Static)
        state_panel = self.query_one("#inspector-state", Static)
        pos_panel = self.query_one("#inspector-position", Static)

        if ls is None:
            spindle_panel.set_state(None)
            word_panel.update("")
            state_panel.update("")
            pos_panel.update("")
            return

        word = word_at(ls.line, column)
        spindle_panel.set_state(ls.state)
        word_panel.update(_describe_word(word, profile) if word else RichText("", end=""))
        state_panel.update(_describe_state(ls.state, profile))
        pos_panel.update(_describe_position(ls.state))


def word_at(line: Line, column: int) -> Word | None:
    """The word covering ``column``, or the one just before it."""
    pos = 0
    last: Word | None = None
    for token in line.tokens:
        width = len(token.text)
        if isinstance(token, Word):
            if pos <= column < pos + width:
                return token
            if pos + width <= column:
                last = token
        pos += width
    return last


def _describe_word(word: Word, profile: Profile) -> Table:
    table = Table.grid(padding=(0, 1))
    table.add_column(style="bold")
    table.add_column()
    table.add_row("Word", RichText(word.text, style="bold yellow"))
    table.add_row("Address", word.addr)

    meaning = None
    if word.addr in ("G", "M"):
        code = g_int(word)
        meaning = profile.describe(word.addr, code if code is not None else str(word.value))
    elif word.addr == profile.feed:
        meaning = "Feed rate"
    elif word.addr == profile.spindle:
        meaning = "Spindle speed"
    elif word.addr == profile.tool_word:
        meaning = "Tool"
    elif word.addr == profile.radius_comp:
        meaning = "Radius offset"
    elif word.addr == profile.length_comp:
        meaning = "Length offset"
    elif word.addr in profile.axes:
        meaning = f"{word.addr} axis"
    elif word.addr in ("I", "J", "K"):
        meaning = "Arc centre offset"
    elif word.addr == "R":
        meaning = "Arc radius or retract level"
    if meaning:
        table.add_row("Means", meaning)

    if word.is_numeric:
        table.add_row("Value", f"{word.value}")
    else:
        table.add_row("Macro", str(word.value))
    return table


def _describe_state(state: ModalState, profile: Profile) -> Table:
    table = Table.grid(padding=(0, 1))
    table.add_column(style="bold")
    table.add_column()

    if state.motion is not None:
        name = profile.describe("G", state.motion) or ""
        table.add_row("Motion", f"G{state.motion:02d} {name}".strip())
    table.add_row("Mode", profile.absolute if state.absolute else profile.incremental)
    table.add_row("Plane", f"G{state.plane_code} ({state.plane})")
    if state.comp != 40:
        table.add_row("Comp", f"G{state.comp} D{state.d if state.d is not None else '?'}")
    if state.tool is not None:
        table.add_row("Tool", f"T{state.tool}" + (f" H{state.h}" if state.h is not None else ""))
    if state.feed is not None:
        table.add_row("Feed", f"{state.feed}")
    if state.coolant:
        table.add_row("Coolant", "on")
    if state.units:
        table.add_row("Units", state.units)
    return table


def _describe_position(state: ModalState) -> Table:
    table = Table.grid(padding=(0, 1))
    table.add_column(style="bold")
    table.add_column(justify="right")
    known = {a: v for a, v in state.position.items() if isinstance(v, Decimal)}
    if not known:
        return table
    table.add_row("Position", "")
    for axis, value in known.items():
        table.add_row(f"  {axis}", f"{value}")
    return table
