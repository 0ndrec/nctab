"""The unified find and replace dialog: live counts, preview, per-match selection."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from textual import work
from textual.app import App, ComposeResult
from textual.widgets import Button, Checkbox, DataTable, Input, Select, Static
from textual.widgets.text_area import Selection

from nctab.app import NctabApp
from nctab.core.parse import parse_text
from nctab.ops.find import Query, ReplaceSpec, preview_replace, replace
from nctab.profiles.loader import Profile, load_profile
from nctab.tui.search_dialog import MAX_ROWS, SearchDialog, SearchRequest
from tests.conftest import GOLDEN_DIR

POCKET = GOLDEN_DIR / "pocket.nc"


@pytest.fixture
def program_file(tmp_path: Path) -> Path:
    dst = tmp_path / "pocket.nc"
    shutil.copy(POCKET, dst)
    return dst


class Host(App[None]):
    def __init__(self, screen) -> None:
        super().__init__()
        self.dialog = screen
        self.result: object = "unset"

    def compose(self) -> ComposeResult:
        return []

    def on_mount(self) -> None:
        self.show()

    @work
    async def show(self) -> None:
        self.result = await self.push_screen_wait(self.dialog)


async def ready(app: Host, pilot) -> None:
    for _ in range(50):
        await pilot.pause()
        if app.dialog.is_mounted and app.dialog.children:
            await pilot.pause()
            await pilot.pause()
            return
    raise AssertionError("dialog never mounted")


def summary(dialog: SearchDialog) -> str:
    return str(dialog.query_one("#sd-summary", Static).content)


def table(dialog: SearchDialog) -> DataTable:
    return dialog.query_one("#sd-results", DataTable)


def mark(dialog: SearchDialog, row: int) -> str:
    """The include marker as it actually reaches the screen."""
    return str(table(dialog).get_row_at(row)[0])


async def type_query(dialog: SearchDialog, pilot, text: str) -> None:
    """Set the query and search now, rather than waiting out the debounce."""
    dialog.query_one("#sd-query", Input).value = text
    dialog.refresh_results()
    await pilot.pause()


def dialog_for(fanuc: Profile, **kwargs) -> Host:
    program = parse_text(POCKET.read_text(), fanuc)
    return Host(SearchDialog(program, fanuc, **kwargs))


# --------------------------------------------------------------------------- find


async def test_starts_empty_and_says_nothing(fanuc: Profile) -> None:
    """An empty box is not an error; it simply has nothing to report yet."""
    app = dialog_for(fanuc)
    async with app.run_test(size=(120, 44)) as pilot:
        await ready(app, pilot)
        assert summary(app.dialog) == ""
        assert table(app.dialog).row_count == 0


async def test_counts_update_as_you_type(fanuc: Profile) -> None:
    app = dialog_for(fanuc)
    async with app.run_test(size=(120, 44)) as pilot:
        await ready(app, pilot)
        await type_query(app.dialog, pilot, "G41")
        assert summary(app.dialog) == "2 matches in 2 lines"
        assert table(app.dialog).row_count == 2
        await type_query(app.dialog, pilot, "G0")
        assert "matches in" in summary(app.dialog)


async def test_no_matches_is_stated_plainly(fanuc: Profile) -> None:
    app = dialog_for(fanuc)
    async with app.run_test(size=(120, 44)) as pilot:
        await ready(app, pilot)
        await type_query(app.dialog, pilot, "ZZZZ")
        assert summary(app.dialog) == "no matches"
        assert table(app.dialog).row_count == 0


async def test_rows_carry_line_and_block(fanuc: Profile) -> None:
    app = dialog_for(fanuc)
    async with app.run_test(size=(120, 44)) as pilot:
        await ready(app, pilot)
        await type_query(app.dialog, pilot, "G41")
        row = table(app.dialog).get_row_at(0)
        assert row[0] == "16"  # 1-based line
        assert row[1] == "N100"
        assert row[2] == "G41"


async def test_a_bad_pattern_quoting_brackets_is_still_readable(fanuc: Profile) -> None:
    """The message quotes the pattern, so [a] must not be eaten as console markup."""
    app = dialog_for(fanuc)
    async with app.run_test(size=(120, 44)) as pilot:
        await ready(app, pilot)
        app.dialog.query_one("#sd-mode", Select).value = "regex"
        await pilot.pause()
        await type_query(app.dialog, pilot, "[a]b(")
        assert "[a]b(" in summary(app.dialog)


async def test_a_bad_pattern_is_reported_not_raised(fanuc: Profile) -> None:
    app = dialog_for(fanuc)
    async with app.run_test(size=(120, 44)) as pilot:
        await ready(app, pilot)
        app.dialog.query_one("#sd-mode", Select).value = "regex"
        await pilot.pause()
        await type_query(app.dialog, pilot, "G(41")
        assert "bad regex" in summary(app.dialog)
        assert table(app.dialog).row_count == 0


async def test_match_case_narrows_the_result(fanuc: Profile) -> None:
    app = dialog_for(fanuc)
    async with app.run_test(size=(120, 44)) as pilot:
        await ready(app, pilot)
        await type_query(app.dialog, pilot, "g41")
        assert summary(app.dialog) == "2 matches in 2 lines"
        app.dialog.query_one("#sd-case", Checkbox).value = True
        await pilot.pause()
        app.dialog.refresh_results()
        await pilot.pause()
        assert summary(app.dialog) == "no matches"


async def test_comments_are_left_out_until_asked_for(fanuc: Profile) -> None:
    app = dialog_for(fanuc)
    async with app.run_test(size=(120, 44)) as pilot:
        await ready(app, pilot)
        await type_query(app.dialog, pilot, "FINISH")
        assert summary(app.dialog) == "no matches"
        app.dialog.query_one("#sd-comments", Checkbox).value = True
        await pilot.pause()
        app.dialog.refresh_results()
        await pilot.pause()
        assert "matches in" in summary(app.dialog)


async def test_code_mode(fanuc: Profile) -> None:
    app = dialog_for(fanuc)
    async with app.run_test(size=(120, 44)) as pilot:
        await ready(app, pilot)
        app.dialog.query_one("#sd-mode", Select).value = "code"
        await pilot.pause()
        await type_query(app.dialog, pilot, "G3")
        assert summary(app.dialog) == "1 matches in 1 lines"
        app.dialog.query_one("#sd-ok", Button).press()
        await pilot.pause()
        await pilot.pause()
    assert isinstance(app.result, SearchRequest)
    assert app.result.query.code == "G3"


async def test_picking_a_row_returns_that_match(fanuc: Profile) -> None:
    """The list is for landing on a particular hit, not just for counting."""
    app = dialog_for(fanuc)
    async with app.run_test(size=(120, 44)) as pilot:
        await ready(app, pilot)
        await type_query(app.dialog, pilot, "G41")
        second = app.dialog.matches[1]
        app.dialog._submit_at(1)
        await pilot.pause()
        await pilot.pause()
    assert isinstance(app.result, SearchRequest)
    assert app.result.start_at == (second.line, second.col)


async def test_the_ok_button_does_not_pick_a_row(fanuc: Profile) -> None:
    app = dialog_for(fanuc)
    async with app.run_test(size=(120, 44)) as pilot:
        await ready(app, pilot)
        await type_query(app.dialog, pilot, "G41")
        app.dialog.query_one("#sd-ok", Button).press()
        await pilot.pause()
        await pilot.pause()
    assert isinstance(app.result, SearchRequest)
    assert app.result.start_at is None
    assert app.result.to is None


async def test_cancel(fanuc: Profile) -> None:
    app = dialog_for(fanuc)
    async with app.run_test(size=(120, 44)) as pilot:
        await ready(app, pilot)
        app.dialog.query_one("#sd-cancel", Button).press()
        await pilot.pause()
        await pilot.pause()
    assert app.result is None


async def test_submitting_nothing_keeps_the_dialog_open(fanuc: Profile) -> None:
    app = dialog_for(fanuc)
    async with app.run_test(size=(120, 44)) as pilot:
        await ready(app, pilot)
        app.dialog.query_one("#sd-ok", Button).press()
        await pilot.pause()
        assert app.result == "unset"
        await pilot.press("escape")
        await pilot.pause()
    assert app.result is None


# --------------------------------------------------------------------------- address mode


async def test_address_mode_swaps_the_input_for_dropdowns(fanuc: Profile) -> None:
    app = dialog_for(fanuc)
    async with app.run_test(size=(120, 44)) as pilot:
        await ready(app, pilot)
        assert app.dialog.query_one("#sd-address-row").display is False
        app.dialog.query_one("#sd-mode", Select).value = "address"
        await pilot.pause()
        await pilot.pause()
        assert app.dialog.query_one("#sd-address-row").display is True
        assert app.dialog.query_one("#sd-query", Input).display is False


async def test_address_dropdown_shows_counts(fanuc: Profile) -> None:
    app = dialog_for(fanuc)
    async with app.run_test(size=(120, 44)) as pilot:
        await ready(app, pilot)
        options = [label for label, _ in app.dialog.query_one("#sd-address", Select)._options]
        assert any(label.startswith("F ") or label.startswith("F  ") for label in options)
        assert any("(" in label for label in options)


async def test_values_offer_what_the_program_actually_uses(fanuc: Profile) -> None:
    app = dialog_for(fanuc)
    async with app.run_test(size=(120, 44)) as pilot:
        await ready(app, pilot)
        app.dialog.query_one("#sd-mode", Select).value = "address"
        await pilot.pause()
        app.dialog.query_one("#sd-address", Select).value = "F"
        await pilot.pause()
        await pilot.pause()
        # the first entry is the blank prompt that "any value" uses
        labels = [label for label, _ in app.dialog.query_one("#sd-value", Select)._options if label]
        assert [label.split()[0] for label in labels] == ["F300", "F900", "F200", "F600"]
        assert "line 15" in labels[0]
        assert summary(app.dialog) == "4 matches in 4 lines"  # blank value means all of them


async def test_choosing_a_value_narrows_to_it(fanuc: Profile) -> None:
    app = dialog_for(fanuc)
    async with app.run_test(size=(120, 44)) as pilot:
        await ready(app, pilot)
        app.dialog.query_one("#sd-mode", Select).value = "address"
        await pilot.pause()
        app.dialog.query_one("#sd-address", Select).value = "F"
        await pilot.pause()
        await pilot.pause()
        app.dialog.query_one("#sd-value", Select).value = "300"
        await pilot.pause()
        await pilot.pause()
        assert summary(app.dialog) == "1 matches in 1 lines"


async def test_changing_address_resets_the_value(fanuc: Profile) -> None:
    app = dialog_for(fanuc)
    async with app.run_test(size=(120, 44)) as pilot:
        await ready(app, pilot)
        app.dialog.query_one("#sd-mode", Select).value = "address"
        await pilot.pause()
        address = app.dialog.query_one("#sd-address", Select)
        values = app.dialog.query_one("#sd-value", Select)
        address.value = "F"
        await pilot.pause()
        await pilot.pause()
        values.value = "300"
        await pilot.pause()
        address.value = "S"
        await pilot.pause()
        await pilot.pause()
        # a value from the old address must not survive, or the search is a lie
        assert app.dialog.build_query().values == ()
        assert summary(app.dialog) == "2 matches in 2 lines"


# --------------------------------------------------------------------------- replace


async def test_replace_shows_before_and_after(fanuc: Profile) -> None:
    app = dialog_for(fanuc, replacing=True)
    async with app.run_test(size=(120, 44)) as pilot:
        await ready(app, pilot)
        app.dialog.query_one("#sd-mode", Select).value = "address"
        await pilot.pause()
        app.dialog.query_one("#sd-address", Select).value = "F"
        await pilot.pause()
        await pilot.pause()
        app.dialog.query_one("#sd-to", Input).value = "250"
        app.dialog.refresh_results()
        await pilot.pause()
        row = table(app.dialog).get_row_at(0)
        assert [str(cell) for cell in row] == ["[x]", "15", "N90", "F300", "F250"]


async def test_replace_marks_a_match_that_will_not_change(fanuc: Profile) -> None:
    """Replacing F300 with 300 is a no-op; say so rather than promising an edit."""
    app = dialog_for(fanuc, replacing=True)
    async with app.run_test(size=(120, 44)) as pilot:
        await ready(app, pilot)
        app.dialog.query_one("#sd-mode", Select).value = "address"
        await pilot.pause()
        app.dialog.query_one("#sd-address", Select).value = "F"
        await pilot.pause()
        await pilot.pause()
        app.dialog.query_one("#sd-value", Select).value = "300"
        await pilot.pause()
        app.dialog.query_one("#sd-to", Input).value = "300"
        app.dialog.refresh_results()
        await pilot.pause()
        assert "no change" in table(app.dialog).get_row_at(0)[4]
        assert "0 actually change" in summary(app.dialog)


async def test_replace_works_on_text_too(fanuc: Profile) -> None:
    """The old dialog could only replace an address word."""
    app = dialog_for(fanuc, replacing=True)
    async with app.run_test(size=(120, 44)) as pilot:
        await ready(app, pilot)
        await type_query(app.dialog, pilot, "G41")
        app.dialog.query_one("#sd-to", Input).value = "G42"
        app.dialog.refresh_results()
        await pilot.pause()
        assert table(app.dialog).get_row_at(0)[3:] == ["G41", "G42"]
        app.dialog.query_one("#sd-ok", Button).press()
        await pilot.pause()
        await pilot.pause()
    assert isinstance(app.result, SearchRequest)
    assert app.result.to == "G42"
    assert app.result.query.text == "G41"


async def test_rows_can_be_switched_off(fanuc: Profile) -> None:
    app = dialog_for(fanuc, replacing=True)
    async with app.run_test(size=(120, 44)) as pilot:
        await ready(app, pilot)
        app.dialog.query_one("#sd-mode", Select).value = "address"
        await pilot.pause()
        app.dialog.query_one("#sd-address", Select).value = "F"
        await pilot.pause()
        await pilot.pause()
        app.dialog.query_one("#sd-to", Input).value = "250"
        app.dialog.refresh_results()
        await pilot.pause()

        widget = table(app.dialog)
        widget.move_cursor(row=0)
        app.dialog.action_toggle_row()
        await pilot.pause()
        assert mark(app.dialog, 0) == "[ ]"
        assert mark(app.dialog, 1) == "[x]"
        assert "3 selected" in summary(app.dialog)

        app.dialog.query_one("#sd-ok", Button).press()
        await pilot.pause()
        await pilot.pause()
    assert isinstance(app.result, SearchRequest)
    assert app.result.only is not None
    assert len(app.result.only) == 3


async def test_all_and_none_buttons(fanuc: Profile) -> None:
    app = dialog_for(fanuc, replacing=True)
    async with app.run_test(size=(120, 44)) as pilot:
        await ready(app, pilot)
        await type_query(app.dialog, pilot, "G01")
        app.dialog.query_one("#sd-to", Input).value = "G1"
        app.dialog.refresh_results()
        await pilot.pause()
        total = len(app.dialog.matches)

        app.dialog.query_one("#sd-none", Button).press()
        await pilot.pause()
        assert app.dialog.selected_keys() == frozenset()
        assert mark(app.dialog, 0) == "[ ]"

        app.dialog.query_one("#sd-ok", Button).press()
        await pilot.pause()
        assert app.result == "unset"  # refused: nothing selected

        app.dialog.query_one("#sd-all", Button).press()
        await pilot.pause()
        assert len(app.dialog.selected_keys()) == total
        app.dialog.query_one("#sd-ok", Button).press()
        await pilot.pause()
        await pilot.pause()
    assert isinstance(app.result, SearchRequest)
    assert app.result.only is None  # every match: no subset needed


async def test_replace_without_a_value_is_refused(fanuc: Profile) -> None:
    app = dialog_for(fanuc, replacing=True)
    async with app.run_test(size=(120, 44)) as pilot:
        await ready(app, pilot)
        await type_query(app.dialog, pilot, "G41")
        app.dialog.query_one("#sd-ok", Button).press()
        await pilot.pause()
        assert app.result == "unset"
        await pilot.press("escape")
        await pilot.pause()
    assert app.result is None


async def test_excluded_rows_are_forgotten_when_the_search_changes(fanuc: Profile) -> None:
    app = dialog_for(fanuc, replacing=True)
    async with app.run_test(size=(120, 44)) as pilot:
        await ready(app, pilot)
        await type_query(app.dialog, pilot, "G01")
        app.dialog.query_one("#sd-to", Input).value = "G1"
        app.dialog.refresh_results()
        await pilot.pause()
        table(app.dialog).move_cursor(row=0)
        app.dialog.action_toggle_row()
        await pilot.pause()
        assert app.dialog.excluded

        await type_query(app.dialog, pilot, "G02")
        assert app.dialog.excluded == set()  # the old columns mean nothing now


# --------------------------------------------------------------------------- preview honesty


def test_preview_agrees_with_the_applied_result(fanuc: Profile) -> None:
    """A preview computed apart from the edit would be free to lie."""
    program = parse_text(POCKET.read_text(), fanuc)
    for spec in (
        ReplaceSpec(Query(addr="F"), to="250"),
        ReplaceSpec(Query(code="G01"), to="1"),
        ReplaceSpec(Query(text="G41"), to="G42"),
        ReplaceSpec(Query(text=r"X(-?\d+)\.", regex=True), to=r"X\1.0"),
    ):
        changes = preview_replace(program, spec, fanuc)
        result = replace(program, spec, fanuc)
        assert sum(1 for c in changes if c.touched) == result.matches
        expected = {c.line: c.line_after for c in changes if c.touched}
        for index, line_after in expected.items():
            assert result.program.lines[index].raw == line_after


def test_preview_honours_a_subset(fanuc: Profile) -> None:
    program = parse_text(POCKET.read_text(), fanuc)
    every = preview_replace(program, ReplaceSpec(Query(addr="F"), to="250"), fanuc)
    one = {(every[0].match.line, every[0].match.col)}
    subset = preview_replace(
        program, ReplaceSpec(Query(addr="F"), to="250", only=frozenset(one)), fanuc
    )
    assert len(subset) == 1
    assert subset[0].after == every[0].after


def test_preview_of_nothing(fanuc: Profile) -> None:
    program = parse_text(POCKET.read_text(), fanuc)
    assert preview_replace(program, ReplaceSpec(Query(addr="Q"), to="1"), fanuc) == []


def test_two_matches_on_one_line(fanuc: Profile) -> None:
    """Both rewrites land, and each row reports its own before and after."""
    program = parse_text("N10 G01 X1. Y1. F100\n", fanuc)
    spec = ReplaceSpec(Query(text=r"(\d)\.", regex=True), to=r"\g<1>.5")
    changes = preview_replace(program, spec, fanuc)
    result = replace(program, spec, fanuc)
    assert len(changes) == 2
    assert result.program.lines[0].raw == "N10 G01 X1.5 Y1.5 F100"
    assert all(c.line_after == "N10 G01 X1.5 Y1.5 F100" for c in changes)


# --------------------------------------------------------------------------- through the app


async def test_find_through_the_app(program_file: Path) -> None:
    app = NctabApp(path=program_file)
    async with app.run_test(size=(140, 44)) as pilot:
        app.action_find()
        await pilot.pause()
        await pilot.pause()
        dialog = app.screen
        assert isinstance(dialog, SearchDialog)
        dialog.query_one("#sd-query", Input).value = "G41"
        dialog.refresh_results()
        await pilot.pause()
        dialog.query_one("#sd-ok", Button).press()
        await pilot.pause()
        await pilot.pause()
        assert app.editor.search.count == 2
        assert "2 matches" in app.status.message


async def test_find_lands_on_the_row_you_picked(program_file: Path) -> None:
    app = NctabApp(path=program_file)
    async with app.run_test(size=(140, 44)) as pilot:
        app.action_find()
        await pilot.pause()
        await pilot.pause()
        dialog = app.screen
        assert isinstance(dialog, SearchDialog)
        dialog.query_one("#sd-query", Input).value = "G41"
        dialog.refresh_results()
        await pilot.pause()
        second = dialog.matches[1]
        dialog._submit_at(1)
        await pilot.pause()
        await pilot.pause()
        assert app.editor.cursor_location[0] == second.line
        assert app.editor.search.position == "2/2"


async def test_replace_through_the_app(program_file: Path) -> None:
    app = NctabApp(path=program_file)
    async with app.run_test(size=(140, 44)) as pilot:
        app.action_replace()
        await pilot.pause()
        await pilot.pause()
        dialog = app.screen
        assert isinstance(dialog, SearchDialog)
        dialog.query_one("#sd-mode", Select).value = "address"
        await pilot.pause()
        dialog.query_one("#sd-address", Select).value = "F"
        await pilot.pause()
        await pilot.pause()
        dialog.query_one("#sd-to", Input).value = "250"
        dialog.refresh_results()
        await pilot.pause()
        dialog.query_one("#sd-ok", Button).press()
        await pilot.pause()
        await pilot.pause()
        assert "F300" not in app.editor.text
        assert app.editor.text.count("F250") == 4
        assert app.modified is True
        assert "replace" in app.status.message


async def test_replace_of_a_subset_through_the_app(program_file: Path) -> None:
    app = NctabApp(path=program_file)
    async with app.run_test(size=(140, 44)) as pilot:
        app.action_replace()
        await pilot.pause()
        await pilot.pause()
        dialog = app.screen
        assert isinstance(dialog, SearchDialog)
        dialog.query_one("#sd-mode", Select).value = "address"
        await pilot.pause()
        dialog.query_one("#sd-address", Select).value = "F"
        await pilot.pause()
        await pilot.pause()
        dialog.query_one("#sd-to", Input).value = "250"
        dialog.refresh_results()
        await pilot.pause()
        dialog.query_one("#sd-results", DataTable).move_cursor(row=0)
        dialog.action_toggle_row()
        await pilot.pause()
        dialog.query_one("#sd-ok", Button).press()
        await pilot.pause()
        await pilot.pause()
        assert "F300" in app.editor.text  # the row that was switched off
        assert app.editor.text.count("F250") == 3


async def test_find_seeds_itself_from_the_selection(program_file: Path) -> None:
    app = NctabApp(path=program_file)
    async with app.run_test(size=(140, 44)) as pilot:
        editor = app.editor
        # line 16 is "N100 G41 D1 X-30. F900"; G41 sits at columns 5 to 8
        editor.selection = Selection((15, 5), (15, 8))
        await pilot.pause()
        app.action_find()
        await pilot.pause()
        await pilot.pause()
        assert app.screen.query_one("#sd-query", Input).value == "G41"


# --------------------------------------------------------------------------- big programs


async def test_a_large_result_set_is_capped_but_counted(tmp_path: Path) -> None:
    """Drawing thousands of rows would stall the dialog; the count stays honest."""
    fanuc = load_profile("fanuc-mill")
    big = "\n".join(f"N{i * 10} G01 X{i}. F100" for i in range(1, MAX_ROWS + 60))
    app = Host(SearchDialog(parse_text(big, fanuc), fanuc))
    async with app.run_test(size=(120, 44)) as pilot:
        await ready(app, pilot)
        await type_query(app.dialog, pilot, "F100")
        assert len(app.dialog.matches) == MAX_ROWS + 59
        assert table(app.dialog).row_count == MAX_ROWS
        assert f"first {MAX_ROWS}" in summary(app.dialog)


# --------------------------------------------------------------------------- layout


@pytest.mark.parametrize("size", [(80, 24), (100, 30), (140, 44)])
async def test_the_dialog_fits_the_terminal(program_file: Path, size: tuple[int, int]) -> None:
    """goal.md section 7 promises 80x24 works.

    The buttons once fell off the bottom because the dialog sized itself to its
    content; the result table now takes what is left instead.
    """
    cols, rows = size
    app = NctabApp(path=program_file)
    async with app.run_test(size=size) as pilot:
        app.action_replace()
        await pilot.pause()
        await pilot.pause()
        dialog = app.screen
        assert isinstance(dialog, SearchDialog)
        dialog.query_one("#sd-mode", Select).value = "address"
        await pilot.pause()
        dialog.query_one("#sd-address", Select).value = "F"
        await pilot.pause()
        await pilot.pause()
        dialog.query_one("#sd-to", Input).value = "250"
        dialog.refresh_results()
        await pilot.pause()
        await pilot.pause()

        for name in ("#sd-mode", "#sd-to", "#sd-summary", "#sd-results", "#sd-ok", "#sd-cancel"):
            region = dialog.query_one(name).region
            assert region.x >= 0 and region.y >= 0, (name, region)
            assert region.x + region.width <= cols, (name, region)
            assert region.y + region.height <= rows, (name, region)
        # the result list must not be squeezed out of existence
        assert dialog.query_one("#sd-results").region.height >= 3
