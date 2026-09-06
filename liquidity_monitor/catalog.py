"""Standalone page metadata for the liquidity monitor."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ToolDefinition:
    title: str
    page_filename: str
    group: str
    description: str
    primary_inputs: str


@dataclass(frozen=True)
class SidebarGuide:
    read_order: tuple[str, ...]
    caveat: str | None = None


TOOL = ToolDefinition(
    title="Liquidity Conditions Monitor",
    page_filename="Liquidity_Conditions_Monitor.py",
    group="U.S. Macro Liquidity",
    description=(
        "Classifies U.S. liquidity across structural reserve capacity, overnight "
        "funding, realized reserve flow, and bank credit."
    ),
    primary_inputs=(
        "Federal Reserve H.4.1 and H.8; Fedwire; Daily Treasury Statement; "
        "New York Fed rates and operations; FRED; Yahoo Finance"
    ),
)

TOOL_CATALOG = (TOOL,)

GUIDE = SidebarGuide(
    read_order=(
        "Start with the Liquidity Conditions Index, regime, direction, and four model layers.",
        "Use Reserve Mechanics to identify which Federal Reserve and Treasury items added or drained reserves.",
        "Use Funding and Markets as independent cross-checks, then verify source dates and freshness in Data and Methods.",
    ),
    caveat=(
        "This is a point-in-time liquidity regime diagnostic for discretionary "
        "research, not a standalone market-timing or portfolio instruction."
    ),
)


def tool_for_page(page_filename: str) -> ToolDefinition | None:
    normalized = page_filename.replace("\\", "/").rsplit("/", 1)[-1]
    return TOOL if normalized == TOOL.page_filename else None


def sidebar_guide_for_page(page_filename: str) -> SidebarGuide | None:
    normalized = page_filename.replace("\\", "/").rsplit("/", 1)[-1]
    return GUIDE if normalized == TOOL.page_filename else None
