"""TUI: highlighting, navigation, search, outline, inspector, operations."""

from __future__ import annotations

import shutil
from decimal import Decimal
from pathlib import Path

import pytest
from textual.widgets import TextArea

from nctab.app import NctabApp
from nctab.core.parse import parse_text
from nctab.ops.find import Query
from nctab.ops.renumber import RenumberSpec, renumber
from nctab.profiles.loader import Profile, load_profile
from nctab.tui import highlight as hl
from nctab.tui.dialogs import TransformRequest
from nctab.tui.inspector import SpindleIndicator, word_at
from nctab.tui.outline import HEADER_LABEL, build_outline
from nctab.tui.search import SearchState
from tests.conftest import GOLDEN_DIR

POCKET = GOLDEN_DIR / "pocket.nc"


@pytest.fixture
def work(tmp_path: Path) -> Path:
    dst = tmp_path / "pocket.nc"
    shutil.copy(POCKET, dst)
    return dst


# --------------------------------------------------------------------------- highlighting


def test_highlight_spans(fanuc: Profile) -> None:
    highlighter = hl.Highlighter(fanuc)
    spans = highlighter.spans("N120 G01 X12.5 I2. F180 T3 (cut)")
    names = [name for _, _, name in spans]
    assert names == [
        hl.BLOCK_NUMBER,
        hl.MOTION,
        hl.AXIS,
        hl.CENTER,
        hl.FEED,
        hl.TOOL,
        hl.COMMENT,
    ]
    # spans cover the right characters
    start, end, _ = spans[2]
    assert "N120 G01 X12.5 I2. F180 T3 (cut)"[start:end] == "X12.5"


def test_highlight_distinguishes_motion_from_prep(fanuc: Profile) -> None:
    highlighter = hl.Highlighter(fanuc)
    assert [n for _, _, n in highlighter.spans("G01")] == [hl.MOTION]
    assert [n for _, _, n in highlighter.spans("G54")] == [hl.PREP]
    assert [n for _, _, n in highlighter.spans("M08")] == [hl.MCODE]


def test_highlight_skip_percent_macro_error(fanuc: Profile) -> None:
    highlighter = hl.Highlighter(fanuc)
    assert hl.SKIP in [n for _, _, n in highlighter.spans("/N10 X1.")]
    assert hl.PERCENT in [n for _, _, n in highlighter.spans("%")]
    assert hl.MACRO in [n for _, _, n in highlighter.spans("#100=1")]
    assert hl.ERROR in [n for _, _, n in highlighter.spans("X1. ??")]


def test_highlight_cache_is_reused(fanuc: Profile) -> None:
    highlighter = hl.Highlighter(fanuc)
    first = highlighter.spans("N10 G01 X1.")
    assert highlighter.spans("N10 G01 X1.") is first


def test_highlight_cache_clears_on_profile_change(fanuc: Profile) -> None:
    highlighter = hl.Highlighter(fanuc)
    highlighter.spans("N10 G01 X1.")
    highlighter.set_profile(load_profile("siemens-iso"))
    assert highlighter._cache == {}


# --------------------------------------------------------------------------- outline


def test_outline_sections(fanuc: Profile) -> None:
    program = parse_text(POCKET.read_text(), fanuc)
    sections = build_outline(program, fanuc)
    labels = [s.label for s, _ in sections]
    assert labels == [HEADER_LABEL, "T1 ROUGH", "T12 FINISH"]
    # the naming comment is consumed by its section, not listed twice
    header_entries = [e.label for e in sections[0][1]]
    assert "T1 ROUGH" not in header_entries
    assert sections[1][0].line == 9 and sections[1][0].block == 40


def test_outline_tool_without_comment(fanuc: Profile) -> None:
    sections = build_outline(parse_text("T7 M06\nX1.\n", fanuc), fanuc)
    assert [s.label for s, _ in sections] == ["T7"]


