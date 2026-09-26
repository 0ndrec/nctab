"""Diagnostic model and the stable JSON report schema (goal.md §6.3)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

Severity = Literal["error", "warning", "info"]
_ORDER: dict[str, int] = {"error": 0, "warning": 1, "info": 2}


class Diagnostic(BaseModel):
    model_config = ConfigDict(frozen=True)

    line: int
    """1-based line number; 0 for whole-program findings."""
    severity: Severity
    code: str
    """Stable kebab-case identifier, e.g. ``unclosed-comment``."""
    message: str
    block: int | None = None
    text: str = ""
    """The source line, for context."""

    @property
    def sort_key(self) -> tuple[int, int, str]:
        return (self.line, _ORDER[self.severity], self.code)


class CheckReport(BaseModel):
    """JSON-stable report. Fields may be added; never renamed or removed."""

    model_config = ConfigDict(frozen=True)

    schema_version: int = 1
    file: str | None = None
    profile: str
    lines: int
    diagnostics: list[Diagnostic]
    errors: int
    warnings: int
    infos: int

    @property
    def ok(self) -> bool:
        return self.errors == 0

    @classmethod
    def build(
        cls, diagnostics: list[Diagnostic], *, profile: str, lines: int, file: str | None = None
    ) -> CheckReport:
        ordered = sorted(diagnostics, key=lambda d: d.sort_key)
        counts = {s: 0 for s in ("error", "warning", "info")}
        for d in ordered:
            counts[d.severity] += 1
        return cls(
            file=file,
            profile=profile,
            lines=lines,
            diagnostics=ordered,
            errors=counts["error"],
            warnings=counts["warning"],
            infos=counts["info"],
        )
