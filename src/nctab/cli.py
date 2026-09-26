"""Command-line entry point (goal.md section 5.1).

Exit codes: 0 ok | 1 program/operation error | 2 parse/validation | 3 I/O.

Write safety (section 14): transforms print a diff and change nothing unless
``--in-place`` / ``-i`` or ``--output`` / ``-o`` is given. ``--dry-run`` forces
the preview even when a target is given.
"""

from __future__ import annotations

import contextlib
import difflib
import json
import sys
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from functools import cache
from pathlib import Path
from typing import Annotated, Literal

from cyclopts import App, Parameter
from rich.console import Console
from rich.table import Table
from rich.text import Text as RText

from nctab import __version__
from nctab.check import CheckReport, check_program, rule_codes
from nctab.config import Config, load_config
from nctab.core.format import Rounding
from nctab.core.io import read_program, write_program
from nctab.core.model import Program
from nctab.diff import DiffOptions, DiffResult, build_report, diff_programs, unified
from nctab.errors import NcIOError, NctabError, ParseError, ProgramError
from nctab.ops.addr_math import MathOp, MathSpec, addr_math
from nctab.ops.base import OpResult, Range
from nctab.ops.case import CaseSpec, change_case
from nctab.ops.feeds import FeedsSpec, feeds
from nctab.ops.find import Match, Query, ReplaceSpec, find, replace, suggest
from nctab.ops.mirror import MirrorSpec, mirror
from nctab.ops.renumber import RenumberSpec, renumber
from nctab.ops.rotate import RotateSpec, rotate
from nctab.ops.scale import LINEAR_AXES, ScaleSpec, scale
from nctab.ops.shift import ShiftSpec, shift
from nctab.ops.stats import Stats, compute_stats
from nctab.ops.strip import StripSpec, strip
from nctab.ops.tools import ToolsReport, collect_tools
from nctab.profiles.loader import Profile, builtin_profile_ids, load_profile
from nctab.snippets import load_snippets

app = App(
    name="nctab",
    help="Terminal NC/G-code editor and toolkit.",
    version=__version__,
    help_format="markdown",
)


def _console(*, stderr: bool = False) -> Console:
    """A console that cannot crash on a character the terminal cannot encode.

    Shop-floor Windows consoles often run a legacy code page, where rich raises
    UnicodeEncodeError instead of printing. Replacing the character is always
    better than losing the command's output.
    """
    stream = sys.stderr if stderr else sys.stdout
    reconfigure = getattr(stream, "reconfigure", None)
    if reconfigure is not None:
        # a stream without an encoding (a pipe under some hosts) cannot be reconfigured
        with contextlib.suppress(ValueError, OSError):
            reconfigure(errors="replace")
    return Console(stderr=stderr)


_out = _console()
_err = _console(stderr=True)


# --------------------------------------------------------------------------- shared options


@Parameter(name="*")
@dataclass(frozen=True)
class Common:
    """Options shared by every command."""

    profile: Annotated[str | None, Parameter(name=["--profile", "-p"])] = None
    """Machine profile id or path to a profile ``.toml``. Defaults to the configured profile."""

    json: bool = False
    """Print machine-readable JSON instead of a table."""

    quiet: Annotated[bool, Parameter(name=["--quiet", "-q"])] = False
    """Suppress informational output."""


@Parameter(name="*")
@dataclass(frozen=True)
class Out:
    """Where a transform writes its result."""

    in_place: Annotated[bool, Parameter(name=["--in-place", "-i"])] = False
    """Overwrite FILE."""

    output: Annotated[Path | None, Parameter(name=["--output", "-o"])] = None
    """Write to this path instead of FILE."""

    dry_run: bool = False
    """Only show the diff, even if -i / -o is given."""

    backup: bool | None = None
    """Keep a ``FILE.bak`` copy before overwriting (created once). Defaults to the config."""

    range: Annotated[str | None, Parameter(name=["--range", "-r"])] = None
    """Limit to lines ``10-200``, blocks ``N100-N500`` or one tool ``T12``."""

    digits: int | None = None
    """Round results to this many fractional digits instead of keeping the source style."""

    rounding: Rounding | None = None
    """Tie-breaking when rounding: HALF_UP (default) or HALF_EVEN."""


