from __future__ import annotations

import tomllib
from pathlib import Path

from nctab.config import (
    PROJECT_FILE,
    Settings,
    find_project_config,
    load_config,
    user_config_file,
)

NO_LAYERS = {"include_user": False, "include_project": False}


def test_defaults() -> None:
    c = load_config(env={}, **NO_LAYERS)
    assert c.defaults.profile == "fanuc-mill"
    assert c.defaults.digits == "preserve"
    assert c.defaults.digits_or_none is None
    assert c.defaults.rounding == "HALF_UP"
    assert c.editor.backup is True and c.editor.autosave_sec == 0
    assert c.sources == [] and c.problems == []


def test_project_file_is_found_upwards(tmp_path: Path) -> None:
    (tmp_path / PROJECT_FILE).write_text('[defaults]\nprofile = "haas-mill"\n', encoding="utf-8")
    deep = tmp_path / "op20" / "rev3"
    deep.mkdir(parents=True)
    assert find_project_config(deep) == tmp_path / PROJECT_FILE
    c = load_config(start=deep, env={}, include_user=False)
    assert c.defaults.profile == "haas-mill"
    assert c.sources == [tmp_path / PROJECT_FILE]


def test_project_overrides_only_what_it_sets(tmp_path: Path) -> None:
    (tmp_path / PROJECT_FILE).write_text(
        '[defaults]\ndigits = 3\n\n[ui]\ntheme = "light"\n', encoding="utf-8"
    )
    c = load_config(start=tmp_path, env={}, include_user=False)
    assert c.defaults.digits == 3 and c.defaults.digits_or_none == 3
    assert c.defaults.profile == "fanuc-mill"  # untouched
    assert c.ui.theme == "light"
    assert c.ui.keybindings == "default"  # untouched


def test_env_beats_files(tmp_path: Path) -> None:
    (tmp_path / PROJECT_FILE).write_text('[defaults]\nprofile = "haas-mill"\n', encoding="utf-8")
    c = load_config(
        start=tmp_path,
        env={"NCTAB_PROFILE": "siemens-iso", "NCTAB_DIGITS": "4", "NCTAB_BACKUP": "0"},
        include_user=False,
    )
    assert c.defaults.profile == "siemens-iso"
    assert c.defaults.digits == 4
    assert c.editor.backup is False


def test_env_preserve_and_booleans(tmp_path: Path) -> None:
    c = load_config(
        start=tmp_path,
        env={"NCTAB_DIGITS": "preserve", "NCTAB_BACKUP": "yes", "NCTAB_AUTOSAVE_SEC": "30"},
        include_user=False,
    )
    assert c.defaults.digits == "preserve"
    assert c.editor.backup is True
    assert c.editor.autosave_sec == 30


def test_bad_env_is_reported_not_fatal(tmp_path: Path) -> None:
    c = load_config(start=tmp_path, env={"NCTAB_DIGITS": "three"}, include_user=False)
    assert c.defaults.digits == "preserve"
    assert any("NCTAB_DIGITS" in p for p in c.problems)


def test_malformed_toml_is_reported_not_fatal(tmp_path: Path) -> None:
    (tmp_path / PROJECT_FILE).write_text("[defaults\nprofile =", encoding="utf-8")
    c = load_config(start=tmp_path, env={}, include_user=False)
    assert c.defaults.profile == "fanuc-mill"
    assert any("invalid TOML" in p for p in c.problems)
    assert c.sources == []


def test_unknown_key_is_rejected_with_defaults_kept(tmp_path: Path) -> None:
    (tmp_path / PROJECT_FILE).write_text("[defaults]\nbogus = 1\n", encoding="utf-8")
    c = load_config(start=tmp_path, env={}, include_user=False)
    assert c.defaults.profile == "fanuc-mill"
    assert any("rejected" in p for p in c.problems)


def test_out_of_range_value_is_rejected(tmp_path: Path) -> None:
    (tmp_path / PROJECT_FILE).write_text("[editor]\ntab_width = 0\n", encoding="utf-8")
    c = load_config(start=tmp_path, env={}, include_user=False)
    assert c.editor.tab_width == 4
    assert c.problems


def test_no_project_file_found(tmp_path: Path) -> None:
    assert find_project_config(tmp_path) is None


def test_user_config_path_is_under_nctab() -> None:
    assert user_config_file().name == "config.toml"
    assert user_config_file().parent.name == "nctab"


def test_settings_round_trip() -> None:
    """The documented TOML in goal.md §12 loads as written."""
    text = """
    [ui]
    theme = "dark"
    keybindings = "default"

    [editor]
    tab_width = 4
    show_invisibles = false
    backup = true
    autosave_sec = 0

    [defaults]
    profile = "fanuc-mill"
    digits = 3
    """
    s = Settings.model_validate(tomllib.loads(text))
    assert s.ui.theme == "dark"
    assert s.defaults.digits == 3
    assert s.editor.tab_width == 4
