"""U.S. U.S. Liquidity Conditions Monitor.

The manager-facing page presents observed reserve mechanics, recent direction,
market context, source integrity, and transparent methodology.
"""

from __future__ import annotations

import os
from html import escape
from pathlib import Path

import pandas as pd
import streamlit as st

from liquidity_monitor.liquidity_formatting import (
    describe_layer_contribution,
    format_basis_points,
    format_normalized,
    format_percentile,
    format_usd_billions,
)
from liquidity_monitor.liquidity_live_snapshot import load_live_snapshot
from liquidity_monitor.liquidity_signal_monitor import (
    current_mechanics_figure,
    diagnostic_summary,
    latest_observed_state,
    liquidity_impulse_figure,
    live_source_status_table,
    load_liquidity_bundle,
    source_status_table,
)
from liquidity_monitor.palette import PASTEL
from liquidity_monitor.structural_liquidity import (
    classify_market_confirmation,
    classify_transmission_state,
    market_confirmation_figure,
    market_confirmation_snapshot,
    transmission_conditions_figure,
    transmission_snapshot,
)
from liquidity_monitor.ui import (
    PageHeader,
    inject_explorer_style,
    render_footer,
    render_kpi_cards,
    render_page_header,
    render_section_header,
    render_selection_note,
    render_sidebar_about,
)
from liquidity_monitor.us_liquidity_model import (
    build_us_liquidity_model,
    funding_market_figure,
    liquidity_conditions_history_figure,
    liquidity_deviation_figure,
    liquidity_layers_figure,
)

ROOT = Path(__file__).resolve().parents[1]
BUNDLE_ROOT = ROOT / "data" / "liquidity_model_bundle"
LIVE_ROOT = Path(
    os.environ.get(
        "US_LIQUIDITY_LIVE_ROOT",
        str(ROOT / "data" / "liquidity_live_snapshot"),
    )
)
TITLE = "Liquidity Conditions Monitor"
REGIME_ROSE = f"{PASTEL['rose']}14"
REGIME_SAGE = f"{PASTEL['sage']}14"

st.set_page_config(
    page_title=TITLE,
    page_icon="◫",
    layout="wide",
    initial_sidebar_state="collapsed",
)
inject_explorer_style(max_width_px=1560)

