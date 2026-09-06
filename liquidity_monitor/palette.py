"""Product design tokens shared by the liquidity monitor and its charts.

The interface uses a restrained institutional palette. Navy is the primary
data color; teal and brick are reserved for supportive and restrictive states;
amber is reserved for freshness or escalation warnings. Additional series
colors are used only when a multi-series chart requires them.
"""

from __future__ import annotations

from typing import Final

PRODUCT: Final[dict[str, str]] = {
    "navy": "#16325C",
    "blue": "#2F6FED",
    "teal": "#17806D",
    "green": "#137A5B",
    "brick": "#B5473C",
    "red": "#B42318",
    "amber": "#B7791F",
    "purple": "#6657A8",
    "slate": "#64748B",
    "steel": "#3E6C88",
    "cyan": "#238A9B",
    "gold": "#A0712B",
    "plum": "#7B5E7B",
    "ink": "#0F172A",
    "secondary": "#475569",
    "muted": "#64748B",
    "border": "#D9E1EA",
    "grid": "#E8EDF3",
    "surface": "#FFFFFF",
    "canvas": "#F6F8FB",
}

SERIES_12: Final[tuple[str, ...]] = (
    PRODUCT["navy"],
    PRODUCT["blue"],
    PRODUCT["teal"],
    PRODUCT["amber"],
    PRODUCT["purple"],
    PRODUCT["steel"],
    PRODUCT["brick"],
    PRODUCT["cyan"],
    PRODUCT["gold"],
    PRODUCT["plum"],
    "#8293A6",
    "#40556F",
)

# Compatibility aliases preserve the analytical modules' existing key-based
# imports while routing every chart through the standalone product palette.
PASTEL: Final[dict[str, str]] = {
    "blue": PRODUCT["blue"],
    "coral": "#B7791F",
    "sage": PRODUCT["green"],
    "amber": "#C88A16",
    "lavender": PRODUCT["purple"],
    "teal": PRODUCT["teal"],
    "rose": PRODUCT["red"],
    "periwinkle": PRODUCT["steel"],
    "olive": "#66845A",
    "mauve": PRODUCT["plum"],
    "sky": PRODUCT["cyan"],
    "apricot": PRODUCT["gold"],
    "mint": "#2B8A6E",
    "salmon": PRODUCT["brick"],
    "cornflower": PRODUCT["navy"],
    "plum": "#584A8A",
    "seafoam": "#1E7468",
    "sand": "#8A641E",
    "slate_blue": PRODUCT["slate"],
    "clay": "#934A38",
}
PASTEL_20: Final[tuple[str, ...]] = tuple(PASTEL.values())

# Legacy names are retained for public notebooks importing the module. Their
# values intentionally follow the new product system.
EXCEL: Final[dict[str, str]] = PASTEL
EXCEL_20: Final[tuple[str, ...]] = PASTEL_20

PASTEL_DIVERGING_SCALE: Final[list[list[float | str]]] = [
    [0.0, PRODUCT["red"]],
    [0.5, PRODUCT["surface"]],
    [1.0, PRODUCT["green"]],
]

PASTEL_RATES_SCALE: Final[list[list[float | str]]] = [
    [0.0, PRODUCT["green"]],
    [0.5, PRODUCT["surface"]],
    [1.0, PRODUCT["red"]],
]


def pastel(index: int) -> str:
    """Return a stable product series color, cycling after all 20 slots."""

    return PASTEL_20[index % len(PASTEL_20)]
