"""The CLI honours the layered config for profile, digits, rounding and backup."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from nctab import cli
from tests.conftest import GOLDEN_DIR

POCKET = GOLDEN_DIR / "pocket.nc"


@pytest.fixture(autouse=True)
def clear_config_cache():
    """Each test reads the config afresh, and leaves no cached value behind."""
    cli.config.cache_clear()
    yield
    cli.config.cache_clear()


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("nctab.config.user_config_file", lambda: tmp_path / "no-such-user.toml")
    shutil.copy(POCKET, tmp_path / "pocket.nc")
    return tmp_path


def run(*args: str, capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    code = cli.main(list(args))
    out, err = capsys.readouterr()
    return code, out, err


def test_project_profile_is_used(project: Path, capsys) -> None:
    (project / ".nctab.toml").write_text('[defaults]\nprofile = "haas-mill"\n', encoding="utf-8")
    code, out, _ = run("stats", "pocket.nc", "--json", capsys=capsys)
    assert code == 0 and '"haas-mill"' in out


def test_flag_beats_project_file(project: Path, capsys) -> None:
    (project / ".nctab.toml").write_text('[defaults]\nprofile = "haas-mill"\n', encoding="utf-8")
    code, out, _ = run("stats", "pocket.nc", "--json", "-p", "siemens-iso", capsys=capsys)
    assert code == 0 and '"siemens-iso"' in out


def test_digits_from_config(project: Path, capsys) -> None:
    (project / ".nctab.toml").write_text("[defaults]\ndigits = 1\n", encoding="utf-8")
    code, _, _ = run("shift", "pocket.nc", "--z", "-0.024", "-i", capsys=capsys)
    assert code == 0
    assert "Z-3." in (project / "pocket.nc").read_text()  # -3.024 rounded to 1 digit
    assert "Z-3.024" not in (project / "pocket.nc").read_text()


def test_rounding_from_config(project: Path, capsys) -> None:
    src = project / "r.nc"
    src.write_text("N10 G90 G01 X1.25 F100\n", encoding="utf-8")
    (project / ".nctab.toml").write_text(
        '[defaults]\ndigits = 1\nrounding = "HALF_EVEN"\n', encoding="utf-8"
    )
    code, _, _ = run("shift", "r.nc", "--x", "0", "--y", "0.0", "-i", capsys=capsys)
    assert code == 0
    # HALF_EVEN keeps 1.2; the default HALF_UP would give 1.3
    code, _, _ = run(
        "math", "r.nc", "--addr", "X", "--op", "mul", "--value", "1", "-i", capsys=capsys
    )
    assert "X1.2 " in (project / "r.nc").read_text()


def test_backup_from_config(project: Path, capsys) -> None:
    (project / ".nctab.toml").write_text("[editor]\nbackup = true\n", encoding="utf-8")
    code, _, _ = run("shift", "pocket.nc", "--z", "-0.02", "-i", capsys=capsys)
    assert code == 0
    assert (project / "pocket.nc.bak").exists()


def test_backup_off_by_config(project: Path, capsys) -> None:
    (project / ".nctab.toml").write_text("[editor]\nbackup = false\n", encoding="utf-8")
    code, _, _ = run("shift", "pocket.nc", "--z", "-0.02", "-i", capsys=capsys)
    assert code == 0
    assert not (project / "pocket.nc.bak").exists()


def test_arc_tolerance_from_config(project: Path, capsys) -> None:
    f = project / "arc.nc"
    f.write_text(
        "%\nF1\nS1 M03\nG90 G00 X0 Y0\nG02 X10.001 Y0. I5. J0.\nM30\n%\n", encoding="utf-8"
    )
    code, _, _ = run("check", "arc.nc", capsys=capsys)
    assert code == 0
    (project / ".nctab.toml").write_text("[defaults]\narc_tolerance = 0.0001\n", encoding="utf-8")
    cli.config.cache_clear()
    code, out, _ = run("check", "arc.nc", capsys=capsys)
    assert code == 2 and "arc-radius-mismatch" in out


def test_bad_config_warns_but_runs(project: Path, capsys) -> None:
    (project / ".nctab.toml").write_text("[defaults\n", encoding="utf-8")
    code, out, err = run("stats", "pocket.nc", "--json", capsys=capsys)
    assert code == 0
    assert "config:" in err and "invalid TOML" in err
    assert '"fanuc-mill"' in out


def test_profiles_marks_the_default(project: Path, capsys) -> None:
    (project / ".nctab.toml").write_text('[defaults]\nprofile = "fanuc-turn"\n', encoding="utf-8")
    code, out, _ = run("profiles", capsys=capsys)
    assert code == 0
    turn = next(line for line in out.splitlines() if line.startswith("fanuc-turn"))
    assert "(default)" in turn
    mill = next(line for line in out.splitlines() if line.startswith("fanuc-mill"))
    assert "(default)" not in mill