# Shared local primitives provide the shell, typography, cards, tables, tabs,
# and footer. The selectors below define monitor-specific content structures.
st.markdown(
    f"""
    <style>
        /* {TITLE} page-specific structures */
        main .liquidity-page-header h1.liquidity-page-title,
        .stMain .liquidity-page-header h1.liquidity-page-title {{
            border: 0 !important;
            margin: 0 !important;
            padding: 0 !important;
        }}
        main h2.liquidity-section-title,
        .stMain h2.liquidity-section-title {{
            border: 0 !important;
            margin: 1rem 0 .24rem !important;
            padding: 0 !important;
        }}
        .liquidity-page-title > span:last-child,
        .liquidity-section-title > span:last-child {{
            display: none !important;
        }}

        .evidence-panel {{
            border: 1px solid #c9c9c9;
            min-height: 100%;
            padding: 1rem;
            background: #ffffff;
        }}

        .evidence-row {{
            border-top: 1px solid #d8d8d8;
            padding: .72rem 0;
            color: #303030;
            font-family: Arial, Helvetica, sans-serif;
            font-size: .75rem;
            line-height: 1.45;
        }}

        .evidence-row:last-child {{ border-bottom: 1px solid #d8d8d8; }}
        .evidence-label {{
            color: #555555;
            font-size: .66rem;
            font-weight: 800;
            letter-spacing: .09em;
            text-transform: uppercase;
        }}
        .evidence-state {{ color: #000000; font-size: .98rem; font-weight: 700; margin: .12rem 0; }}
        .evidence-note {{ color: #5a5a5a; font-size: .70rem; }}
        .evidence-watch {{
            border-top: 1px solid #d8d8d8;
            color: #303030;
            font-family: Arial, Helvetica, sans-serif;
            font-size: .72rem;
            line-height: 1.45;
            margin-top: .68rem;
            padding-top: .68rem;
        }}
        .evidence-watch strong {{ color: #000000; }}

        .section-kicker {{
            color: #555555;
            font-family: Arial, Helvetica, sans-serif;
            font-size: .66rem;
            font-weight: 800;
            letter-spacing: .12em;
            line-height: 1.25;
            text-transform: uppercase;
            margin-bottom: .35rem;
        }}

        .regime-classifier {{
            max-width: 980px;
            margin-top: .7rem;
            padding: .72rem .9rem .8rem;
            border: 1px solid #c9c9c9;
            background: #ffffff;
        }}

        .classifier-grid {{
            display: grid;
            grid-template-columns: 94px repeat(3, minmax(0, 1fr));
            gap: 6px;
            width: 100%;
        }}

        .classifier-corner,
        .classifier-column,
        .classifier-row {{
            display: flex;
            align-items: center;
            color: #666666;
            font-family: Arial, Helvetica, sans-serif;
            font-size: .65rem;
            font-weight: 800;
            letter-spacing: .08em;
            line-height: 1.25;
            text-transform: uppercase;
        }}

        .classifier-corner {{ align-items: flex-end; }}
        .classifier-column {{ justify-content: center; text-align: center; padding-bottom: .15rem; }}
        .classifier-row {{ justify-content: flex-end; padding-right: .45rem; text-align: right; }}

        .regime-cell {{
            min-height: 48px;
            display: flex;
            flex-direction: column;
            justify-content: center;
            border: 1px solid #d8d8d8;
            padding: .42rem .58rem;
            color: #333333;
            font-family: Arial, Helvetica, sans-serif;
        }}

        .regime-cell.below_normal {{ background: {REGIME_ROSE}; }}
        .regime-cell.near_normal {{ background: #f6f4ed; }}
        .regime-cell.above_normal {{ background: {REGIME_SAGE}; }}

        .regime-cell.active {{
            background: #000000;
            border: 2px solid #000000;
            color: #ffffff;
        }}

        .regime-cell-title {{
            font-size: .75rem;
            font-weight: 800;
            letter-spacing: .015em;
            line-height: 1.2;
            hyphens: none;
            overflow-wrap: normal;
            word-break: normal;
        }}

        .classifier-axis-note {{
            color: #666666;
            font-family: Arial, Helvetica, sans-serif;
            font-size: .64rem;
            letter-spacing: .04em;
            margin: .55rem 0 0 100px;
            text-align: center;
        }}

        .source-ledger {{
            border-top: 1px solid #c9c9c9;
            margin-top: .35rem;
        }}

        .source-row {{
            display: grid;
            grid-template-columns: minmax(135px, .8fr) minmax(180px, 1fr) minmax(190px, 1.25fr);
            gap: 1rem;
            align-items: start;
            border-bottom: 1px solid #e2e2e2;
            padding: .68rem 0;
            font-family: Arial, Helvetica, sans-serif;
            font-size: .76rem;
            line-height: 1.45;
        }}

        .source-name {{ color: #000000; font-weight: 700; }}
        .source-key {{ color: #666666; font-size: .68rem; margin-top: .12rem; }}
        .source-status {{ color: #202020; font-weight: 700; letter-spacing: .025em; }}
        .source-value {{ color: #000000; font-weight: 700; }}
        .source-clock {{ color: #5a5a5a; font-size: .70rem; margin-top: .12rem; }}

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

        section[data-testid="stSidebar"][aria-expanded="false"] * {{
            visibility: hidden !important;
            pointer-events: none !important;
        }}

        button[data-testid="stExpandSidebarButton"],
        [data-testid="stSidebarCollapseButton"] button {{
            min-width: 52px !important;
            width: 52px !important;
            min-height: 44px !important;
            height: 44px !important;
        }}

        button[data-testid="stExpandSidebarButton"] [data-testid="stIconMaterial"],
        [data-testid="stSidebarCollapseButton"] [data-testid="stIconMaterial"] {{
            display: none !important;
        }}

        button[data-testid="stExpandSidebarButton"]::after {{
            content: "Menu";
            color: inherit;
            font-family: Arial, Helvetica, sans-serif;
            font-size: .68rem;
            font-weight: 800;
            letter-spacing: .04em;
            text-transform: uppercase;
        }}

        [data-testid="stSidebarCollapseButton"] button::after {{
            content: "Close";
            color: inherit;
            font-family: Arial, Helvetica, sans-serif;
            font-size: .68rem;
            font-weight: 800;
            letter-spacing: .04em;
            text-transform: uppercase;
        }}

        .mechanics-ledger {{ border-top: 1px solid #c9c9c9; }}
        .ledger-header {{
            display: grid;
            gap: 1rem;
            border-bottom: 1px solid #a8a8a8;
            padding: .5rem 0;
            color: #555555;
            font-family: Arial, Helvetica, sans-serif;
            font-size: .64rem;
            font-weight: 800;
            letter-spacing: .08em;
            line-height: 1.25;
            text-transform: uppercase;
        }}
        .source-ledger .ledger-header {{
            grid-template-columns: minmax(135px, .8fr) minmax(180px, 1fr) minmax(190px, 1.25fr);
        }}
        .mechanics-ledger .ledger-header {{
            grid-template-columns: minmax(120px, .55fr) minmax(180px, 1fr) minmax(180px, 1fr);
        }}
        .mechanics-row {{
            display: grid;
            grid-template-columns: minmax(120px, .55fr) minmax(180px, 1fr) minmax(180px, 1fr);
            gap: 1rem;
            border-bottom: 1px solid #e2e2e2;
            padding: .72rem 0;
            color: #303030;
            font-family: Arial, Helvetica, sans-serif;
            font-size: .76rem;
            line-height: 1.45;
        }}
        .mechanics-row strong {{ color: #000000; }}

        @media (max-width: 760px) {{
            .regime-classifier {{ padding: .72rem .62rem .8rem; }}
            .classifier-grid {{ grid-template-columns: 68px repeat(3, minmax(0, 1fr)); gap: 4px; }}
            .classifier-column, .classifier-row {{ font-size: .62rem; letter-spacing: .035em; }}
            .classifier-row {{ padding-right: .2rem; }}
            .regime-cell {{ min-height: 42px; padding: .3rem .4rem; }}
            .regime-cell-title {{ font-size: .69rem; }}
            .classifier-axis-note {{ margin-left: 72px; }}

            .stTabs [data-baseweb="tab-list"] {{
                display: grid !important;
                grid-template-columns: repeat(2, minmax(0, 1fr)) !important;
                overflow: visible !important;
                gap: 0 !important;
                border: 1px solid #000000 !important;
                border-right: 0 !important;
                border-bottom: 0 !important;
            }}
            .stTabs [data-baseweb="tab"] {{
                width: 100% !important;
                min-width: 0 !important;
                min-height: 44px !important;
                height: 44px !important;
                justify-content: center !important;
                border-right: 1px solid #000000 !important;
                border-bottom: 1px solid #000000 !important;
                padding: 0 .45rem !important;
                white-space: normal !important;
                text-align: center !important;
            }}
            .stTabs [data-baseweb="tab-highlight"] {{ display: none !important; }}

            .source-row,
            .mechanics-row {{
                grid-template-columns: 1fr;
                gap: .22rem;
            }}
            .ledger-header {{ display: none; }}
        }}

        @media (max-width: 440px) {{
            .classifier-grid {{ grid-template-columns: 76px repeat(3, minmax(0, 1fr)); }}
            .classifier-corner,
            .classifier-column,
            .classifier-row {{ font-size: .58rem; letter-spacing: .015em; }}
            .classifier-row {{ padding-right: .15rem; }}
            .regime-cell {{ min-height: 42px; padding: .28rem .3rem; }}
            .regime-cell-title {{ font-size: .66rem; line-height: 1.18; }}
            .classifier-axis-note {{ margin-left: 80px; }}
        }}
    </style>
    """,
    unsafe_allow_html=True,
)


def _load_bundle(manifest_mtime_ns: int):
    """Load and verify the packaged history for the current page run.

    Streamlit executes multipage files through a dynamic module.  Decorating a
    page-local function with ``st.cache_data`` makes Python's source inspector
    parse only a suffix of that dynamic module, which can fail after CSS or HTML
    edits even when the page itself is valid Python.  The underlying CSV bundle
    is small, so a verified load on each rerun is the safer release behaviour.
    """

    del manifest_mtime_ns
    return load_liquidity_bundle(BUNDLE_ROOT, verify_hashes=True)


