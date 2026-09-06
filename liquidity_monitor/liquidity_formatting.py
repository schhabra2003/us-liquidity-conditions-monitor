"""Canonical number formatting for the U.S. Liquidity Conditions Monitor.

Raw monetary values remain numeric USD billions in the research bundle. These
helpers own display scaling and precision so pages, tables, charts, tooltips,
and downstream exports do not independently invent unit conventions.
"""

from __future__ import annotations

import math
from decimal import ROUND_HALF_UP, Decimal
from typing import Final

MISSING_VALUE: Final[str] = "Not available"

UNIT_USD_BILLIONS: Final[str] = "USD billions"
UNIT_PERCENTAGE_POINTS: Final[str] = "percentage points"
UNIT_PERCENT: Final[str] = "percent"
UNIT_INDEX_POINTS: Final[str] = "index points"
UNIT_USD_PRICE: Final[str] = "USD per share"


def _finite_float(value: object) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _sign_prefix(value: float, signed: bool) -> str:
    if value < 0:
        return "−"
    return "+" if signed and value > 0 else ""


def _fixed(value: float, decimals: int) -> str:
    quantum = Decimal(1).scaleb(-decimals)
    rounded = Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP)
    return f"{rounded:,.{decimals}f}"


def format_usd_billions(value_bn: object, *, signed: bool = False) -> str:
    """Format a numeric USD-billions value using a T/B/M display scale.

    The unit threshold is based on absolute magnitude. Values at or above
    1,000 billion use trillions; values at or above 1 billion use billions;
    smaller values use millions. Every displayed monetary level uses exactly
    two decimal places.
    """

    value = _finite_float(value_bn)
    if value is None:
        return MISSING_VALUE
    magnitude = abs(value)
    sign = _sign_prefix(value, signed)
    if magnitude >= 1_000:
        return f"{sign}${_fixed(magnitude / 1_000, 2)}T"
    if magnitude >= 1:
        return f"{sign}${_fixed(magnitude, 2)}B"
    return f"{sign}${_fixed(magnitude * 1_000, 2)}M"


def format_basis_points(
    value: object, *, signed: bool = False, decimals: int = 1
) -> str:
    """Format a basis-point value with one decimal by default."""

    parsed = _finite_float(value)
    if parsed is None:
        return MISSING_VALUE
    sign = _sign_prefix(parsed, signed)
    return f"{sign}{_fixed(abs(parsed), decimals)} bp"


def format_percent(value: object, *, signed: bool = False) -> str:
    """Format a percentage level or change with exactly two decimals."""

    parsed = _finite_float(value)
    if parsed is None:
        return MISSING_VALUE
    sign = _sign_prefix(parsed, signed)
    return f"{sign}{_fixed(abs(parsed), 2)}%"


def format_percentage_points(value: object, *, signed: bool = False) -> str:
    """Format percentage points with exactly two decimals."""

    parsed = _finite_float(value)
    if parsed is None:
        return MISSING_VALUE
    sign = _sign_prefix(parsed, signed)
    return f"{sign}{_fixed(abs(parsed), 2)} pp"


def format_market_price(value: object) -> str:
    """Format a U.S.-dollar market price with exactly two decimals."""

    parsed = _finite_float(value)
    if parsed is None:
        return MISSING_VALUE
    sign = "−" if parsed < 0 else ""
    return f"{sign}${_fixed(abs(parsed), 2)}"


def format_index_points(value: object) -> str:
    """Format an index level with exactly two decimals."""

    parsed = _finite_float(value)
    return MISSING_VALUE if parsed is None else _fixed(parsed, 2)


def format_normalized(value: object, *, signed: bool = False) -> str:
    """Format a unitless normalized diagnostic with exactly two decimals."""

    parsed = _finite_float(value)
    if parsed is None:
        return MISSING_VALUE
    sign = _sign_prefix(parsed, signed)
    return f"{sign}{_fixed(abs(parsed), 2)}"


def format_score(value: object) -> str:
    """Format a bounded percentile-style score as a whole number out of 100."""

    parsed = _finite_float(value)
    if parsed is None:
        return MISSING_VALUE
    bounded = min(100.0, max(0.0, parsed))
    return f"{_fixed(bounded, 0)} / 100"


def format_percentile(value: object) -> str:
    """Format a percentile with a grammatically correct integer ordinal."""

    parsed = _finite_float(value)
    if parsed is None:
        return MISSING_VALUE
    rounded = int(
        Decimal(str(min(100.0, max(0.0, parsed)))).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )
    remainder_100 = rounded % 100
    if 11 <= remainder_100 <= 13:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(rounded % 10, "th")
    return f"{rounded}{suffix} percentile"


def describe_layer_contribution(
    layer: str, contribution: object
) -> tuple[str, str, str]:
    """Return sign-aware manager copy for the weakest weighted model layer.

    The caller supplies the minimum weighted contribution across all model
    layers. A positive minimum therefore means every layer is supportive.
    Values that round to zero at the monitor's two-decimal presentation
    precision are described as neutral rather than as a drag or tailwind.
    """

    parsed = _finite_float(contribution)
    if parsed is None:
        return (
            "Model-layer contribution",
            f"{layer} does not have an available weighted contribution.",
            f"The weighted contribution for {layer} is not available.",
        )
    rendered = format_normalized(parsed, signed=True)
    if parsed <= -0.005:
        return (
            "Primary model drag",
            f"{layer} is the primary drag.",
            f"The largest negative contribution is {layer} at {rendered}.",
        )
    if parsed >= 0.005:
        return (
            "Smallest positive model layer",
            f"All four model layers are supportive; {layer} has the smallest positive contribution.",
            f"Every model layer is positive. The smallest positive contribution is {layer} at {rendered}.",
        )
    return (
        "Least supportive model layer",
        f"{layer} is neutral and is the least supportive model layer.",
        f"The least supportive model layer is {layer}, with a neutral contribution of {rendered}.",
    )


def format_source_value(value: object, unit: str) -> str:
    """Format a source-ledger value from its canonical backend unit."""

    if unit == UNIT_USD_BILLIONS:
        return format_usd_billions(value)
    if unit == UNIT_PERCENTAGE_POINTS:
        return format_percentage_points(value)
    if unit == UNIT_PERCENT:
        return format_percent(value)
    if unit == UNIT_INDEX_POINTS:
        return format_index_points(value)
    if unit == UNIT_USD_PRICE:
        return format_market_price(value)
    return format_normalized(value)
