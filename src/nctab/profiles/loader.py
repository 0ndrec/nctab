"""Machine profile model and loader (goal.md §6.1).

Resolution order for ``load_profile(name)``:

1. ``name`` is an existing ``.toml`` path → load it directly.
2. ``<user config dir>/nctab/profiles/<name>.toml``
3. built-in ``nctab/profiles/<name>.toml``
"""

from __future__ import annotations

import tomllib
from functools import cache
from importlib import resources
from pathlib import Path
from typing import Literal

from platformdirs import user_config_path
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from nctab.errors import ProfileError

DEFAULT_PROFILE = "fanuc-mill"


class Profile(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    label: str
    block_number: str = "N"
    comment: list[str] = Field(default_factory=lambda: [";", "()"])
    program_delimiters: list[str] = Field(default_factory=lambda: ["%"])
    axes: list[str] = Field(default_factory=lambda: ["X", "Y", "Z", "A", "B", "C"])
    arc_ijk: bool = True
    arc_r: bool = True
    arc_center_absolute: bool = False  # Fanuc: IJK are offsets from the start point
    diameter_mode: bool = False
    """Lathes program X as a diameter. v1 only records it; no value is halved."""
    tool_word: str = "T"
    length_comp: str = "H"
    radius_comp: str = "D"
    feed: str = "F"
    spindle: str = "S"
    incremental: str = "G91"
    absolute: str = "G90"
    planes: dict[str, str] = Field(default_factory=lambda: {"G17": "XY", "G18": "ZX", "G19": "YZ"})
    toolchange_patterns: list[str] = Field(default_factory=lambda: ["T{num}", "M06"])
    skip_address: str = "/"
    case: Literal["upper", "lower"] = "upper"
    decimal_sep: str = "."
    units: Literal["mm", "inch"] = "mm"
    digits: int = 3
    gcodes: dict[str, str] = Field(default_factory=dict)
    mcodes: dict[str, str] = Field(default_factory=dict)

    @field_validator("axes", "comment", "program_delimiters", mode="after")
    @classmethod
    def _upper_letters(cls, v: list[str]) -> list[str]:
        return [s.upper() if len(s) == 1 and s.isalpha() else s for s in v]

    # -- convenience -----------------------------------------------------------

    @property
    def semicolon_comments(self) -> bool:
        return ";" in self.comment

    @property
    def paren_comments(self) -> bool:
        return "()" in self.comment

    def describe(self, addr: str, value: int | str) -> str | None:
        """Human description of a G/M code from the profile dictionary."""
        key = f"{addr.upper()}{int(value):02d}" if isinstance(value, int) else f"{addr}{value}"
        table = self.gcodes if addr.upper() == "G" else self.mcodes
        return table.get(key) or table.get(f"{addr.upper()}{value}")


def user_profiles_dir() -> Path:
    return user_config_path("nctab") / "profiles"


def _builtin_dir():
    return resources.files("nctab.profiles")


def builtin_profile_ids() -> list[str]:
    return sorted(p.name[:-5] for p in _builtin_dir().iterdir() if p.name.endswith(".toml"))


def _parse_profile(text: str, source: str) -> Profile:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise ProfileError(f"profile {source}: invalid TOML: {e}") from e
    try:
        return Profile.model_validate(data)
    except ValidationError as e:
        raise ProfileError(f"profile {source}: {e}") from e


@cache
def load_profile(name: str | None = None) -> Profile:
    name = name or DEFAULT_PROFILE

    as_path = Path(name)
    if as_path.suffix == ".toml" and as_path.is_file():
        return _parse_profile(as_path.read_text(encoding="utf-8"), str(as_path))

    user_file = user_profiles_dir() / f"{name}.toml"
    if user_file.is_file():
        return _parse_profile(user_file.read_text(encoding="utf-8"), str(user_file))

    builtin = _builtin_dir() / f"{name}.toml"
    if builtin.is_file():
        return _parse_profile(builtin.read_text(encoding="utf-8"), f"builtin:{name}")

    known = ", ".join(builtin_profile_ids())
    raise ProfileError(f"unknown profile {name!r}; built-in profiles: {known}")
