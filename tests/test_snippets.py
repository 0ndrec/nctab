"""Snippet catalogue: loading, validation, rendering."""

from __future__ import annotations

from pathlib import Path

import pytest

from nctab.core.parse import parse_text
from nctab.errors import ProgramError
from nctab.profiles.loader import load_profile
from nctab.snippets import Snippet, load_snippets, user_snippets_dir
from nctab.snippets.loader import SnippetField

# --------------------------------------------------------------------------- loading


def test_builtin_catalogue_for_each_profile() -> None:
    mill = load_snippets("fanuc-mill")
    assert mill.problems == []
    assert {s.id for s in mill} >= {
        "tool-change",
        "program-header",
        "program-footer",
        "safe-retract",
        "drill-cycle",
        "peck-drill",
    }
    turn = load_snippets("fanuc-turn")
    assert "turn-header" in {s.id for s in turn}
    assert "drill-cycle" not in {s.id for s in turn}  # milling only


def test_common_snippets_reach_every_profile() -> None:
    for profile_id in ("fanuc-mill", "fanuc-turn", "generic-iso", "haas-mill"):
        catalogue = load_snippets(profile_id)
        assert "tool-change" in catalogue.snippets, profile_id
        assert catalogue.problems == []


def test_catalogue_is_sorted_by_title() -> None:
    titles = [s.title for s in load_snippets("fanuc-mill")]
    assert titles == sorted(titles)


def test_unknown_snippet_lists_what_is_available() -> None:
    catalogue = load_snippets("fanuc-mill")
    with pytest.raises(ProgramError, match="tool-change"):
        catalogue.get("no-such-snippet")


def test_user_snippet_shadows_a_builtin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("nctab.snippets.loader.user_snippets_dir", lambda: tmp_path)
    (tmp_path / "tool-change.toml").write_text(
        'id = "tool-change"\ntitle = "Shop tool change"\nbody = "M06\\n"\n', encoding="utf-8"
    )
    catalogue = load_snippets("fanuc-mill")
    assert catalogue.get("tool-change").title == "Shop tool change"
    assert catalogue.problems == []


def test_user_profile_folder_shadows_the_user_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("nctab.snippets.loader.user_snippets_dir", lambda: tmp_path)
    (tmp_path / "x.toml").write_text('id = "x"\ntitle = "root"\nbody = "A\\n"\n', encoding="utf-8")
    folder = tmp_path / "fanuc-mill"
    folder.mkdir()
    (folder / "x.toml").write_text('id = "x"\ntitle = "profile"\nbody = "B\\n"\n', encoding="utf-8")
    assert load_snippets("fanuc-mill").get("x").title == "profile"


def test_broken_user_snippet_is_reported_not_fatal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("nctab.snippets.loader.user_snippets_dir", lambda: tmp_path)
    (tmp_path / "bad.toml").write_text("id = \n", encoding="utf-8")
    (tmp_path / "missing-body.toml").write_text('id = "mb"\ntitle = "t"\n', encoding="utf-8")
    catalogue = load_snippets("fanuc-mill")
    assert len(catalogue.problems) == 2
    assert "tool-change" in catalogue.snippets  # the built-ins still loaded


def test_user_snippets_dir_is_under_nctab() -> None:
    assert user_snippets_dir().name == "snippets"
    assert user_snippets_dir().parent.name == "nctab"


# --------------------------------------------------------------------------- rendering


def test_render_with_values() -> None:
    catalogue = load_snippets("fanuc-mill")
    body = catalogue.get("tool-change").render({"T": 7, "S": 4500})
    assert body == "M05\nG28 G91 Z0\nG90\nT7 M06\nG43 H7 Z50.\nS4500 M03\n"


def test_render_uses_defaults() -> None:
    body = load_snippets("fanuc-mill").get("drill-cycle").render({})
    assert "Z-10. R2. F150" in body


def test_format_spec_pads() -> None:
    body = load_snippets("fanuc-mill").get("program-header").render({"O": 20})
    assert "O0020" in body


def test_floats_are_written_the_nc_way() -> None:
    """A bare Z-10 can be read in the least significant increment; keep the dot."""
    catalogue = load_snippets("fanuc-mill")
    assert "Z-10." in catalogue.get("drill-cycle").render({"Z": -10})
    assert "Z-10.0" not in catalogue.get("drill-cycle").render({"Z": -10})
    assert "Z-12.75" in catalogue.get("drill-cycle").render({"Z": "-12.75"})
    assert "Z100." in catalogue.get("safe-retract").render({"Z": 100})


def test_body_always_ends_with_a_newline() -> None:
    snippet = Snippet(id="x", title="x", body="G00 X1.")
    assert snippet.render({}) == "G00 X1.\n"


def test_no_fields_snippet() -> None:
    body = load_snippets("fanuc-mill").get("program-footer").render({})
    assert body.startswith("M09") and body.rstrip().endswith("%")


# --------------------------------------------------------------------------- validation


def test_required_field_without_default() -> None:
    field = SnippetField(name="T", type="int")
    with pytest.raises(ProgramError, match="required"):
        field.coerce(None)


def test_int_field_rejects_text() -> None:
    field = SnippetField(name="T", type="int", default=1)
    with pytest.raises(ProgramError, match="whole number"):
        field.coerce("abc")


def test_float_field_rejects_text() -> None:
    field = SnippetField(name="Z", type="float", default=0)
    with pytest.raises(ProgramError, match="not a number"):
        field.coerce("deep")


def test_range_is_enforced() -> None:
    field = SnippetField(name="T", label="Tool", type="int", min=1, max=99, default=1)
    assert field.coerce(50) == "50"
    with pytest.raises(ProgramError, match="at least 1"):
        field.coerce(0)
    with pytest.raises(ProgramError, match="at most 99"):
        field.coerce(100)


def test_choice_is_enforced() -> None:
    field = SnippetField(name="W", type="choice", choices=["G54", "G55"], default="G54")
    assert field.coerce("G55") == "G55"
    with pytest.raises(ProgramError, match="not one of"):
        field.coerce("G99")


def test_label_defaults_to_the_name() -> None:
    assert SnippetField(name="T").label == "T"
    assert SnippetField(name="T", label="Tool").label == "Tool"


def test_placeholder_without_a_field_is_reported() -> None:
    snippet = Snippet(id="x", title="x", body="T{T} M06\n")
    with pytest.raises(ProgramError, match="no field for placeholder"):
        snippet.render({})


def test_malformed_body_is_reported() -> None:
    snippet = Snippet(id="x", title="x", body="T{ M06\n")
    with pytest.raises(ProgramError, match="malformed body"):
        snippet.render({})


def test_rendered_snippets_parse_as_nc() -> None:
    """Whatever a snippet produces must be valid NC for its profile."""
    for profile_id in ("fanuc-mill", "fanuc-turn"):
        profile = load_profile(profile_id)
        for snippet in load_snippets(profile_id):
            program = parse_text(snippet.render({}), profile)
            assert program.issues == [], f"{profile_id}/{snippet.id}: {program.issues}"
