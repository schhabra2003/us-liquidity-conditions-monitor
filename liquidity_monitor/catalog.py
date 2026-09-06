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
    title="U.S. Liquidity Monitor",
    page_filename="Liquidity_Conditions_Monitor.py",
    group="U.S. dollar liquidity",
    description=(
        "Tracks the level and direction of U.S. dollar liquidity using reserve "
        "capacity, funding conditions, reserve flows, and bank credit."
    ),
    primary_inputs=(
        "Federal Reserve H.4.1 and H.8; Fedwire; Daily Treasury Statement; "
        "New York Fed rates and operations; FRED; Yahoo Finance"
    ),
)

TOOL_CATALOG = (TOOL,)

GUIDE = SidebarGuide(
    read_order=(
        "Start with the index level, four-week trend, and primary drivers.",
        "Review Reserve flows to identify the Federal Reserve and Treasury items adding or draining reserves.",
        "Use Funding and markets as confirmation, then verify source timing under Data and methodology.",
    ),
    caveat=(
        "This model describes the current U.S. liquidity backdrop. It is not a "
        "standalone market-timing or portfolio instruction."
    ),
)


def tool_for_page(page_filename: str) -> ToolDefinition | None:
    normalized = page_filename.replace("\\", "/").rsplit("/", 1)[-1]
    return TOOL if normalized == TOOL.page_filename else None


def sidebar_guide_for_page(page_filename: str) -> SidebarGuide | None:
    normalized = page_filename.replace("\\", "/").rsplit("/", 1)[-1]
    return GUIDE if normalized == TOOL.page_filename else None
