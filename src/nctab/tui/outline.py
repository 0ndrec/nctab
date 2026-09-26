"""Program outline: tool sections and label comments (goal.md §5.2)."""

from __future__ import annotations

from dataclasses import dataclass

from textual.message import Message
from textual.widgets import Tree
from textual.widgets.tree import TreeNode

from nctab.core.model import LineKind, Program
from nctab.core.state import g_int
from nctab.profiles.loader import Profile

_MIN_LABEL_LENGTH = 3
_LOOK_BACK = 3
HEADER_LABEL = "(header)"


@dataclass(frozen=True, slots=True)
class OutlineEntry:
    line: int  # 0-based
    label: str
    block: int | None = None


Section = tuple[OutlineEntry, list[OutlineEntry]]


def _clean(comment: str) -> str:
    return comment.strip("();").strip("- ").strip()


def build_outline(program: Program, profile: Profile) -> list[Section]:
    """Tool sections, each with the label comments inside it.

    A comment just above a tool change names that tool, so it becomes the
    section's label instead of a separate entry. Lines before the first tool
    change go into a leading header section, so nothing is unreachable.
    """
    t_addr = profile.tool_word
    sections: list[Section] = []
    current: list[OutlineEntry] | None = None
    last_tool: int | None = None

    for line in program.lines:
        word = line.word(t_addr)
        tool = g_int(word) if word is not None else None

        if tool is not None and tool != last_tool:
            last_tool = tool
            name = _clean(line.comment or "")
            if not name and current is not None:
                name = _take_label_above(current, line.index)
            current = []
            sections.append(
                (OutlineEntry(line.index, _format(tool, name), line.block_number), current)
            )
            continue

        if line.kind is LineKind.COMMENT:
            inner = _clean(line.comment or "")
            if len(inner) >= _MIN_LABEL_LENGTH:
                if current is None:
                    current = []
                    sections.append((OutlineEntry(0, HEADER_LABEL), current))
                current.append(OutlineEntry(line.index, inner, line.block_number))

    return sections


def _take_label_above(entries: list[OutlineEntry], index: int) -> str:
    """Consume the nearest label comment just above ``index``, if there is one."""
    if entries and 0 < index - entries[-1].line <= _LOOK_BACK:
        return entries.pop().label
    return ""


def _format(tool: int, name: str) -> str:
    """``T12 FINISH`` — never ``T12 T12 FINISH``."""
    if not name:
        return f"T{tool}"
    words = name.split()
    if words and words[0].upper() == f"T{tool}":
        name = " ".join(words[1:])
    return f"T{tool} {name}".strip()


class Outline(Tree[OutlineEntry]):
    """Clicking a node moves the editor to that line."""

    class Selected(Message):
        def __init__(self, line: int) -> None:
            super().__init__()
            self.line = line

    def __init__(self, **kwargs) -> None:
        super().__init__("Program", **kwargs)
        self.show_root = False
        self.guide_depth = 2

    def rebuild(self, program: Program, profile: Profile) -> None:
        self.clear()
        sections = build_outline(program, profile)
        if not sections:
            self.root.add_leaf("(no tool changes)", data=OutlineEntry(0, ""))
            return
        for section, labels in sections:
            node: TreeNode[OutlineEntry] = self.root.add(section.label, data=section, expand=True)
            for label in labels:
                node.add_leaf(label.label, data=label)

    def on_tree_node_selected(self, event: Tree.NodeSelected[OutlineEntry]) -> None:
        event.stop()
        if event.node.data is not None:
            self.post_message(self.Selected(event.node.data.line))
