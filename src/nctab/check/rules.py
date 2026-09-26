"""Syntax and light-semantic checks (goal.md §6.3).

Each rule is a function ``(ctx) -> Iterable[Diagnostic]`` registered in ``RULES``.
Rules never modify the program and never raise: anything they cannot judge is
left alone. Adding a rule means appending to ``RULES`` and giving it a new
stable ``code``.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from decimal import Decimal

from nctab.check.model import Diagnostic, Severity
from nctab.core.model import LineKind, Program
from nctab.core.state import CANNED_CYCLES, LineState, g_int, states
from nctab.geom.arc import center_from_ijk, center_from_r, radius_mismatch
from nctab.profiles.loader import Profile

DEFAULT_ARC_TOLERANCE = Decimal("0.001")


@dataclass(frozen=True, slots=True)
class Context:
    program: Program
    profile: Profile
    line_states: list[LineState]
    arc_tolerance: Decimal = DEFAULT_ARC_TOLERANCE

    def diag(self, ls: LineState | None, severity: Severity, code: str, message: str) -> Diagnostic:
        if ls is None:
            return Diagnostic(line=0, severity=severity, code=code, message=message)
        return Diagnostic(
            line=ls.line.index + 1,
            severity=severity,
            code=code,
            message=message,
            block=ls.line.block_number,
            text=ls.line.raw,
        )


Rule = Callable[[Context], Iterable[Diagnostic]]
RULES: list[Rule] = []


def rule(fn: Rule) -> Rule:
    RULES.append(fn)
    return fn


# --------------------------------------------------------------------------- syntax


@rule
def parse_issues(ctx: Context) -> Iterator[Diagnostic]:
    """Problems the tokeniser recorded: unclosed comments, stray characters, bare letters."""
    severity: dict[str, Severity] = {
        "unclosed-comment": "error",
        "word-no-value": "error",
        "bad-macro": "error",
        "unexpected-char": "warning",
    }
    for issue in ctx.program.issues:
        ls = ctx.line_states[issue.line] if issue.line < len(ctx.line_states) else None
        yield ctx.diag(ls, severity.get(issue.code, "warning"), issue.code, issue.message)


@rule
def duplicate_address(ctx: Context) -> Iterator[Diagnostic]:
    """Two words with the same address in one block (``X1. X2.``) — v1 does not support it."""
    exempt = {"G", "M"}
    for ls in ctx.line_states:
        seen: dict[str, int] = {}
        for w in ls.line.words:
            if w.addr in exempt:
                continue
            seen[w.addr] = seen.get(w.addr, 0) + 1
        for addr, n in seen.items():
            if n > 1:
                yield ctx.diag(
                    ls, "error", "duplicate-address", f"address {addr} appears {n} times"
                )


@rule
def unknown_code(ctx: Context) -> Iterator[Diagnostic]:
    """G or M code the profile's dictionary does not list."""
    if not ctx.profile.gcodes and not ctx.profile.mcodes:
        return
    for ls in ctx.line_states:
        for w in ls.line.words:
            if w.addr not in ("G", "M") or not isinstance(w.value, Decimal):
                continue
            table = ctx.profile.gcodes if w.addr == "G" else ctx.profile.mcodes
            if not table:
                continue
            code = g_int(w)
            keys = (
                {f"{w.addr}{code:02d}", f"{w.addr}{code}"}
                if code is not None
                else {f"{w.addr}{w.value.normalize():f}"}
            )
            if not (keys & table.keys()):
                yield ctx.diag(
                    ls, "warning", "unknown-code", f"{w.text} is not in profile {ctx.profile.id}"
                )


# --------------------------------------------------------------------------- semantics


@rule
def comp_without_offset(ctx: Context) -> Iterator[Diagnostic]:
    """G41/G42 turned on without a D word, here or already modal."""
    d_addr = ctx.profile.radius_comp
    for ls in ctx.line_states:
        codes = {g_int(w) for w in ls.line.words if w.addr == "G"}
        if not (codes & {41, 42}):
            continue
        if ls.line.has(d_addr) or ls.state.d is not None:
            continue
        yield ctx.diag(
            ls, "warning", "comp-without-offset", f"cutter compensation without a {d_addr} word"
        )


