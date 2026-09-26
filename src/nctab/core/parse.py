"""Tokeniser and parser for ISO / Fanuc-style NC text (goal.md §6.1).

The parser is deliberately dumb about semantics: it splits each line into
tokens that cover every source byte, classifies the line, and records anything
suspicious as a ``ParseIssue`` instead of raising. Modal-state analysis lives in
``nctab.core.state``; validation lives in ``nctab.check``.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from nctab.core.model import Line, LineKind, ParseIssue, Program, Text, Token, Word
from nctab.profiles.loader import Profile

_EOL = re.compile(r"\r\n|\n|\r")
_NUMBER = re.compile(r"\s*[+-]?(?:\d+\.?\d*|\.\d+)")
_MACRO_VAR = re.compile(r"#(?:\d+|\[)")
_MACRO_KEYWORD = re.compile(
    r"(?:IF|WHILE|GOTO|GO\s*TO|DO|END|THEN|ELSE)(?=[\d\[\s#]|$)", re.IGNORECASE
)
_MOTION_G = frozenset({0, 1, 2, 3})


def split_lines(text: str) -> list[tuple[str, str]]:
    """Split into ``(content, eol)`` pairs. Every byte is preserved.

    An empty string yields one empty line with an empty terminator, so the
    roundtrip of ``""`` is ``""``.
    """
    out: list[tuple[str, str]] = []
    start = 0
    for m in _EOL.finditer(text):
        out.append((text[start : m.start()], m.group()))
        start = m.end()
    if start < len(text) or not out:
        out.append((text[start:], ""))
    return out


def _match_brackets(text: str, i: int) -> int:
    """Return index just past the ``]`` matching ``text[i] == '['``; len(text) if unclosed."""
    depth = 0
    for j in range(i, len(text)):
        c = text[j]
        if c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
            if depth == 0:
                return j + 1
    return len(text)


def _scan_macro_expr(text: str, i: int, profile: Profile) -> int:
    """Consume a macro right-hand side up to a comment start or end of line."""
    j = i
    n = len(text)
    while j < n:
        c = text[j]
        if c == ";" and profile.semicolon_comments:
            break
        if c == "(" and profile.paren_comments:
            break
        if c == "[":
            j = _match_brackets(text, j)
            continue
        j += 1
    # trailing whitespace belongs to a space token
    while j > i and text[j - 1].isspace():
        j -= 1
    return j


def tokenize(
    text: str, profile: Profile, line_no: int = 0
) -> tuple[tuple[Token, ...], list[ParseIssue]]:
    """Tokenise one line (without terminator)."""
    tokens: list[Token] = []
    issues: list[ParseIssue] = []
    i = 0
    n = len(text)
    seen_content = False  # anything except whitespace / skip already emitted

    def issue(code: str, msg: str) -> None:
        issues.append(ParseIssue(line_no, code, msg))

    while i < n:
        c = text[i]

        # whitespace
        if c.isspace():
            j = i + 1
            while j < n and text[j].isspace():
                j += 1
            tokens.append(Text("space", text[i:j]))
            i = j
            continue

        # ; comment to end of line
        if c == ";" and profile.semicolon_comments:
            tokens.append(Text("comment", text[i:]))
            break

        # ( ... ) comment
        if c == "(" and profile.paren_comments:
            close = text.find(")", i + 1)
            if close == -1:
                issue("unclosed-comment", "unclosed '(' comment")
                tokens.append(Text("comment", text[i:]))
                break
            tokens.append(Text("comment", text[i : close + 1]))
            i = close + 1
            seen_content = True
            continue

        # block skip: "/" or "/3" at the start of the block
        if c == profile.skip_address and not seen_content:
            j = i + 1
            if j < n and text[j].isdigit():
                j += 1
            tokens.append(Text("skip", text[i:j]))
            i = j
            continue

        # program delimiter
        if c in profile.program_delimiters:
            tokens.append(Text("percent", c))
            i += 1
            seen_content = True
            continue

        # macro statement: #100 = ...   or  #[#1+2] = ...
        if c == "#":
            m = _MACRO_VAR.match(text, i)
            if m is None:
                issue("bad-macro", "'#' not followed by a variable number")
                tokens.append(Text("other", c))
                i += 1
                continue
            j = _match_brackets(text, i + 1) if text[i + 1] == "[" else m.end()
            k = j
            while k < n and text[k].isspace():
                k += 1
            if k < n and text[k] == "=":
                j = _scan_macro_expr(text, k + 1, profile)
            tokens.append(Text("macro", text[i:j]))
            i = j
            seen_content = True
            continue

        # address letter
        if c.isalpha():
            kw = _MACRO_KEYWORD.match(text, i)
            if kw is not None and not _NUMBER.match(text, i + 1):
                j = _scan_macro_expr(text, kw.end(), profile)
                tokens.append(Text("macro", text[i:j]))
                i = j
                seen_content = True
                continue

            m = _NUMBER.match(text, i + 1)
            if m is not None:
                word_text = text[i : m.end()]
                try:
                    value: Decimal | str = Decimal(m.group().strip())
                except InvalidOperation:  # pragma: no cover — regex guarantees validity
                    value = m.group().strip()
                tokens.append(Word(c.upper(), value, word_text))
                i = m.end()
                seen_content = True
                continue

            # X#100  X[#1+2]  X-#100
            j = i + 1
            if j < n and text[j] in "+-":
                j += 1
            if j < n and text[j] == "#":
                mv = _MACRO_VAR.match(text, j)
                if mv is not None:
                    j = _match_brackets(text, j + 1) if text[j + 1] == "[" else mv.end()
                    tokens.append(Word(c.upper(), text[i + 1 : j], text[i:j]))
                    i = j
                    seen_content = True
                    continue
            if j < n and text[j] == "[":
                j = _match_brackets(text, j)
                tokens.append(Word(c.upper(), text[i + 1 : j], text[i:j]))
                i = j
                seen_content = True
                continue

            # bare letter (or letters) without a value
            j = i + 1
            while j < n and text[j].isalpha():
                j += 1
            issue("word-no-value", f"address {text[i:j]!r} without a numeric value")
            tokens.append(Text("other", text[i:j]))
            i = j
            seen_content = True
            continue

        # anything else: one character of garbage
        issue("unexpected-char", f"unexpected character {c!r}")
        tokens.append(Text("other", c))
        i += 1
        seen_content = True

    return tuple(tokens), issues


def _classify(tokens: tuple[Token, ...], profile: Profile) -> LineKind:
    words = [t for t in tokens if isinstance(t, Word)]
    texts = [t for t in tokens if isinstance(t, Text)]
    kinds = {t.kind for t in texts}

    if not words and kinds <= {"space"}:
        return LineKind.BLANK
    if "percent" in kinds:
        return LineKind.HEADER
    if not words or all(w.addr == profile.block_number for w in words):
        if "comment" in kinds and kinds <= {"space", "comment", "skip"}:
            return LineKind.COMMENT
        return LineKind.OTHER

    axes = set(profile.axes)
    has_axis = False
    has_g = False
    has_m = False
    only_o = True
    for w in words:
        if w.addr == profile.block_number:
            continue
        if w.addr != "O":
            only_o = False
        if w.addr in axes:
            has_axis = True
        elif w.addr == "G":
            has_g = True
            if (
                isinstance(w.value, Decimal)
                and w.value == w.value.to_integral_value()
                and int(w.value) in _MOTION_G
            ):
                has_axis = True  # G00–G03 count as motion even without axes
        elif w.addr == "M":
            has_m = True

    if only_o:
        return LineKind.HEADER
    if has_axis:
        return LineKind.MOTION
    if has_g:
        return LineKind.PREP
    if has_m:
        return LineKind.MCODE
    return LineKind.OTHER


def _block_number(tokens: tuple[Token, ...], profile: Profile) -> int | None:
    for t in tokens:
        if isinstance(t, Word) and t.addr == profile.block_number:
            if isinstance(t.value, Decimal) and t.value == t.value.to_integral_value():
                return int(t.value)
            return None
    return None


def parse_line(
    content: str, eol: str, index: int, profile: Profile
) -> tuple[Line, list[ParseIssue]]:
    tokens, issues = tokenize(content, profile, index)
    skipped = any(isinstance(t, Text) and t.kind == "skip" for t in tokens)
    line = Line(
        index=index,
        tokens=tokens,
        eol=eol,
        kind=_classify(tokens, profile),
        block_number=_block_number(tokens, profile),
        skipped=skipped,
    )
    return line, issues


def parse_text(text: str, profile: Profile) -> Program:
    """Parse a whole program. ``parse_text(t).text == t`` for any ``t``."""
    program = Program()
    for index, (content, eol) in enumerate(split_lines(text)):
        line, issues = parse_line(content, eol, index, profile)
        program.lines.append(line)
        program.issues.extend(issues)
    return program
