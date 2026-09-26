from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from nctab.core.model import LineKind, Text, Word
from nctab.core.parse import parse_text, split_lines, tokenize
from nctab.profiles.loader import Profile, load_profile

# --------------------------------------------------------------------------- roundtrip


def test_golden_roundtrip(golden_path: Path, fanuc: Profile) -> None:
    text = golden_path.read_text(encoding="utf-8")
    assert parse_text(text, fanuc).text == text


@pytest.mark.parametrize(
    "text",
    [
        "",
        "\n",
        "N10 G01 X1.\n",
        "N10 G01 X1.",
        "a\r\nb\nc\rd",  # mixed line endings
        "  \t \n\n",
        "(unclosed comment\nN20 X1.",
        "N10 X#100 Y[#1+2.5] Z-#3\n#100=[#101*2] ; set\n",
        "IF[#1EQ1]GOTO100\nWHILE[#1LT10]DO1\nEND1\n",
        "%\nO1234\n%\n",
        "N10 G01 X 12.5 Y -3.\n",  # spaces between address and value
        "N10 G01 X12.5 ??? Y1.\n",  # garbage
    ],
)
def test_roundtrip_edge_cases(text: str, fanuc: Profile) -> None:
    assert parse_text(text, fanuc).text == text


@given(st.text(alphabet=st.characters(max_codepoint=0x24F), max_size=200))
def test_roundtrip_property(text: str) -> None:
    assert parse_text(text, load_profile("fanuc-mill")).text == text


# --------------------------------------------------------------------------- split


def test_split_lines_preserves_eols() -> None:
    assert split_lines("") == [("", "")]
    assert split_lines("a") == [("a", "")]
    assert split_lines("a\n") == [("a", "\n")]
    assert split_lines("a\r\nb") == [("a", "\r\n"), ("b", "")]
    assert split_lines("\n\n") == [("", "\n"), ("", "\n")]


# --------------------------------------------------------------------------- tokens


def words(text: str, profile: Profile) -> list[Word]:
    toks, _ = tokenize(text, profile)
    return [t for t in toks if isinstance(t, Word)]


def test_basic_words(fanuc: Profile) -> None:
    ws = words("N120 G01 X12.5 Z-0.2 F180", fanuc)
    assert [(w.addr, w.value) for w in ws] == [
        ("N", Decimal(120)),
        ("G", Decimal(1)),
        ("X", Decimal("12.5")),
        ("Z", Decimal("-0.2")),
        ("F", Decimal(180)),
    ]
    assert ws[3].text == "Z-0.2"
    assert ws[3].value_text == "-0.2"


def test_preserves_scale_and_style(fanuc: Profile) -> None:
    ws = words("X-0.0130 Y12. Z.5 A+3", fanuc)
    assert ws[0].value == Decimal("-0.0130")
    assert ws[0].value.as_tuple().exponent == -4
    assert ws[1].text == "Y12."
    assert ws[2].text == "Z.5"
    assert ws[3].text == "A+3"


def test_lowercase_address_is_normalised_but_text_kept(fanuc: Profile) -> None:
    (w,) = words("x12.5", fanuc)
    assert w.addr == "X"
    assert w.text == "x12.5"


def test_comments(fanuc: Profile) -> None:
    toks, issues = tokenize("N10 G01 X1. (MOVE) ; trailing", fanuc)
    comments = [t.text for t in toks if isinstance(t, Text) and t.kind == "comment"]
    assert comments == ["(MOVE)", "; trailing"]
    assert issues == []


def test_unclosed_comment_reports_issue(fanuc: Profile) -> None:
    toks, issues = tokenize("N10 (oops X1.", fanuc, line_no=7)
    assert len(issues) == 1
    assert issues[0].code == "unclosed-comment"
    assert issues[0].line == 7
    # everything after "(" is swallowed as comment, X1. is not a word
    assert [t.addr for t in toks if isinstance(t, Word)] == ["N"]


def test_n_inside_comment_is_not_a_block_number(fanuc: Profile) -> None:
    prog = parse_text("(N999 not a block) X1.\n", fanuc)
    assert prog.lines[0].block_number is None


