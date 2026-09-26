"""Exception hierarchy mapped to CLI exit codes (goal.md §5.1)."""

from __future__ import annotations


class NctabError(Exception):
    """Base error. ``exit_code`` is what the CLI returns to the shell."""

    exit_code: int = 1

    def __init__(self, message: str, *, exit_code: int | None = None) -> None:
        super().__init__(message)
        if exit_code is not None:
            self.exit_code = exit_code


class ProgramError(NctabError):
    """Errors in the NC program itself or in requested operation parameters."""

    exit_code = 1


class ParseError(NctabError):
    """Syntax or validation failure."""

    exit_code = 2


class NcIOError(NctabError):
    """File system, encoding, network or serial failures."""

    exit_code = 3


class ProfileError(NctabError):
    """Unknown or malformed machine profile."""

    exit_code = 2
