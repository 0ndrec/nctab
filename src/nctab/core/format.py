"""Rendering a ``Program`` back to text and formatting numbers (goal.md §11).

Stage 0 provides the roundtrip renderer and the *preserve-original* number
formatter. Profile-driven quantisation (``digits``, ``rounding``) is added in
stage 1 together with the operations that need it.
"""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal
from typing import Literal

from nctab.core.model import Program, Word

Rounding = Literal["HALF_UP", "HALF_EVEN"]
_ROUNDING = {"HALF_UP": ROUND_HALF_UP, "HALF_EVEN": ROUND_HALF_EVEN}


def format_program(program: Program) -> str:
    """Serialise. Lines never touched by an operation come back byte-for-byte."""
    return program.text


def _split_number_text(text: str) -> tuple[str, str, str, str]:
    """``"-012.500"`` → (sign, int_part, ".", frac_part)."""
    sign = ""
    if text[:1] in "+-":
        sign, text = text[0], text[1:]
    if "." in text:
        ip, fp = text.split(".", 1)
        return sign, ip, ".", fp
    return sign, text, "", ""


def format_decimal(
    value: Decimal,
    *,
    like: str | None = None,
    digits: int | None = None,
    rounding: Rounding = "HALF_UP",
) -> str:
    """Render ``value`` for an NC word.

    ``like`` is the original source text of the number (``"-0.0130"``); when
    given and ``digits`` is ``None`` the result keeps the original number of
    fractional digits, presence of a leading zero, a trailing dot and an
    explicit ``+`` sign. When ``digits`` is given the value is quantised to
    that many fractional digits and trailing zeros are stripped unless the
    original text had them.
    """
    if value.is_nan() or value.is_infinite():
        raise ValueError(f"cannot format {value}")

    sign_plus = False
    leading_zero = True
    trailing_dot = False
    frac_len: int | None = None
    keep_trailing_zeros = False

    if like is not None:
        like = like.strip()
        sign, ip, dot, fp = _split_number_text(like)
        sign_plus = sign == "+"
        leading_zero = ip != "" or not dot
        trailing_dot = bool(dot) and fp == ""
        if dot and fp:
            frac_len = len(fp)
            keep_trailing_zeros = fp.endswith("0")

    if digits is not None:
        q = Decimal(1).scaleb(-digits)
        value = value.quantize(q, rounding=_ROUNDING[rounding])
        if not keep_trailing_zeros:
            value = _strip_zeros(value)
    elif frac_len is not None:
        # preserve original scale, but never lose significant digits the value now carries
        exp = value.normalize().as_tuple().exponent
        cur = -exp if isinstance(exp, int) and exp < 0 else 0
        target = max(frac_len, cur)
        value = value.quantize(Decimal(1).scaleb(-target), rounding=_ROUNDING[rounding])
    else:
        value = _strip_zeros(value)

    text = f"{value:f}"
    neg = text.startswith("-") and value != 0  # never emit -0
    if text.startswith("-"):
        text = text[1:]
    if text.startswith("0.") and not leading_zero:
        text = text[1:]
    if "." not in text and trailing_dot:
        text += "."
    if neg:
        text = "-" + text
    elif sign_plus:
        text = "+" + text
    return text


def _strip_zeros(value: Decimal) -> Decimal:
    if value == value.to_integral_value():
        return value.quantize(Decimal(1))
    return value.normalize()


def replace_value(
    word: Word, value: Decimal, *, digits: int | None = None, rounding: Rounding = "HALF_UP"
) -> Word:
    """New ``Word`` with the same address and source style, new numeric value."""
    text = word.text[0] + format_decimal(
        value, like=word.value_text, digits=digits, rounding=rounding
    )
    return Word(word.addr, value, text)