def test_outline_comment_on_the_tool_line(fanuc: Profile) -> None:
    sections = build_outline(parse_text("T7 M06 (SPOT DRILL)\n", fanuc), fanuc)
    assert [s.label for s, _ in sections] == ["T7 SPOT DRILL"]


def test_outline_no_tools(fanuc: Profile) -> None:
    assert build_outline(parse_text("G00 X1.\n", fanuc), fanuc) == []


# --------------------------------------------------------------------------- search state


def test_search_state_cycles_and_wraps(fanuc: Profile) -> None:
    program = parse_text("F1\nF2\nF3\n", fanuc)
    state = SearchState()
    assert state.run(program, fanuc, Query(addr="F")) == 3
    assert state.position == "0/3"
    assert state.next().lineno == 1
    assert state.position == "1/3"
    assert state.next().lineno == 2
    assert state.next().lineno == 3
    assert state.next().lineno == 1  # wraps
    assert state.prev().lineno == 3  # wraps back
    state.clear()
    assert not state.active and state.position == "0/0"


def test_search_starts_from_the_cursor(fanuc: Profile) -> None:
    program = parse_text("F1\nF2\nF3\n", fanuc)
    state = SearchState()
    state.run(program, fanuc, Query(addr="F"))
    assert state.next(from_line=1).lineno == 2
    state.index = -1
    assert state.prev(from_line=2).lineno == 2


def test_search_refresh_keeps_position(fanuc: Profile) -> None:
    state = SearchState()
    state.run(parse_text("F1\nF2\nF3\n", fanuc), fanuc, Query(addr="F"))
    state.next()
    state.next()  # on F2
    state.refresh(parse_text("F1\nF2\nF3\nF4\n", fanuc), fanuc)
    assert state.count == 4
    assert state.current.lineno == 2


def test_search_refresh_when_match_disappears(fanuc: Profile) -> None:
    state = SearchState()
    state.run(parse_text("F1\nF2\n", fanuc), fanuc, Query(addr="F"))
    state.next()
    state.refresh(parse_text("X1\n", fanuc), fanuc)
    assert state.count == 0 and state.current is None


def test_matches_on_line(fanuc: Profile) -> None:
    state = SearchState()
    state.run(parse_text("F1 F2\nF3\n", fanuc), fanuc, Query(addr="F"))
    assert len(state.matches_on(0)) == 2
    assert len(state.matches_on(1)) == 1


# --------------------------------------------------------------------------- inspector


def test_word_at_column(fanuc: Profile) -> None:
    line = parse_text("N120 G01 X12.5 Z-0.2", fanuc).lines[0]
    assert word_at(line, 0).addr == "N"
    assert word_at(line, 6).addr == "G"
    assert word_at(line, 10).addr == "X"
    assert word_at(line, 13).addr == "X"  # inside the value
    assert word_at(line, 8).addr == "G"  # on the space: the word before
    assert word_at(line, 99).addr == "Z"  # past the end


def test_word_at_on_empty_line(fanuc: Profile) -> None:
    assert word_at(parse_text("\n", fanuc).lines[0], 0) is None


# --------------------------------------------------------------------------- the app


async def test_app_opens_and_reports_state(work: Path) -> None:
    app = NctabApp(path=work)
    async with app.run_test():
        assert app.editor.document.line_count == 56
        assert "pocket.nc" in app.sub_title
        assert "fanuc-mill" in app.sub_title
        assert app.modified is False
        assert [str(c.label) for c in app.outline.root.children] == [
            HEADER_LABEL,
            "T1 ROUGH",
            "T12 FINISH",
        ]


async def test_app_highlights_the_rendered_line(work: Path) -> None:
    app = NctabApp(path=work)
    async with app.run_test():
        line = app.editor.get_line(5)
        assert line.plain == "N10 G21 G17 G40 G49 G80 G90"
        assert len(line.spans) == 7  # one per word