def _dec(text: str | None, name: str) -> Decimal | None:
    if text is None:
        return None
    try:
        return Decimal(text.strip())
    except InvalidOperation as e:
        raise ProgramError(f"{name}: {text!r} is not a number") from e


def _dec_list(text: str | None, name: str) -> tuple[Decimal, ...]:
    if not text:
        return ()
    out: list[Decimal] = []
    for part in text.split(","):
        if part.strip():
            v = _dec(part, name)
            assert v is not None
            out.append(v)
    return tuple(out)


@cache
def config() -> Config:
    """The effective configuration, read once per process."""
    cfg = load_config()
    for problem in cfg.problems:
        _err.print(f"[yellow]config:[/] {problem}")
    return cfg


def _resolve_profile(common: Common) -> Profile:
    return load_profile(common.profile or config().defaults.profile)


def _digits(out: Out) -> int | None:
    return out.digits if out.digits is not None else config().defaults.digits_or_none


def _rounding(out: Out) -> Rounding:
    return out.rounding or config().defaults.rounding


def _backup(out: Out) -> bool:
    return out.backup if out.backup is not None else config().editor.backup


def _load(file: Path, common: Common) -> tuple[Profile, Program]:
    profile = _resolve_profile(common)
    return profile, read_program(config().resolve(file), profile)


def _finish(before: Program, result: OpResult, src: Path, out: Out, common: Common) -> None:
    # src is what the user typed; --in-place must write to the file actually read,
    # which may have come from the configured G-code folder. --output is theirs.
    src = config().resolve(src)
    target = out.output or src
    writing = (out.in_place or out.output is not None) and not out.dry_run
    diff = "".join(
        difflib.unified_diff(
            before.text.splitlines(keepends=True),
            result.program.text.splitlines(keepends=True),
            fromfile=str(src),
            tofile=str(target),
        )
    )
    written: str | None = None
    if writing and result.changed:
        write_program(result.program, target, backup=_backup(out))
        written = str(target)
    elif writing and out.output is not None:
        write_program(result.program, target, backup=False)  # explicit -o: always produce the file
        written = str(target)

    if common.json:
        _out.print_json(
            json.dumps(
                {
                    "changed_lines": result.changed_lines,
                    "matches": result.matches,
                    "warnings": result.warnings,
                    "written": written,
                    "diff": diff,
                }
            )
        )
        return

    if not writing and diff:
        _out.print(RText(diff, no_wrap=True), end="")
    for w in result.warnings:
        _err.print(f"[yellow]warning:[/] {w}")
    if common.quiet:
        return
    summary = f"{result.changed_lines} lines changed, {result.matches} words"
    if written:
        _err.print(f"{summary}; written to {written}")
    elif writing:
        _err.print(f"{summary}; nothing to write")
    else:
        _err.print(f"{summary} (dry run - use -i or -o to write)")


# --------------------------------------------------------------------------- editor / info


@app.default
def default(file: Path | None = None, *, common: Common | None = None) -> None:
    """Open the TUI editor (``nctab FILE`` is the same as ``nctab edit FILE``)."""
    edit(file, common=common)


@app.command
def edit(file: Path | None = None, *, common: Common | None = None) -> None:
    """Open FILE in the TUI editor.

    Keys: ``Ctrl+F`` find, ``F3``/``Shift+F3`` next and previous match,
    ``Ctrl+G`` go to a line or ``N`` block, ``F4``/``Shift+F4`` tool changes,
    ``F5``/``Shift+F5`` motion changes, ``Ctrl+B`` then a letter to bookmark,
    ``Ctrl+J`` then a letter to jump, ``Ctrl+H`` replace, ``Ctrl+N`` renumber,
    ``Ctrl+T`` transform, ``Ctrl+O`` outline, ``Ctrl+S`` save, ``F1`` help.
    """
    from nctab.app import run  # imported late so the CLI starts without Textual

    common = common or Common()
    cfg = config()
    profile = _resolve_profile(common)
    if file is not None:
        file = cfg.resolve(file)
        if not file.exists():
            raise NcIOError(f"cannot read {file}: no such file")
    run(path=file, profile=profile, config=cfg)