def _load_live(manifest_mtime_ns: int):
    """Load and verify the current snapshot for the current page run."""

    del manifest_mtime_ns
    return load_live_snapshot(LIVE_ROOT, verify_hashes=True)


def _render_chart_accessibility(label: str, summary_text: str) -> None:
    """Expose a concise chart interpretation to non-visual navigation."""

    accessible_text = f"{label}. {summary_text}"
    st.markdown(
        "<div class='visually-hidden' role='img' aria-label='"
        + escape(accessible_text, quote=True)
        + "'>"
        + escape(accessible_text)
        + "</div>",
        unsafe_allow_html=True,
    )


try:
    bundle = _load_bundle((BUNDLE_ROOT / "manifest.json").stat().st_mtime_ns)
except (FileNotFoundError, ValueError) as error:
    render_page_header(
        PageHeader(
            title=TITLE,
            eyebrow="U.S. Macro Liquidity",
            description=(
                "Institutional U.S. liquidity mechanics, market context, and validation."
            ),
        )
    )
    st.error(f"The hash-verified research bundle could not be loaded: {error}")
    st.caption(
        "Run scripts/export_liquidity_research_bundle.py against a validated research release."
    )
    render_footer(
        data_note=(
            "No liquidity state was issued because the research bundle failed integrity checks."
        )
    )
    st.stop()


try:
    live_snapshot = _load_live((LIVE_ROOT / "manifest.json").stat().st_mtime_ns)
    live_error = None
except (FileNotFoundError, ValueError) as error:
    live_snapshot = None
    live_error = str(error)

summary = diagnostic_summary(bundle, live_snapshot=live_snapshot)
latest = latest_observed_state(bundle, live_snapshot)
liquidity_result = None
liquidity_error = None
if live_snapshot is not None:
    try:
        liquidity_result = build_us_liquidity_model(live_snapshot)
    except (KeyError, ValueError, FileNotFoundError) as error:
        liquidity_error = str(error)

with st.sidebar:
    render_sidebar_about("Liquidity_Conditions_Monitor.py")
    st.header("Display")
    lookback_label = st.selectbox(
        "Historical window", ("1 year", "3 years", "5 years", "Full history"), index=1
    )
    lookback_years = {
        "1 year": 1,
        "3 years": 3,
        "5 years": 5,
        "Full history": None,
    }[lookback_label]
    lookback_window_text = (
        "full-history" if lookback_years is None else f"{lookback_years}-year"
    )
    st.caption("Display controls do not alter the underlying data or calculations.")
    st.divider()
    st.header("Data status")
    st.caption(f"Latest source observations through {summary['observed_as_of'].date()}")
    st.caption(f"Reserve accounting through {summary['accounting_as_of'].date()}")
    st.caption(f"Market context through {summary['market_as_of'].date()}")
    if live_snapshot is not None and liquidity_result is not None:
        st.caption("Schemas, row counts, and checksums verified.")
    else:
        st.caption("The current operating release did not pass validation.")


if live_snapshot is None or liquidity_result is None:
    failure_detail = live_error or liquidity_error or "Current model output is unavailable."
    render_page_header(
        PageHeader(
            title=TITLE,
            eyebrow="U.S. Macro Liquidity",
            description=(
                "The current U.S. liquidity release did not pass publication controls."
            ),
            as_of="No current liquidity regime issued",
            source_note="The last-good release remains preserved for investigation.",
        )
    )
    st.error("Current liquidity regime unavailable")
    st.caption(f"Validation detail: {failure_detail}")
    st.markdown(
        "The monitor has suppressed the regime, direction, index, and component readings. "
        "Refresh and validate the operating snapshot before using this page."
    )
    render_footer(
        data_note=(
            "No current liquidity state was issued because the operating release failed integrity checks."
        )
    )
    st.stop()


current_count = summary["sources_total"] - summary["sources_stale"]
reserve_score = float(summary["reserve_percentile"])
reserve_change = float(summary["reserve_impulse_change_4w_bp"])
trend_label = str(summary["observed_regime_trend"])
trend_read = trend_label.lower()
reserve_regime = f"{summary['mechanical_direction']}, {trend_read}"
trend_band = float(summary["observed_regime_trend_band_bp"])
current_reserve_impulse = float(summary["reserve_impulse_bp"])

source_table = (
    live_source_status_table(live_snapshot)
    if live_snapshot is not None
    else source_status_table(bundle)
)
refresh_mask = ~source_table["Live status"].astype(str).str.startswith("CURRENT")
refresh_sources = source_table.loc[refresh_mask, "Series"].astype(str).tolist()
refresh_count = len(refresh_sources)
if refresh_count == 0:
    coverage_note = (
        f"All {summary['sources_total']} required sources are current under their "
        "release schedules and have passed integrity checks."
    )
elif refresh_count == 1:
    coverage_note = (
        f"1 of {summary['sources_total']} required sources requires refresh. "
        f"{refresh_sources[0]} is stale under its release schedule."
    )
else:
    stale_list = ", ".join(refresh_sources[:-1]) + f", and {refresh_sources[-1]}"
    coverage_note = (
        f"{refresh_count} of {summary['sources_total']} required sources require "
        f"refresh. {stale_list} are stale under their release schedules."
    )

reserve_change_abs = format_basis_points(abs(reserve_change))
if reserve_change > 0 and current_reserve_impulse < 0:
    reserve_change_direction = f"The reserve drain eased by {reserve_change_abs}"
elif reserve_change > 0:
    reserve_change_direction = f"Reserve addition strengthened by {reserve_change_abs}"
elif reserve_change < 0 and current_reserve_impulse > 0:
    reserve_change_direction = f"Reserve addition weakened by {reserve_change_abs}"
elif reserve_change < 0:
    reserve_change_direction = f"The reserve drain deepened by {reserve_change_abs}"
else:
    reserve_change_direction = "Reserve flow was unchanged"

