"""One dialog for find and replace (goal.md section 5.2, PLAN.md section 1.4a).

Find and replace were two forms that shared almost everything and disagreed on
what they could do: replace only ever worked on an address, and neither showed
what you were about to change. This is one dialog with a mode selector, live
results as you type, and a per-match preview of before and after.

Nothing is guessed at:

* the match count updates while you type, so an empty search is obvious before
  you commit to it
* every match is listed with its line and block number
* in replace mode each row shows what that match becomes, computed by the same
  code that performs the edit
* rows can be switched off one at a time, so "all except that one" needs no
  cleverness with the pattern
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Literal

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Checkbox, DataTable, Input, Label, Select, Static

from nctab.core.model import Program
from nctab.errors import NctabError
from nctab.ops.find import (
    Change,
    Match,
    Query,
    ReplaceSpec,
    find,
    preview_replace,
    suggest,
    suggest_addresses,
)
from nctab.profiles.loader import Profile
from nctab.tui.dialogs import NcDialog, chosen

Mode = Literal["text", "regex", "address", "code"]

MODES: list[tuple[str, str]] = [
    ("Text", "text"),
    ("Pattern", "regex"),
    ("Address word", "address"),
    ("G or M code", "code"),
]

PLACEHOLDER = {
    "text": "text to find, e.g. G41 D",
    "regex": r"pattern, e.g. X(\d+)\.",
    "address": "address letter, e.g. F",
    "code": "code, e.g. G02 or M8",
}

#: how long to wait after a keystroke before searching again
DEBOUNCE = 0.15
#: rows drawn in the results table; the count line still reports the true total
MAX_ROWS = 400


@dataclass(frozen=True, slots=True)
class SearchRequest:
    """What the dialog returns. ``to`` is ``None`` when it was only a search."""

    query: Query
    to: str | None = None
    only: frozenset[tuple[int, int]] | None = None
    start_at: tuple[int, int] | None = None
    """The match the user picked from the list, as ``(line, column)``."""

    @property
    def is_replace(self) -> bool:
        return self.to is not None


def _decimal(text: str) -> Decimal | None:
    text = text.strip()
    if not text:
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


class SearchDialog(NcDialog):
    """Find, or find and replace, with a live preview."""

    BINDINGS = [
        Binding("escape", "dismiss_dialog", "Cancel"),
        Binding("space", "toggle_row", "Include/exclude", show=False),
        Binding("ctrl+a", "select_all_rows", "All", show=False),
    ]

    def __init__(
        self,
        program: Program,
        profile: Profile,
        *,
        replacing: bool = False,
        initial: str = "",
    ) -> None:
        super().__init__("Replace" if replacing else "Find")
        self.program = program
        self.profile = profile
        self.replacing = replacing
        self.initial = initial
        self.matches: list[Match] = []
        self.changes: list[Change] = []
        self.excluded: set[tuple[int, int]] = set()
        self._timer = None
        self._error = ""

    # -- layout -------------------------------------------------------------

    def compose(self) -> ComposeResult:
        addresses = [(f"{a}   ({n})", a) for a, n in suggest_addresses(self.program, self.profile)]
        with Vertical(classes="dialog dialog-search"):
            yield Label("Replace" if self.replacing else "Find", classes="dialog-title")

            with Horizontal(classes="dialog-row"):
                yield Select(MODES, value="text", allow_blank=False, id="sd-mode")
                yield Input(value=self.initial, placeholder=PLACEHOLDER["text"], id="sd-query")

            with Horizontal(classes="dialog-row", id="sd-address-row"):
                yield Label("Address", classes="dialog-label")
                yield Select(addresses, prompt="pick one", allow_blank=True, id="sd-address")
                yield Label("Value", classes="dialog-label")
                yield Select([], prompt="any", allow_blank=True, id="sd-value")

            if self.replacing:
                with Horizontal(classes="dialog-row"):
                    yield Label("Replace with", classes="dialog-label")
                    yield Input(placeholder="new value or text", id="sd-to")

            # one row: the two switches, the running count, and the bulk toggles.
            # The dialog has to stay usable at the 80x24 minimum of goal.md
            # section 7, so every row it does not need is a row the result
            # table gets instead.
            with Horizontal(classes="dialog-row"):
                yield Checkbox("Match case", id="sd-case")
                yield Checkbox("Comments", id="sd-comments")
                yield Static("", id="sd-summary")
                if self.replacing:
                    yield Button("All", id="sd-all", classes="tiny")
                    yield Button("None", id="sd-none", classes="tiny")

            yield DataTable(id="sd-results", cursor_type="row", zebra_stripes=True)

            with Horizontal(classes="dialog-row"):
                yield Button(
                    "Replace" if self.replacing else "Go to match",
                    variant="primary",
                    id="sd-ok",
                )
                yield Button("Cancel", id="sd-cancel")

    def on_mount(self) -> None:
        table = self.query_one("#sd-results", DataTable)
        if self.replacing:
            table.add_columns(" ", "Line", "Block", "Before", "After")
        else:
            table.add_columns("Line", "Block", "Match", "Text")
        self._show_address_row(False)
        self.query_one("#sd-query", Input).focus()
        self.refresh_results()

    # -- mode ---------------------------------------------------------------

    @property
    def mode(self) -> Mode:
        value = chosen(self.query_one("#sd-mode", Select))
        return value if value in ("text", "regex", "address", "code") else "text"  # type: ignore[return-value]

    def _show_address_row(self, showing: bool) -> None:
        self.query_one("#sd-address-row").display = showing
        self.query_one("#sd-query", Input).display = not showing

    @on(Select.Changed, "#sd-mode")
    def mode_changed(self) -> None:
        mode = self.mode
        self._show_address_row(mode == "address")
        query = self.query_one("#sd-query", Input)
        query.placeholder = PLACEHOLDER[mode]
        if mode == "address":
            self.query_one("#sd-address", Select).focus()
        else:
            query.focus()
        self.refresh_results()

    @on(Select.Changed, "#sd-address")
    def address_changed(self) -> None:
        """Offer the values that address actually takes in this program."""
        values = self.query_one("#sd-value", Select)
        address = chosen(self.query_one("#sd-address", Select))
        if address is None:
            values.set_options([])
        else:
            hints = suggest(self.program, self.profile, address)
            values.set_options(
                [(f"{h.text}   ({h.count} on line {h.first_line})", str(h.value)) for h in hints]
            )
        # Select.BLANK is a plain False in this version; NULL is the real sentinel
        values.value = Select.NULL
        self.refresh_results()

    @on(Select.Changed, "#sd-value")
    @on(Checkbox.Changed)
    def option_changed(self) -> None:
        self.refresh_results()

    @on(Input.Changed)
    def text_changed(self) -> None:
        """Search a moment after the last keystroke, not on every one."""
        if self._timer is not None:
            self._timer.stop()
        self._timer = self.set_timer(DEBOUNCE, self.refresh_results)

    # -- searching ----------------------------------------------------------

    def build_query(self) -> Query | None:
        """The query for the current form, or ``None`` when it is not usable yet."""
        mode = self.mode
        self._error = ""
        case = self.query_one("#sd-case", Checkbox).value
        comments = self.query_one("#sd-comments", Checkbox).value

        try:
            if mode == "address":
                address = chosen(self.query_one("#sd-address", Select))
                if address is None:
                    return None
                value = _decimal(chosen(self.query_one("#sd-value", Select)) or "")
                return Query(
                    addr=address,
                    values=(value,) if value is not None else (),
                    in_comments=comments,
                    ignore_case=not case,
                )
            text = self.query_one("#sd-query", Input).value.strip()
            if not text:
                return None
            if mode == "code":
                return Query(code=text, in_comments=comments, ignore_case=not case)
            return Query(
                text=text, regex=mode == "regex", ignore_case=not case, in_comments=comments
            )
        except NctabError as e:
            self._error = str(e)
            return None

    def refresh_results(self) -> None:
        self._timer = None
        query = self.build_query()
        self.matches = []
        self.changes = []
        if query is not None:
            try:
                self.matches = find(self.program, self.profile, query)
            except NctabError as e:
                self._error = str(e)
        if self.replacing and self.matches and query is not None:
            self.changes = preview_replace(
                self.program, ReplaceSpec(query=query, to=self._to_text()), self.profile
            )
        self.excluded &= {(m.line, m.col) for m in self.matches}
        self._fill_table()
        self._fill_summary()

    def _to_text(self) -> str:
        return self.query_one("#sd-to", Input).value.strip() if self.replacing else ""

    def _fill_table(self) -> None:
        table = self.query_one("#sd-results", DataTable)
        table.clear()
        if self.replacing:
            for change in self.changes[:MAX_ROWS]:
                key = f"{change.match.line}:{change.match.col}"
                excluded = (change.match.line, change.match.col) in self.excluded
                # Text(), not str: a bare [x] is swallowed as Rich console markup.
                mark = Text("[ ]" if excluded else "[x]")
                block = f"N{change.match.block_number}" if change.match.block_number else "-"
                after = change.after if change.touched else f"{change.after} (no change)"
                table.add_row(mark, str(change.lineno), block, change.before, after, key=key)
            return
        for match in self.matches[:MAX_ROWS]:
            key = f"{match.line}:{match.col}"
            block = f"N{match.block_number}" if match.block_number else "-"
            table.add_row(str(match.lineno), block, match.text, match.line_text.strip(), key=key)

    def _fill_summary(self) -> None:
        summary = self.query_one("#sd-summary", Static)
        if self._error:
            # Text(), not markup: the message quotes the pattern the user typed.
            summary.update(Text(self._error, style="red"))
            return
        if not self.matches:
            query = self.build_query()
            summary.update("" if query is None else "no matches")
            return

        lines = len({m.line for m in self.matches})
        text = f"{len(self.matches)} matches in {lines} lines"
        if self.replacing:
            chosen_count = len(self.selected_keys())
            changing = sum(
                1
                for c in self.changes
                if c.touched and (c.match.line, c.match.col) not in self.excluded
            )
            if chosen_count != len(self.matches):
                text += f" | {chosen_count} selected"
            if changing != chosen_count:
                text += f" | {changing} actually change"
        if len(self.matches) > MAX_ROWS:
            text += f" | showing the first {MAX_ROWS}"
        summary.update(text)

    # -- per-match selection -------------------------------------------------

    def selected_keys(self) -> frozenset[tuple[int, int]]:
        return frozenset(
            (m.line, m.col) for m in self.matches if (m.line, m.col) not in self.excluded
        )

    def action_toggle_row(self) -> None:
        if not self.replacing:
            return
        table = self.query_one("#sd-results", DataTable)
        if table.row_count == 0:
            return
        row = table.cursor_row
        if not 0 <= row < len(self.changes):
            return
        match = self.changes[row].match
        key = (match.line, match.col)
        self.excluded.symmetric_difference_update({key})
        self._fill_table()
        self._fill_summary()
        table.move_cursor(row=row)

    @on(DataTable.RowSelected, "#sd-results")
    def row_selected(self, event: DataTable.RowSelected) -> None:
        if self.replacing:
            self.action_toggle_row()
            return
        self._submit_at(event.cursor_row)

    @on(Button.Pressed, "#sd-all")
    def select_all(self) -> None:
        self.excluded.clear()
        self._fill_table()
        self._fill_summary()

    def action_select_all_rows(self) -> None:
        self.select_all()

    @on(Button.Pressed, "#sd-none")
    def select_none(self) -> None:
        self.excluded = {(m.line, m.col) for m in self.matches}
        self._fill_table()
        self._fill_summary()

    # -- finishing ----------------------------------------------------------

    @on(Button.Pressed, "#sd-cancel")
    def cancel(self) -> None:
        self.dismiss(None)

    @on(Input.Submitted)
    @on(Button.Pressed, "#sd-ok")
    def submit(self) -> None:
        self._submit_at(None)

    def _submit_at(self, row: int | None) -> None:
        query = self.build_query()
        if query is None:
            self.notify(self._error or "Nothing to search for", severity="warning")
            return
        if not self.matches:
            self.notify("No matches", severity="warning")
            return
        if not self.replacing:
            picked = None
            if row is not None and 0 <= row < len(self.matches):
                match = self.matches[row]
                picked = (match.line, match.col)
            self.dismiss(SearchRequest(query=query, start_at=picked))
            return
        if not self._to_text():
            self.notify("Give a replacement value", severity="warning")
            self.query_one("#sd-to", Input).focus()
            return
        only = self.selected_keys()
        if not only:
            self.notify("Every match is switched off", severity="warning")
            return
        subset = None if len(only) == len(self.matches) else only
        self.dismiss(SearchRequest(query=query, to=self._to_text(), only=subset))
