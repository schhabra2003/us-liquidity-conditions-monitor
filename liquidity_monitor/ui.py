"""Standalone product presentation primitives for the liquidity monitor."""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
from typing import Mapping, Optional, Sequence

import pandas as pd
import streamlit as st

from .catalog import sidebar_guide_for_page, tool_for_page


@dataclass(frozen=True)
class PageHeader:
    """Content used by the product header."""

    title: str
    description: str
    eyebrow: str = "U.S. dollar liquidity"
    as_of: Optional[str] = None
    source_note: Optional[str] = None


def inject_explorer_style(max_width_px: int = 1360) -> None:
    """Inject the single design system used by the standalone application."""

    st.markdown(
        f"""
        <style>
        :root {{
            color-scheme: light;
            --lq-canvas: #FFFFFF;
            --lq-surface: #FFFFFF;
            --lq-surface-muted: #F1F3F5;
            --lq-ink: #111827;
            --lq-text: #303846;
            --lq-muted: #667085;
            --lq-border: #D6DAE1;
            --lq-border-strong: #BCC3CD;
            --lq-navy: #152B49;
            --lq-blue: #2458A6;
            --lq-teal: #137A5B;
            --lq-teal-bg: #EAF7F2;
            --lq-red: #B42318;
            --lq-red-bg: #FEF1F1;
            --lq-amber: #8A5A00;
            --lq-amber-bg: #FFF8E1;
            --lq-info-bg: #EFF6FF;
            --lq-radius-sm: 2px;
            --lq-radius-md: 3px;
            --lq-radius-lg: 4px;
            --lq-shadow: none;
            --lq-font: Arial, Helvetica, sans-serif;
        }}

        html, body, .stApp,
        [data-testid="stAppViewContainer"],
        [data-testid="stMain"] {{
            background: var(--lq-canvas) !important;
            color: var(--lq-ink) !important;
            font-family: var(--lq-font) !important;
            font-variant-numeric: tabular-nums lining-nums;
        }}

        * {{ box-sizing: border-box; }}
        [data-testid="stDecoration"] {{ display: none !important; }}

        header[data-testid="stHeader"],
        section[data-testid="stSidebar"],
        [data-testid="stSidebarCollapsedControl"] {{ display: none !important; }}

        .block-container {{
            width: min(100%, {int(max_width_px)}px) !important;
            max-width: {int(max_width_px)}px !important;
            padding: 1.5rem clamp(1.25rem, 2.2vw, 2.5rem) 2.5rem !important;
        }}

        main, main p, main li, main label,
        [data-testid="stMain"] p,
        [data-testid="stMain"] li,
        [data-testid="stMain"] label {{
            font-family: var(--lq-font) !important;
            color: var(--lq-text) !important;
            font-size: 13px;
            line-height: 1.45;
        }}

        main h1, main h2, main h3,
        [data-testid="stMain"] h1,
        [data-testid="stMain"] h2,
        [data-testid="stMain"] h3 {{
            border: 0 !important;
            color: var(--lq-ink) !important;
            font-family: var(--lq-font) !important;
            letter-spacing: -.02em !important;
        }}

        button,
        [data-testid="stBaseButton-secondary"],
        [data-testid="stBaseButton-primary"],
        [data-testid="stDownloadButton"] button {{
            min-height: 34px !important;
            border: 1px solid var(--lq-border-strong) !important;
            border-radius: var(--lq-radius-sm) !important;
            background: var(--lq-surface) !important;
            color: var(--lq-ink) !important;
            box-shadow: none !important;
            font-family: var(--lq-font) !important;
            font-size: 12px !important;
            font-weight: 600 !important;
            transition: background-color .15s ease, border-color .15s ease,
                color .15s ease !important;
        }}
        button:hover,
        [data-testid="stDownloadButton"] button:hover {{
            border-color: var(--lq-navy) !important;
            background: var(--lq-info-bg) !important;
            color: var(--lq-navy) !important;
        }}
        button:focus-visible,
        [role="tab"]:focus-visible,
        summary:focus-visible {{
            outline: 3px solid rgba(47, 111, 237, .28) !important;
            outline-offset: 2px !important;
        }}

        [data-baseweb="select"] > div,
        [data-baseweb="input"] > div {{
            min-height: 34px !important;
            border-color: var(--lq-border-strong) !important;
            border-radius: var(--lq-radius-sm) !important;
            background: var(--lq-surface) !important;
            box-shadow: none !important;
        }}

        .stTabs [data-baseweb="tab-list"] {{
            gap: 26px !important;
            border-bottom: 1px solid var(--lq-border) !important;
            margin: 2px 0 16px !important;
            overflow-x: auto !important;
        }}
        .stTabs [data-baseweb="tab"] {{
            min-height: 38px !important;
            height: 38px !important;
            border: 0 !important;
            border-radius: 0 !important;
            padding: 0 2px !important;
            background: transparent !important;
            color: var(--lq-muted) !important;
            font-family: var(--lq-font) !important;
            font-size: 13px !important;
            font-weight: 600 !important;
            white-space: nowrap !important;
        }}
        .stTabs [data-baseweb="tab"]:hover {{ color: var(--lq-navy) !important; }}
        .stTabs [aria-selected="true"] {{ color: var(--lq-navy) !important; }}
        .stTabs [data-baseweb="tab-highlight"] {{
            height: 2px !important;
            border-radius: 3px 3px 0 0 !important;
            background: var(--lq-blue) !important;
        }}

        [data-testid="stAlert"] {{
            border: 1px solid #E8D59B !important;
            border-radius: 0 !important;
            background: var(--lq-amber-bg) !important;
            color: var(--lq-ink) !important;
            box-shadow: none !important;
        }}
        [data-testid="stAlert"] p {{ color: var(--lq-text) !important; }}

        [data-testid="stExpander"] details {{
            border: 1px solid var(--lq-border) !important;
            border-radius: var(--lq-radius-sm) !important;
            background: var(--lq-surface) !important;
            box-shadow: var(--lq-shadow) !important;
            overflow: hidden;
        }}
        [data-testid="stExpander"] summary {{
            min-height: 48px;
            color: var(--lq-navy) !important;
            font-family: var(--lq-font) !important;
            font-size: 14px !important;
            font-weight: 600 !important;
        }}

        div[data-testid="stPlotlyChart"] {{
            width: 100% !important;
            max-width: 100% !important;
            border: 1px solid var(--lq-border) !important;
            border-radius: 0 !important;
            background: var(--lq-surface) !important;
            box-shadow: var(--lq-shadow) !important;
            overflow: hidden !important;
            padding: 4px;
        }}
        div[data-testid="stPlotlyChart"] .modebar {{ display: none !important; }}

        div[data-testid="stDataFrame"],
        div[data-testid="stTable"] {{
            border: 1px solid var(--lq-border) !important;
            border-radius: 0 !important;
            background: var(--lq-surface) !important;
            box-shadow: var(--lq-shadow) !important;
            overflow: hidden !important;
        }}

        [data-testid="stCaptionContainer"], .stCaption {{
            color: var(--lq-muted) !important;
            font-family: var(--lq-font) !important;
            font-size: 12px !important;
            line-height: 1.5 !important;
        }}

        .liquidity-page-header {{
            display: grid;
            grid-template-columns: minmax(0, 1fr) minmax(360px, auto);
            gap: 32px;
            align-items: end;
            margin: 0 0 14px;
            padding: 0 0 14px;
            border-bottom: 2px solid var(--lq-navy);
        }}
        .liquidity-header-copy {{ min-width: 0; }}
        .liquidity-eyebrow {{
            margin: 0 0 4px;
            color: var(--lq-muted);
            font-size: 10px;
            font-weight: 700;
            letter-spacing: .12em;
            line-height: 1.4;
            text-transform: uppercase;
        }}
        .liquidity-page-title {{
            margin: 0 !important;
            padding: 0 !important;
            color: var(--lq-ink) !important;
            font-family: var(--lq-font) !important;
            font-size: clamp(25px, 2.1vw, 31px) !important;
            font-weight: 700 !important;
            letter-spacing: -.02em !important;
            line-height: 1.08 !important;
        }}
        .liquidity-page-description {{
            max-width: 860px;
            margin: 5px 0 0;
            color: var(--lq-text);
            font-size: 13px;
            line-height: 1.4;
        }}
        .liquidity-status {{
            display: flex;
            flex-wrap: wrap;
            justify-content: flex-end;
            gap: 3px 14px;
            margin: 0;
            color: var(--lq-muted);
            font-size: 11px;
            font-weight: 500;
            line-height: 1.35;
            text-align: right;
        }}
        .liquidity-status span {{ white-space: normal; }}

        .liquidity-kpi-grid {{
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            margin: 0 0 24px;
            border: 1px solid var(--lq-border);
            border-radius: var(--lq-radius-lg);
            background: var(--lq-surface);
            box-shadow: var(--lq-shadow);
            overflow: hidden;
        }}
        .liquidity-kpi-card {{
            min-height: 92px;
            padding: 14px 16px;
            border-right: 1px solid var(--lq-border);
            background: var(--lq-surface);
        }}
        .liquidity-kpi-card:last-child {{ border-right: 0; }}
        .liquidity-kpi-label {{
            margin-bottom: 6px;
            color: var(--lq-muted);
            font-size: 12px;
            font-weight: 600;
            letter-spacing: .01em;
        }}
        .liquidity-kpi-value {{
            color: var(--lq-ink);
            font-size: clamp(19px, 1.55vw, 24px);
            font-weight: 700;
            letter-spacing: -.025em;
            line-height: 1.15;
        }}
        .liquidity-kpi-note {{
            margin-top: 5px;
            color: var(--lq-muted);
            font-size: 12px;
            line-height: 1.45;
        }}

        .liquidity-selection-note {{
            margin: 0 0 16px;
            padding: 18px 20px;
            border: 1px solid var(--lq-border);
            border-radius: var(--lq-radius-md);
            background: var(--lq-surface);
            color: var(--lq-text);
            font-size: 14px;
            line-height: 1.55;
            box-shadow: var(--lq-shadow);
        }}
        .liquidity-selection-label {{
            margin-bottom: 6px;
            color: var(--lq-navy);
            font-size: 12px;
            font-weight: 700;
        }}

        .liquidity-regime-strip {{
            display: grid;
            grid-template-columns: 1.15fr repeat(5, minmax(0, 1fr));
            border: 1px solid var(--lq-border);
            border-top: 3px solid var(--lq-navy);
            background: var(--lq-surface);
        }}
        .regime-cell {{
            min-width: 0;
            min-height: 102px;
            padding: 13px 14px;
            border-right: 1px solid var(--lq-border);
        }}
        .regime-cell:last-child {{ border-right: 0; }}
        .regime-score-cell {{ background: #F5F7FA; }}
        .regime-label {{
            min-height: 28px;
            color: var(--lq-muted);
            font-size: 10px;
            font-weight: 700;
            letter-spacing: .055em;
            line-height: 1.35;
            text-transform: uppercase;
        }}
        .regime-score {{
            color: var(--lq-ink);
            font-size: 33px;
            font-weight: 700;
            letter-spacing: -.035em;
            line-height: 1;
        }}
        .regime-score span {{ margin-left: 3px; color: var(--lq-muted); font-size: 12px; font-weight: 400; }}
        .regime-value {{
            min-height: 28px;
            color: var(--lq-ink);
            font-size: 18px;
            font-weight: 700;
            letter-spacing: -.015em;
            line-height: 1.18;
        }}
        .regime-value.compact {{ font-size: 14px; letter-spacing: 0; }}
        .regime-value.supportive {{ color: var(--lq-teal); }}
        .regime-value.restrictive {{ color: var(--lq-red); }}
        .regime-value.balanced {{ color: var(--lq-amber); }}
        .regime-footnote {{
            margin-top: 5px;
            color: var(--lq-muted);
            font-size: 10px;
            line-height: 1.3;
        }}
        .regime-combined-mobile {{ display: none; }}

        .liquidity-banner {{
            display: grid;
            grid-template-columns: auto 1fr;
            gap: 12px;
            align-items: start;
            margin: 0 0 10px;
            padding: 8px 11px;
            border: 1px solid var(--lq-border);
            border-radius: 0;
            background: var(--lq-surface);
        }}
        .liquidity-banner.warning {{ border-color: #E8D59B; background: var(--lq-amber-bg); }}
        .liquidity-banner.info {{ border-color: #C9D9EE; background: var(--lq-info-bg); }}
        .liquidity-banner.error {{ border-color: #F1C2BE; background: var(--lq-red-bg); }}
        .liquidity-banner.success {{ border-color: #B6E0D0; background: var(--lq-teal-bg); }}
        .banner-icon {{
            width: 20px;
            height: 20px;
            display: grid;
            place-items: center;
            border-radius: 50%;
            background: var(--lq-surface);
            color: var(--lq-amber);
            font-size: 11px;
            font-weight: 800;
        }}
        .liquidity-banner.error .banner-icon {{ color: var(--lq-red); }}
        .liquidity-banner.success .banner-icon {{ color: var(--lq-teal); }}
        .liquidity-banner.info .banner-icon {{ color: var(--lq-blue); }}
        .banner-title {{ color: var(--lq-ink); font-size: 12px; font-weight: 700; }}
        .banner-text {{ margin-top: 1px; color: var(--lq-text); font-size: 12px; line-height: 1.4; }}

        .liquidity-section-title {{
            margin: 18px 0 3px !important;
            padding: 0 !important;
            color: var(--lq-ink) !important;
            font-family: var(--lq-font) !important;
            font-size: 17px !important;
            font-weight: 700 !important;
            letter-spacing: -.01em !important;
            line-height: 1.35 !important;
        }}
        .liquidity-section-subtitle {{
            max-width: 1050px;
            margin-bottom: 8px;
            color: var(--lq-muted);
            font-size: 12px;
            line-height: 1.4;
        }}

        .mechanics-ledger,
        .source-ledger {{
            margin: 8px 0 20px;
            border: 1px solid var(--lq-border);
            border-radius: var(--lq-radius-md);
            background: var(--lq-surface);
            box-shadow: var(--lq-shadow);
            overflow: hidden;
        }}
        .ledger-header,
        .mechanics-row,
        .source-row {{
            display: grid;
            gap: 20px;
            align-items: start;
            padding: 13px 16px;
            border-bottom: 1px solid var(--lq-border);
            color: var(--lq-text);
            font-family: var(--lq-font);
            font-size: 13px;
            line-height: 1.45;
        }}
        .ledger-header {{
            background: var(--lq-surface-muted);
            color: var(--lq-muted);
            font-size: 11px;
            font-weight: 700;
            letter-spacing: .035em;
            text-transform: uppercase;
        }}
        .mechanics-ledger .ledger-header,
        .mechanics-row {{ grid-template-columns: minmax(150px, .7fr) minmax(220px, 1.35fr) minmax(190px, 1fr); }}
        .source-ledger .ledger-header,
        .source-row {{ grid-template-columns: minmax(170px, .85fr) minmax(190px, .85fr) minmax(250px, 1.25fr); }}
        .mechanics-row:last-child,
        .source-row:last-child {{ border-bottom: 0; }}
        .mechanics-row strong,
        .source-name,
        .source-value {{ color: var(--lq-ink); font-weight: 600; }}
        .source-key,
        .source-clock,
        .evidence-note {{ margin-top: 3px; color: var(--lq-muted); font-size: 12px; line-height: 1.45; }}
        .source-key a {{ color: var(--lq-blue); text-decoration: none; }}
        .source-key a:hover {{ text-decoration: underline; }}
        .source-status {{ color: var(--lq-text); font-weight: 600; }}

        .evidence-note {{
            margin: -8px 0 20px;
            padding: 0 4px;
        }}

        .visually-hidden {{
            position: absolute !important;
            width: 1px !important;
            height: 1px !important;
            padding: 0 !important;
            margin: -1px !important;
            overflow: hidden !important;
            clip: rect(0, 0, 0, 0) !important;
            white-space: nowrap !important;
            border: 0 !important;
        }}

        .liquidity-footer {{
            display: flex;
            justify-content: space-between;
            gap: 24px;
            margin-top: 48px;
            padding-top: 18px;
            border-top: 1px solid var(--lq-border);
            color: var(--lq-muted);
            font-size: 11px;
            line-height: 1.5;
        }}
        .liquidity-footer-note {{ max-width: 960px; }}
        .liquidity-footer-product {{ white-space: nowrap; }}

        @media (max-width: 900px) {{
            .block-container {{ padding: 1.25rem 1.5rem 2.5rem !important; }}
            .liquidity-page-header {{ grid-template-columns: 1fr; gap: 8px; align-items: start; }}
            .liquidity-status {{ justify-content: flex-start; text-align: left; }}
            .liquidity-regime-strip {{ grid-template-columns: repeat(3, minmax(0, 1fr)); }}
            .regime-cell {{ border-bottom: 1px solid var(--lq-border); }}
            .regime-cell:nth-child(3n) {{ border-right: 0; }}
            .regime-cell:nth-child(n+4) {{ border-bottom: 0; }}
            .liquidity-kpi-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
            .liquidity-kpi-card:nth-child(2) {{ border-right: 0; }}
            .liquidity-kpi-card:nth-child(n+3) {{ border-top: 1px solid var(--lq-border); }}
            .mechanics-ledger .ledger-header,
            .mechanics-row,
            .source-ledger .ledger-header,
            .source-row {{ grid-template-columns: minmax(130px, .7fr) minmax(180px, 1fr) minmax(190px, 1fr); }}
        }}

        @media (max-width: 600px) {{
            .block-container {{
                width: 100% !important;
                max-width: 100% !important;
                padding: 1rem 1rem 2rem !important;
                overflow-x: clip !important;
            }}
            .liquidity-page-header {{ grid-template-columns: 1fr; gap: 6px; margin-bottom: 10px; padding-bottom: 10px; }}
            .liquidity-page-title {{ font-size: 22px !important; }}
            .liquidity-page-description {{ font-size: 12px; }}
            .liquidity-status {{ display: block; }}
            .liquidity-status span {{ display: block; margin-top: 2px; }}
            .liquidity-regime-strip {{
                grid-template-columns: repeat(2, minmax(0, 1fr));
                grid-template-areas:
                    "score combined"
                    "driver driver"
                    "funding risk";
            }}
            .regime-cell {{ min-height: 72px; padding: 9px 11px; border-right: 1px solid var(--lq-border); border-bottom: 1px solid var(--lq-border); }}
            .regime-score-cell {{ grid-area: score; }}
            .regime-level-cell,
            .regime-trend-cell {{ display: none; }}
            .regime-driver-cell {{ grid-area: driver; border-right: 0; }}
            .regime-funding-cell {{ grid-area: funding; border-bottom: 0; }}
            .regime-risk-cell {{ grid-area: risk; border-right: 0; border-bottom: 0; }}
            .regime-combined-mobile {{ display: block; grid-area: combined; border-right: 0; }}
            .regime-label {{ min-height: auto; margin-bottom: 3px; }}
            .regime-score {{ font-size: 30px; }}
            .regime-value {{ font-size: 16px; }}
            .regime-footnote {{ margin-top: 3px; }}
            .liquidity-banner.info {{ grid-template-columns: 1fr; padding: 6px 9px; }}
            .liquidity-banner.info .banner-icon,
            .liquidity-banner.info .banner-text {{ display: none; }}
            .liquidity-banner.info .banner-title {{ font-size: 11px; }}
            .liquidity-kpi-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
            .liquidity-kpi-card {{ min-height: 108px; border-top: 0; }}
            .liquidity-kpi-card:nth-child(2n) {{ border-right: 0; }}
            .liquidity-kpi-card:nth-child(n+3) {{ border-top: 1px solid var(--lq-border); }}
            .stTabs [data-baseweb="tab-list"] {{
                display: grid !important;
                grid-template-columns: repeat(2, minmax(0, 1fr)) !important;
                gap: 0 16px !important;
                overflow: visible !important;
            }}
            .stTabs [data-baseweb="tab"] {{
                width: 100% !important;
                min-width: 0 !important;
                justify-content: flex-start !important;
                text-align: left !important;
            }}
            .stTabs [data-baseweb="tab-highlight"] {{ display: none !important; }}
            .stTabs [aria-selected="true"] {{ border-bottom: 3px solid var(--lq-blue) !important; }}
            .liquidity-footer {{ display: block; }}
            .liquidity-footer-product {{ display: block; margin-top: 8px; }}
            div[data-testid="stPlotlyChart"] {{ padding: 0; }}
            .ledger-header {{ display: none; }}
            .mechanics-row,
            .source-row {{ grid-template-columns: 1fr; gap: 4px; padding: 14px; }}
        }}

        @media (prefers-reduced-motion: reduce) {{
            *, *::before, *::after {{ scroll-behavior: auto !important; transition: none !important; }}
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


# Backwards-compatible names for notebooks using the public module.
inject_institutional_theme = inject_explorer_style
inject_base_style = inject_explorer_style


def inject_institutional_tool_finish() -> None:
    """Compatibility no-op; the standalone product uses one theme layer."""


def render_kpi_cards(cards: Sequence[tuple[str, str, str]]) -> None:
    """Render decision metrics as one coherent command strip."""

    body = []
    for label, value, note in cards:
        body.append(
            "<div class='liquidity-kpi-card'>"
            f"<div class='liquidity-kpi-label'>{escape(str(label))}</div>"
            f"<div class='liquidity-kpi-value'>{escape(str(value))}</div>"
            f"<div class='liquidity-kpi-note'>{escape(str(note))}</div>"
            "</div>"
        )
    st.markdown(
        "<div class='liquidity-kpi-grid'>" + "".join(body) + "</div>",
        unsafe_allow_html=True,
    )


def render_regime_summary(
    *,
    index: float,
    level: str,
    trend: str,
    four_week_change: str,
    percentile: str,
    primary_driver: str,
    primary_driver_label: str,
    primary_driver_note: str,
    funding_state: str,
    market_confirmation: str,
    publication_current: bool = True,
) -> None:
    """Render a compact sell-side regime summary."""

    index_label = (
        "U.S. Liquidity Conditions Index"
        if publication_current
        else "Last verified Liquidity Conditions Index"
    )
    level_class = {
        "supportive": "supportive",
        "balanced": "balanced",
        "restrictive": "restrictive",
    }.get(level.lower(), "balanced")
    trend_class = {
        "improving": "supportive",
        "stable": "balanced",
        "deteriorating": "restrictive",
    }.get(trend.lower(), "balanced")
    st.markdown(
        "<section class='liquidity-regime-strip' aria-label='"
        f"{escape(level, quote=True)} liquidity, {escape(trend, quote=True)}'>"
        "<div class='regime-cell regime-score-cell'>"
        f"<div class='regime-label'>{escape(index_label)}</div>"
        f"<div class='regime-score'>{index:.1f}<span>/100</span></div>"
        f"<div class='regime-footnote'>{escape(percentile)}</div>"
        "</div>"
        "<div class='regime-cell regime-level-cell'>"
        "<div class='regime-label'>Level</div>"
        f"<div class='regime-value {level_class}'>{escape(level)}</div>"
        "<div class='regime-footnote'>Below 35 is restrictive</div>"
        "</div>"
        "<div class='regime-cell regime-trend-cell'>"
        "<div class='regime-label'>Four-week direction</div>"
        f"<div class='regime-value {trend_class}'>{escape(trend)}</div>"
        f"<div class='regime-footnote'>{escape(four_week_change)}</div>"
        "</div>"
        "<div class='regime-cell regime-driver-cell'>"
        f"<div class='regime-label'>{escape(primary_driver_label)}</div>"
        f"<div class='regime-value compact'>{escape(primary_driver)}</div>"
        f"<div class='regime-footnote'>{escape(primary_driver_note)}</div>"
        "</div>"
        "<div class='regime-cell regime-funding-cell'>"
        "<div class='regime-label'>Funding</div>"
        f"<div class='regime-value compact'>{escape(funding_state)}</div>"
        "<div class='regime-footnote'>Independent stress check</div>"
        "</div>"
        "<div class='regime-cell regime-risk-cell'>"
        "<div class='regime-label'>Risk confirmation</div>"
        f"<div class='regime-value compact'>{escape(market_confirmation)}</div>"
        "<div class='regime-footnote'>Zero index weight</div>"
        "</div>"
        "<div class='regime-cell regime-combined-mobile'>"
        "<div class='regime-label'>Regime</div>"
        f"<div class='regime-value {level_class}'>{escape(level)} / {escape(trend)}</div>"
        f"<div class='regime-footnote'>{escape(four_week_change)}</div>"
        "</div>"
        "</section>",
        unsafe_allow_html=True,
    )


def render_status_banner(title: str, text: str, tone: str = "warning") -> None:
    """Render a concise publication or data-health state."""

    safe_tone = tone if tone in {"warning", "error", "success", "info"} else "warning"
    symbol = {"warning": "!", "error": "×", "success": "✓", "info": "i"}[safe_tone]
    st.markdown(
        f"<div class='liquidity-banner {safe_tone}' role='status'>"
        f"<div class='banner-icon' aria-hidden='true'>{symbol}</div>"
        "<div>"
        f"<div class='banner-title'>{escape(title)}</div>"
        f"<div class='banner-text'>{escape(text)}</div>"
        "</div></div>",
        unsafe_allow_html=True,
    )


def render_selection_note(label: str, text: str) -> None:
    """Render a concise narrative note."""

    st.markdown(
        "<div class='liquidity-selection-note'>"
        f"<div class='liquidity-selection-label'>{escape(str(label))}</div>"
        f"<div>{escape(str(text))}</div>"
        "</div>",
        unsafe_allow_html=True,
    )


def render_section_header(title: str, subtitle: str) -> None:
    """Render a consistent analytical section heading."""

    st.markdown(
        f"<h2 class='liquidity-section-title'>{escape(str(title))}</h2>"
        f"<div class='liquidity-section-subtitle'>{escape(str(subtitle))}</div>",
        unsafe_allow_html=True,
    )


def render_sidebar_about(page_filename: str) -> None:
    """Render concise model guidance in the optional sidebar."""

    tool = tool_for_page(page_filename)
    guide = sidebar_guide_for_page(page_filename)
    if tool is None or guide is None:
        raise ValueError(f"No sidebar guide is registered for {page_filename!r}")
    steps = "\n".join(
        f"{index}. {step}" for index, step in enumerate(guide.read_order, start=1)
    )
    st.header("About this model")
    st.markdown(f"{tool.description}\n\n**How to use this dashboard**\n\n{steps}")
    if guide.caveat:
        st.caption(guide.caveat)
    st.divider()


def render_page_header(header: PageHeader) -> None:
    """Render compact product identity and model-date metadata."""

    status_items = [item for item in (header.as_of, header.source_note) if item]
    status = "".join(f"<span>{escape(item)}</span>" for item in status_items)
    st.markdown(
        "<header class='liquidity-page-header'>"
        "<div class='liquidity-header-copy'>"
        f"<div class='liquidity-eyebrow'>{escape(header.eyebrow)}</div>"
        f"<h1 class='liquidity-page-title'>{escape(header.title)}</h1>"
        f"<div class='liquidity-page-description'>{escape(header.description)}</div>"
        "</div>"
        + (f"<div class='liquidity-status'>{status}</div>" if status else "<div></div>")
        + "</header>",
        unsafe_allow_html=True,
    )


def render_status_line(**items: object) -> None:
    """Render escaped status metadata while omitting missing values."""

    parts = [
        f"<span>{escape(label.replace('_', ' ').title())}: {escape(str(value))}</span>"
        for label, value in items.items()
        if value not in (None, "")
    ]
    if parts:
        st.markdown(
            "<div class='liquidity-status'>" + "".join(parts) + "</div>",
            unsafe_allow_html=True,
        )


def metric_table(
    frame: pd.DataFrame, column_config: Optional[Mapping[str, object]] = None
) -> None:
    """Render a consistent full-width table without transforming values."""

    st.dataframe(
        frame,
        use_container_width=True,
        hide_index=True,
        column_config=dict(column_config or {}),
    )


def dataframe_download(label: str, frame: pd.DataFrame, filename: str) -> None:
    """Offer a CSV export of underlying numeric values."""

    st.download_button(
        label=label,
        data=frame.to_csv(index=False).encode("utf-8"),
        file_name=filename,
        mime="text/csv",
    )


def render_footer(
    text: str = "U.S. Liquidity Monitor | Independent research tool",
    data_note: Optional[str] = None,
) -> None:
    """Render the standalone product footer."""

    if data_note is None:
        data_note = (
            "Public-source research. Dates and release status are shown in the dashboard. "
            "Missing observations remain unavailable rather than being fabricated."
        )
    st.markdown(
        "<footer class='liquidity-footer'>"
        f"<span class='liquidity-footer-note'>{escape(data_note)}</span>"
        f"<span class='liquidity-footer-product'>{escape(text)}</span>"
        "</footer>",
        unsafe_allow_html=True,
    )