reserve_driver_effects = {
    "Federal Reserve assets": float(latest["fed_asset_change_4w_bp"]),
    "Treasury General Account": -float(latest["tga_change_4w_bp_assets"]),
    "Overnight reverse repo": -float(latest["onrrp_change_4w_bp_assets"]),
    "Currency": -float(latest["currency_change_4w_bp_assets"]),
    "Other liabilities and accounting residual": float(
        latest["other_liability_residual_4w_bp"]
    ),
}
if current_reserve_impulse < 0:
    reserve_flow_label = "drain"
    dominant_driver = min(reserve_driver_effects, key=reserve_driver_effects.get)
    dominant_role = "negative contributor"
elif current_reserve_impulse > 0:
    reserve_flow_label = "addition"
    dominant_driver = max(reserve_driver_effects, key=reserve_driver_effects.get)
    dominant_role = "positive contributor"
else:
    reserve_flow_label = "change"
    dominant_driver = max(
        reserve_driver_effects, key=lambda key: abs(reserve_driver_effects[key])
    )
    dominant_role = "largest absolute contributor"
dominant_driver_value = reserve_driver_effects[dominant_driver]
reserve_driver_title = f"Drivers of the four-week reserve {reserve_flow_label}"
if dominant_driver == "Other liabilities and accounting residual":
    reserve_driver_note = (
        f"{dominant_driver} are the largest current {dominant_role} at "
        f"{format_basis_points(dominant_driver_value, signed=True)}. This category "
        "captures non-TGA Federal Reserve liabilities and reserve changes not explained "
        "by the separately displayed accounting drivers."
    )
else:
    reserve_driver_note = (
        f"{dominant_driver} is the largest current {dominant_role} at "
        f"{format_basis_points(dominant_driver_value, signed=True)}. The five displayed "
        "drivers reconcile to the net reserve impulse."
    )
if abs(reserve_change) <= trend_band:
    reserve_change_note = (
        f"{reserve_change_direction}. The move remains within the model's normal-variation "
        "band and does not constitute a material regime change."
    )
else:
    reserve_change_note = (
        f"{reserve_change_direction}. The move exceeds the model's normal-variation "
        "band and constitutes a material regime change."
    )

if liquidity_result is not None:
    current_deviation = float(
        liquidity_result.history["mechanical_deviation_bp"].dropna().iloc[-1]
    )
    deviation_direction = "stronger" if current_deviation >= 0 else "weaker"
    deviation_state = str(liquidity_result.current["mechanical_deviation_state"])
    if deviation_state == "Near seasonal norm":
        deviation_range_text = "has a standardized deviation near its historical norm"
    elif deviation_state == "More supportive than seasonal norm":
        deviation_range_text = "has a materially supportive standardized deviation"
    else:
        deviation_range_text = "has a materially restrictive standardized deviation"
    seasonal_note = (
        f"Reserve flow is {format_basis_points(abs(current_deviation))} "
        f"{deviation_direction} than the prior seasonal median and "
        f"{deviation_range_text}."
    )
else:
    current_deviation = float("nan")
    deviation_state = "Not available"
    seasonal_note = "Current seasonal comparison is unavailable."
last_refresh_utc = (
    str(live_snapshot.manifest.get("retrieved_at_utc", "Not available"))[:19].replace("T", " ")
    if live_snapshot is not None
    else "Not available"
)

model_date_value = (
    pd.Timestamp(liquidity_result.current["date"])
    if liquidity_result is not None
    else summary["observed_as_of"]
)
model_date = model_date_value.strftime("%b %d, %Y").replace(" 0", " ")
accounting_date = summary["accounting_as_of"].strftime("%b %d, %Y").replace(" 0", " ")
market_date = summary["market_as_of"].strftime("%b %d, %Y").replace(" 0", " ")
render_page_header(
    PageHeader(
        title=TITLE,
        eyebrow="U.S. Macro Liquidity",
        description=(
            "A point-in-time U.S. liquidity regime built from four weighted layers: reserve "
            "capacity, funding markets, realized reserve flow, and bank credit. Mechanical "
            "seasonality is a separate zero-weight diagnostic."
        ),
        as_of=f"Model date {model_date}; markets through {market_date}",
        source_note=(
            f"Reserve accounting through {accounting_date}; source coverage "
            f"{current_count} of {summary['sources_total']} current"
        ),
    )
)
if live_error:
    st.warning(
        "The current observation release could not be verified. The page is using the frozen research anchor. "
        f"Detail: {live_error}"
    )
if liquidity_error:
    st.warning(f"U.S. liquidity conditions are unavailable. Detail: {liquidity_error}")

