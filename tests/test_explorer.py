"""The G-code folder setting and the file explorer in the left panel."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from nctab.app import NctabApp
from nctab.config import Config, DefaultsConfig, Settings, load_config
from nctab.tui.explorer import Explorer, looks_like_nc, nc_files
from tests.conftest import GOLDEN_DIR

POCKET = GOLDEN_DIR / "pocket.nc"


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    """A shop folder: programs, a sub-folder, and the noise that surrounds them."""
    shutil.copy(POCKET, tmp_path / "pocket.nc")
    (tmp_path / "part.ngc").write_text("%\nN10 M30\n%\n", encoding="utf-8")
    (tmp_path / "OP20.TAP").write_text("%\nN10 M30\n%\n", encoding="utf-8")
    (tmp_path / "notes.md").write_text("not a program\n", encoding="utf-8")
    (tmp_path / "pocket.nc.bak").write_text("%\n%\n", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    (tmp_path / ".git").mkdir()
    return tmp_path


def app_config(directory: Path) -> Config:
    return Config(settings=Settings(defaults=DefaultsConfig(directory=str(directory))))


# --------------------------------------------------------------------------- suffixes


@pytest.mark.parametrize(
    "name",
    ["a.nc", "a.NC", "a.ngc", "a.gcode", "a.tap", "a.mpf", "a.eia", "a.iso", "a.txt", "a.g"],
)
def test_nc_suffixes_are_offered(name: str) -> None:
    assert looks_like_nc(Path(name))


@pytest.mark.parametrize("name", ["a.md", "a.py", "a.pdf", "a.bak", "a.tmp", "a", "a.nc.bak"])
def test_other_suffixes_are_not(name: str) -> None:
    assert not looks_like_nc(Path(name))


def test_nc_files_lists_programs_only(folder: Path) -> None:
    assert [p.name for p in nc_files(folder)] == ["OP20.TAP", "part.ngc", "pocket.nc"]


def test_nc_files_on_a_missing_folder_is_empty(tmp_path: Path) -> None:
    assert nc_files(tmp_path / "nope") == []


# --------------------------------------------------------------------------- config


def test_directory_defaults_to_the_working_directory() -> None:
    config = load_config(env={}, include_user=False, include_project=False)
    assert config.defaults.directory == ""
    assert config.defaults.gcode_dir == Path.cwd()


def test_directory_from_a_project_file(tmp_path: Path) -> None:
    (tmp_path / ".nctab.toml").write_text('[defaults]\ndirectory = "/mnt/nc"\n', encoding="utf-8")
    config = load_config(start=tmp_path, env={}, include_user=False)
    assert config.defaults.gcode_dir == Path("/mnt/nc")


def test_directory_from_the_environment(tmp_path: Path) -> None:
    config = load_config(start=tmp_path, env={"NCTAB_DIR": str(tmp_path)}, include_user=False)
    assert config.defaults.gcode_dir == tmp_path


def test_directory_expands_a_tilde() -> None:
    config = Config(settings=Settings(defaults=DefaultsConfig(directory="~/nc")))
    resolved = config.defaults.gcode_dir
    assert "~" not in str(resolved)
    assert resolved.is_absolute()


def test_resolve_finds_a_bare_name_in_the_folder(folder: Path) -> None:
    config = app_config(folder)
    assert config.resolve("pocket.nc") == folder / "pocket.nc"


def test_resolve_prefers_the_working_directory(folder: Path, monkeypatch) -> None:
    """A file that exists where the user is standing wins over the shop folder."""
    here = folder / "sub"
    (here / "pocket.nc").write_text("%\nN10 M30\n%\n", encoding="utf-8")
    monkeypatch.chdir(here)
    assert app_config(folder).resolve("pocket.nc") == Path("pocket.nc")


def test_resolve_leaves_an_absolute_path_alone(folder: Path, tmp_path: Path) -> None:
    other = tmp_path.parent / "elsewhere.nc"
    assert app_config(folder).resolve(other) == other


def test_resolve_returns_a_missing_name_unchanged(folder: Path) -> None:
    """The caller reports the missing file, with the name the user typed."""
    assert app_config(folder).resolve("nope.nc") == Path("nope.nc")


# --------------------------------------------------------------------------- the panel


async def test_explorer_lists_programs_and_folders(folder: Path) -> None:
    app = NctabApp(config=app_config(folder))
    async with app.run_test(size=(140, 44)) as pilot:
        await pilot.pause()
        await pilot.pause()
        labels = sorted(str(node.label) for node in app.explorer.root.children)
        assert labels == ["OP20.TAP", "part.ngc", "pocket.nc", "sub"]
        assert "notes.md" not in labels
        assert "pocket.nc.bak" not in labels
        assert ".git" not in labels


async def test_side_panel_starts_on_files_with_no_file_open(folder: Path) -> None:
    app = NctabApp(config=app_config(folder))
    async with app.run_test(size=(140, 44)) as pilot:
        await pilot.pause()
        assert app.side.active == "tab-files"


async def test_side_panel_starts_on_the_outline_with_a_file(folder: Path) -> None:
    app = NctabApp(path=folder / "pocket.nc", config=app_config(folder))
    async with app.run_test(size=(140, 44)) as pilot:
        await pilot.pause()
        assert app.side.active == "tab-outline"


async def test_f9_toggles_and_focuses(folder: Path) -> None:
    app = NctabApp(path=folder / "pocket.nc", config=app_config(folder))
    async with app.run_test(size=(140, 44)) as pilot:
        await pilot.pause()
        await pilot.press("f9")
        await pilot.pause()
        assert app.side.active == "tab-files"
        assert app.focused is app.explorer
        await pilot.press("f9")
        await pilot.pause()
        assert app.side.active == "tab-outline"
        assert app.focused is app.outline


async def test_opening_a_file_from_the_list(folder: Path) -> None:
    app = NctabApp(config=app_config(folder))
    async with app.run_test(size=(140, 44)) as pilot:
        await pilot.pause()
        app.post_message(Explorer.Open(folder / "pocket.nc"))
        await pilot.pause()
        await pilot.pause()
        assert app.path == folder / "pocket.nc"
        assert app.editor.document.line_count == 56
        assert app.side.active == "tab-outline"  # the outline is what you want next
        assert app.modified is False


async def test_unsaved_changes_block_the_open(folder: Path) -> None:
    app = NctabApp(path=folder / "pocket.nc", config=app_config(folder))
    async with app.run_test(size=(140, 44)) as pilot:
        await pilot.pause()
        app.editor.insert("(edit)\n", (0, 0))
        app.mark_modified()
        await pilot.pause()

        app.post_message(Explorer.Open(folder / "part.ngc"))
        await pilot.pause()
        await pilot.pause()
        assert app.path == folder / "pocket.nc"  # still the edited file
        assert app.modified is True

        app.action_discard_and_open()
        await pilot.pause()
        await pilot.pause()
        assert app.path == folder / "part.ngc"
        assert app.modified is False


async def test_discard_with_nothing_waiting(folder: Path) -> None:
    app = NctabApp(path=folder / "pocket.nc", config=app_config(folder))
    async with app.run_test(size=(140, 44)) as pilot:
        await pilot.pause()
        app.action_discard_and_open()
        await pilot.pause()
        assert "nothing waiting" in app.status.message
        assert app.path == folder / "pocket.nc"


async def test_saving_clears_the_pending_open(folder: Path) -> None:
    """After a save the file list should just work, with no stale offer."""
    app = NctabApp(path=folder / "pocket.nc", config=app_config(folder))
    async with app.run_test(size=(140, 44)) as pilot:
        await pilot.pause()
        app.editor.insert("(edit)\n", (0, 0))
        app.mark_modified()
        await pilot.pause()
        app.action_save()
        await pilot.pause()
        assert app.modified is False

        app.post_message(Explorer.Open(folder / "part.ngc"))
        await pilot.pause()
        await pilot.pause()
        assert app.path == folder / "part.ngc"
