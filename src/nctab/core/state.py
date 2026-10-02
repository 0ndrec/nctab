"""Modal state tracking (goal.md §6.1 «Модальное состояние»).

``iter_states`` walks a program from the top and yields, for every line, the
state *effective for that line*: G/M/T/F/S words of the line are applied first
(Fanuc semantics — ``G91`` on a block applies to that block), then the axis
position is advanced by the line's motion.

This is analysis only. Operations use it to decide, e.g., whether an ``X`` word
is absolute or incremental and which plane an arc lies in. Nothing here writes.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field, replace
from decimal import Decimal
from typing import Literal

from nctab.core.model import Line, LineKind, Program, Word
from nctab.profiles.loader import Profile

MOTION_CODES = frozenset({0, 1, 2, 3})
CANNED_CYCLES = frozenset({73, 74, 76, 81, 82, 83, 84, 85, 86, 87, 88, 89})
_HOME_CODES = frozenset({28, 30, 53})
# M05 stop, M19 orientation, M02/M30 program end: the spindle is not turning after any of them
_SPINDLE_STOP_CODES = frozenset({2, 5, 19, 30})

Spindle = Literal["cw", "ccw", "off"]


def g_int(word: Word) -> int | None:
    """Integer G/M number for ``G01`` / ``G1`` / ``G54``; ``None`` for ``G54.1`` or macros."""
    if not isinstance(word.value, Decimal):
        return None
    if word.value != word.value.to_integral_value():
        return None
    return int(word.value)


@dataclass(frozen=True, slots=True)
class ModalState:
    motion: int | None = None  # 0–3, canned cycle code, or None
    absolute: bool = True
    plane: str = "XY"
    plane_code: int = 17
    comp: int = 40
    units: Literal["mm", "inch"] | None = None
    feed_mode: int = 94
    tool: int | None = None
    d: int | None = None
    h: int | None = None
    feed: Decimal | None = None
    speed: Decimal | None = None
    spindle: Spindle = "off"
    coolant: bool = False
    # absolute position per axis; None = unknown (e.g. after G28)
    position: dict[str, Decimal | None] = field(default_factory=dict)
    # position before this line's motion
    start: dict[str, Decimal | None] = field(default_factory=dict)

    @property
    def incremental(self) -> bool:
        return not self.absolute

    @property
    def is_arc(self) -> bool:
        return self.motion in (2, 3)

    @property
    def plane_axes(self) -> tuple[str, str]:
        return self.plane[0], self.plane[1]

    @property
    def in_canned_cycle(self) -> bool:
        return self.motion in CANNED_CYCLES

    def pos(self, axis: str) -> Decimal | None:
        return self.position.get(axis)


@dataclass(frozen=True, slots=True)
class LineState:
    line: Line
    state: ModalState

    @property
    def is_motion(self) -> bool:
        """The line actually moves an axis (has axis words and a motion/cycle mode)."""
        return self.line.kind is LineKind.MOTION and self.state.motion is not None


def _initial(profile: Profile) -> ModalState:
    plane_code = 17
    plane = "XY"
    for code, axes in profile.planes.items():
        if code.upper() == "G17":
            plane, plane_code = axes, 17
            break
    return ModalState(
        plane=plane,
        plane_code=plane_code,
        position=dict.fromkeys(profile.axes),
        start=dict.fromkeys(profile.axes),
    )


def apply_line(state: ModalState, line: Line, profile: Profile) -> ModalState:
    """Return the state effective for ``line`` (words applied, position advanced)."""
    if line.kind in (LineKind.BLANK, LineKind.COMMENT, LineKind.HEADER):
        return replace(state, start=dict(state.position))

    motion = state.motion
    absolute = state.absolute
    plane, plane_code = state.plane, state.plane_code
    comp = state.comp
    units = state.units
    feed_mode = state.feed_mode
    tool, d, h = state.tool, state.d, state.h
    feed, speed = state.feed, state.speed
    spindle: Spindle = state.spindle
    coolant = state.coolant
    home = False
    axis_words: list[Word] = []
    axis_set = set(profile.axes)

    for w in line.words:
        a = w.addr
        if a in axis_set:
            axis_words.append(w)
        elif a == "G":
            code = g_int(w)
            if code is None:
                continue
            if code in MOTION_CODES or code in CANNED_CYCLES:
                motion = code
            elif code == 80:
                motion = None
            elif f"G{code:02d}" in profile.planes:
                plane = profile.planes[f"G{code:02d}"]
                plane_code = code
            elif code == 90 and profile.absolute == "G90":
                absolute = True
            elif code == 91 and profile.incremental == "G91":
                absolute = False
            elif code in (40, 41, 42):
                comp = code
            elif code == 20:
                units = "inch"
            elif code == 21:
                units = "mm"
            elif code in (94, 95):
                feed_mode = code
            elif code in _HOME_CODES:
                home = True
        elif a == "M":
            code = g_int(w)
            if code == 3:
                spindle = "cw"
            elif code == 4:
                spindle = "ccw"
            elif code in _SPINDLE_STOP_CODES:
                spindle = "off"
            elif code in (7, 8):
                coolant = True
            elif code == 9:
                coolant = False
        elif a == profile.tool_word:
            tool = g_int(w)
        elif a == profile.radius_comp:
            d = g_int(w)
        elif a == profile.length_comp:
            h = g_int(w)
        elif a == profile.feed and isinstance(w.value, Decimal):
            feed = w.value
        elif a == profile.spindle and isinstance(w.value, Decimal):
            speed = w.value

    start = dict(state.position)
    position = dict(state.position)
    for w in axis_words:
        if not isinstance(w.value, Decimal):
            position[w.addr] = None  # macro value: unknown
            continue
        if home:
            position[w.addr] = None  # reference return: destination unknown
        elif absolute:
            position[w.addr] = w.value
        else:
            cur = position.get(w.addr)
            position[w.addr] = cur + w.value if cur is not None else None

    return ModalState(
        motion=motion,
        absolute=absolute,
        plane=plane,
        plane_code=plane_code,
        comp=comp,
        units=units,
        feed_mode=feed_mode,
        tool=tool,
        d=d,
        h=h,
        feed=feed,
        speed=speed,
        spindle=spindle,
        coolant=coolant,
        position=position,
        start=start,
    )


def iter_states(program: Program, profile: Profile) -> Iterator[LineState]:
    state = _initial(profile)
    for line in program.lines:
        state = apply_line(state, line, profile)
        yield LineState(line, state)


def states(program: Program, profile: Profile) -> list[LineState]:
    return list(iter_states(program, profile))
