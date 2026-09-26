from __future__ import annotations

from decimal import Decimal

import pytest

from nctab.core.parse import parse_text
from nctab.errors import ProgramError
from nctab.ops.base import Range
from nctab.ops.find import Query, ReplaceSpec, find, replace, suggest, suggest_addresses
from nctab.profiles.loader import Profile
from tests.conftest import GOLDEN_DIR

D = Decimal
POCKET = GOLDEN_DIR / "pocket.nc"
SAMPLE = "N10 G01 X1. F300 (F300 in comment)\nN20 G1 X2. F300.\nN30 G02 X3. F250 ; f300\nN40 M8\n"


@pytest.fixture
def prog(fanuc: Profile):
    return parse_text(SAMPLE, fanuc)


# --------------------------------------------------------------------------- query validation


def test_query_modes() -> None:
    with pytest.raises(ProgramError):
        Query()
    with pytest.raises(ProgramError):
        Query(text="x", addr="F")
    with pytest.raises(ProgramError):
        Query(code="X1")
    assert Query(addr="F").mode == "word"
    assert Query(code="G1").mode == "code"
    assert Query(text="x").mode == "text"


# --------------------------------------------------------------------------- find


def test_find_word(prog, fanuc: Profile) -> None:
    ms = find(prog, fanuc, Query(addr="F"))
    assert [(m.lineno, m.text) for m in ms] == [(1, "F300"), (2, "F300."), (3, "F250")]
    ms = find(prog, fanuc, Query(addr="f", values=(D(300),)))
    assert [(m.lineno, m.text) for m in ms] == [(1, "F300"), (2, "F300.")]
    ms = find(prog, fanuc, Query(addr="F", min_value=D(260)))
    assert len(ms) == 2
    ms = find(prog, fanuc, Query(addr="F", max_value=D(260)))
    assert [m.text for m in ms] == ["F250"]
    assert ms[0].col == 12 and ms[0].length == 4 and ms[0].block_number == 30


def test_find_code(prog, fanuc: Profile) -> None:
    assert [m.lineno for m in find(prog, fanuc, Query(code="G01"))] == [1, 2]
    assert [m.lineno for m in find(prog, fanuc, Query(code="g1"))] == [1, 2]
    assert [m.text for m in find(prog, fanuc, Query(code="M08"))] == ["M8"]


def test_find_text_excludes_comments(prog, fanuc: Profile) -> None:
    ms = find(prog, fanuc, Query(text="F300"))
    assert [(m.lineno, m.col) for m in ms] == [(1, 12), (2, 11)]
    ms = find(prog, fanuc, Query(text="F300", in_comments=True))
    assert [(m.lineno, m.col) for m in ms] == [(1, 12), (1, 18), (2, 11), (3, 19)]
    ms = find(prog, fanuc, Query(text="F300", in_comments=True, ignore_case=False))
    assert len(ms) == 3


def test_find_regex_and_range(prog, fanuc: Profile) -> None:
    ms = find(prog, fanuc, Query(text=r"X\d\.", regex=True))
    assert [m.text for m in ms] == ["X1.", "X2.", "X3."]
    ms = find(prog, fanuc, Query(text=r"X\d\.", regex=True, range=Range.parse("N20-N30")))
    assert [m.text for m in ms] == ["X2.", "X3."]
    with pytest.raises(ProgramError, match="bad regex"):
        find(prog, fanuc, Query(text="(", regex=True))


# --------------------------------------------------------------------------- hints


def test_suggest(prog, fanuc: Profile) -> None:
    hints = suggest(prog, fanuc, "f")
    assert [(h.text, h.count, h.first_line, h.last_line) for h in hints] == [
        ("F300", 2, 1, 2),
        ("F250", 1, 3, 3),
    ]
    assert hints[0].first_block == 10 and hints[0].last_block == 20
    assert suggest(prog, fanuc, "Q") == []