@rule
def length_comp_without_offset(ctx: Context) -> Iterator[Diagnostic]:
    """G43/G44 without an H word."""
    h_addr = ctx.profile.length_comp
    for ls in ctx.line_states:
        codes = {g_int(w) for w in ls.line.words if w.addr == "G"}
        if not (codes & {43, 44}) or ls.line.has(h_addr):
            continue
        yield ctx.diag(
            ls, "warning", "length-comp-without-offset", f"G43/G44 without an {h_addr} word"
        )


@rule
def cutting_without_spindle(ctx: Context) -> Iterator[Diagnostic]:
    """The first feed move happens while the spindle is off."""
    for ls in ctx.line_states:
        if not ls.is_motion or ls.state.motion == 0:
            continue
        if ls.state.spindle != "off":
            return  # spindle started before the first cut: nothing to report
        yield ctx.diag(
            ls, "warning", "cutting-without-spindle", "feed move before M03/M04 starts the spindle"
        )
        return


@rule
def speed_without_spindle(ctx: Context) -> Iterator[Diagnostic]:
    """An S word with no M03/M04 anywhere before the first cut."""
    s_addr = ctx.profile.spindle
    for ls in ctx.line_states:
        if ls.line.has(s_addr) and ls.state.spindle == "off":
            has_m = any(g_int(w) in (3, 4) for w in ls.line.words if w.addr == "M")
            if not has_m:
                yield ctx.diag(
                    ls,
                    "info",
                    "speed-without-spindle",
                    f"{s_addr} word without M03/M04 on the block",
                )


@rule
def incremental_not_restored(ctx: Context) -> Iterator[Diagnostic]:
    """Program ends while still in G91."""
    if not ctx.line_states:
        return
    last = ctx.line_states[-1]
    if last.state.incremental:
        yield ctx.diag(
            last,
            "warning",
            "incremental-not-restored",
            f"program ends in {ctx.profile.incremental} ({ctx.profile.absolute} is never restored)",
        )


@rule
def feed_missing(ctx: Context) -> Iterator[Diagnostic]:
    """A G01/G02/G03 move with no feed rate in effect."""
    for ls in ctx.line_states:
        if not ls.is_motion or ls.state.motion not in (1, 2, 3):
            continue
        if ls.state.feed is None:
            yield ctx.diag(ls, "error", "feed-missing", "feed move with no F word in effect")
            return
        return


@rule
def tool_not_changed(ctx: Context) -> Iterator[Diagnostic]:
    """A T word that is never followed by M06 before the next motion.

    Only for dialects that actually use M06: on a lathe ``T0101`` selects the
    tool and its offset on its own.
    """
    if not any("M06" in p.upper() for p in ctx.profile.toolchange_patterns):
        return
    t_addr = ctx.profile.tool_word
    pending: LineState | None = None
    for ls in ctx.line_states:
        if any(g_int(w) == 6 for w in ls.line.words if w.addr == "M"):
            pending = None
            continue
        if ls.line.has(t_addr):
            pending = ls
            continue
        if pending is not None and ls.is_motion:
            yield ctx.diag(
                pending, "info", "tool-not-changed", "T word without M06 before the next motion"
            )
            pending = None


@rule
def missing_program_end(ctx: Context) -> Iterator[Diagnostic]:
    """No M02/M30 anywhere."""
    for ls in ctx.line_states:
        if any(g_int(w) in (2, 30) for w in ls.line.words if w.addr == "M"):
            return
    yield ctx.diag(None, "warning", "missing-program-end", "no M02 or M30 in the program")


@rule
def missing_delimiter(ctx: Context) -> Iterator[Diagnostic]:
    """Fanuc-style dialects expect the program to be wrapped in ``%`` (goal.md §14)."""
    if not ctx.profile.program_delimiters:
        return
    delim = ctx.profile.program_delimiters[0]
    found = any(delim in ls.line.raw for ls in ctx.line_states if ls.line.kind is LineKind.HEADER)
    if not found:
        yield ctx.diag(
            None, "warning", "missing-delimiter", f"program has no {delim} delimiter line"
        )


