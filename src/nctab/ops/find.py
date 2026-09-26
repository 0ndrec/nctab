"""Search, value hints and batch replace (PLAN.md §1.4a).

Three query styles, mutually exclusive:

* **word** — ``addr`` (plus optional ``values`` / ``min_value`` / ``max_value``)
  matches whole address words: ``F`` with value 300 → every ``F300`` / ``F300.``.
* **code** — ``"G01"`` / ``"M8"`` matches that G/M code regardless of zero padding.
* **text** — plain substring or regex over the line text. Comments are excluded
  unless ``in_comments``.

``suggest`` returns the distinct values of an address with counts and where
they occur — the "hints" shown before a replace and the source of completion
in the TUI.
"""

from __future__ import annotations

import re
from collections import OrderedDict
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from nctab.core.format import Rounding, replace_value
from nctab.core.model import Line, LineKind, Program, Text, Token, Word
from nctab.core.parse import parse_line
from nctab.errors import ProgramError
from nctab.ops.base import OpResult, Range
from nctab.profiles.loader import Profile

_CODE = re.compile(r"^([GM])(\d+(?:\.\d+)?)$", re.IGNORECASE)
_SKIP_KINDS = frozenset({LineKind.BLANK})


@dataclass(frozen=True, slots=True)
class Query:
    text: str | None = None
    regex: bool = False
    ignore_case: bool = True
    addr: str | None = None
    values: tuple[Decimal, ...] = ()
    min_value: Decimal | None = None
    max_value: Decimal | None = None
    code: str | None = None
    in_comments: bool = False
    range: Range = field(default_factory=Range)

    def __post_init__(self) -> None:
        modes = sum(x is not None for x in (self.text, self.addr, self.code))
        if modes == 0:
            raise ProgramError("query needs --text, --addr or --code")
        if modes > 1:
            raise ProgramError("use only one of --text, --addr, --code")
        if self.code is not None and not _CODE.match(self.code):
            raise ProgramError(f"bad code {self.code!r}; expected e.g. G01 or M8")

    @property
    def mode(self) -> str:
        if self.addr is not None:
            return "word"
        if self.code is not None:
            return "code"
        return "text"

    def pattern(self) -> re.Pattern[str]:
        assert self.text is not None
        flags = re.IGNORECASE if self.ignore_case else 0
        src = self.text if self.regex else re.escape(self.text)
        try:
            return re.compile(src, flags)
        except re.error as e:
            raise ProgramError(f"bad regex {self.text!r}: {e}") from e

    def _code_parts(self) -> tuple[str, Decimal]:
        assert self.code is not None
        m = _CODE.match(self.code)
        assert m is not None
        return m.group(1).upper(), Decimal(m.group(2))

    def word_matches(self, w: Word) -> bool:
        if self.mode == "code":
            addr, val = self._code_parts()
            return w.addr == addr and isinstance(w.value, Decimal) and w.value == val
        assert self.addr is not None
        if w.addr != self.addr.upper():
            return False
        if not self.values and self.min_value is None and self.max_value is None:
            return True
        if not isinstance(w.value, Decimal):
            return False
        if self.values and w.value not in self.values:
            return False
        if self.min_value is not None and w.value < self.min_value:
            return False
        return not (self.max_value is not None and w.value > self.max_value)


@dataclass(frozen=True, slots=True)
class Match:
    line: int  # 0-based index
    col: int
    length: int
    text: str
    block_number: int | None
    line_text: str

    @property
    def lineno(self) -> int:
        return self.line + 1


def _token_spans(line: Line) -> list[tuple[Token, int, int]]:
    out: list[tuple[Token, int, int]] = []
    pos = 0
    for t in line.tokens:
        out.append((t, pos, pos + len(t.text)))
        pos += len(t.text)
    return out


def _comment_spans(line: Line) -> list[tuple[int, int]]:
    return [(a, b) for t, a, b in _token_spans(line) if isinstance(t, Text) and t.kind == "comment"]