async def test_tool_navigation(work: Path) -> None:
    app = NctabApp(path=work)
    async with app.run_test():
        editor = app.editor
        editor.goto_line(1)
        assert editor.next_tool() and editor.cursor_location[0] == 9
        assert editor.next_tool() and editor.cursor_location[0] == 32
        assert editor.next_tool() and editor.cursor_location[0] == 9  # wraps
        assert editor.prev_tool() and editor.cursor_location[0] == 32  # wraps back


async def test_mode_navigation(work: Path) -> None:
    app = NctabApp(path=work)
    async with app.run_test():
        editor = app.editor
        editor.goto_line(1)
        assert editor.next_mode()
        first = editor.cursor_location[0]
        assert editor.next_mode() and editor.cursor_location[0] > first


async def test_goto_line_and_block(work: Path) -> None:
    app = NctabApp(path=work)
    async with app.run_test():
        editor = app.editor
        editor.goto_line(12)
        assert editor.cursor_location[0] == 11
        assert editor.goto_block(120)
        assert editor.program.lines[editor.cursor_location[0]].block_number == 120
        assert editor.goto_block(99999) is False


async def test_bookmarks(work: Path) -> None:
    app = NctabApp(path=work)
    async with app.run_test():
        editor = app.editor
        editor.goto_line(20)
        assert editor.set_bookmark("a")
        editor.goto_line(1)
        assert editor.goto_bookmark("a")
        assert editor.cursor_location[0] == 19
        assert editor.goto_bookmark("z") is False
        assert editor.set_bookmark("A") is False


async def test_search_in_the_app(work: Path) -> None:
    app = NctabApp(path=work)
    async with app.run_test():
        editor = app.editor
        editor.goto_line(1)
        count = editor.search.run(editor.program, app.profile, Query(addr="F"))
        assert count == 4
        match = editor.find_next()
        assert match is not None and match.text == "F300"
        assert editor.cursor_location[0] == match.line
        assert editor.search.position == "1/4"


async def test_search_marks_are_drawn(work: Path) -> None:
    app = NctabApp(path=work)
    async with app.run_test():
        editor = app.editor
        editor.search.run(editor.program, app.profile, Query(addr="F"))
        editor.find_next()
        current = editor.search.current
        line = editor.get_line(current.line)
        # the match adds a span on top of the syntax highlighting
        assert any(s.start == current.col for s in line.spans)


async def test_function_key_navigation(work: Path) -> None:
    app = NctabApp(path=work)
    async with app.run_test() as pilot:
        editor = app.editor
        editor.goto_line(1)
        editor.focus()
        await pilot.press("f4")
        await pilot.pause()
        assert editor.cursor_location[0] == 9
        await pilot.press("f4")
        await pilot.pause()
        assert editor.cursor_location[0] == 32
        await pilot.press("shift+f4")
        await pilot.pause()
        assert editor.cursor_location[0] == 9


async def test_brackets_still_type_into_the_program(work: Path) -> None:
    """A bare "]" must reach the buffer: the editor is always in insert mode."""
    app = NctabApp(path=work)
    async with app.run_test() as pilot:
        editor = app.editor
        editor.goto_line(1)
        editor.focus()
        await pilot.press("]", "[", "m")
        await pilot.pause()
        assert editor.document.get_line(0).startswith("][m")


async def test_bookmark_prompt(work: Path) -> None:
    app = NctabApp(path=work)
    async with app.run_test() as pilot:
        editor = app.editor
        editor.goto_line(20)
        editor.focus()
        await pilot.press("ctrl+b")
        await pilot.pause()
        assert editor.pending_prefix == "mark"
        await pilot.press("a")
        await pilot.pause()
        assert editor.bookmarks == {"a": 19}
        # the letter was swallowed, not typed
        assert "a" not in editor.document.get_line(19)[:1]
        editor.goto_line(1)
        await pilot.press("ctrl+j")
        await pilot.pause()
        await pilot.press("a")
        await pilot.pause()
        assert editor.cursor_location[0] == 19


