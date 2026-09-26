"""Command palette (goal.md section 5.2).

Textual's own palette is driven by a provider, so ``Ctrl+P`` lists the same
actions the key bindings reach, and is the discoverable path to anything that
has no dedicated key.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import partial

from textual.command import DiscoveryHit, Hit, Hits, Provider


@dataclass(frozen=True, slots=True)
class Command:
    text: str
    """What the palette shows."""
    action: str
    """Name of the ``action_*`` method on the app."""
    binding: str = ""
    """Key that also runs it, shown as a hint."""


COMMANDS: tuple[Command, ...] = (
    Command("Find in the program", "find", "Ctrl+F"),
    Command("Replace values in bulk", "replace", "Ctrl+H"),
    Command("Go to a line or block", "goto", "Ctrl+G"),
    Command("Jump to the next tool change", "next_tool", "F4"),
    Command("Jump to the previous tool change", "prev_tool", "Shift+F4"),
    Command("Renumber blocks", "renumber", "Ctrl+N"),
    Command("Shift, scale, mirror or rotate", "transform", "Ctrl+T"),
    Command("Insert a snippet", "snippet", "F2"),
    Command("Check the program for problems", "check", ""),
    Command("Save the file", "save", "Ctrl+S"),
    Command("Show the file list", "toggle_side", "F9"),
)


class NctabCommands(Provider):
    """Offers every nctab action to the command palette."""

    def _runner(self, command: Command):
        return getattr(self.app, f"action_{command.action}", None)

    async def discover(self) -> Hits:
        """What the palette shows before anything is typed."""
        for command in COMMANDS:
            runner = self._runner(command)
            if runner is None:
                continue
            yield DiscoveryHit(command.text, partial(_run, runner), help=command.binding or None)

    async def search(self, query: str) -> Hits:
        matcher = self.matcher(query)
        for command in COMMANDS:
            score = matcher.match(command.text)
            if not score:
                continue
            runner = self._runner(command)
            if runner is None:
                continue
            yield Hit(
                score,
                matcher.highlight(command.text),
                partial(_run, runner),
                help=command.binding or None,
            )


def _run(action) -> None:
    """Palette callbacks must not return the worker an action may hand back."""
    action()
