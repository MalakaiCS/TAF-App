"""Checking the numbers that go into a calculation.

Shared by the calculator, the packing planner and the labels, so a quantity
of 2.5 or a width of "nan" is refused the same way everywhere and with the
same words.
"""
from __future__ import annotations

import math
from typing import Any, Optional


def positive_int(value: Any) -> Optional[int]:
    """A whole number of 1 or more, or None.

    Accepts an int or a string of digits. Refuses booleans (True is 1 to
    Python and to nobody else), fractions and anything below one.
    """
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value if value >= 1 else None
    if isinstance(value, float):
        if math.isfinite(value) and value.is_integer() and value >= 1:
            return int(value)
        return None
    text = str(value).strip()
    if text.isdigit():
        number = int(text)
        return number if number >= 1 else None
    return None


def finite(value: Any) -> Optional[float]:
    """A finite number, or None."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def positive(value: Any) -> Optional[float]:
    """A finite number greater than zero, or None."""
    number = finite(value)
    return number if number is not None and number > 0 else None


def non_negative(value: Any) -> Optional[float]:
    number = finite(value)
    return number if number is not None and number >= 0 else None


def ceil_to(value: float, step: float) -> float:
    """Round up to a whole number of steps, without float noise turning an
    exact 600 into 612 because 600/12 came out as 50.00000000001."""
    return math.ceil(round(value / step, 9)) * step


def kg_text(value: Optional[float], places: int = 3) -> str:
    """A weight for display: three places by default, or blank if unknown."""
    if value is None:
        return ""
    return f"{value:.{places}f}"


def trim_zeros(text: str) -> str:
    """3.20 -> 3.2, 3.0 -> 3, 3.45 -> 3.45. Keeps what was entered otherwise."""
    if "." not in text:
        return text
    text = text.rstrip("0").rstrip(".")
    return text or "0"