if liquidity_result is not None:
    liquidity = liquidity_result.current
    state_code = str(liquidity["state_code"]).lower()
    direction_code = str(liquidity["direction"]).lower()
    level_css = {
        "restrictive": "below_normal",
        "balanced": "near_normal",
        "supportive": "above_normal",
    }
    cells = []
    for row_code, row_label in (
        ("improving", "Improving"),
        ("stable", "Stable"),
        ("deteriorating", "Deteriorating"),
    ):
        cells.append(f"<div class='classifier-row'>{row_label}</div>")
        for column_code in ("restrictive", "balanced", "supportive"):
            active = row_code == direction_code and column_code == state_code
            cells.append(
                f"<div class='regime-cell {level_css[column_code]}{' active' if active else ''}'>"
                + (
                    "<div class='regime-cell-title'>Current</div>"
                    if active
                    else "<span aria-hidden='true'>&nbsp;</span>"
                )
                + "</div>"
            )

    transmission = transmission_snapshot(live_snapshot)
    market_confirmation = market_confirmation_snapshot(live_snapshot)
    transmission_mean = float(transmission["tightening_score_z"].mean())
    conditions_state = classify_transmission_state(transmission)
    if transmission_mean > 0.15:
        transmission_direction = "net tightening"
    elif transmission_mean < -0.15:
        transmission_direction = "net easing"
    else:
        transmission_direction = "little aggregate change"
    market_state, market_positive, market_available = classify_market_confirmation(
        market_confirmation
    )
    funding_spread = float(latest["sofr_admin_bp"])
    effr_spread = float(latest["effr_admin_bp"])
    funding_state = str(liquidity["funding_state"])
    funding_stress_veto = bool(liquidity["funding_stress_veto"])
    repo_usage = float(latest["repo_add_bn"])
    repo_usage_clause = (
        "no Federal Reserve overnight repo operations reported"
        if abs(repo_usage) < 1e-12
        else f"Federal Reserve overnight repo operations total {format_usd_billions(repo_usage)}"
    )
    weakest_component = liquidity_result.layers.nsmallest(
        1, "weighted_contribution"
    ).iloc[0]
    weakest_layer = str(weakest_component["layer"])
    weakest_contribution = float(weakest_component["weighted_contribution"])
    (
        weakest_layer_label,
        weakest_layer_sentence,
        weakest_layer_accessibility,
    ) = describe_layer_contribution(weakest_layer, weakest_contribution)

    index_history = liquidity_result.history["liquidity_conditions_index"].dropna()
    index_change_4w = (
        float(index_history.iloc[-1] - index_history.iloc[-5])
        if len(index_history) >= 5
        else float("nan")
    )
    normalized_change_4w = float(liquidity["change_4w"])
    normalized_stability_band = float(liquidity["direction_band"])
    normalized_change_label = format_normalized(
        normalized_change_4w, signed=True
    )
    normalized_band_label = format_normalized(normalized_stability_band)
    if direction_code == "deteriorating":
        index_change_summary = f"down {abs(index_change_4w):.1f} index points"
        index_history_summary = f"{abs(index_change_4w):.1f} points lower"
        index_direction_note = (
            f"Down {abs(index_change_4w):.1f} index points. The underlying normalized "
            f"composite moved {normalized_change_label}, beyond the −{normalized_band_label} "
            "stability threshold."
        )
    elif direction_code == "improving":
        index_change_summary = f"up {abs(index_change_4w):.1f} index points"
        index_history_summary = f"{abs(index_change_4w):.1f} points higher"
        index_direction_note = (
            f"Up {abs(index_change_4w):.1f} index points. The underlying normalized "
            f"composite moved {normalized_change_label}, beyond the +{normalized_band_label} "
            "stability threshold."
        )
    else:
        index_change_summary = f"changed {abs(index_change_4w):.1f} index points"
        index_history_summary = f"changed {abs(index_change_4w):.1f} points"
        index_direction_note = (
            f"Changed {abs(index_change_4w):.1f} index points. The underlying normalized "
            f"composite moved {normalized_change_label}, inside the ±{normalized_band_label} "
            "stability range."
        )
    percentile_value = float(liquidity["percentile"])
    if state_code == "restrictive":
        regime_interpretation = "a cautionary liquidity backdrop"
    elif state_code == "supportive":
        regime_interpretation = "a supportive liquidity backdrop"
    else:
        regime_interpretation = "a balanced liquidity backdrop"
    if funding_state == "Stressed":
        funding_conclusion = (
            "The overnight funding stress threshold is breached and requires escalation regardless "
            "of the index level."
        )
    elif funding_state == "Pressured":
        funding_conclusion = (
            "Overnight funding pressure is present and warrants closer monitoring."
        )
    else:
        funding_conclusion = "No overnight funding stress threshold is breached."
    current_read = (
        f"U.S. liquidity is {str(liquidity['state']).lower()} and "
        f"{str(liquidity['direction']).lower()}. At {float(liquidity['index']):.1f} of 100, "
        f"the index is {index_change_summary} over four weeks and ranks at the "
        f"{format_percentile(percentile_value)} of its prior five-year window. "
        f"{weakest_layer_sentence} Funding is {funding_state.lower()}, financial conditions are "
        f"{conditions_state.lower()}, and "
        f"{market_positive} of {market_available} cross-asset measures support risk appetite. "
        f"This indicates {regime_interpretation}. {funding_conclusion}"
    )
    render_selection_note("Current liquidity read", current_read)
    render_kpi_cards(
        (
            (
                "Liquidity conditions",
                str(liquidity["state"]).upper(),
                f"Index {float(liquidity['index']):.1f} of 100; the balanced range begins at 35.0.",
            ),
            (
                "Four-week direction",
                str(liquidity["direction"]).upper(),
                index_direction_note,
            ),
            (
                "Historical position",
                format_percentile(percentile_value).upper(),
                f"Only {percentile_value:.0f}% of the prior {int(liquidity['percentile_reference_observations'])} weekly observations were lower.",
            ),
            (
                "Funding state",
                funding_state.upper(),
                f"SOFR is {format_basis_points(funding_spread, signed=True)} versus IORB; {repo_usage_clause}.",
            ),
        )
    )
    if refresh_count:
        st.warning(
            f"Data refresh required. {coverage_note} Interpret the current direction with "
            "caution until the source package is refreshed."
        )
    if funding_stress_veto:
        st.error(
            "Funding stress alert. Absolute overnight-funding thresholds are stressed. "
            "The numerical index classification remains unchanged so the level shown in "
            "the regime matrix continues to reconcile to the 0-to-100 index."
        )
else:
    st.error(
        "The current U.S. liquidity regime could not be calculated from the verified "
        "source package. Review the data status before using this page."
    )

overview_tab, reserve_tab, funding_tab, methodology_tab = st.tabs(
    ("Overview", "Reserve mechanics", "Funding and markets", "Data and methods")
)