@app.command
def stats(file: Path, *, path: bool = True, common: Common | None = None) -> None:
    """Overview of FILE: line counts, axis min/max, G/M codes, tools, feeds, speeds.

    Path lengths are a geometric estimate, not a cycle time: no machine kinematics,
    no acceleration. Pass ``--no-path`` to skip the modal walk on very large files.
    """
    common = common or Common()
    profile, program = _load(file, common)
    report = compute_stats(program, profile, file=str(file), path=path)
    if common.json:
        _out.print_json(report.model_dump_json())
    else:
        _print_stats(report)


@app.command
def profiles() -> None:
    """List available machine profiles."""
    active = config().defaults.profile
    for pid in builtin_profile_ids():
        p = load_profile(pid)
        mark = " [green](default)[/]" if pid == active else ""
        _out.print(f"[bold]{pid}[/]  {p.label}{mark}")


@app.command
def tools(file: Path, *, common: Common | None = None) -> None:
    """List the tools used by FILE, with their offsets, speeds, feeds and section."""
    common = common or Common()
    profile, program = _load(file, common)
    report = collect_tools(program, profile, file=str(file))
    if common.json:
        _out.print_json(report.model_dump_json())
        return
    _print_tools(report)


@app.command
def check(
    file: Path,
    *,
    strict: bool = False,
    arc_tolerance: str | None = None,
    rules: bool = False,
    common: Common | None = None,
) -> None:
    """Validate FILE: syntax, arcs, compensation, spindle, program end.

    Exit code is 2 when an error is found, or also on a warning with ``--strict``.
    ``--rules`` lists every diagnostic code instead of checking.
    """
    common = common or Common()
    if rules:
        for code in rule_codes():
            _out.print(code)
        return
    profile, program = _load(file, common)
    tol = _dec(arc_tolerance, "--arc-tolerance")
    if tol is None:
        tol = Decimal(str(config().defaults.arc_tolerance))
    report = CheckReport.build(
        check_program(program, profile, arc_tolerance=tol),
        profile=profile.id,
        lines=len(program),
        file=str(file),
    )
    if common.json:
        _out.print_json(report.model_dump_json())
    else:
        _print_check(report, common)
    if report.errors or (strict and report.warnings):
        raise ParseError(
            f"{report.errors} errors, {report.warnings} warnings in {file}",
        )


@app.command(name="diff")
def diff_cmd(
    a: Path,
    b: Path,
    *,
    ignore_n: bool = False,
    ignore_whitespace: bool = False,
    ignore_comments: bool = False,
    ignore_zeros: bool = False,
    ignore_case: bool = False,
    ignore_blank: bool = False,
    normalize_all: bool = False,
    context: int = 3,
    side_by_side: bool = False,
    common: Common | None = None,
) -> None:
    """Compare two NC programs, ignoring differences you choose not to care about.

    ``--normalize-all`` turns on every ignore flag at once. Exit code is 1 when the
    files differ, so the command can gate a CI step.
    """
    common = common or Common()
    profile = _resolve_profile(common)
    a, b = config().resolve(a), config().resolve(b)
    prog_a = read_program(a, profile)
    prog_b = read_program(b, profile)
    opts = DiffOptions(
        ignore_block_numbers=ignore_n or normalize_all,
        ignore_whitespace=ignore_whitespace or normalize_all,
        ignore_comments=ignore_comments or normalize_all,
        ignore_leading_zeros=ignore_zeros or normalize_all,
        ignore_case=ignore_case or normalize_all,
        ignore_blank_lines=ignore_blank or normalize_all,
    )
    if common.json:
        _out.print_json(
            build_report(
                prog_a, prog_b, profile, opts, a_name=str(a), b_name=str(b)
            ).model_dump_json()
        )
        result = diff_programs(prog_a, prog_b, profile, opts)
    elif side_by_side:
        result = diff_programs(prog_a, prog_b, profile, opts)
        _print_side_by_side(result)
    else:
        result = diff_programs(prog_a, prog_b, profile, opts)
        text = unified(prog_a, prog_b, profile, opts, a_name=str(a), b_name=str(b), context=context)
        if text:
            _out.print(RText(text, no_wrap=True), end="")
    if result.identical:
        if not common.quiet and not common.json:
            _err.print("files are identical")
        return
    added, removed, changed = result.counts()
    if not common.quiet and not common.json:
        _err.print(f"{added} added, {removed} removed, {changed} changed")
    raise ProgramError(f"{a} and {b} differ")