def test_suggest_on_golden(fanuc: Profile) -> None:
    prog = parse_text(POCKET.read_text(), fanuc)
    hints = suggest(prog, fanuc, "F")
    assert [h.text for h in hints] == ["F300", "F900", "F200", "F600"]
    hints = suggest(prog, fanuc, "F", Range(tool=12))
    assert [h.text for h in hints] == ["F200", "F600"]
    addrs = dict(suggest_addresses(prog, fanuc))
    assert addrs["N"] == 47 and addrs["T"] == 2


# --------------------------------------------------------------------------- replace


def test_replace_word_keeps_style(prog, fanuc: Profile) -> None:
    res = replace(prog, ReplaceSpec(Query(addr="F", values=(D(300),)), to="250"), fanuc)
    lines = res.program.text.splitlines()
    assert lines[0] == "N10 G01 X1. F250 (F300 in comment)"
    assert lines[1] == "N20 G1 X2. F250."
    assert lines[2] == "N30 G02 X3. F250 ; f300"
    assert res.changed == [0, 1] and res.matches == 2


def test_replace_all_of_addr(prog, fanuc: Profile) -> None:
    res = replace(prog, ReplaceSpec(Query(addr="F"), to="100"), fanuc)
    assert res.matches == 3
    assert "F250" not in res.program.text


def test_replace_with_macro_value(prog, fanuc: Profile) -> None:
    res = replace(prog, ReplaceSpec(Query(addr="F", values=(D(250),)), to="#500"), fanuc)
    assert res.program.text.splitlines()[2] == "N30 G02 X3. F#500 ; f300"


def test_replace_code_keeps_padding(prog, fanuc: Profile) -> None:
    res = replace(prog, ReplaceSpec(Query(code="G1"), to="0"), fanuc)
    lines = res.program.text.splitlines()
    assert lines[0].startswith("N10 G00 ") and lines[1].startswith("N20 G0 ")
    res = replace(prog, ReplaceSpec(Query(code="M8"), to="7"), fanuc)
    assert res.program.text.splitlines()[3] == "N40 M7"


def test_replace_text_and_regex(prog, fanuc: Profile) -> None:
    res = replace(prog, ReplaceSpec(Query(text="F300"), to="F999"), fanuc)
    lines = res.program.text.splitlines()
    assert lines[0] == "N10 G01 X1. F999 (F300 in comment)"  # comment untouched
    assert lines[1] == "N20 G1 X2. F999."
    res = replace(prog, ReplaceSpec(Query(text=r"X(\d)\.", regex=True), to=r"X\1.0"), fanuc)
    assert "X1.0 " in res.program.text and "X3.0 " in res.program.text
    assert res.matches == 3


def test_replace_in_comments(prog, fanuc: Profile) -> None:
    res = replace(prog, ReplaceSpec(Query(text="F300", in_comments=True), to="F1"), fanuc)
    assert res.program.text.splitlines()[0] == "N10 G01 X1. F1 (F1 in comment)"


def test_replace_only_subset(prog, fanuc: Profile) -> None:
    ms = find(prog, fanuc, Query(addr="F"))
    only = frozenset((m.line, m.col) for m in ms[1:])
    res = replace(prog, ReplaceSpec(Query(addr="F"), to="1", only=only), fanuc)
    assert res.changed == [1, 2]


def test_replace_noop(prog, fanuc: Profile) -> None:
    res = replace(prog, ReplaceSpec(Query(addr="Q"), to="1"), fanuc)
    assert res.changed == [] and res.program.text == prog.text
    res = replace(prog, ReplaceSpec(Query(addr="F", values=(D(250),)), to="250"), fanuc)
    assert res.changed == []


def test_replace_warns_on_broken_result(prog, fanuc: Profile) -> None:
    res = replace(prog, ReplaceSpec(Query(text="X1."), to="X"), fanuc)
    assert any("word-no-value" in w for w in res.warnings)
