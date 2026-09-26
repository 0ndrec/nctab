"""Modal dialogs (goal.md section 5.2).

Every dialog returns a spec; the app applies it through ``ops.*`` so the TUI
never duplicates transform logic (goal.md section 10). Find and replace live in
``search_dialog.py``, which needs more room than the rest.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Input, Label, Select, Static
from textual.widgets._select import NoSelection

from nctab.ops.renumber import RenumberSpec


def chosen(select: Select) -> str | None:
    """The selected option, or ``None`` when the dropdown is still blank.

    Textual's blank sentinel is ``Select.NULL`` (an instance of ``NoSelection``);
    ``Select.BLANK`` is a plain ``False`` and comparing against it silently
    treats "nothing chosen" as a real value.
    """
    value = select.value
    if value is None or isinstance(value, NoSelection):
        return None
    return str(value)


def _decimal(text: str) -> Decimal | None:
    text = text.strip()
    if not text:
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


class NcDialog(ModalScreen):
    """Common chrome: a titled box, Escape to cancel."""

    BINDINGS = [("escape", "dismiss_dialog", "Cancel")]

    def __init__(self, title: str) -> None:
        super().__init__()
        self.dialog_title = title

    def action_dismiss_dialog(self) -> None:
        self.dismiss(None)


# --------------------------------------------------------------------------- goto


class GotoDialog(NcDialog):
    """``123`` for a line, ``N120`` for a block number."""

    def __init__(self) -> None:
        super().__init__("Go to")

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label("Go to line or block", classes="dialog-title")
            yield Input(placeholder="123 or N120", id="goto-target")
            yield Static("Enter jumps, Escape cancels", classes="dialog-hint")

    def on_mount(self) -> None:
        self.query_one("#goto-target", Input).focus()

    @on(Input.Submitted)
    def submit(self, event: Input.Submitted) -> None:
        self.dismiss(event.value.strip())


# --------------------------------------------------------------------------- find


# --------------------------------------------------------------------------- replace


# --------------------------------------------------------------------------- renumber


class RenumberDialog(NcDialog):
    def __init__(self) -> None:
        super().__init__("Renumber")

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label("Renumber blocks", classes="dialog-title")
            with Horizontal(classes="dialog-row"):
                yield Label("Start", classes="dialog-label")
                yield Input(value="10", id="ren-start", classes="narrow")
                yield Label("Step", classes="dialog-label")
                yield Input(value="10", id="ren-step", classes="narrow")
                yield Label("Width", classes="dialog-label")
                yield Input(value="0", id="ren-width", classes="narrow")
            with Horizontal(classes="dialog-row"):
                yield Checkbox("Number comment lines", id="ren-comments")
                yield Checkbox("Remove numbers instead", id="ren-strip")
            with Horizontal(classes="dialog-row"):
                yield Button("Apply", variant="primary", id="ren-ok")
                yield Button("Cancel", id="ren-cancel")

    def on_mount(self) -> None:
        self.query_one("#ren-start", Input).focus()

    @on(Button.Pressed, "#ren-cancel")
    def cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#ren-ok")
    def submit(self) -> None:
        def number(widget_id: str, fallback: int) -> int:
            try:
                return int(self.query_one(widget_id, Input).value.strip() or fallback)
            except ValueError:
                return fallback

        step = number("#ren-step", 10)
        if step <= 0:
            self.notify("Step must be positive", severity="error")
            return
        self.dismiss(
            RenumberSpec(
                start=number("#ren-start", 10),
                step=step,
                width=number("#ren-width", 0),
                number_comments=self.query_one("#ren-comments", Checkbox).value,
                strip=self.query_one("#ren-strip", Checkbox).value,
            )
        )


# --------------------------------------------------------------------------- transform


@dataclass(frozen=True, slots=True)
class TransformRequest:
    kind: str  # shift | scale | mirror | rotate | feeds
    values: dict[str, Decimal]
    axis: str = "X"
    also_incremental: bool = False


class TransformDialog(NcDialog):
    """One form for the geometric transforms; the app turns it into an ``ops`` spec."""

    KINDS = [("Shift", "shift"), ("Scale", "scale"), ("Mirror", "mirror"), ("Rotate", "rotate")]

    def __init__(self, axes: list[str]) -> None:
        super().__init__("Transform")
        self.axes = axes

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog dialog-wide"):
            yield Label("Transform", classes="dialog-title")
            yield Select(self.KINDS, value="shift", allow_blank=False, id="tr-kind")
            with VerticalScroll(id="tr-fields"):
                with Horizontal(classes="dialog-row"):
                    yield Label("X", classes="dialog-label")
                    yield Input(placeholder="0", id="tr-x", classes="narrow")
                    yield Label("Y", classes="dialog-label")
                    yield Input(placeholder="0", id="tr-y", classes="narrow")
                    yield Label("Z", classes="dialog-label")
                    yield Input(placeholder="0", id="tr-z", classes="narrow")
                with Horizontal(classes="dialog-row", id="tr-extra"):
                    yield Label("Factor / degrees", classes="dialog-label")
                    yield Input(placeholder="1.0", id="tr-amount", classes="narrow")
                    yield Label("Axis", classes="dialog-label")
                    yield Select(
                        [(a, a) for a in self.axes],
                        value=self.axes[0] if self.axes else "X",
                        allow_blank=False,
                        id="tr-axis",
                    )
                yield Checkbox("Also incremental blocks", id="tr-incremental")
            with Horizontal(classes="dialog-row"):
                yield Button("Apply", variant="primary", id="tr-ok")
                yield Button("Cancel", id="tr-cancel")

    def on_mount(self) -> None:
        self.query_one("#tr-x", Input).focus()

    @on(Button.Pressed, "#tr-cancel")
    def cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#tr-ok")
    def submit(self) -> None:
        kind = chosen(self.query_one("#tr-kind", Select)) or "shift"
        values: dict[str, Decimal] = {}
        for axis in ("x", "y", "z"):
            v = _decimal(self.query_one(f"#tr-{axis}", Input).value)
            if v is not None:
                values[axis.upper()] = v
        amount = _decimal(self.query_one("#tr-amount", Input).value)
        if kind in ("scale", "rotate"):
            if amount is None:
                self.notify(
                    "Give a factor" if kind == "scale" else "Give an angle", severity="error"
                )
                return
            values["amount"] = amount
        elif kind == "shift" and not values:
            self.notify("Give at least one axis offset", severity="error")
            return
        self.dismiss(
            TransformRequest(
                kind=kind,
                values=values,
                axis=chosen(self.query_one("#tr-axis", Select)) or "X",
                also_incremental=self.query_one("#tr-incremental", Checkbox).value,
            )
        )
