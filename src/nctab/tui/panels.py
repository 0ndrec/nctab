"""Snippet insertion (goal.md section 6.5)."""

from __future__ import annotations

from dataclasses import dataclass

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Checkbox, Input, Label, Select, Static

from nctab.errors import NctabError
from nctab.snippets import Snippet, SnippetCatalogue
from nctab.tui.dialogs import NcDialog, chosen

_FIELD_PREFIX = "snip-field-"


@dataclass(frozen=True, slots=True)
class SnippetRequest:
    snippet: Snippet
    body: str
    after_tool_change: bool


class SnippetDialog(NcDialog):
    """Pick a snippet, fill its fields, see the body before inserting it."""

    def __init__(self, catalogue: SnippetCatalogue) -> None:
        super().__init__("Insert snippet")
        self.catalogue = catalogue
        self.items = list(catalogue)

    def compose(self) -> ComposeResult:
        options = [(s.title, s.id) for s in self.items]
        with Vertical(classes="dialog dialog-wide"):
            yield Label("Insert snippet", classes="dialog-title")
            if not self.items:
                yield Static("No snippets for this profile", classes="dialog-hint")
                with Horizontal(classes="dialog-row"):
                    yield Button("Cancel", id="snip-cancel")
                return
            yield Select(
                options,
                value=self.items[0].id,
                allow_blank=False,
                id="snip-choose",
            )
            yield Static("", id="snip-description", classes="dialog-hint")
            yield VerticalScroll(id="snip-fields")
            yield Static("", id="snip-preview", classes="snippet-preview")
            with Horizontal(classes="dialog-row"):
                yield Checkbox("After the next tool change", id="snip-after-tool")
                yield Button("Insert", variant="primary", id="snip-ok")
                yield Button("Cancel", id="snip-cancel")

    def on_mount(self) -> None:
        if self.items:
            self._rebuild_fields(self.items[0])

    @property
    def current(self) -> Snippet | None:
        if not self.items:
            return None
        chosen_id = chosen(self.query_one("#snip-choose", Select))
        if chosen_id is None:
            return self.items[0]
        return self.catalogue.snippets.get(chosen_id, self.items[0])

    @on(Select.Changed, "#snip-choose")
    def snippet_changed(self) -> None:
        snippet = self.current
        if snippet is not None:
            self._rebuild_fields(snippet)

    def _rebuild_fields(self, snippet: Snippet) -> None:
        container = self.query_one("#snip-fields", VerticalScroll)
        container.remove_children()
        self.query_one("#snip-description", Static).update(snippet.description)
        for field in snippet.fields:
            default = "" if field.default is None else str(field.default)
            row = Horizontal(classes="dialog-row")
            container.mount(row)
            row.mount(Label(field.label, classes="dialog-label"))
            row.mount(Input(value=default, id=f"{_FIELD_PREFIX}{field.name}", classes="narrow"))
        self.call_after_refresh(self._refresh_preview)

    def _values(self) -> dict[str, str | int | float | None]:
        values: dict[str, str | int | float | None] = {}
        snippet = self.current
        if snippet is None:
            return values
        for field in snippet.fields:
            widget = self.query_one(f"#{_FIELD_PREFIX}{field.name}", Input)
            values[field.name] = widget.value
        return values

    @on(Input.Changed)
    def field_changed(self) -> None:
        self._refresh_preview()

    def _refresh_preview(self) -> None:
        snippet = self.current
        preview = self.query_one("#snip-preview", Static)
        if snippet is None:
            preview.update("")
            return
        try:
            preview.update(snippet.render(self._values()).rstrip("\n"))
        except NctabError as e:
            preview.update(f"[red]{e}[/]")

    @on(Button.Pressed, "#snip-cancel")
    def cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#snip-ok")
    def submit(self) -> None:
        snippet = self.current
        if snippet is None:
            self.dismiss(None)
            return
        try:
            body = snippet.render(self._values())
        except NctabError as e:
            self.notify(str(e), severity="error")
            return
        after = self.query_one("#snip-after-tool", Checkbox).value
        self.dismiss(SnippetRequest(snippet=snippet, body=body, after_tool_change=after))
