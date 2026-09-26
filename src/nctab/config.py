"""Layered configuration (goal.md §12).

Later layers win:

1. the defaults in this module
2. ``<user config dir>/nctab/config.toml``
3. ``./.nctab.toml`` in the project, or the nearest one above the current
   directory (so a shop can drop one at the root of a job folder)
4. environment variables ``NCTAB_*``
5. CLI flags, applied by the caller

Reading never fails on a bad file: a malformed or unreadable layer is skipped
and recorded in ``Config.problems`` so the CLI can warn without refusing to run.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from platformdirs import user_config_path
from pydantic import BaseModel, ConfigDict, Field, ValidationError

PROJECT_FILE = ".nctab.toml"
Rounding = Literal["HALF_UP", "HALF_EVEN"]


class UiConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    theme: str = "dark"
    keybindings: Literal["default", "vim"] = "default"


class EditorConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    tab_width: int = Field(default=4, ge=1, le=16)
    show_invisibles: bool = False
    backup: bool = True
    autosave_sec: int = Field(default=0, ge=0)
    """0 disables autosave."""


class DefaultsConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    directory: str = ""
    """Folder the G-code programs live in.

    The explorer opens here, and a bare file name the CLI cannot find in the
    working directory is looked up here as well. Empty means the working
    directory, so nothing changes until a shop sets it.
    """
    profile: str = "fanuc-mill"
    digits: int | Literal["preserve"] = "preserve"
    """Fractional digits for rewritten numbers, or ``preserve`` to keep the source style."""
    rounding: Rounding = "HALF_UP"
    arc_tolerance: float = 0.001
    """Radius mismatch a ``check`` run tolerates, in program units."""

    @property
    def digits_or_none(self) -> int | None:
        """``None`` when numbers keep their original style."""
        return None if self.digits == "preserve" else self.digits

    @property
    def gcode_dir(self) -> Path:
        """The configured folder, with ``~`` expanded; the cwd when unset."""
        if not self.directory.strip():
            return Path.cwd()
        return Path(self.directory).expanduser()


class Settings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    ui: UiConfig = UiConfig()
    editor: EditorConfig = EditorConfig()
    defaults: DefaultsConfig = DefaultsConfig()


@dataclass(frozen=True, slots=True)
class Config:
    settings: Settings
    sources: list[Path] = field(default_factory=list)
    """Files that were actually read, in the order they were applied."""
    problems: list[str] = field(default_factory=list)

    @property
    def ui(self) -> UiConfig:
        return self.settings.ui

    @property
    def editor(self) -> EditorConfig:
        return self.settings.editor

    @property
    def defaults(self) -> DefaultsConfig:
        return self.settings.defaults

    def resolve(self, name: str | Path) -> Path:
        """Find a program by name.

        An absolute path, or one that exists as given, is used as it stands.
        Otherwise the configured G-code folder is tried, so a technologist can
        type ``nctab stats OP20.nc`` from anywhere. A name found in neither
        place comes back unchanged, and the caller reports the missing file.
        """
        path = Path(name)
        if path.is_absolute() or path.exists():
            return path
        candidate = self.defaults.gcode_dir / path
        return candidate if candidate.exists() else path


def user_config_file() -> Path:
    return user_config_path("nctab") / "config.toml"


def find_project_config(start: Path | None = None) -> Path | None:
    """Nearest ``.nctab.toml`` at or above ``start``."""
    here = (start or Path.cwd()).resolve()
    for directory in (here, *here.parents):
        candidate = directory / PROJECT_FILE
        if candidate.is_file():
            return candidate
    return None


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in overlay.items():
        current = out.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            out[key] = _deep_merge(current, value)
        else:
            out[key] = value
    return out


_ENV_MAP: dict[str, tuple[str, str, type]] = {
    "NCTAB_DIR": ("defaults", "directory", str),
    "NCTAB_PROFILE": ("defaults", "profile", str),
    "NCTAB_DIGITS": ("defaults", "digits", int),
    "NCTAB_ROUNDING": ("defaults", "rounding", str),
    "NCTAB_THEME": ("ui", "theme", str),
    "NCTAB_KEYBINDINGS": ("ui", "keybindings", str),
    "NCTAB_BACKUP": ("editor", "backup", bool),
    "NCTAB_AUTOSAVE_SEC": ("editor", "autosave_sec", int),
}


def _env_layer(env: dict[str, str], problems: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, (section, key, kind) in _ENV_MAP.items():
        raw = env.get(name)
        if raw is None or raw == "":
            continue
        try:
            if kind is bool:
                value: Any = raw.strip().lower() in ("1", "true", "yes", "on")
            elif kind is int:
                value = "preserve" if raw.strip().lower() == "preserve" else int(raw)
            else:
                value = raw
        except ValueError:
            problems.append(f"{name}: {raw!r} is not valid; ignored")
            continue
        out.setdefault(section, {})[key] = value
    return out


def _read_toml(path: Path, problems: list[str]) -> dict[str, Any] | None:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except OSError as e:
        problems.append(f"{path}: cannot read ({e.strerror or e}); ignored")
        return None
    except tomllib.TOMLDecodeError as e:
        problems.append(f"{path}: invalid TOML ({e}); ignored")
        return None
    return data


def load_config(
    *,
    start: Path | None = None,
    env: dict[str, str] | None = None,
    include_user: bool = True,
    include_project: bool = True,
) -> Config:
    """Build the effective configuration from every layer."""
    env = os.environ.copy() if env is None else env
    problems: list[str] = []
    sources: list[Path] = []
    merged: dict[str, Any] = {}

    candidates: list[Path] = []
    if include_user:
        candidates.append(user_config_file())
    if include_project:
        project = find_project_config(start)
        if project is not None:
            candidates.append(project)

    for path in candidates:
        if not path.is_file():
            continue
        data = _read_toml(path, problems)
        if data is None:
            continue
        merged = _deep_merge(merged, data)
        sources.append(path)

    merged = _deep_merge(merged, _env_layer(env, problems))

    try:
        settings = Settings.model_validate(merged)
    except ValidationError as e:
        problems.append(f"configuration rejected, using defaults: {e}")
        settings = Settings()

    return Config(settings=settings, sources=sources, problems=problems)
