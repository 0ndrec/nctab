from __future__ import annotations

from pathlib import Path

import pytest

from nctab.errors import ProfileError
from nctab.profiles.loader import builtin_profile_ids, load_profile


def test_builtins_load() -> None:
    ids = builtin_profile_ids()
    assert "fanuc-mill" in ids
    assert "generic-iso" in ids
    for pid in ids:
        p = load_profile(pid)
        assert p.id == pid
        assert p.axes
        assert p.gcodes


def test_default_profile() -> None:
    assert load_profile(None).id == "fanuc-mill"


def test_unknown_profile() -> None:
    with pytest.raises(ProfileError, match="unknown profile"):
        load_profile("does-not-exist")


def test_profile_from_path(tmp_path: Path) -> None:
    f = tmp_path / "my.toml"
    f.write_text('id = "my"\nlabel = "Mine"\naxes = ["x", "z"]\n', encoding="utf-8")
    p = load_profile(str(f))
    assert p.id == "my"
    assert p.axes == ["X", "Z"]  # single letters are upper-cased


def test_bad_toml(tmp_path: Path) -> None:
    f = tmp_path / "bad.toml"
    f.write_text("id = \n", encoding="utf-8")
    with pytest.raises(ProfileError, match="invalid TOML"):
        load_profile(str(f))


def test_extra_key_rejected(tmp_path: Path) -> None:
    f = tmp_path / "extra.toml"
    f.write_text('id = "e"\nlabel = "E"\nbogus = 1\n', encoding="utf-8")
    with pytest.raises(ProfileError):
        load_profile(str(f))


def test_describe() -> None:
    p = load_profile("fanuc-mill")
    assert p.describe("G", 1) == "Linear interpolation"
    assert p.describe("M", 6) == "Tool change"
    assert p.describe("G", 999) is None
