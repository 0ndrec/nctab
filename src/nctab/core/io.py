"""Reading and writing NC files (goal.md §2 «Безопасность записи», §14).

* Encoding: UTF-8 (with or without BOM) is tried first, then cp1251 — shop
  floor programs with Cyrillic comments are usually cp1251 — then latin-1,
  which never fails. The detected encoding is stored on the ``Program`` and
  reused on write so the bytes stay the same.
* Writing is atomic: ``<file>.tmp`` then ``os.replace``.
* ``backup=True`` creates ``<file>.bak`` once — it is not overwritten if it
  already exists, so the first backup of a session survives repeated saves.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from nctab.core.model import Program
from nctab.core.parse import parse_text
from nctab.errors import NcIOError
from nctab.profiles.loader import Profile

_BOM = b"\xef\xbb\xbf"
_FALLBACK_ENCODINGS = ("cp1251", "latin-1")


def decode_bytes(data: bytes) -> tuple[str, str, bool]:
    """Return ``(text, encoding, had_bom)``."""
    if data.startswith(_BOM):
        return data[len(_BOM) :].decode("utf-8", errors="replace"), "utf-8", True
    try:
        return data.decode("utf-8"), "utf-8", False
    except UnicodeDecodeError:
        pass
    for enc in _FALLBACK_ENCODINGS:
        try:
            return data.decode(enc), enc, False
        except UnicodeDecodeError:
            continue
    raise NcIOError("could not decode file")  # pragma: no cover — latin-1 never fails


def encode_program(program: Program) -> bytes:
    data = program.text.encode(program.encoding, errors="replace")
    return _BOM + data if program.bom else data


def read_program(path: str | Path, profile: Profile) -> Program:
    path = Path(path)
    try:
        data = path.read_bytes()
    except OSError as e:
        raise NcIOError(f"cannot read {path}: {e.strerror or e}") from e
    text, encoding, bom = decode_bytes(data)
    program = parse_text(text, profile)
    program.encoding = encoding
    program.bom = bom
    return program


def write_program(program: Program, path: str | Path, *, backup: bool = False) -> Path:
    """Atomically write ``program`` to ``path``. Returns the path written."""
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    try:
        if backup and path.exists():
            bak = path.with_name(path.name + ".bak")
            if not bak.exists():
                shutil.copy2(path, bak)
        tmp.write_bytes(encode_program(program))
        os.replace(tmp, path)
    except OSError as e:
        tmp.unlink(missing_ok=True)
        raise NcIOError(f"cannot write {path}: {e.strerror or e}") from e
    return path