# --------------------------------------------------------------------------- transforms


@app.command(name="renumber")
def renumber_cmd(
    file: Path,
    *,
    start: int = 10,
    step: int = 10,
    width: int = 0,
    comments: bool = False,
    strip: bool = False,
    out: Out | None = None,
    common: Common | None = None,
) -> None:
    """Renumber N blocks (or remove them with --strip).

    Blank lines, ``%`` and O-number lines are never numbered. Comment-only lines
    keep an existing N but do not get a new one unless ``--comments``.
    """
    common, out = common or Common(), out or Out()
    profile, program = _load(file, common)
    spec = RenumberSpec(
        start=start,
        step=step,
        width=width,
        number_comments=comments,
        strip=strip,
        range=Range.parse(out.range),
    )
    _finish(program, renumber(program, spec, profile), file, out, common)


@app.command(name="shift")
def shift_cmd(
    file: Path,
    *,
    x: str | None = None,
    y: str | None = None,
    z: str | None = None,
    a: str | None = None,
    b: str | None = None,
    c: str | None = None,
    also_incremental: bool = False,
    out: Out | None = None,
    common: Common | None = None,
) -> None:
    """Translate absolute coordinates: ``shift part.nc --z -0.02 -o part_z.nc``.

    Words in G91 blocks are left alone unless ``--also-incremental``. Arc centres
    (I/J/K) move only for dialects that store them as absolute coordinates.
    Canned-cycle ``R`` follows ``Z``.
    """
    common, out = common or Common(), out or Out()
    deltas = {
        axis: v
        for axis, raw in (("X", x), ("Y", y), ("Z", z), ("A", a), ("B", b), ("C", c))
        if (v := _dec(raw, f"--{axis.lower()}")) is not None
    }
    if not deltas:
        raise ProgramError("give at least one of --x/--y/--z/--a/--b/--c")
    profile, program = _load(file, common)
    spec = ShiftSpec(
        deltas=deltas,
        also_incremental=also_incremental,
        digits=_digits(out),
        rounding=_rounding(out),
        range=Range.parse(out.range),
    )
    _finish(program, shift(program, spec, profile), file, out, common)


@app.command(name="math")
def math_cmd(
    file: Path,
    *,
    addr: str,
    op: MathOp = "add",
    value: str,
    out: Out | None = None,
    common: Common | None = None,
) -> None:
    """Arithmetic on every word of ADDR (comma-separated list allowed).

    Example: ``--addr Z --op add --value -0.013``.

    Not modal-aware - touches absolute and incremental words alike. Use ``shift`` for geometry.
    """
    common, out = common or Common(), out or Out()
    profile, program = _load(file, common)
    k = _dec(value, "--value")
    assert k is not None
    spec = MathSpec(
        addrs=tuple(s.strip().upper() for s in addr.split(",") if s.strip()),
        op=op,
        value=k,
        digits=_digits(out),
        rounding=_rounding(out),
        range=Range.parse(out.range),
    )
    _finish(program, addr_math(program, spec, profile), file, out, common)


@app.command(name="feeds")
def feeds_cmd(
    file: Path,
    *,
    f_scale: str | None = None,
    f_min: str | None = None,
    f_max: str | None = None,
    s_scale: str | None = None,
    s_min: str | None = None,
    s_max: str | None = None,
    out: Out | None = None,
    common: Common | None = None,
) -> None:
    """Scale and clamp feeds (F) and spindle speeds (S): ``--f-scale 0.9 --f-min 80``."""
    common, out = common or Common(), out or Out()
    profile, program = _load(file, common)
    spec = FeedsSpec(
        f_scale=_dec(f_scale, "--f-scale"),
        f_min=_dec(f_min, "--f-min"),
        f_max=_dec(f_max, "--f-max"),
        s_scale=_dec(s_scale, "--s-scale"),
        s_min=_dec(s_min, "--s-min"),
        s_max=_dec(s_max, "--s-max"),
        digits=_digits(out),
        rounding=_rounding(out),
        range=Range.parse(out.range),
    )
    if spec.is_noop:
        raise ProgramError(
            "nothing to do: give --f-scale/--f-min/--f-max/--s-scale/--s-min/--s-max"
        )
    _finish(program, feeds(program, spec, profile), file, out, common)


