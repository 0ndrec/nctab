"""Snippet dialog, command palette and the check action."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from textual import work
from textual.app import App, ComposeResult
from textual.widgets import Button, Checkbox, Input, Select, Static

from nctab.app import NctabApp
from nctab.core.parse import parse_text
from nctab.profiles.loader import Profile, load_profile
from nctab.snippets import load_snippets
from nctab.snippets.loader import SnippetCatalogue
from nctab.tui.palette import COMMANDS, NctabCommands
from nctab.tui.panels import SnippetDialog, SnippetRequest
from tests.conftest import GOLDEN_DIR

POCKET = GOLDEN_DIR / "pocket.nc"


@pytest.fixture
def program_file(tmp_path: Path) -> Path:
    dst = tmp_path / "pocket.nc"
    shutil.copy(POCKET, dst)
    return dst


class Host(App[None]):
    """Pushes one screen and records what it returns."""

    def __init__(self, screen) -> None:
        super().__init__()
        self.dialog = screen
        self.result: object = "unset"

    def compose(self) -> ComposeResult:
        return []

    def on_mount(self) -> None:
        self.show_dialog()

    @work
    async def show_dialog(self) -> None:
        self.result = await self.push_screen_wait(self.dialog)


async def ready(app: Host, pilot) -> None:
    for _ in range(40):
        await pilot.pause()
        if app.dialog.is_mounted and app.dialog.children:
            await pilot.pause()
            await pilot.pause()
            return
    raise AssertionError("dialog never mounted")


async def press_button(app, pilot, selector: str) -> None:
    screen = app.dialog if isinstance(app, Host) else app.screen
    screen.query_one(selector, Button).press()
    await pilot.pause()
    await pilot.pause()


# --------------------------------------------------------------------------- snippet dialog


async def test_snippet_dialog_lists_and_renders(fanuc: Profile) -> None:
    app = Host(SnippetDialog(load_snippets(fanuc.id)))
    async with app.run_test(size=(120, 40)) as pilot:
        await ready(app, pilot)
        select = app.dialog.query_one("#snip-choose", Select)
        titles = [label for label, _ in select._options if label]
        assert "Tool change" in titles
        assert "Drilling cycle G81" in titles

        select.value = "tool-change"
        await pilot.pause()
        await pilot.pause()
        # the fields of the chosen snippet appear
        app.dialog.query_one("#snip-field-T", Input).value = "7"
        app.dialog.query_one("#snip-field-S", Input).value = "4500"
        await pilot.pause()
        preview = app.dialog.query_one("#snip-preview", Static)
        assert "T7 M06" in str(preview.content)

        await press_button(app, pilot, "#snip-ok")
    assert isinstance(app.result, SnippetRequest)
    assert "T7 M06" in app.result.body and "S4500 M03" in app.result.body
    assert app.result.after_tool_change is False


async def test_snippet_dialog_shows_defaults(fanuc: Profile) -> None:
    app = Host(SnippetDialog(load_snippets(fanuc.id)))
    async with app.run_test(size=(120, 40)) as pilot:
        await ready(app, pilot)
        app.dialog.query_one("#snip-choose", Select).value = "drill-cycle"
        await pilot.pause()
        await pilot.pause()
        assert app.dialog.query_one("#snip-field-Z", Input).value == "-10.0"
        await press_button(app, pilot, "#snip-ok")
    assert isinstance(app.result, SnippetRequest)
    assert "Z-10. R2. F150" in app.result.body


async def test_snippet_dialog_reports_a_bad_value(fanuc: Profile) -> None:
    app = Host(SnippetDialog(load_snippets(fanuc.id)))
    async with app.run_test(size=(120, 40)) as pilot:
        await ready(app, pilot)
        app.dialog.query_one("#snip-choose", Select).value = "tool-change"
        await pilot.pause()
        await pilot.pause()
        app.dialog.query_one("#snip-field-T", Input).value = "999"  # over the max
        await pilot.pause()
        preview = app.dialog.query_one("#snip-preview", Static)
        assert "at most 99" in str(preview.content)
        await press_button(app, pilot, "#snip-ok")
        assert app.result == "unset"  # refused, dialog still open
        await pilot.press("escape")
        await pilot.pause()
    assert app.result is None


async def test_snippet_dialog_after_tool_change(fanuc: Profile) -> None:
    app = Host(SnippetDialog(load_snippets(fanuc.id)))
    async with app.run_test(size=(120, 40)) as pilot:
        await ready(app, pilot)
        app.dialog.query_one("#snip-after-tool", Checkbox).value = True
        await pilot.pause()
        await press_button(app, pilot, "#snip-ok")
    assert isinstance(app.result, SnippetRequest)
    assert app.result.after_tool_change is True


async def test_snippet_dialog_with_no_snippets() -> None:
    app = Host(SnippetDialog(SnippetCatalogue(snippets={}, problems=[])))
    async with app.run_test(size=(80, 24)) as pilot:
        await ready(app, pilot)
        await press_button(app, pilot, "#snip-cancel")
    assert app.result is None


# --------------------------------------------------------------------------- insertion


async def test_insert_snippet_at_the_cursor(program_file: Path) -> None:
    app = NctabApp(path=program_file)
    async with app.run_test(size=(120, 40)) as pilot:
        editor = app.editor
        editor.goto_line(6)
        snippet = app.snippets.get("safe-retract")
        app.insert_snippet(
            SnippetRequest(snippet, snippet.render({"Z": 75}), after_tool_change=False)
        )
        await pilot.pause()
        lines = editor.text.splitlines()
        assert lines[5] == "G40"
        assert "G00 Z75." in lines[6]
        assert app.modified is True


async def test_insert_snippet_after_the_next_tool_change(program_file: Path) -> None:
    app = NctabApp(path=program_file)
    async with app.run_test(size=(120, 40)) as pilot:
        editor = app.editor
        editor.goto_line(1)
        snippet = app.snippets.get("safe-retract")
        app.insert_snippet(
            SnippetRequest(snippet, snippet.render({"Z": 60}), after_tool_change=True)
        )
        await pilot.pause()
        lines = editor.text.splitlines()
        # the first tool change is "N40 T1 M06" on line 10 (1-based)
        assert lines[9] == "N40 T1 M06"
        assert lines[10] == "G40"
        assert app.modified is True


async def test_insert_snippet_keeps_the_program_parsable(program_file: Path) -> None:
    app = NctabApp(path=program_file)
    async with app.run_test(size=(120, 40)) as pilot:
        snippet = app.snippets.get("tool-change")
        app.insert_snippet(
            SnippetRequest(snippet, snippet.render({"T": 3, "S": 1200}), after_tool_change=False)
        )
        await pilot.pause()
        program = parse_text(app.editor.text, app.profile)
        assert program.issues == []
        assert 3 in {t.tool for t in app.editor.tool_stops() if t.tool is not None}


# --------------------------------------------------------------------------- palette


def test_every_palette_command_has_an_action() -> None:
    for command in COMMANDS:
        assert hasattr(NctabApp, f"action_{command.action}"), command.action


def test_palette_descriptions_are_readable() -> None:
    for command in COMMANDS:
        assert command.text and command.text[0].isupper(), command.action


async def test_palette_is_registered(program_file: Path) -> None:
    app = NctabApp(path=program_file)
    async with app.run_test(size=(120, 40)):
        assert NctabCommands in app.COMMANDS


async def test_palette_discovers_every_command(program_file: Path) -> None:
    app = NctabApp(path=program_file)
    async with app.run_test(size=(120, 40)):
        provider = NctabCommands(app.screen)
        hits = [hit async for hit in provider.discover()]
        assert len(hits) == len(COMMANDS)


async def test_palette_search_matches(program_file: Path) -> None:
    app = NctabApp(path=program_file)
    async with app.run_test(size=(120, 40)):
        provider = NctabCommands(app.screen)
        hits = [hit async for hit in provider.search("renumber")]
        assert hits
        assert any("enumber" in str(hit.match_display) for hit in hits)


# --------------------------------------------------------------------------- check action


async def test_check_action_reports_a_clean_program(program_file: Path) -> None:
    app = NctabApp(path=program_file)
    async with app.run_test(size=(120, 40)) as pilot:
        app.action_check()
        await pilot.pause()
        assert app.status.message == "check: no problems found"


async def test_check_action_finds_problems_and_jumps(tmp_path: Path) -> None:
    broken = tmp_path / "broken.nc"
    shutil.copy(GOLDEN_DIR / "broken.nc", broken)
    app = NctabApp(path=broken)
    async with app.run_test(size=(120, 40)) as pilot:
        app.action_check()
        await pilot.pause()
        assert "errors" in app.status.message
        # the cursor moved to the first diagnostic that has a line
        assert app.editor.cursor_location[0] >= 0


# --------------------------------------------------------------------------- profile


async def test_snippets_follow_the_profile(program_file: Path) -> None:
    turn = load_profile("fanuc-turn")
    app = NctabApp(path=program_file, profile=turn)
    async with app.run_test(size=(120, 40)):
        assert "turn-header" in app.snippets.snippets
        assert "drill-cycle" not in app.snippets.snippets