def _inside(spans: list[tuple[int, int]], a: int, b: int) -> bool:
    return any(a >= s and b <= e for s, e in spans)


def find(program: Program, profile: Profile, query: Query) -> list[Match]:
    selected = query.range.select(program, profile)
    out: list[Match] = []
    pattern = query.pattern() if query.mode == "text" else None

    for line in program.lines:
        if line.index not in selected or line.kind in _SKIP_KINDS:
            continue
        raw = line.raw
        if pattern is None:
            for t, a, b in _token_spans(line):
                if isinstance(t, Word) and query.word_matches(t):
                    out.append(Match(line.index, a, b - a, t.text, line.block_number, raw))
            continue
        comments = _comment_spans(line)
        for m in pattern.finditer(raw):
            if m.end() == m.start():
                continue
            if not query.in_comments and _inside(comments, m.start(), m.end()):
                continue
            out.append(
                Match(line.index, m.start(), m.end() - m.start(), m.group(), line.block_number, raw)
            )
    return out


# --------------------------------------------------------------------------- hints


@dataclass(frozen=True, slots=True)
class ValueHint:
    text: str  # as written in the file, e.g. "F300."
    value: Decimal | str
    count: int
    first_line: int  # 1-based
    last_line: int
    first_block: int | None
    last_block: int | None


def suggest(
    program: Program, profile: Profile, addr: str, rng: Range | None = None
) -> list[ValueHint]:
    """Distinct values of ``addr`` in the (range of the) program, most frequent first."""
    addr = addr.upper()
    selected = (rng or Range()).select(program, profile)
    acc: OrderedDict[str, list] = OrderedDict()
    for line in program.lines:
        if line.index not in selected:
            continue
        for w in line.tokens:
            if not isinstance(w, Word) or w.addr != addr:
                continue
            key = f"{w.value}" if isinstance(w.value, Decimal) else w.value
            rec = acc.get(key)
            if rec is None:
                acc[key] = [
                    w.text,
                    w.value,
                    1,
                    line.index + 1,
                    line.index + 1,
                    line.block_number,
                    line.block_number,
                ]
            else:
                rec[2] += 1
                rec[4] = line.index + 1
                rec[6] = line.block_number
    hints = [ValueHint(*r) for r in acc.values()]
    hints.sort(key=lambda h: (-h.count, h.first_line))
    return hints


def suggest_addresses(program: Program, profile: Profile) -> list[tuple[str, int]]:
    """Addresses present in the program with counts — for the TUI address picker."""
    counts: dict[str, int] = {}
    for line in program.lines:
        for w in line.tokens:
            if isinstance(w, Word):
                counts[w.addr] = counts.get(w.addr, 0) + 1
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))


# --------------------------------------------------------------------------- replace


@dataclass(frozen=True, slots=True)
class ReplaceSpec:
    query: Query
    to: str
    """New value text for word/code queries (``250``, ``#100``); replacement string for text
    queries (regex back-references ``\\1`` allowed when ``query.regex``)."""
    digits: int | None = None
    rounding: Rounding = "HALF_UP"
    only: frozenset[tuple[int, int]] | None = None
    """Restrict to these ``(line, col)`` matches — the TUI's per-match checkboxes."""


def _new_word(w: Word, to: str, spec: ReplaceSpec) -> Word:
    to = to.strip()
    try:
        value = Decimal(to)
    except InvalidOperation:
        return Word(w.addr, to, w.text[0] + to)
    if spec.query.mode == "code":
        # G1 → G01 style: keep zero padding of the source
        src = w.value_text.strip()
        pad = len(src.split(".", 1)[0]) if src and src[0].isdigit() else 0
        int_part, _, frac = to.partition(".")
        if pad and int_part.isdigit():
            int_part = int_part.zfill(pad)
        text = int_part + (("." + frac) if frac else "")
        return Word(w.addr, value, w.text[0] + text)
    return replace_value(w, value, digits=spec.digits, rounding=spec.rounding)


