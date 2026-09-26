"""File explorer for the left panel.

Shows the folder of G-code programs: directories plus files whose suffix looks
like NC. Hidden entries and the tool's own artefacts (``.bak``, ``.tmp``) stay
out of the way, because a shop folder is full of them.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from textual.message import Message
from textual.widgets import DirectoryTree

NC_SUFFIXES: frozenset[str] = frozenset(
    {
        ".nc",
        ".ngc",
        ".gcode",
        ".g",
        ".tap",
        ".cnc",
        ".mpf",
        ".spf",
        ".eia",
        ".iso",
        ".min",
        ".prg",
        ".pgm",
        ".anc",
        ".fnc",
        ".dnc",
        ".txt",
    }
)

HIDDEN_SUFFIXES: frozenset[str] = frozenset({".bak", ".tmp"})


def looks_like_nc(path: Path) -> bool:
    """Whether the explorer should offer this file."""
    suffix = path.suffix.lower()
    return suffix in NC_SUFFIXES and suffix not in HIDDEN_SUFFIXES


def nc_files(directory: Path) -> list[Path]:
    """NC files directly in ``directory``, sorted by name. Never raises."""
    try:
        entries = list(directory.iterdir())
    except OSError:
        return []
    return sorted((p for p in entries if p.is_file() and looks_like_nc(p)), key=lambda p: p.name)


class Explorer(DirectoryTree):
    """A directory tree limited to NC programs.

    Emits ``Explorer.Open`` when a file is chosen, so the app decides what to do
    about unsaved changes rather than the widget.
    """

    class Open(Message):
        def __init__(self, path: Path) -> None:
            super().__init__()
            self.path = path

    def __init__(self, root: Path, **kwargs) -> None:
        super().__init__(str(root), **kwargs)
        self.guide_depth = 2

    def filter_paths(self, paths: Iterable[Path]) -> Iterable[Path]:
        for path in paths:
            if path.name.startswith("."):
                continue
            if path.is_dir() or looks_like_nc(path):
                yield path

    def change_root(self, root: Path) -> None:
        self.path = str(root)
        self.reload()

    def on_directory_tree_file_selected(self, event: DirectoryTree.FileSelected) -> None:
        event.stop()
        self.post_message(self.Open(Path(event.path)))
