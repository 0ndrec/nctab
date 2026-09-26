"""NC-aware comparison (goal.md §6.4)."""

from nctab.diff.compare import (
    DiffReport,
    DiffResult,
    Hunk,
    Row,
    build_report,
    diff_programs,
    unified,
)
from nctab.diff.normalize import DiffOptions, comparable, normalize, normalize_line

__all__ = [
    "DiffOptions",
    "DiffReport",
    "DiffResult",
    "Hunk",
    "Row",
    "build_report",
    "comparable",
    "diff_programs",
    "normalize",
    "normalize_line",
    "unified",
]
