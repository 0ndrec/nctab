"""Architecture guard (goal.md §10): dependencies only point downward.

tui / cli / app
    ↓
ops / check / diff / dnc
    ↓
core
    ↓
profiles + geom (+ errors)
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

SRC = Path(__file__).parent.parent / "src" / "nctab"

LAYER: dict[str, int] = {
    "errors": 0,
    "profiles": 0,
    "geom": 0,
    "core": 1,
    "ops": 2,
    "check": 2,
    "diff": 2,
    "dnc": 2,
    "snippets": 2,
    "config": 2,
    "tui": 3,
    "app": 3,
    "cli": 3,
}


def _layer_of(module: str) -> int | None:
    parts = module.split(".")
    if parts[0] != "nctab" or len(parts) == 1:
        return None
    return LAYER.get(parts[1])


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            out.add(node.module)
    return out


def _module_name(path: Path) -> str:
    rel = path.relative_to(SRC.parent).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


ALL_SOURCES = sorted(p for p in SRC.rglob("*.py"))


@pytest.mark.parametrize("path", ALL_SOURCES, ids=lambda p: str(p.relative_to(SRC)))
def test_no_upward_imports(path: Path) -> None:
    me = _module_name(path)
    my_layer = _layer_of(me)
    if my_layer is None:
        return  # nctab/__init__.py
    for imp in _imports(path):
        their = _layer_of(imp)
        if their is None:
            continue
        assert their <= my_layer, f"{me} (layer {my_layer}) imports {imp} (layer {their})"


def test_core_and_ops_do_not_use_float() -> None:
    """Rule 3 of PLAN.md: no float in core/ops; geom and stats may use it internally."""
    pattern = re.compile(r"\bfloat\(")
    offenders = [
        str(p.relative_to(SRC))
        for sub in ("core", "ops")
        for p in (SRC / sub).rglob("*.py")
        if pattern.search(p.read_text(encoding="utf-8"))
    ]
    assert offenders == []