# --------------------------------------------------------------------------- arcs


@rule
def arc_problems(ctx: Context) -> Iterator[Diagnostic]:
    """R together with IJK, an arc with neither, or a centre the endpoints disagree with."""
    for ls in ctx.line_states:
        state = ls.state
        if not state.is_arc or ls.line.kind is not LineKind.MOTION:
            continue
        u, v = state.plane[0], state.plane[1]
        i_addr = {"X": "I", "Y": "J", "Z": "K"}.get(u)
        j_addr = {"X": "I", "Y": "J", "Z": "K"}.get(v)
        wr = ls.line.word("R")
        wi = ls.line.word(i_addr) if i_addr else None
        wj = ls.line.word(j_addr) if j_addr else None

        if wr is not None and (wi is not None or wj is not None):
            yield ctx.diag(ls, "error", "arc-r-and-ijk", "arc gives both R and I/J/K")
            continue
        if wr is None and wi is None and wj is None:
            yield ctx.diag(ls, "error", "arc-no-center", "arc has neither R nor I/J/K")
            continue

        su, sv = state.start.get(u), state.start.get(v)
        eu, ev = state.position.get(u), state.position.get(v)
        if None in (su, sv, eu, ev):
            continue
        assert su is not None and sv is not None and eu is not None and ev is not None

        if wr is not None and wr.is_numeric:
            if su == eu and sv == ev:
                yield ctx.diag(
                    ls, "error", "arc-r-full-circle", "R cannot describe a full circle; use I/J/K"
                )
                continue
            if center_from_r(su, sv, eu, ev, wr.number, state.motion == 2) is None:
                yield ctx.diag(ls, "error", "arc-r-too-small", f"chord is longer than 2*{wr.text}")
            continue

        if (wi is None or wi.is_numeric) and (wj is None or wj.is_numeric):
            i = wi.number if wi is not None else Decimal(0)
            j = wj.number if wj is not None else Decimal(0)
            if ctx.profile.arc_center_absolute:
                cu, cv = i, j
            else:
                cu, cv = center_from_ijk(su, sv, i, j)
            delta = radius_mismatch(su, sv, eu, ev, cu, cv)
            if delta > ctx.arc_tolerance:
                yield ctx.diag(
                    ls,
                    "error",
                    "arc-radius-mismatch",
                    f"start and end radii differ by {delta:.4f}",
                )


@rule
def cycle_without_cancel(ctx: Context) -> Iterator[Diagnostic]:
    """A canned cycle that is still active at the end of the program."""
    if not ctx.line_states:
        return
    last = ctx.line_states[-1]
    if last.state.motion in CANNED_CYCLES:
        yield ctx.diag(
            last,
            "warning",
            "cycle-without-cancel",
            f"canned cycle G{last.state.motion} is never cancelled by G80",
        )


# --------------------------------------------------------------------------- driver


def check_program(
    program: Program,
    profile: Profile,
    *,
    arc_tolerance: Decimal = DEFAULT_ARC_TOLERANCE,
) -> list[Diagnostic]:
    ctx = Context(program, profile, states(program, profile), arc_tolerance)
    out: list[Diagnostic] = []
    for r in RULES:
        out.extend(r(ctx))
    return out


def rule_codes() -> list[str]:
    """Every code a rule can emit — for documentation and the ``--only`` filter."""
    return sorted(
        {
            "unclosed-comment",
            "word-no-value",
            "bad-macro",
            "unexpected-char",
            "duplicate-address",
            "unknown-code",
            "comp-without-offset",
            "length-comp-without-offset",
            "cutting-without-spindle",
            "speed-without-spindle",
            "incremental-not-restored",
            "feed-missing",
            "tool-not-changed",
            "missing-program-end",
            "missing-delimiter",
            "arc-r-and-ijk",
            "arc-no-center",
            "arc-r-full-circle",
            "arc-r-too-small",
            "arc-radius-mismatch",
            "cycle-without-cancel",
        }
    )
