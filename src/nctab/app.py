"""The Textual application (goal.md §5.2).

Layout::

    ┌ nctab  OP20.nc  fanuc-mill  LN 412  G90 G17 G41 T12  *modified ┐
    ├──────────────┬─────────────────────────────────┬───────────────┤
    │ Outline/Files│ Editor                          │ Inspector     │
    ├──────────────┴─────────────────────────────────┴───────────────┤
    │ status / diagnostics                                           │
    └────────────────────────────────────────────────────────────────┘

The app owns no transform logic: dialogs return specs and these handlers call
``ops.*``, the same functions the CLI uses (goal.md §10).
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import Footer, Header, Static, TabbedContent, TabPane

from nctab.check import CheckReport, check_program
from nctab.config import Config, load_config
from nctab.core.io import read_program, write_program
from nctab.core.parse import parse_text
from nctab.core.state import ModalState, apply_line
from nctab.errors import NctabError
from nctab.ops.base import OpResult, Range
from nctab.ops.find import ReplaceSpec, replace
from nctab.ops.mirror import MirrorSpec, mirror
from nctab.ops.renumber import RenumberSpec, renumber
from nctab.ops.rotate import RotateSpec, rotate
from nctab.ops.scale import ScaleSpec, scale
from nctab.ops.shift import ShiftSpec, shift
from nctab.profiles.loader import Profile, load_profile
from nctab.snippets import load_snippets
from nctab.tui.dialogs import (
    GotoDialog,
    RenumberDialog,
    TransformDialog,
    TransformRequest,
)
from nctab.tui.editor import NcEditor
from nctab.tui.explorer import Explorer
from nctab.tui.inspector import Inspector
from nctab.tui.outline import Outline
from nctab.tui.palette import NctabCommands
from nctab.tui.panels import SnippetDialog, SnippetRequest
from nctab.tui.search_dialog import SearchDialog, SearchRequest

CSS_PATH = Path(__file__).with_name("nctab.tcss")


class StatusBar(Static):
    """Bottom line: the last message, plus the search counter."""

    message = reactive("")
    search = reactive("")

    def render(self) -> str:
        return f"{self.message}  {self.search}".strip()


class NctabApp(App[None]):
    """The nctab editor."""

    CSS_PATH = CSS_PATH
    TITLE = "nctab"

    # The editor is always in insert mode, so every binding here must be a key
    # that cannot be part of a program. No bare letters, no brackets.
    BINDINGS = [
        Binding("ctrl+s", "save", "Save"),
        Binding("ctrl+q", "quit", "Quit"),
        Binding("ctrl+f", "find", "Find"),
        Binding("f3", "find_next", "Next match"),
        Binding("shift+f3", "find_prev", "Prev match", show=False),
        Binding("ctrl+h", "replace", "Replace"),
        Binding("ctrl+g", "goto", "Go to"),
        Binding("f4", "next_tool", "Next tool"),
        Binding("shift+f4", "prev_tool", "Prev tool", show=False),
        Binding("f5", "next_mode", "Next G", show=False),
        Binding("shift+f5", "prev_mode", "Prev G", show=False),
        Binding("ctrl+b", "set_bookmark", "Mark", show=False),
        Binding("ctrl+j", "goto_bookmark", "Jump", show=False),
        Binding("ctrl+n", "renumber", "Renumber"),
        Binding("ctrl+t", "transform", "Transform"),
        Binding("f2", "snippet", "Snippet"),
        Binding("ctrl+o", "focus_side", "Side panel", show=False),
        Binding("f9", "toggle_side", "Outline/Files"),
        Binding("ctrl+r", "discard_and_open", "Discard and open", show=False),
        Binding("f1", "help", "Help"),
    ]

    COMMANDS = App.COMMANDS | {NctabCommands}

    modified = reactive(False)

    def __init__(
        self,
        path: Path | None = None,
        profile: Profile | None = None,
        config: Config | None = None,
    ) -> None:
        super().__init__()
        self.config = config or load_config()
        self.profile = profile or load_profile(self.config.defaults.profile)
        self.path = path
        self._saved_text = ""
        self._pending_open: Path | None = None
        self.snippets = load_snippets(self.profile.id)

    # -- composition --------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Horizontal(id="main"):
            with TabbedContent(id="side", initial=self._initial_tab()):
                with TabPane("Outline", id="tab-outline"):
                    yield Outline(id="outline")
                with TabPane("Files", id="tab-files"):
                    yield Explorer(self.config.defaults.gcode_dir, id="explorer")
            with Vertical(id="editor-pane"):
                yield NcEditor(self.profile, id="editor")
            yield Inspector(id="inspector")
        yield StatusBar(id="status")
        yield Footer()

    def on_mount(self) -> None:
        editor = self.editor
        if self.path is not None:
            self.open_path(self.path)
        else:
            editor.load_program("")
        editor.focus()
        self.refresh_outline()
        self.update_title()

    # -- accessors ----------------------------------------------------------

    @property
    def editor(self) -> NcEditor:
        return self.query_one("#editor", NcEditor)

    @property
    def outline(self) -> Outline:
        return self.query_one("#outline", Outline)

    @property
    def explorer(self) -> Explorer:
        return self.query_one("#explorer", Explorer)

    @property
    def side(self) -> TabbedContent:
        return self.query_one("#side", TabbedContent)

    def _initial_tab(self) -> str:
        """Start on the file list when there is nothing open to outline."""
        return "tab-outline" if self.path is not None else "tab-files"

    @property
    def inspector(self) -> Inspector:
        return self.query_one("#inspector", Inspector)

    @property
    def status(self) -> StatusBar:
        return self.query_one("#status", StatusBar)

    # -- files --------------------------------------------------------------

    def open_path(self, path: Path) -> None:
        try:
            program = read_program(path, self.profile)
        except NctabError as e:
            self.notify(str(e), severity="error")
            return
        self.path = path
        self.editor.load_program(program.text)
        self._saved_text = program.text
        self.modified = False
        self.refresh_outline()
        self.update_title()
        self._pending_open = None
        self.say(f"Opened {path}")

    def action_save(self) -> None:
        if self.path is None:
            self.notify("No file name; use the CLI to write this buffer", severity="warning")
            return
        text = self.editor.text
        program = parse_text(text, self.profile)
        try:
            write_program(program, self.path, backup=self.config.editor.backup)
        except NctabError as e:
            self.notify(str(e), severity="error")
            return
        self._saved_text = text
        self.modified = False
        self.update_title()
        self.say(f"Saved {self.path}")

    # -- status -------------------------------------------------------------

    def say(self, message: str) -> None:
        self.status.message = message

    def mark_modified(self) -> None:
        """Recompute the dirty flag from the buffer, not from an edit event."""
        self.modified = self.editor.text != self._saved_text
        self.update_title()

    def update_title(self) -> None:
        name = self.path.name if self.path else "(no file)"
        row = self.editor.cursor_location[0] + 1
        state = self.current_state()
        bits = [name, self.profile.id, f"LN {row}"]
        if state is not None:
            modal = []
            if state.motion is not None:
                modal.append(f"G{state.motion:02d}")
            modal.append(self.profile.absolute if state.absolute else self.profile.incremental)
            modal.append(f"G{state.plane_code}")
            if state.comp != 40:
                modal.append(f"G{state.comp}")
            if state.tool is not None:
                modal.append(f"T{state.tool}")
            bits.append(" ".join(modal))
        if self.modified:
            bits.append("*" + "modified")
        self.sub_title = "  ".join(bits)

    def current_state(self) -> ModalState | None:
        """Modal state in effect on the cursor's line."""
        editor = self.editor
        row = editor.cursor_location[0]
        program = editor.program
        if row >= len(program.lines):
            return None
        state = ModalState(
            position=dict.fromkeys(self.profile.axes),
            start=dict.fromkeys(self.profile.axes),
        )
        for line in program.lines[: row + 1]:
            state = apply_line(state, line, self.profile)
        return state

    def refresh_inspector(self) -> None:
        from nctab.core.state import LineState

        editor = self.editor
        row, col = editor.cursor_location
        program = editor.program
        state = self.current_state()
        if state is None or row >= len(program.lines):
            self.inspector.update(self.profile, None, col)
            return
        self.inspector.update(self.profile, LineState(program.lines[row], state), col)

    def refresh_outline(self) -> None:
        self.outline.rebuild(self.editor.program, self.profile)

    # -- events -------------------------------------------------------------

    @on(NcEditor.Changed)
    def text_changed(self) -> None:
        editor = self.editor
        editor.invalidate_program()
        self.modified = editor.text != self._saved_text
        if editor.search.query is not None:
            editor.search.refresh(editor.program, self.profile)
            self.status.search = f"match {editor.search.position}"
        self.update_title()

    @on(NcEditor.SelectionChanged)
    def selection_changed(self) -> None:
        self.update_title()
        self.refresh_inspector()

    @on(NcEditor.SearchMoved)
    def search_moved(self, event: NcEditor.SearchMoved) -> None:
        self.status.search = f"match {event.state.position}"

    @on(Outline.Selected)
    def outline_selected(self, event: Outline.Selected) -> None:
        self.editor.goto_line(event.line, one_based=False)
        self.editor.focus()

    @on(Explorer.Open)
    def explorer_open(self, event: Explorer.Open) -> None:
        """Open a file from the list, unless that would throw away edits."""
        if self.modified:
            self.notify(
                f"{self.path.name if self.path else 'the buffer'} has unsaved changes; "
                "save with Ctrl+S or press Ctrl+R to discard and open",
                severity="warning",
            )
            self._pending_open = event.path
            return
        self.open_path(event.path)
        self.side.active = "tab-outline"
        self.editor.focus()

    def action_discard_and_open(self) -> None:
        """Open the file the explorer offered, dropping unsaved changes."""
        pending, self._pending_open = self._pending_open, None
        if pending is None:
            self.say("nothing waiting to open")
            return
        self.open_path(pending)
        self.side.active = "tab-outline"
        self.editor.focus()

    # -- bookmarks ----------------------------------------------------------

    @on(NcEditor.PromptKey)
    def prompt_key(self, event: NcEditor.PromptKey) -> None:
        """A bookmark prompt received its letter."""
        editor = self.editor
        letter = event.character
        if event.purpose == "mark":
            ok = editor.set_bookmark(letter)
            self.say(f"bookmark {letter} set" if ok else "letters a-z only")
        else:
            ok = editor.goto_bookmark(letter)
            self.say(f"bookmark {letter}" if ok else f"no bookmark {letter}")

    def action_set_bookmark(self) -> None:
        self.editor.await_key("mark")
        self.say("set bookmark: press a letter")

    def action_goto_bookmark(self) -> None:
        marks = " ".join(sorted(self.editor.bookmarks)) or "none set"
        self.editor.await_key("jump")
        self.say(f"jump to bookmark ({marks}): press a letter")

    # -- structural navigation ----------------------------------------------

    def action_next_tool(self) -> None:
        self.say("next tool" if self.editor.next_tool() else "no tool changes")

    def action_prev_tool(self) -> None:
        self.say("previous tool" if self.editor.prev_tool() else "no tool changes")

    def action_next_mode(self) -> None:
        self.say("next motion block" if self.editor.next_mode() else "no motion blocks")

    def action_prev_mode(self) -> None:
        self.say("previous motion block" if self.editor.prev_mode() else "no motion blocks")

    # -- actions ------------------------------------------------------------

    def action_focus_side(self) -> None:
        """Focus whichever of the two left-hand tabs is showing."""
        if self.side.active == "tab-files":
            self.explorer.focus()
        else:
            self.outline.focus()

    def action_toggle_side(self) -> None:
        self.side.active = "tab-files" if self.side.active == "tab-outline" else "tab-outline"
        self.action_focus_side()

    def action_find_next(self) -> None:
        if self.editor.find_next() is None:
            self.say("no matches")

    def action_find_prev(self) -> None:
        if self.editor.find_prev() is None:
            self.say("no matches")

    def action_help(self) -> None:
        self.say(
            "^F find  F3/shift+F3 next,prev  ^G goto  F4/shift+F4 tool  "
            "F5/shift+F5 motion  ^B mark  ^J jump  ^H replace  ^N renumber  "
            "^T transform  F2 snippet  F9 outline/files  ^O side  ^P commands  ^S save  ^Q quit"
        )

    @work
    async def action_goto(self) -> None:
        target = await self.push_screen_wait(GotoDialog())
        if not target:
            return
        editor = self.editor
        text = str(target).strip()
        if text[:1].upper() == "N":
            number = text[1:].strip()
            ok = number.isdigit() and editor.goto_block(int(number))
            self.say(f"block N{number}" if ok else f"no block N{number}")
            return
        if text.isdigit():
            editor.goto_line(int(text))
            self.say(f"line {text}")
        else:
            self.say(f"cannot parse {text!r}")

    @work
    async def action_find(self) -> None:
        editor = self.editor
        result = await self.push_screen_wait(
            SearchDialog(editor.program, self.profile, initial=editor.selected_text.strip())
        )
        if not isinstance(result, SearchRequest):
            return
        self.run_search(result)

    @work
    async def action_replace(self) -> None:
        editor = self.editor
        result = await self.push_screen_wait(
            SearchDialog(editor.program, self.profile, replacing=True)
        )
        if not isinstance(result, SearchRequest) or result.to is None:
            return
        # keep the matches lit so the edit can be seen against the search
        self.run_search(result, announce=False)
        spec = ReplaceSpec(
            query=result.query,
            to=result.to,
            digits=self.config.defaults.digits_or_none,
            rounding=self.config.defaults.rounding,
            only=result.only,
        )
        self.apply_op(replace(editor.program, spec, self.profile), "replace")

    def run_search(self, request: SearchRequest, *, announce: bool = True) -> None:
        """Light up the matches, then land on the one the user picked."""
        editor = self.editor
        count = editor.search.run(editor.program, self.profile, request.query)
        editor.refresh()
        if not count:
            self.status.search = f"match {editor.search.position}"
            if announce:
                self.say("no matches")
            return
        if request.start_at is not None:
            line, col = request.start_at
            editor.search.index = next(
                (i for i, m in enumerate(editor.search.matches) if (m.line, m.col) == (line, col)),
                -1,
            )
        if editor.search.current is not None:
            editor.goto_match(editor.search.current)
        else:
            editor.find_next()
        self.status.search = f"match {editor.search.position}"
        if announce:
            self.say(f"{count} matches")

    @work
    async def action_renumber(self) -> None:
        spec = await self.push_screen_wait(RenumberDialog())
        if not isinstance(spec, RenumberSpec):
            return
        editor = self.editor
        self.apply_op(renumber(editor.program, spec, self.profile), "renumber")

    @work
    async def action_transform(self) -> None:
        result = await self.push_screen_wait(TransformDialog(list(self.profile.axes)))
        if not isinstance(result, TransformRequest):
            return
        self.apply_transform(result)

    @work
    async def action_snippet(self) -> None:
        result = await self.push_screen_wait(SnippetDialog(self.snippets))
        if not isinstance(result, SnippetRequest):
            return
        self.insert_snippet(result)

    def action_check(self) -> None:
        """Run the same rules the CLI runs and report in the status bar."""
        editor = self.editor
        report = CheckReport.build(
            check_program(editor.program, self.profile),
            profile=self.profile.id,
            lines=len(editor.program),
        )
        if not report.diagnostics:
            self.say("check: no problems found")
            return
        self.say(f"check: {report.errors} errors, {report.warnings} warnings")
        first = report.diagnostics[0]
        if first.line:
            editor.goto_line(first.line)
        for diagnostic in report.diagnostics[:5]:
            severity = "error" if diagnostic.severity == "error" else "warning"
            where = f"{diagnostic.line}: " if diagnostic.line else ""
            self.notify(f"{where}{diagnostic.message}", severity=severity)

    def insert_snippet(self, request: SnippetRequest) -> None:
        """Put the rendered body at the cursor, or after the next tool change."""
        editor = self.editor
        row = editor.cursor_location[0]
        if request.after_tool_change:
            stops = [s.line for s in editor.tool_stops() if s.line >= row]
            row = (stops[0] + 1) if stops else row
        editor.insert(request.body, (row, 0))
        editor.invalidate_program()
        editor.goto_line(row, one_based=False)
        self.mark_modified()
        self.refresh_outline()
        self.refresh_inspector()
        self.say(f"inserted {request.snippet.title}")

    # -- applying operations -------------------------------------------------

    def apply_transform(self, request: TransformRequest) -> None:
        editor = self.editor
        program = editor.program
        digits = self.config.defaults.digits_or_none
        rounding = self.config.defaults.rounding
        values = request.values
        amount = values.get("amount", Decimal(1))

        try:
            if request.kind == "shift":
                result = shift(
                    program,
                    ShiftSpec(
                        deltas={k: v for k, v in values.items() if k != "amount"},
                        also_incremental=request.also_incremental,
                        digits=digits,
                        rounding=rounding,
                    ),
                    self.profile,
                )
            elif request.kind == "scale":
                result = scale(
                    program,
                    ScaleSpec(
                        factor=amount,
                        about={k: v for k, v in values.items() if k != "amount"},
                        digits=digits,
                        rounding=rounding,
                    ),
                    self.profile,
                )
            elif request.kind == "mirror":
                result = mirror(
                    program,
                    MirrorSpec(
                        axis=request.axis,
                        about=values.get(request.axis, Decimal(0)),
                        digits=digits,
                        rounding=rounding,
                    ),
                    self.profile,
                )
            elif request.kind == "rotate":
                result = rotate(
                    program,
                    RotateSpec(
                        deg=amount,
                        cx=values.get("X", Decimal(0)),
                        cy=values.get("Y", Decimal(0)),
                        digits=digits,
                        rounding=rounding,
                        range=Range(),
                    ),
                    self.profile,
                )
            else:
                self.say(f"unknown transform {request.kind}")
                return
        except NctabError as e:
            self.notify(str(e), severity="error")
            return
        self.apply_op(result, request.kind)

    def apply_op(self, result: OpResult, label: str) -> None:
        """Put an operation's output into the editor, keeping undo working."""
        editor = self.editor
        if not result.changed:
            self.say(f"{label}: nothing to change")
            for warning in result.warnings:
                self.notify(warning, severity="warning")
            return
        row, col = editor.cursor_location
        editor.replace(
            result.program.text,
            (0, 0),
            editor.document.end,
            maintain_selection_offset=False,
        )
        editor.invalidate_program()
        editor.goto_line(min(row, editor.document.line_count - 1), col, one_based=False)
        self.mark_modified()
        self.refresh_outline()
        self.refresh_inspector()
        self.say(f"{label}: {result.changed_lines} lines, {result.matches} words")
        for warning in result.warnings:
            self.notify(warning, severity="warning")


def run(path: Path | None = None, profile: Profile | None = None, config: Config | None = None):
    """Entry point used by ``nctab edit``."""
    NctabApp(path=path, profile=profile, config=config).run()