@dataclass(frozen=True, slots=True)
class Change:
    """What one match turns into.

    ``after`` is the replacement for that match alone; ``line_after`` is the
    whole line once every selected match on it has been rewritten. ``touched``
    is False when the value is already what you asked for, so the UI can show
    it greyed out rather than promising an edit that will not happen.
    """

    match: Match
    after: str
    line_after: str
    touched: bool

    @property
    def before(self) -> str:
        return self.match.text

    @property
    def line(self) -> int:
        return self.match.line

    @property
    def lineno(self) -> int:
        return self.match.lineno


def _selected(program: Program, spec: ReplaceSpec, profile: Profile) -> list[Match]:
    matches = find(program, profile, spec.query)
    if spec.only is not None:
        matches = [m for m in matches if (m.line, m.col) in spec.only]
    return matches


def _rewrite_line(
    line: Line, matches: list[Match], spec: ReplaceSpec, pattern: re.Pattern[str] | None
) -> tuple[str, dict[int, str]]:
    """The line's new text, plus what each match became, keyed by its column.

    Shared by ``replace`` and ``preview_replace`` so the two can never disagree.
    """
    if pattern is None:
        spans = {a: t for t, a, _ in _token_spans(line)}
        tokens = list(line.tokens)
        became: dict[int, str] = {}
        for m in matches:
            word = spans[m.col]
            assert isinstance(word, Word)
            new = _new_word(word, spec.to, spec)
            became[m.col] = new.text
            if new.text != word.text:
                tokens[line.tokens.index(word)] = new
        return "".join(t.text for t in tokens), became

    raw = line.raw
    became = {}
    for m in sorted(matches, key=lambda m: m.col, reverse=True):
        mo = pattern.match(raw, m.col, m.col + m.length)
        assert mo is not None
        repl = mo.expand(spec.to) if spec.query.regex else spec.to
        became[m.col] = repl
        raw = raw[: m.col] + repl + raw[m.col + m.length :]
    return raw, became


def _group(matches: list[Match]) -> dict[int, list[Match]]:
    by_line: dict[int, list[Match]] = {}
    for m in matches:
        by_line.setdefault(m.line, []).append(m)
    return by_line


def preview_replace(program: Program, spec: ReplaceSpec, profile: Profile) -> list[Change]:
    """What ``replace`` would do, match by match, without touching the program."""
    matches = _selected(program, spec, profile)
    if not matches:
        return []
    pattern = spec.query.pattern() if spec.query.mode == "text" else None
    by_line = _group(matches)
    out: list[Change] = []
    for index, ms in sorted(by_line.items()):
        line = program.lines[index]
        raw, became = _rewrite_line(line, ms, spec, pattern)
        for m in ms:
            after = became.get(m.col, m.text)
            out.append(Change(match=m, after=after, line_after=raw, touched=after != m.text))
    return out


def replace(program: Program, spec: ReplaceSpec, profile: Profile) -> OpResult:
    matches = _selected(program, spec, profile)
    result = OpResult(program=program)
    if not matches:
        return result

    pattern = spec.query.pattern() if spec.query.mode == "text" else None
    by_line = _group(matches)
    new_lines: list[Line] = []
    for line in program.lines:
        ms = by_line.get(line.index)
        if not ms:
            new_lines.append(line)
            continue

        raw, became = _rewrite_line(line, ms, spec, pattern)
        result.matches += sum(1 for m in ms if became.get(m.col, m.text) != m.text)
        if raw == line.raw:
            new_lines.append(line)
            continue
        new_line, issues = parse_line(raw, line.eol, line.index, profile)
        for iss in issues:
            result.warn(f"line {line.index + 1}: replacement produced {iss.code}: {iss.message}")
        new_lines.append(new_line)
        result.changed.append(line.index)

    result.program = program.with_lines(new_lines)
    return result
