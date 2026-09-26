"""Go to, renumber and transform dialogs. Find and replace live in test_search_dialog.py."""

from __future__ import annotations

import shutil
from decimal import Decimal
from pathlib import Path

import pytest
from textual import work
from textual.app import App, ComposeResult
from textual.widgets import Button, Checkbox, Input, Select

from nctab.app import NctabApp
from nctab.ops.renumber import RenumberSpec
from nctab.tui.dialogs import (
    GotoDialog,
    RenumberDialog,
    TransformDialog,
    TransformRequest,
)
from tests.conftest import GOLDEN_DIR

POCKET = GOLDEN_DIR / "pocket.nc"


@pytest.fixture
def program_file(tmp_path: Path) -> Path:
    dst = tmp_path / "pocket.nc"
    shutil.copy(POCKET, dst)
    return dst


class Host(App[None]):
    """Minimal host so a dialog can be pushed without the whole editor.

    ``push_screen_wait`` has to run inside a worker, which is also how the real
    app drives its dialogs.
    """

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


async def press_button(app, pilot, selector: str) -> None:
    """Press a dialog button by id.

    ``pilot.click`` needs the target to be inside the visible region, which makes
    the test depend on the terminal size; pressing the widget does not.
    """
    screen = app.dialog if isinstance(app, Host) else app.screen
    screen.query_one(selector, Button).press()
    await pilot.pause()
    await pilot.pause()


async def ready(app: Host, pilot) -> None:
    """Wait until the worker has pushed the dialog and its widgets exist."""
    for _ in range(40):
        await pilot.pause()
        if app.dialog.is_mounted and app.dialog.children:
            await pilot.pause()
            return
    raise AssertionError("dialog never mounted")


# --------------------------------------------------------------------------- goto


async def test_goto_dialog_returns_the_text() -> None:
    app = Host(GotoDialog())
    async with app.run_test() as pilot:
        await ready(app, pilot)
        app.dialog.query_one("#goto-target", Input).value = "N120"
        await pilot.press("enter")
        await pilot.pause()
    assert app.result == "N120"


async def test_goto_dialog_escape_cancels() -> None:
    app = Host(GotoDialog())
    async with app.run_test() as pilot:
        await ready(app, pilot)
        await pilot.press("escape")
        await pilot.pause()
    assert app.result is None


# --------------------------------------------------------------------------- renumber


async def test_renumber_dialog() -> None:
    app = Host(RenumberDialog())
    async with app.run_test() as pilot:
        await ready(app, pilot)
        app.dialog.query_one("#ren-start", Input).value = "100"
        app.dialog.query_one("#ren-step", Input).value = "5"
        app.dialog.query_one("#ren-width", Input).value = "4"
        app.dialog.query_one("#ren-comments", Checkbox).value = True
        await press_button(app, pilot, "#ren-ok")
        await pilot.pause()
    assert isinstance(app.result, RenumberSpec)
    assert (app.result.start, app.result.step, app.result.width) == (100, 5, 4)
    assert app.result.number_comments is True


async def test_renumber_dialog_rejects_zero_step() -> None:
    app = Host(RenumberDialog())
    async with app.run_test() as pilot:
        await ready(app, pilot)
        app.dialog.query_one("#ren-step", Input).value = "0"
        await press_button(app, pilot, "#ren-ok")
        await pilot.pause()
        assert app.result == "unset"  # still open
        await pilot.press("escape")
        await pilot.pause()
    assert app.result is None


async def test_renumber_dialog_bad_input_falls_back() -> None:
    app = Host(RenumberDialog())
    async with app.run_test() as pilot:
        await ready(app, pilot)
        app.dialog.query_one("#ren-start", Input).value = "abc"
        await press_button(app, pilot, "#ren-ok")
        await pilot.pause()
    assert isinstance(app.result, RenumberSpec)
    assert app.result.start == 10  # the default, not a crash


