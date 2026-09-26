from __future__ import annotations

from pathlib import Path

import pytest

from nctab.core.io import decode_bytes, encode_program, read_program, write_program
from nctab.errors import NcIOError
from nctab.profiles.loader import Profile


def test_utf8_roundtrip(tmp_path: Path, fanuc: Profile) -> None:
    src = tmp_path / "a.nc"
    data = "%\nN10 G01 X1. (Фреза)\n%\n".encode()
    src.write_bytes(data)
    prog = read_program(src, fanuc)
    assert prog.encoding == "utf-8"
    assert prog.bom is False
    assert encode_program(prog) == data


def test_utf8_bom_roundtrip(tmp_path: Path, fanuc: Profile) -> None:
    src = tmp_path / "a.nc"
    data = b"\xef\xbb\xbf" + b"N10 X1.\n"
    src.write_bytes(data)
    prog = read_program(src, fanuc)
    assert prog.bom is True
    assert encode_program(prog) == data


def test_cp1251_roundtrip(tmp_path: Path, fanuc: Profile) -> None:
    src = tmp_path / "a.nc"
    data = "N10 G01 X1. (ЧЕРНОВАЯ)\r\nN20 M30\r\n".encode("cp1251")
    src.write_bytes(data)
    prog = read_program(src, fanuc)
    assert prog.encoding == "cp1251"
    assert prog.lines[0].comment == "(ЧЕРНОВАЯ)"
    assert encode_program(prog) == data


def test_decode_fallback_latin1() -> None:
    # 0x98 is undefined in cp1251 → falls through to latin-1
    text, enc, bom = decode_bytes(b"X1. \x98\n")
    assert enc == "latin-1"
    assert bom is False
    assert text.endswith("\n")


def test_write_atomic_and_backup(tmp_path: Path, fanuc: Profile) -> None:
    src = tmp_path / "a.nc"
    src.write_text("N10 X1.\n", encoding="utf-8")
    prog = read_program(src, fanuc)

    write_program(prog, src, backup=True)
    bak = tmp_path / "a.nc.bak"
    assert bak.read_text(encoding="utf-8") == "N10 X1.\n"
    assert not (tmp_path / "a.nc.tmp").exists()

    # second save must not overwrite the first backup
    src.write_text("N10 X2.\n", encoding="utf-8")
    prog2 = read_program(src, fanuc)
    write_program(prog2, src, backup=True)
    assert bak.read_text(encoding="utf-8") == "N10 X1.\n"
    assert src.read_text(encoding="utf-8") == "N10 X2.\n"


def test_write_to_new_path(tmp_path: Path, fanuc: Profile) -> None:
    src = tmp_path / "a.nc"
    src.write_text("N10 X1.\n", encoding="utf-8")
    prog = read_program(src, fanuc)
    out = write_program(prog, tmp_path / "b.nc", backup=True)
    assert out.read_text(encoding="utf-8") == "N10 X1.\n"
    assert not (tmp_path / "b.nc.bak").exists()


def test_read_missing_raises(tmp_path: Path, fanuc: Profile) -> None:
    with pytest.raises(NcIOError, match="cannot read"):
        read_program(tmp_path / "missing.nc", fanuc)


def test_write_to_bad_dir_raises(tmp_path: Path, fanuc: Profile) -> None:
    src = tmp_path / "a.nc"
    src.write_text("N10 X1.\n", encoding="utf-8")
    prog = read_program(src, fanuc)
    with pytest.raises(NcIOError, match="cannot write"):
        write_program(prog, tmp_path / "no" / "such" / "dir" / "b.nc")