@app.command(name="strip")
def strip_cmd(
    file: Path,
    *,
    n: bool = False,
    comments: bool = False,
    blank: bool = False,
    skip_marks: bool = False,
    skipped_blocks: bool = False,
    spaces: bool = False,
    out: Out | None = None,
    common: Common | None = None,
) -> None:
    """Remove block numbers, comments, blank lines, ``/`` marks or blocks, and spaces.

    Flags: ``--n`` ``--comments`` ``--blank`` ``--skip-marks`` ``--skipped-blocks`` ``--spaces``.
    """
    common, out = common or Common(), out or Out()
    profile, program = _load(file, common)
    spec = StripSpec(
        block_numbers=n,
        comments=comments,
        blank=blank,
        skip_marks=skip_marks,
        skipped_blocks=skipped_blocks,
        spaces=spaces,
        range=Range.parse(out.range),
    )
    if spec.is_noop:
        raise ProgramError(
            "nothing to do: give --n/--comments/--blank/--skip-marks/--skipped-blocks/--spaces"
        )
    _finish(program, strip(program, spec, profile), file, out, common)


@app.command(name="case")
def case_cmd(
    file: Path,
    to: Literal["upper", "lower"] = "upper",
    *,
    out: Out | None = None,
    common: Common | None = None,
) -> None:
    """Upper- or lower-case the code. Comments are left as they are."""
    common, out = common or Common(), out or Out()
    profile, program = _load(file, common)
    spec = CaseSpec(case=to, range=Range.parse(out.range))
    _finish(program, change_case(program, spec, profile), file, out, common)


@app.command(name="scale")
def scale_cmd(
    file: Path,
    *,
    factor: str,
    about: str = "0,0,0",
    axes: str = ",".join(LINEAR_AXES),
    also_feed: bool = False,
    out: Out | None = None,
    common: Common | None = None,
) -> None:
    """Scale linear axes about a point: ``--factor 1.02 --about 0,0,0``.

    Arc I/J/K and R scale with the geometry; canned-cycle R follows Z. F is untouched
    unless ``--also-feed``. Rotary axes (A/B/C) are never scaled.
    """
    common, out = common or Common(), out or Out()
    profile, program = _load(file, common)
    f = _dec(factor, "--factor")
    assert f is not None
    parts = [p for p in about.split(",") if p.strip()]
    axis_list = tuple(a.strip().upper() for a in axes.split(",") if a.strip())
    center = {
        axis: v
        for axis, raw in zip(("X", "Y", "Z"), parts, strict=False)
        if (v := _dec(raw, "--about")) is not None
    }
    spec = ScaleSpec(
        factor=f,
        about=center,
        axes=axis_list,
        also_feed=also_feed,
        digits=_digits(out),
        rounding=_rounding(out),
        range=Range.parse(out.range),
    )
    _finish(program, scale(program, spec, profile), file, out, common)


@app.command(name="mirror")
def mirror_cmd(
    file: Path,
    *,
    axis: str,
    about: str = "0",
    out: Out | None = None,
    common: Common | None = None,
) -> None:
    """Mirror across an axis: ``--axis x`` negates X, flips I, swaps G02<->G03 and G41<->G42."""
    common, out = common or Common(), out or Out()
    profile, program = _load(file, common)
    c = _dec(about, "--about")
    assert c is not None
    spec = MirrorSpec(axis=axis.upper(), about=c, digits=out.digits, range=Range.parse(out.range))
    _finish(program, mirror(program, spec, profile), file, out, common)


@app.command(name="rotate")
def rotate_cmd(
    file: Path,
    *,
    deg: str,
    cx: str = "0",
    cy: str = "0",
    force: bool = False,
    out: Out | None = None,
    common: Common | None = None,
) -> None:
    """Rotate in the G17 plane about (cx, cy): ``--deg 90 --cx 50 --cy 25``.

    Multiples of 90 degrees are exact. Other angles are rounded to ``--digits`` (default: profile).
    Planes G18/G19 are refused without ``--force``.
    """
    common, out = common or Common(), out or Out()
    profile, program = _load(file, common)
    d, x0, y0 = _dec(deg, "--deg"), _dec(cx, "--cx"), _dec(cy, "--cy")
    assert d is not None and x0 is not None and y0 is not None
    spec = RotateSpec(
        deg=d, cx=x0, cy=y0, force=force, digits=out.digits, range=Range.parse(out.range)
    )
    _finish(program, rotate(program, spec, profile), file, out, common)