with overview_tab:
    if liquidity_result is not None:
        render_section_header(
            "Liquidity regime classification",
            "Columns show the liquidity level. Rows show the material four-week direction of change.",
        )
        classifier_col, evidence_col = st.columns([1.0, 1.45], gap="large")
        with classifier_col:
            st.markdown(
                "<div class='regime-classifier' role='img' "
                f"aria-label='U.S. liquidity conditions are {escape(str(liquidity['regime']), quote=True)}.'>"
                "<div class='classifier-grid'>"
                "<div class='classifier-corner'>Direction</div>"
                "<div class='classifier-column'>Restrictive<br>&lt; 35</div>"
                "<div class='classifier-column'>Balanced<br>35 to 65</div>"
                "<div class='classifier-column'>Supportive<br>&gt; 65</div>"
                + "".join(cells)
                + "</div>"
                "<div class='classifier-axis-note'>Level reflects the filtered index. Direction reflects the four-week change.</div>"
                "</div>",
                unsafe_allow_html=True,
            )
        with evidence_col:
            st.markdown(
                "<div class='evidence-panel'>"
                "<div class='section-kicker'>What is driving the call</div>"
                f"<div class='evidence-row'><div class='evidence-label'>{escape(weakest_layer_label)}</div>"
                f"<div class='evidence-state'>{escape(weakest_layer)}</div><div>Weighted contribution {format_normalized(weakest_contribution, signed=True)} normalized model units.</div></div>"
                "<div class='evidence-row'><div class='evidence-label'>Realized reserve flow</div>"
                f"<div class='evidence-state'>{escape(str(liquidity['reserve_impulse_state']))}</div><div>Four-week reserve impulse {format_basis_points(summary['reserve_impulse_bp'], signed=True)}.</div></div>"
                "<div class='evidence-row'><div class='evidence-label'>Overnight funding</div>"
                f"<div class='evidence-state'>{escape(funding_state)}</div><div>SOFR is {format_basis_points(funding_spread, signed=True)} versus IORB; EFFR is {format_basis_points(effr_spread, signed=True)} versus IORB.</div></div>"
                "<div class='evidence-row'><div class='evidence-label'>Financial conditions</div>"
                f"<div class='evidence-state'>{escape(conditions_state)}</div><div>{escape(transmission_direction.capitalize())}; composite score {format_normalized(transmission_mean, signed=True)}.</div></div>"
                "<div class='evidence-row'><div class='evidence-label'>Risk confirmation</div>"
                f"<div class='evidence-state'>{market_positive} of {market_available} supportive</div><div>{escape(market_state)}. Confirmation only; these measures do not affect the index.</div></div>"
                "<div class='evidence-watch'><strong>Escalation conditions:</strong> wider funding spreads, weaker credit, deteriorating cross-asset confirmation, or another material decline in the Liquidity Conditions Index.</div>"
                "</div>",
                unsafe_allow_html=True,
            )

        render_section_header(
            "Liquidity regime drivers",
            "Weighted contribution of each model layer. Positive values support liquidity; negative values restrain it.",
        )
        _render_chart_accessibility(
            "Liquidity regime drivers",
            f"{weakest_layer_accessibility} The four index layers sum to {float(liquidity_result.layers['weighted_contribution'].sum()):+.2f} normalized model units before filtering and transformation.",
        )
        st.plotly_chart(
            liquidity_layers_figure(liquidity_result),
            width="stretch",
            config={"displayModeBar": False},
        )

        render_section_header(
            "U.S. liquidity conditions history",
            "The black line is the filtered regime index. Faint markers show weekly measurements. Background bands identify restrictive, balanced, and supportive conditions.",
        )
        _render_chart_accessibility(
            "U.S. liquidity conditions history",
            f"The current filtered index is {float(liquidity['index']):.1f}, {index_history_summary} over four weeks, and in the {state_code} range.",
        )
        st.plotly_chart(
            liquidity_conditions_history_figure(liquidity_result, lookback_years),
            width="stretch",
            config={"displayModeBar": False},
        )

        with st.expander("Show structural reserve capacity detail"):
            st.caption(
                "The 35 percent structural layer is shown separately to make its reserve "
                "and bank-buffer inputs transparent. Scores use information available before "
                "the current observation."
            )
            capacity_rows = []
            for _, component in liquidity_result.capacity_components.iterrows():
                unit = str(component["unit"])
                raw_value = float(component["raw_value"])
                current_level = (
                    f"{raw_value:.2f}%" if unit == "%" else f"{raw_value:.2f}x"
                )
                component_score = float(component["score_z"])
                component_state = (
                    "Restrictive"
                    if component_score < -0.35
                    else "Supportive"
                    if component_score > 0.35
                    else "Neutral"
                )
                capacity_rows.append(
                    "<div class='mechanics-row'>"
                    f"<div><strong>{escape(str(component['component']))}</strong></div>"
                    f"<div>{escape(current_level)}</div>"
                    f"<div>{component_state}; {format_normalized(component_score, signed=True)}</div>"
                    "</div>"
                )
            st.markdown(
                "<div class='mechanics-ledger'>"
                "<div class='ledger-header'><div>Indicator</div><div>Current level</div><div>Historical state</div></div>"
                + "".join(capacity_rows)
                + "</div>",
                unsafe_allow_html=True,
            )