# --------------------------------------------------------------------------- transform


async def test_transform_dialog_shift() -> None:
    app = Host(TransformDialog(["X", "Y", "Z"]))
    async with app.run_test() as pilot:
        await ready(app, pilot)
        app.dialog.query_one("#tr-z", Input).value = "-0.02"
        await press_button(app, pilot, "#tr-ok")
        await pilot.pause()
    assert isinstance(app.result, TransformRequest)
    assert app.result.kind == "shift"
    assert app.result.values == {"Z": Decimal("-0.02")}


async def test_transform_dialog_shift_needs_an_offset() -> None:
    app = Host(TransformDialog(["X", "Y", "Z"]))
    async with app.run_test() as pilot:
        await ready(app, pilot)
        await press_button(app, pilot, "#tr-ok")
        await pilot.pause()
        assert app.result == "unset"
        await pilot.press("escape")
        await pilot.pause()
    assert app.result is None


async def test_transform_dialog_rotate_needs_an_angle() -> None:
    app = Host(TransformDialog(["X", "Y", "Z"]))
    async with app.run_test() as pilot:
        await ready(app, pilot)
        app.dialog.query_one("#tr-kind", Select).value = "rotate"
        await pilot.pause()
        await press_button(app, pilot, "#tr-ok")
        await pilot.pause()
        assert app.result == "unset"
        app.dialog.query_one("#tr-amount", Input).value = "90"
        await press_button(app, pilot, "#tr-ok")
        await pilot.pause()
    assert isinstance(app.result, TransformRequest)
    assert app.result.kind == "rotate"
    assert app.result.values["amount"] == Decimal(90)


async def test_transform_dialog_mirror_axis() -> None:
    app = Host(TransformDialog(["X", "Y", "Z"]))
    async with app.run_test() as pilot:
        await ready(app, pilot)
        app.dialog.query_one("#tr-kind", Select).value = "mirror"
        await pilot.pause()
        app.dialog.query_one("#tr-axis", Select).value = "Y"
        await press_button(app, pilot, "#tr-ok")
        await pilot.pause()
    assert isinstance(app.result, TransformRequest)
    assert app.result.kind == "mirror" and app.result.axis == "Y"


# --------------------------------------------------------------------------- end to end


async def test_goto_through_the_app(program_file: Path) -> None:
    app = NctabApp(path=program_file)
    async with app.run_test() as pilot:
        app.action_goto()
        await pilot.pause()
        app.screen.query_one("#goto-target", Input).value = "N120"
        await pilot.press("enter")
        await pilot.pause()
        line = app.editor.program.lines[app.editor.cursor_location[0]]
        assert line.block_number == 120
        assert "N120" in app.status.message


async def test_goto_rejects_nonsense(program_file: Path) -> None:
    app = NctabApp(path=program_file)
    async with app.run_test() as pilot:
        app.action_goto()
        await pilot.pause()
        app.screen.query_one("#goto-target", Input).value = "banana"
        await pilot.press("enter")
        await pilot.pause()
        assert "cannot parse" in app.status.message


async def test_transform_through_the_dialog(program_file: Path) -> None:
    app = NctabApp(path=program_file)
    async with app.run_test() as pilot:
        app.action_transform()
        await pilot.pause()
        app.screen.query_one("#tr-z", Input).value = "-0.02"
        await press_button(app, pilot, "#tr-ok")
        await pilot.pause()
        assert "Z-3.02 F300" in app.editor.text


async def test_renumber_through_the_dialog(program_file: Path) -> None:
    app = NctabApp(path=program_file)
    async with app.run_test() as pilot:
        app.action_renumber()
        await pilot.pause()
        app.screen.query_one("#ren-start", Input).value = "1000"
        app.screen.query_one("#ren-step", Input).value = "1"
        await press_button(app, pilot, "#ren-ok")
        await pilot.pause()
        assert "N1000 G21" in app.editor.text