@app.command(name="snippets")
def snippets_cmd(
    snippet: str | None = None,
    *,
    set_: Annotated[list[str] | None, Parameter(name=["--set"])] = None,
    common: Common | None = None,
) -> None:
    """List the snippets for a profile, or render one.

    ``nctab snippets`` lists them; ``nctab snippets tool-change --set T=7 --set S=4500``
    prints the filled body, ready to paste or redirect into a file.
    """
    common = common or Common()
    profile = _resolve_profile(common)
    catalogue = load_snippets(profile.id)
    for problem in catalogue.problems:
        _err.print(f"[yellow]snippet:[/] {problem}")

    if snippet is None:
        if common.json:
            _out.print_json(
                json.dumps(
                    [
                        {
                            "id": s.id,
                            "title": s.title,
                            "description": s.description,
                            "fields": [
                                {
                                    "name": f.name,
                                    "label": f.label,
                                    "type": f.type,
                                    "default": f.default,
                                }
                                for f in s.fields
                            ],
                        }
                        for s in catalogue
                    ]
                )
            )
            return
        table = Table(title=f"Snippets for {profile.id}", title_justify="left")
        table.add_column("Id")
        table.add_column("Title")
        table.add_column("Fields")
        for item in catalogue:
            table.add_row(item.id, item.title, " ".join(item.field_names) or "-")
        _out.print(table)
        return

    values: dict[str, str | int | float | None] = {}
    for pair in set_ or []:
        name, sep, value = pair.partition("=")
        if not sep:
            raise ProgramError(f"--set expects NAME=VALUE, got {pair!r}")
        values[name.strip()] = value
    body = catalogue.get(snippet).render(values)
    _out.print(RText(body, no_wrap=True), end="")


# --------------------------------------------------------------------------- find / replace


def _query(
    text: str | None,
    *,
    regex: bool,
    case: bool,
    addr: str | None,
    value: str | None,
    min_: str | None,
    max_: str | None,
    code: str | None,
    in_comments: bool,
    rng: str | None,
) -> Query:
    return Query(
        text=text,
        regex=regex,
        ignore_case=not case,
        addr=addr.upper() if addr else None,
        values=_dec_list(value, "--value"),
        min_value=_dec(min_, "--min"),
        max_value=_dec(max_, "--max"),
        code=code,
        in_comments=in_comments,
        range=Range.parse(rng),
    )


@app.command(name="find")
def find_cmd(
    file: Path,
    text: str | None = None,
    *,
    regex: bool = False,
    case: bool = False,
    addr: str | None = None,
    value: str | None = None,
    min: str | None = None,
    max: str | None = None,
    code: str | None = None,
    in_comments: bool = False,
    range: Annotated[str | None, Parameter(name=["--range", "-r"])] = None,
    common: Common | None = None,
) -> None:
    """Search FILE.

    * ``find part.nc "G41 D"`` - text (add ``--regex`` for a pattern, ``--case`` to match case)
    * ``find part.nc --addr F`` - **hints**: every distinct F value with counts and where it occurs
    * ``find part.nc --addr F --value 300`` - the F300 words (``--min/--max`` for a range)
    * ``find part.nc --code G02`` - every G02 / G2 block
    """
    common = common or Common()
    profile, program = _load(file, common)

    hints_mode = addr is not None and not value and min is None and max is None and text is None
    if hints_mode:
        assert addr is not None
        hints = suggest(program, profile, addr, Range.parse(range))
        if common.json:
            _out.print_json(
                json.dumps(
                    [
                        {
                            "text": h.text,
                            "value": str(h.value),
                            "count": h.count,
                            "first_line": h.first_line,
                            "last_line": h.last_line,
                            "first_block": h.first_block,
                            "last_block": h.last_block,
                        }
                        for h in hints
                    ]
                )
            )
            return
        if not hints:
            _err.print(f"no {addr.upper()} words found")
            return
        t = Table(title=f"{addr.upper()} values in {file.name}", title_justify="left")
        t.add_column("Value")
        t.add_column("Count", justify="right")
        t.add_column("Lines")
        t.add_column("Blocks")
        for h in hints:
            lines = _span(h.first_line, h.last_line)
            blocks = "-" if h.first_block is None else _span(h.first_block, h.last_block, "N")
            t.add_row(h.text, str(h.count), lines, blocks)
        _out.print(t)
        return

    q = _query(
        text,
        regex=regex,
        case=case,
        addr=addr,
        value=value,
        min_=min,
        max_=max,
        code=code,
        in_comments=in_comments,
        rng=range,
    )
    matches = find(program, profile, q)
    if common.json:
        _out.print_json(
            json.dumps(
                [
                    {
                        "line": m.lineno,
                        "col": m.col,
                        "length": m.length,
                        "text": m.text,
                        "block": m.block_number,
                        "line_text": m.line_text,
                    }
                    for m in matches
                ]
            )
        )
        return
    _print_matches(matches)
    if not common.quiet:
        _err.print(f"{len(matches)} matches in {len({m.line for m in matches})} lines")


