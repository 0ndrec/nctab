"""Snippet catalogue (goal.md section 6.5).

A snippet is a TOML file with named fields and a body. Placeholders in the body
are ``{Name}``; a field may also carry ``format`` to control how its value is
written (``"02d"`` gives ``T07``).

Search order, later shadowing earlier by id:

1. built-in ``nctab/snippets/<profile-id>/*.toml``
2. built-in ``nctab/snippets/common/*.toml``
3. ``<user config dir>/nctab/snippets/<profile-id>/*.toml``
4. ``<user config dir>/nctab/snippets/*.toml``
"""

from __future__ import annotations

import tomllib
from collections.abc import Iterator
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from importlib import resources
from pathlib import Path
from typing import Literal

from platformdirs import user_config_path
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from nctab.errors import ProgramError

COMMON = "common"
FieldType = Literal["int", "float", "str", "choice"]


class SnippetField(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    label: str = ""
    type: FieldType = "str"
    default: str | int | float | None = None
    min: float | None = None
    max: float | None = None
    choices: list[str] = Field(default_factory=list)
    format: str = ""
    """Python format spec applied to the value, e.g. ``02d`` for ``T07``."""

    def model_post_init(self, _context: object) -> None:
        if not self.label:
            object.__setattr__(self, "label", self.name)

    def coerce(self, raw: str | int | float | None) -> str:
        """Validate a user-entered value and render it for the body."""
        if raw is None or raw == "":
            if self.default is None:
                raise ProgramError(f"{self.label}: a value is required")
            raw = self.default

        if self.type == "int":
            value: object = _as_int(raw, self.label)
        elif self.type == "float":
            value = _as_decimal(raw, self.label)
        else:
            value = str(raw)
            if self.type == "choice" and self.choices and value not in self.choices:
                allowed = ", ".join(self.choices)
                raise ProgramError(f"{self.label}: {value!r} is not one of {allowed}")

        if self.type in ("int", "float"):
            numeric = Decimal(str(value))
            if self.min is not None and numeric < Decimal(str(self.min)):
                raise ProgramError(f"{self.label}: must be at least {self.min}")
            if self.max is not None and numeric > Decimal(str(self.max)):
                raise ProgramError(f"{self.label}: must be at most {self.max}")

        if self.format:
            try:
                return format(value, self.format)
            except (ValueError, TypeError) as e:
                raise ProgramError(f"{self.label}: cannot format {value!r}: {e}") from e
        if isinstance(value, Decimal):
            return _nc_number(value)
        return str(value)


def _nc_number(value: Decimal) -> str:
    """Write a decimal the way a post does: ``-10.`` rather than ``-10.0`` or ``-10``.

    The trailing dot matters: on some controls a bare ``Z-10`` is read in the
    least significant increment, which would be a hundredth of the intended move.
    """
    text = f"{value:f}"
    if "." not in text:
        return text + "."
    text = text.rstrip("0")
    return text


def _as_int(raw: object, label: str) -> int:
    try:
        return int(str(raw).strip())
    except ValueError as e:
        raise ProgramError(f"{label}: {raw!r} is not a whole number") from e


def _as_decimal(raw: object, label: str) -> Decimal:
    try:
        return Decimal(str(raw).strip())
    except InvalidOperation as e:
        raise ProgramError(f"{label}: {raw!r} is not a number") from e


class Snippet(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    title: str
    description: str = ""
    profile: str = ""
    """Profile id this snippet belongs to; empty means any."""
    fields: list[SnippetField] = Field(default_factory=list)
    body: str

    @property
    def field_names(self) -> list[str]:
        return [f.name for f in self.fields]

    def render(self, values: dict[str, str | int | float | None]) -> str:
        """Fill the body. Every field is validated; unknown keys are ignored."""
        rendered = {f.name: f.coerce(values.get(f.name)) for f in self.fields}
        try:
            body = self.body.format(**rendered)
        except KeyError as e:
            raise ProgramError(f"snippet {self.id}: no field for placeholder {e}") from e
        except (IndexError, ValueError) as e:
            raise ProgramError(f"snippet {self.id}: malformed body: {e}") from e
        return body if body.endswith("\n") else body + "\n"


@dataclass(frozen=True, slots=True)
class SnippetCatalogue:
    snippets: dict[str, Snippet]
    problems: list[str]

    def __iter__(self) -> Iterator[Snippet]:
        return iter(sorted(self.snippets.values(), key=lambda s: s.title))

    def __len__(self) -> int:
        return len(self.snippets)

    def get(self, snippet_id: str) -> Snippet:
        snippet = self.snippets.get(snippet_id)
        if snippet is None:
            known = ", ".join(sorted(self.snippets)) or "none"
            raise ProgramError(f"unknown snippet {snippet_id!r}; available: {known}")
        return snippet


def user_snippets_dir() -> Path:
    return user_config_path("nctab") / "snippets"


def _parse(text: str, source: str, problems: list[str]) -> Snippet | None:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        problems.append(f"{source}: invalid TOML ({e}); ignored")
        return None
    try:
        return Snippet.model_validate(data)
    except ValidationError as e:
        problems.append(f"{source}: {e}; ignored")
        return None


def _load_builtin(folder: str, into: dict[str, Snippet], problems: list[str]) -> None:
    root = resources.files("nctab.snippets")
    directory = root / folder
    if not directory.is_dir():
        return
    for entry in sorted(directory.iterdir(), key=lambda p: p.name):
        if entry.name.endswith(".toml"):
            snippet = _parse(
                entry.read_text(encoding="utf-8"), f"builtin:{folder}/{entry.name}", problems
            )
            if snippet is not None:
                into[snippet.id] = snippet


def _load_dir(directory: Path, into: dict[str, Snippet], problems: list[str]) -> None:
    if not directory.is_dir():
        return
    for path in sorted(directory.glob("*.toml")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as e:
            problems.append(f"{path}: cannot read ({e.strerror or e}); ignored")
            continue
        snippet = _parse(text, str(path), problems)
        if snippet is not None:
            into[snippet.id] = snippet


def load_snippets(profile_id: str) -> SnippetCatalogue:
    """Every snippet available for this profile, user files shadowing built-ins."""
    found: dict[str, Snippet] = {}
    problems: list[str] = []
    _load_builtin(COMMON, found, problems)
    _load_builtin(profile_id, found, problems)
    user = user_snippets_dir()
    _load_dir(user, found, problems)
    _load_dir(user / profile_id, found, problems)
    return SnippetCatalogue(snippets=found, problems=problems)