with reserve_tab:
    render_section_header(
        f"Observed reserve-flow regime: {reserve_regime}",
        f"The four-week reserve impulse is {format_basis_points(summary['reserve_impulse_bp'], signed=True)} of lagged Federal Reserve assets, placing it at the {format_percentile(reserve_score)} of its five-year history. Its rate of change is {trend_read}.",
    )
    render_kpi_cards(
        (
            ("Current reserve impulse", format_basis_points(summary["reserve_impulse_bp"], signed=True), "Four-week reserve change as a share of lagged Fed assets."),
            ("Five-year historical rank", format_percentile(reserve_score), "Rank among the prior 260 valid weekly observations."),
            (
                "Four-week change in reserve impulse",
                format_basis_points(reserve_change, signed=True),
                reserve_change_note,
            ),
            (
                "Seasonal deviation",
                format_basis_points(current_deviation, signed=True)
                if liquidity_result is not None
                else "Not available",
                seasonal_note,
            ),
        )
    )
    render_section_header(
        reserve_driver_title,
        f"Net reserve impulse {format_basis_points(summary['reserve_impulse_bp'], signed=True)} at the common accounting clock {latest.get('accounting_asof_date', summary['latest_signal_date'].date())}. Positive values add reserves; negative values drain reserves.",
    )
    _render_chart_accessibility(
        reserve_driver_title,
        f"The net reserve impulse is {format_basis_points(summary['reserve_impulse_bp'], signed=True)}. {reserve_driver_note}",
    )
    st.plotly_chart(current_mechanics_figure(bundle, live_snapshot), width="stretch", config={"displayModeBar": False})
    st.markdown(
        f"<div class='evidence-note'>{escape(reserve_driver_note)}</div>",
        unsafe_allow_html=True,
    )
    render_section_header(
        "Historical reserve impulse and decomposition",
        "The upper panel shows realized reserve flow. The lower panel explains it with Fed assets, TGA, ON RRP, currency, and other liabilities.",
    )
    _render_chart_accessibility(
        "Historical reserve impulse and decomposition",
        f"The current four-week reserve impulse is {format_basis_points(summary['reserve_impulse_bp'], signed=True)}. The chart uses the selected {lookback_window_text} window.",
    )
    st.plotly_chart(liquidity_impulse_figure(bundle, lookback_years, live_snapshot), width="stretch", config={"displayModeBar": False})
    if liquidity_result is not None:
        render_section_header(
            "Reserve flow relative to its seasonal pattern",
            "Bars show the realized four-week reserve impulse minus the median for nearby calendar weeks in prior years. This is a mechanical seasonal deviation, not a market-consensus surprise.",
        )
        _render_chart_accessibility(
            "Reserve flow relative to its seasonal pattern",
            f"Reserve flow is {format_basis_points(abs(current_deviation))} {deviation_direction} than the prior seasonal median and {deviation_range_text}.",
        )
        st.plotly_chart(liquidity_deviation_figure(liquidity_result, lookback_years), width="stretch", config={"displayModeBar": False})
    render_section_header(
        "Current balance-sheet levels",
        "Stock levels and four-week reserve effects answer different questions. Reserve effects are measured in basis points of lagged Federal Reserve assets.",
    )
    current_levels = (
        ("Reserve balances", format_usd_billions(latest["reserves_bn"]), f"Four-week effect: {format_basis_points(latest['reserve_impulse_4w_bp'], signed=True)}"),
        ("Commercial bank deposits", format_usd_billions(latest["deposits_bn"]), f"Reserves are {float(latest['reserve_deposit_pct']):.2f}% of deposits"),
        ("Treasury General Account, H.4.1", format_usd_billions(latest["tga_h41_bn"]), f"Four-week effect: {format_basis_points(-float(latest['tga_change_4w_bp_assets']), signed=True)}"),
        ("Treasury General Account, daily statement", format_usd_billions(latest["tga_dts_bn"]), "Latest daily Treasury level; not paired with the H.4.1 four-week effect."),
        ("Overnight reverse repo", format_usd_billions(latest["onrrp_bn"]), f"Four-week effect: {format_basis_points(-float(latest['onrrp_change_4w_bp_assets']), signed=True)}"),
        ("Federal Reserve assets", format_usd_billions(latest["assets_bn"]), f"Four-week effect: {format_basis_points(latest['fed_asset_change_4w_bp'], signed=True)}"),
    )
    st.markdown(
        "<div class='mechanics-ledger'>"
        "<div class='ledger-header'><div>Metric</div><div>Current level</div><div>Four-week reserve effect or context</div></div>"
        + "".join(
            "<div class='mechanics-row'>" f"<div><strong>{escape(item)}</strong></div>" f"<div>{escape(level)}</div>" f"<div>{escape(effect)}</div>" "</div>"
            for item, level, effect in current_levels
        ) + "</div>",
        unsafe_allow_html=True,
    )
    with st.expander("How to interpret reserve drivers"):
        st.markdown(
            "Fed asset expansion generally adds reserve capacity. A rising TGA and rising currency generally drain reserves. "
            "ON RRP runoff can release cash, but not every dollar becomes a bank reserve. Treasury buybacks can ease duration absorption without creating reserves."
        )

with funding_tab:
    if liquidity_result is not None and live_snapshot is not None:
        secured_spreads = {
            "SOFR": float(latest["sofr_admin_bp"]),
            "TGCR": float(latest["tgcr_admin_bp"]),
            "BGCR": float(latest["bgcr_admin_bp"]),
        }
        secured_low_name, secured_low_value = min(
            secured_spreads.items(), key=lambda item: item[1]
        )
        secured_high_name, secured_high_value = max(
            secured_spreads.items(), key=lambda item: item[1]
        )
        render_section_header(
            "Overnight funding conditions",
            "SOFR, TGCR, BGCR, and EFFR relative to IORB show whether cash is moving smoothly through overnight funding markets. The index uses representative secured SOFR, unsecured EFFR, and SOFR dispersion; TGCR and BGCR remain diagnostics. Wider positive spreads and greater rate dispersion indicate increasing funding pressure.",
        )
        render_kpi_cards(
            (
                ("SOFR minus IORB", format_basis_points(latest["sofr_admin_bp"], signed=True), f"SOFR {latest['sofr']:.2f}%; IORB {latest['iorb']:.2f}%."),
                (
                    "Secured repo spreads to IORB",
                    f"{secured_low_value:+.1f} to {secured_high_value:+.1f} bp".replace("-", "−"),
                    f"Observed range from {secured_low_name} to {secured_high_name} across BGCR, TGCR, and SOFR.",
                ),
                ("Funding state", funding_state, f"SOFR interquartile range {latest['sofr_iqr_bp']:.1f} bp; {repo_usage_clause}."),
            )
        )
        _render_chart_accessibility(
            "Overnight funding conditions",
            f"Funding is {funding_state.lower()}. SOFR is {format_basis_points(latest['sofr_admin_bp'], signed=True)} relative to IORB and EFFR is {format_basis_points(latest['effr_admin_bp'], signed=True)} relative to IORB.",
        )
        st.plotly_chart(funding_market_figure(liquidity_result, lookback_years), width="stretch", config={"displayModeBar": False})
        render_section_header(
            "Financial-conditions context",
            "Twenty-session changes in credit spreads, the broad dollar, and real yields are scaled by their prior volatility. Positive values indicate tightening; negative values indicate easing. These are market-context measures and do not affect the Liquidity Conditions Index.",
        )
        _render_chart_accessibility(
            "Twenty-session financial-conditions context",
            f"The component signals are {conditions_state.lower()}, with {transmission_direction}. The composite tightening score is {format_normalized(transmission_mean, signed=True)}.",
        )
        st.plotly_chart(transmission_conditions_figure(live_snapshot), width="stretch", config={"displayModeBar": False})
        render_section_header(
            "Cross-asset risk confirmation",
            "Twenty-session, volatility-scaled traded-asset ratios show whether current risk appetite is broad or narrow. Positive values indicate stronger risk appetite; negative values indicate weaker risk appetite. These measures provide confirmation only and do not prove that liquidity caused the market move.",
        )
        _render_chart_accessibility(
            "Twenty-session cross-asset risk confirmation",
            f"{market_positive} of {market_available} measures support risk appetite. This confirmation layer does not affect the Liquidity Conditions Index.",
        )
        st.plotly_chart(market_confirmation_figure(live_snapshot), width="stretch", config={"displayModeBar": False})