@app.command(name="replace")
def replace_cmd(
    file: Path,
    text: str | None = None,
    *,
    to: str,
    regex: bool = False,
    case: bool = False,
    addr: str | None = None,
    value: str | None = None,
    min: str | None = None,
    max: str | None = None,
    code: str | None = None,
    in_comments: bool = False,
    out: Out | None = None,
    common: Common | None = None,
) -> None:
    """Batch replace. Same selectors as ``find``; ``--to`` is the new value.

    * ``replace part.nc --addr F --value 300 --to 250`` - F300 -> F250 (number style kept)
    * ``replace part.nc --addr F --to 250`` - every F in range
    * ``replace part.nc --code M8 --to 7`` - M08 -> M07
    * ``replace part.nc --regex 'X(\\d+)\\.' --to 'X\\1.0'`` - regex with back-references

    Without ``-i`` / ``-o`` only the diff is shown.
    """
    common, out = common or Common(), out or Out()
    profile, program = _load(file, common)
    q = _query(
        text,
        regex=regex,
        case=case,
        addr=addr,
        value=value,
        min_=min,
        max_=max,
        code=code,
        in_comments=in_comments,
        rng=out.range,
    )
    spec = ReplaceSpec(query=q, to=to, digits=out.digits)
    _finish(program, replace(program, spec, profile), file, out, common)


# --------------------------------------------------------------------------- rendering


def _span(a: int | None, b: int | None, prefix: str = "") -> str:
    if a == b or b is None:
        return f"{prefix}{a}"
    return f"{prefix}{a}-{prefix}{b}"


def _print_matches(matches: list[Match]) -> None:
    for m in matches:
        line = RText(m.line_text, no_wrap=True)
        line.stylize("bold reverse", m.col, m.col + m.length)
        prefix = RText(f"{m.lineno:>6} ", style="dim")
        if m.block_number is not None:
            prefix.append(f"N{m.block_number:<6} ", style="cyan")
        else:
            prefix.append(" " * 8)
        _out.print(prefix + line)


def _print_tools(report: ToolsReport) -> None:
    if not report.tools:
        _err.print("no tool words found")
        return
    t = Table(title=f"Tools in {report.file or '-'}", title_justify="left")
    t.add_column("T", justify="right")
    t.add_column("Name")
    t.add_column("Line", justify="right")
    t.add_column("Blocks", justify="right")
    t.add_column("D")
    t.add_column("H")
    t.add_column("S")
    t.add_column("F")
    for u in report.tools:
        t.add_row(
            f"T{u.tool}",
            (u.comment or "").strip("()").strip() or "-",
            str(u.first_line),
            str(u.blocks),
            " ".join(map(str, u.d)) or "-",
            " ".join(map(str, u.h)) or "-",
            " ".join(f"{v:f}" for v in u.speeds) or "-",
            " ".join(f"{v:f}" for v in u.feeds) or "-",
        )
    _out.print(t)


_SEVERITY_STYLE = {"error": "red", "warning": "yellow", "info": "cyan"}


