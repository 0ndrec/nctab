"""Program model (goal.md §6.1).

Design notes
------------
* A ``Line`` is a sequence of *tokens*. Every byte of the source line lives in
  exactly one token, so ``"".join(t.text for t in tokens)`` reproduces the
  original text. This is what guarantees byte-for-byte roundtrip for lines an
  operation does not touch, and lets an operation replace a single word without
  disturbing spacing, case or neighbouring tokens.
* Numbers are ``Decimal`` — never ``float``. ``Decimal("0.0130")`` keeps its
  exponent, which is how *preserve-original* formatting knows the source had four
  fractional digits.
* Lines and words are immutable. Operations produce new ``Line`` objects and a
  new ``Program``; the input is never mutated.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from decimal import Decimal
from enum import StrEnum
from typing import Literal

# --------------------------------------------------------------------------- tokens


@dataclass(frozen=True, slots=True)
class Word:
    """An address letter plus its value, e.g. ``X-0.0130``.

    ``addr`` is normalised to upper case; ``text`` is the exact source text
    (including the original case of the letter and the number as written).
    ``value`` is ``Decimal`` for numeric words and ``str`` for macro
    expressions such as ``#100`` or ``[#1+2.5]``.
    """

    addr: str
    value: Decimal | str
    text: str

    @property
    def is_numeric(self) -> bool:
        return isinstance(self.value, Decimal)

    @property
    def number(self) -> Decimal:
        """Numeric value; raises ``TypeError`` for macro words."""
        if not isinstance(self.value, Decimal):
            raise TypeError(f"word {self.text!r} is not numeric")
        return self.value

    @property
    def value_text(self) -> str:
        """The source text after the address letter."""
        return self.text[1:]


TextKind = Literal["space", "comment", "skip", "percent", "macro", "other"]


@dataclass(frozen=True, slots=True)
class Text:
    """Any non-word token: whitespace, comment, block-skip, ``%``, macro, garbage."""

    kind: TextKind
    text: str


Token = Word | Text


# --------------------------------------------------------------------------- line


class LineKind(StrEnum):
    HEADER = "header"  # % delimiter or O-number line
    MOTION = "motion"  # has axis words or G00–G03
    PREP = "prep"  # G words only (G17, G90, G54 …)
    MCODE = "mcode"  # M words without motion
    OTHER = "other"  # F/S/T/D/H only, macro, unknown
    BLANK = "blank"
    COMMENT = "comment"


@dataclass(frozen=True, slots=True)
class Line:
    index: int
    tokens: tuple[Token, ...]
    eol: str  # "\n", "\r\n" or "" for a final line without newline
    kind: LineKind
    block_number: int | None = None
    skipped: bool = False

    # -- derived views -------------------------------------------------------

    @property
    def raw(self) -> str:
        """Source text of the line without the line terminator."""
        return "".join(t.text for t in self.tokens)

    @property
    def words(self) -> tuple[Word, ...]:
        """All address words except the block number."""
        return tuple(t for t in self.tokens if isinstance(t, Word) and t.addr != "N")

    @property
    def comment(self) -> str | None:
        parts = [t.text for t in self.tokens if isinstance(t, Text) and t.kind == "comment"]
        return " ".join(parts) if parts else None

    def word(self, addr: str) -> Word | None:
        """First word with the given address, or ``None``."""
        addr = addr.upper()
        for t in self.tokens:
            if isinstance(t, Word) and t.addr == addr:
                return t
        return None

    def has(self, addr: str) -> bool:
        return self.word(addr) is not None

    # -- immutable updates ---------------------------------------------------

    def with_tokens(self, tokens: tuple[Token, ...], **changes: object) -> Line:
        return replace(self, tokens=tokens, **changes)  # type: ignore[arg-type]

    def replace_token(self, old: Token, new: Token) -> Line:
        """Return a copy with ``old`` (matched by identity) swapped for ``new``."""
        toks = tuple(new if t is old else t for t in self.tokens)
        return replace(self, tokens=toks)


# --------------------------------------------------------------------------- program


@dataclass(frozen=True, slots=True)
class ParseIssue:
    """A problem noticed while tokenising. Reported by ``check``."""

    line: int
    code: str
    message: str


@dataclass(slots=True)
class Program:
    lines: list[Line] = field(default_factory=list)
    issues: list[ParseIssue] = field(default_factory=list)
    encoding: str = "utf-8"
    bom: bool = False

    def __len__(self) -> int:
        return len(self.lines)

    def __iter__(self):
        return iter(self.lines)

    def __getitem__(self, i: int) -> Line:
        return self.lines[i]

    @property
    def text(self) -> str:
        return "".join(line.raw + line.eol for line in self.lines)

    def with_lines(self, lines: list[Line]) -> Program:
        return Program(lines=lines, issues=list(self.issues), encoding=self.encoding, bom=self.bom)