with methodology_tab:
    render_section_header(
        "Data integrity",
        (
            f"{current_count} of {summary['sources_total']} required sources are current. Last successful refresh {last_refresh_utc} UTC. Schemas, row counts, and checksums are verified. Each input is checked against its own publication calendar; a verified unchanged value remains current."
            if live_snapshot is not None
            else "Source freshness is measured against the packaged weekly anchor and each input's publication calendar."
        ),
    )
    if not summary["sources_current"]:
        st.warning(
            f"{coverage_note} Treat the current liquidity read as incomplete until source "
            "coverage is current."
        )

    source_display = source_table.copy()
    source_display["Series"] = source_display["Series"].replace(
        {
            "Federal Reserve assets": "Fed assets",
            "Treasury General Account": "TGA",
            "Overnight reverse repo": "ON RRP",
            "Currency in circulation": "Currency",
            "Baa minus 10-year": "Baa − 10Y",
            "Market context inputs": "Market context",
            "Commercial bank deposits": "Bank deposits",
            "Effective federal funds rate": "EFFR",
            "High yield option-adjusted spread": "HY OAS",
            "Investment grade option-adjusted spread": "IG OAS",
            "Broad U.S. dollar index": "Broad dollar",
            "10-year real yield": "10Y real yield",
        }
    )
    source_display["Live status"] = source_display["Live status"].replace(
        {
            "CURRENT · SCHEDULED LAG": "CURRENT · EXPECTED RELEASE LAG",
            "CURRENT · UNCHANGED": "CURRENT · UNCHANGED",
            "STALE · REFRESH REQUIRED": "STALE · REFRESH REQUIRED",
        }
    )
    source_display.loc[
        source_display["Series"].eq("Market context"), "Display value"
    ] = "18 instruments current"
    with st.expander("Source-level freshness and lineage"):
        source_rows = []
        for _, source in source_display.iterrows():
            if "Expected date" in source_display.columns:
                clock = (
                    f"Observed date: {source['Observation date']}. "
                    f"Expected date: {source['Expected date']}."
                )
            else:
                clock = (
                    f"Observed date: {source['Observation date']}. "
                    f"Age: {float(source['Age now, days']):.0f} days. "
                    f"Freshness limit: {float(source['Freshness limit, days']):.0f} days."
                )
            provider = escape(str(source["Primary source"]))
            source_url = escape(str(source["Source URL"]), quote=True)
            source_rows.append(
                "<div class='source-row'>"
                f"<div><div class='source-name'>{escape(str(source['Series']))}</div>"
                f"<div class='source-key'>{escape(str(source['Source series']))}; "
                f"<a href='{source_url}' target='_blank' rel='noopener noreferrer'>{provider}</a></div></div>"
                f"<div class='source-status'>{escape(str(source['Live status']))}</div>"
                f"<div><span class='source-value'>{escape(str(source['Display value']))}</span>"
                f"<div class='source-clock'>{escape(clock)}</div></div>"
                "</div>"
            )
        st.markdown(
            "<div class='source-ledger'>"
            "<div class='ledger-header'><div>Series and source</div><div>Status</div><div>Value and release timing</div></div>"
            + "".join(source_rows)
            + "</div>",
            unsafe_allow_html=True,
        )

    render_section_header(
        "How the U.S. liquidity classifier is built",
        "The classifier combines four index layers. Structural capacity, reserve flow, and bank credit are scaled against their own prior histories. Funding is anchored to absolute overnight-rate spreads. Every layer is oriented so that higher values indicate more supportive liquidity. It is a discretionary market input, not a standalone trading instruction.",
    )
    methodology = (
        (
            "Structural reserve capacity, 35%",
            "Common-date reserves relative to bank assets, deposits, and Fedwire payments, plus aggregate large-bank and small-bank cash proxies",
            "Longer-term banking-system liquidity cushion",
        ),
        (
            "Overnight funding support, 25%",
            "SOFR and EFFR relative to IORB, plus SOFR dispersion; TGCR and BGCR are diagnostic only, and total Federal Reserve overnight repo operations are an absolute stress alert",
            "Secured and unsecured funding transmission without triple-counting nested repo rates",
        ),
        (
            "Realized reserve impulse, 30%",
            "Four-week and thirteen-week changes in reserve balances divided by lagged Fed assets",
            "Current reserve addition or drain",
        ),
        (
            "Bank credit creation, 10%",
            "Thirteen-week growth in Federal Reserve H.8 bank credit",
            "Shows whether bank credit is expanding or contracting",
        ),
        (
            "Mechanical seasonal deviation, diagnostic only",
            "Current reserve impulse relative to nearby calendar weeks in prior years",
            "Comparison with the prior seasonal pattern; receives no second index weight",
        ),
        (
            "Accounting attribution",
            "Fed assets, TGA, ON RRP, currency, and other liabilities",
            "Explains reserve flow and receives no extra weight",
        ),
        (
            "Independent market confirmation",
            "Credit, real yields, broad dollar, breadth, high beta, crypto, EM, and volatility",
            "Confirmation only; does not affect the index",
        ),
    )
    st.markdown(
        "<div class='mechanics-ledger'>"
        "<div class='ledger-header'><div>Model layer</div><div>Construction</div><div>Decision role</div></div>"
        + "".join(
            "<div class='mechanics-row'>"
            f"<div><strong>{escape(layer)}</strong></div>"
            f"<div>{escape(definition)}</div>"
            f"<div>{escape(output)}</div>"
            "</div>"
            for layer, definition, output in methodology
        )
        + "</div>",
        unsafe_allow_html=True,
    )

render_footer(
    data_note=(
        "Sources: Federal Reserve H.4.1 and H.8, Fedwire, U.S. Treasury, New York Fed, FRED, and Yahoo Finance. "
        "Data dates are shown above. Checksums verified."
    )
)
