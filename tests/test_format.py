from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from nctab.core.format import format_decimal, replace_value
from nctab.core.model import Word

D = Decimal


@pytest.mark.parametrize(
    ("value", "like", "expected"),
    [
        # preserve scale of original
        (D("-0.0130"), "-0.0130", "-0.0130"),
        (D("-0.013"), "-0.0130", "-0.0130"),
        (D("12.5"), "12.5", "12.5"),
        (D("12.48"), "12.5", "12.48"),  # never drop precision the value carries
        # trailing dot style
        (D("12"), "12.", "12."),
        (D("13"), "12.", "13."),
        (D("12.5"), "12.", "12.5"),
        # leading zero omitted style
        (D("0.5"), ".5", ".5"),
        (D("-0.5"), "-.5", "-.5"),
        (D("1.5"), ".5", "1.5"),
        # explicit plus
        (D("3"), "+3", "+3"),
        (D("-3"), "+3", "-3"),
        # negative zero is never emitted
        (D("-0.000"), "-0.020", "0.000"),
        (D("0"), "-5.", "0."),
        # no template: shortest form
        (D("12.500"), None, "12.5"),
        (D("12.000"), None, "12"),
        (D("-0.0130"), None, "-0.013"),
        (D("1E+2"), None, "100"),
    ],
)
def test_format_decimal_preserve(value: Decimal, like: str | None, expected: str) -> None:
    assert format_decimal(value, like=like) == expected


@pytest.mark.parametrize(
    ("value", "like", "digits", "rounding", "expected"),
    [
        (D("12.34567"), None, 3, "HALF_UP", "12.346"),
        (D("12.3455"), None, 3, "HALF_UP", "12.346"),
        (D("12.3455"), None, 3, "HALF_EVEN", "12.346"),
        (D("12.3445"), None, 3, "HALF_UP", "12.345"),
        (D("12.3445"), None, 3, "HALF_EVEN", "12.344"),
        (D("12.5"), None, 3, "HALF_UP", "12.5"),  # trailing zeros stripped
        (D("12.5"), "12.000", 3, "HALF_UP", "12.500"),  # unless original had them
        (D("12"), "12.", 3, "HALF_UP", "12."),
        (D("-0.0004"), None, 3, "HALF_UP", "0"),
    ],
)
def test_format_decimal_digits(
    value: Decimal, like: str | None, digits: int, rounding: str, expected: str
) -> None:
    assert format_decimal(value, like=like, digits=digits, rounding=rounding) == expected  # type: ignore[arg-type]


def test_replace_value_keeps_style() -> None:
    w = Word("X", D("-0.0130"), "x-0.0130")
    out = replace_value(w, D("-0.0130") + D("0.0200"))
    assert out.text == "x0.0070"
    assert out.value == D("0.0070")
    assert out.addr == "X"


@given(
    st.decimals(min_value=-99999, max_value=99999, places=4, allow_nan=False, allow_infinity=False)
)
def test_format_roundtrip(value: Decimal) -> None:
    text = format_decimal(value)
    assert Decimal(text) == value


@given(
    st.decimals(min_value=-99999, max_value=99999, places=4, allow_nan=False, allow_infinity=False)
)
def test_add_zero_is_identity(value: Decimal) -> None:
    like = format_decimal(value)
    assert format_decimal(value + D(0), like=like) == like