async def test_renumber_through_the_app(work: Path) -> None:
    app = NctabApp(path=work)
    async with app.run_test():
        app.apply_op(
            renumber(app.editor.program, RenumberSpec(start=1000, step=5), app.profile),
            "renumber",
        )
        assert "N1000 G21" in app.editor.text
        assert app.modified is True
        # the outline survived the rewrite
        assert len(app.outline.root.children) == 3


async def test_transform_through_the_app(work: Path) -> None:
    app = NctabApp(path=work)
    async with app.run_test():
        app.apply_transform(TransformRequest(kind="shift", values={"Z": Decimal("-0.02")}))
        assert "Z-3.02 F300" in app.editor.text
        assert app.modified is True


async def test_transform_reports_nothing_to_change(work: Path) -> None:
    app = NctabApp(path=work)
    async with app.run_test():
        app.apply_transform(TransformRequest(kind="shift", values={"Z": Decimal(0)}))
        assert "nothing to change" in app.status.message
        assert app.modified is False


async def test_save_writes_and_clears_modified(work: Path) -> None:
    app = NctabApp(path=work)
    async with app.run_test():
        app.apply_transform(TransformRequest(kind="shift", values={"Z": Decimal("-0.02")}))
        assert app.modified is True
        app.action_save()
        assert app.modified is False
        assert "Z-3.02 F300" in work.read_text()


async def test_inspector_describes_the_word_under_the_cursor(work: Path) -> None:
    app = NctabApp(path=work)
    async with app.run_test() as pilot:
        editor = app.editor
        editor.goto_line(15)  # N90 G01 Z-3. F300
        await pilot.pause()
        app.refresh_inspector()
        state = app.current_state()
        assert state is not None
        assert state.tool == 1
        assert state.feed is not None


async def test_spindle_indicator_follows_the_cursor(work: Path) -> None:
    app = NctabApp(path=work)
    async with app.run_test() as pilot:
        indicator = app.query_one("#inspector-spindle", SpindleIndicator)
        for line, cls, label in (
            (10, "-off", "■ STOP"),  # N40 T1 M06: not started yet
            (15, "-cw", "↻ CW  S4500"),  # N90 G01 Z-3. F300
            (29, "-off", "■ STOP  S4500"),  # N230 M05
        ):
            app.editor.goto_line(line)
            await pilot.pause()
            app.refresh_inspector()
            assert indicator.has_class(cls)
            assert label in str(indicator.content)


async def test_opening_a_missing_file_is_reported(tmp_path: Path) -> None:
    app = NctabApp(path=tmp_path / "nope.nc")
    async with app.run_test():
        assert app.editor.document.line_count == 1  # empty buffer, no crash


def test_app_bindings_never_shadow_the_editor() -> None:
    """Regression guard: TextArea already owns f6, f7 and the usual edit keys.

    A binding that the editor consumes would silently do the wrong thing, which
    is how f7 once selected the whole document instead of jumping to a tool.
    """

    def keys(bindings) -> set[str]:
        out: set[str] = set()
        for binding in bindings:
            for key in str(getattr(binding, "key", binding)).split(","):
                out.add(key.strip())
        return out

    editor_keys = keys(TextArea.BINDINGS)
    ours = keys(NctabApp.BINDINGS)
    # ctrl+q is the App's own quit, which we deliberately re-declare
    assert (ours & editor_keys) - {"ctrl+q"} == set()


def test_no_binding_is_a_plain_character() -> None:
    """The editor is always in insert mode, so bindings must not eat typing."""
    for binding in NctabApp.BINDINGS:
        for raw in str(getattr(binding, "key", binding)).split(","):
            key = raw.strip()
            assert len(key) > 1, f"{key!r} would be swallowed instead of typed"