def test_skip_block(fanuc: Profile) -> None:
    prog = parse_text("/N210 G00 Z50.\n/3 X1.\nX/1\n", fanuc)
    assert prog.lines[0].skipped is True
    assert prog.lines[0].block_number == 210
    assert prog.lines[1].skipped is True
    assert prog.lines[2].skipped is False  # "/" mid-line is not a skip


def test_percent(fanuc: Profile) -> None:
    prog = parse_text("%\nO0020\nN10 X1.\n%\n", fanuc)
    assert prog.lines[0].kind is LineKind.HEADER
    assert prog.lines[1].kind is LineKind.HEADER
    assert prog.lines[3].kind is LineKind.HEADER


def test_arc_r_sign_preserved(fanuc: Profile) -> None:
    ws = words("G03 X-22. Y18. R-8.", fanuc)
    r = next(w for w in ws if w.addr == "R")
    assert r.value == Decimal("-8")
    assert r.text == "R-8."


def test_macro_words(fanuc: Profile) -> None:
    ws = words("X#100 Y[#1+2.5] Z-#3", fanuc)
    assert [(w.addr, w.value) for w in ws] == [("X", "#100"), ("Y", "[#1+2.5]"), ("Z", "-#3")]
    assert all(not w.is_numeric for w in ws)


def test_macro_statement(fanuc: Profile) -> None:
    toks, issues = tokenize("#100=[#101*2] ; set", fanuc)
    assert issues == []
    assert toks[0] == Text("macro", "#100=[#101*2]")
    assert toks[-1].kind == "comment"  # type: ignore[union-attr]


def test_macro_keywords(fanuc: Profile) -> None:
    for line in ("IF[#1EQ1]GOTO100", "WHILE[#1LT10]DO1", "END1", "GOTO 50"):
        toks, issues = tokenize(line, fanuc)
        assert issues == [], line
        assert toks[0].kind == "macro", line  # type: ignore[union-attr]


def test_garbage_reports_issue(fanuc: Profile) -> None:
    toks, issues = tokenize("X1. ?? Y2.", fanuc)
    assert [i.code for i in issues] == ["unexpected-char", "unexpected-char"]
    assert [w.addr for w in toks if isinstance(w, Word)] == ["X", "Y"]


def test_bare_letter_reports_issue(fanuc: Profile) -> None:
    _, issues = tokenize("G X1.", fanuc)
    assert [i.code for i in issues] == ["word-no-value"]


# --------------------------------------------------------------------------- classification


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("", LineKind.BLANK),
        ("   ", LineKind.BLANK),
        ("(just a comment)", LineKind.COMMENT),
        ("N10 (only comment)", LineKind.COMMENT),
        ("%", LineKind.HEADER),
        ("O0020 (POCKET)", LineKind.HEADER),
        ("N10 G01 X1.", LineKind.MOTION),
        ("N10 X1.", LineKind.MOTION),
        ("G00", LineKind.MOTION),
        ("N10 G17 G90 G54", LineKind.PREP),
        ("N10 M08", LineKind.MCODE),
        ("N10 T1 M06", LineKind.MCODE),
        ("N10 S4500 F300", LineKind.OTHER),
        ("#100=1", LineKind.OTHER),
        ("N10", LineKind.OTHER),
    ],
)
def test_line_kind(text: str, kind: LineKind, fanuc: Profile) -> None:
    assert parse_text(text, fanuc).lines[0].kind is kind


def test_line_views(fanuc: Profile) -> None:
    line = parse_text("N120 G01 X12.5 Z-0.2 F180 (cut)", fanuc).lines[0]
    assert line.raw == "N120 G01 X12.5 Z-0.2 F180 (cut)"
    assert line.block_number == 120
    assert [w.addr for w in line.words] == ["G", "X", "Z", "F"]
    assert line.comment == "(cut)"
    assert line.word("z") is not None
    assert line.word("z").value == Decimal("-0.2")  # type: ignore[union-attr]
    assert line.has("Y") is False


def test_replace_token_is_local(fanuc: Profile) -> None:
    line = parse_text("N120  G01   X12.5 Z-0.2 F180", fanuc).lines[0]
    old = line.word("X")
    assert old is not None
    new = Word("X", Decimal("13"), "X13.")
    out = line.replace_token(old, new)
    assert out.raw == "N120  G01   X13. Z-0.2 F180"
    assert line.raw == "N120  G01   X12.5 Z-0.2 F180"  # original untouched