def _print_check(report: CheckReport, common: Common) -> None:
    for d in report.diagnostics:
        style = _SEVERITY_STYLE[d.severity]
        where = f"{d.line}" if d.line else "-"
        block = f" N{d.block}" if d.block is not None else ""
        _out.print(
            f"[dim]{where:>5}[/]{block} [{style}]{d.severity}[/] [bold]{d.code}[/] {d.message}"
        )
        if d.text:
            _out.print(f"        [dim]{d.text}[/]")
    if common.quiet:
        return
    if not report.diagnostics:
        _err.print(f"{report.file}: no problems found")
        return
    _err.print(f"{report.errors} errors, {report.warnings} warnings, {report.infos} notes")


def _print_side_by_side(result: DiffResult) -> None:
    marks = {"equal": " ", "replace": "~", "delete": "-", "insert": "+"}
    styles = {"equal": "", "replace": "yellow", "delete": "red", "insert": "green"}
    t = Table(box=None, pad_edge=False, show_header=True)
    t.add_column("", width=1)
    t.add_column("#", justify="right", style="dim")
    t.add_column("A", overflow="fold")
    t.add_column("#", justify="right", style="dim")
    t.add_column("B", overflow="fold")
    for row in result.rows:
        style = styles[row.kind]
        t.add_row(
            marks[row.kind],
            str(row.left_line or ""),
            RText(row.left or "", style=style),
            str(row.right_line or ""),
            RText(row.right or "", style=style),
        )
    _out.print(t)


def _print_stats(s: Stats) -> None:
    head = Table.grid(padding=(0, 2))
    head.add_row("[bold]File[/]", s.file or "-")
    head.add_row("[bold]Profile[/]", s.profile)
    head.add_row("[bold]Lines[/]", str(s.lines))
    head.add_row(
        "[bold]Blocks[/]",
        f"{s.blocks} (motion {s.motion_blocks}, skipped {s.skipped_blocks})",
    )
    head.add_row("[bold]Comments / blank[/]", f"{s.comment_lines} / {s.blank_lines}")
    if s.parse_issues:
        head.add_row("[bold yellow]Parse issues[/]", f"[yellow]{s.parse_issues}[/]")
    _out.print(head)

    if s.axes:
        t = Table(title="Axes", title_justify="left")
        t.add_column("Axis")
        t.add_column("Min", justify="right")
        t.add_column("Max", justify="right")
        t.add_column("Span", justify="right")
        for a, r in s.axes.items():
            t.add_row(a, f"{r.min:f}", f"{r.max:f}", f"{r.span:f}")
        _out.print(t)

    def fmt_counts(d: dict[str, int]) -> str:
        return "  ".join(f"{k}*{v}" for k, v in d.items()) or "-"

    if s.path is not None:
        pt = Table.grid(padding=(0, 2))
        pt.add_row("[bold]Rapid G00[/]", f"{s.path.rapid:f}")
        pt.add_row("[bold]Feed G01[/]", f"{s.path.feed:f}")
        pt.add_row("[bold]Arc G02/G03[/]", f"{s.path.arc:f}")
        pt.add_row("[bold]Cutting total[/]", f"{s.path.cutting:f}")
        pt.add_row("[bold]All motion[/]", f"{s.path.total:f}")
        if s.path.skipped:
            pt.add_row("[bold yellow]Skipped blocks[/]", f"[yellow]{s.path.skipped}[/]")
        _out.print(pt)

    misc = Table.grid(padding=(0, 2))
    misc.add_row("[bold]G[/]", fmt_counts(s.gcodes))
    misc.add_row("[bold]M[/]", fmt_counts(s.mcodes))
    misc.add_row("[bold]Tools[/]", " ".join(f"T{t}" for t in s.tools) or "-")
    misc.add_row("[bold]Feeds[/]", " ".join(f"{f:f}" for f in s.feeds) or "-")
    misc.add_row("[bold]Speeds[/]", " ".join(f"{v:f}" for v in s.speeds) or "-")
    _out.print(misc)


# --------------------------------------------------------------------------- entry


def main(argv: list[str] | None = None) -> int:
    try:
        app(argv, result_action="return_value")
    except NctabError as e:
        _err.print(f"[red]error:[/] {e}")
        return e.exit_code
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
