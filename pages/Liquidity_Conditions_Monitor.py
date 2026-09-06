"""Standalone U.S. Liquidity Monitor.

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
from liquidity_monitor.structural_liquidity import (
    classify_market_confirmation,
    classify_transmission_state,
    confirmation_components_for_stale_sources,
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
    render_regime_summary,
    render_section_header,
    render_status_banner,
)
from liquidity_monitor.us_liquidity_model import (
    CORE_SOURCE_FIELDS,
    build_us_liquidity_model,
    funding_market_figure,
    liquidity_conditions_history_figure,
    liquidity_deviation_figure,
    liquidity_layers_figure,
    liquidity_regime_map_figure,
)

ROOT = Path(__file__).resolve().parents[1]
BUNDLE_ROOT = ROOT / "data" / "liquidity_model_bundle"
LIVE_ROOT = Path(
    os.environ.get(
        "US_LIQUIDITY_LIVE_ROOT",
        str(ROOT / "data" / "liquidity_live_snapshot"),
    )
)
TITLE = "U.S. Liquidity Monitor"

st.set_page_config(
    page_title=TITLE,
    page_icon="◉",
    layout="wide",
    initial_sidebar_state="collapsed",
)
inject_explorer_style(max_width_px=1560)


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
            eyebrow="U.S. dollar liquidity",
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

if live_snapshot is None or liquidity_result is None:
    failure_detail = live_error or liquidity_error or "Current model output is unavailable."
    render_page_header(
        PageHeader(
            title=TITLE,
            eyebrow="U.S. dollar liquidity",
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
refresh_fields = set(source_table.loc[refresh_mask, "field"].astype(str))
core_refresh_mask = refresh_mask & source_table["field"].astype(str).isin(CORE_SOURCE_FIELDS)
core_refresh_sources = source_table.loc[core_refresh_mask, "Series"].astype(str).tolist()
core_refresh_count = len(core_refresh_sources)
excluded_confirmation_components = confirmation_components_for_stale_sources(
    refresh_fields
)
supplemental_refresh_note = (
    "Zero-weight confirmation measures tied to the stale source are excluded "
    "from the current confirmation count."
    if excluded_confirmation_components
    else "The affected zero-weight diagnostic retains its last verified observation and date."
)
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
reserve_change_kpi_note = (
    f"{reserve_change_direction}. "
    + (
        "Within the normal-variation band."
        if abs(reserve_change) <= trend_band
        else "Outside the normal-variation band."
    )
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
    seasonal_kpi_note = (
        f"{format_basis_points(abs(current_deviation))} {deviation_direction} than the prior median; "
        f"{deviation_state.lower()}."
    )
else:
    current_deviation = float("nan")
    deviation_state = "Not available"
    seasonal_note = "Current seasonal comparison is unavailable."
    seasonal_kpi_note = seasonal_note
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
        eyebrow="U.S. dollar liquidity",
        description=(
            "Tracks the level, direction, and principal drivers of U.S. liquidity conditions."
        ),
        as_of=f"Model date: {model_date} | Market data through: {market_date}",
        source_note=(
            f"Reserve data through: {accounting_date} | Sources current: "
            f"{current_count}/{summary['sources_total']}"
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

    transmission = transmission_snapshot(live_snapshot)
    market_confirmation = market_confirmation_snapshot(
        live_snapshot, excluded_confirmation_components
    )
    transmission_mean = float(transmission["tightening_score_z"].mean())
    conditions_state = classify_transmission_state(transmission)
    if transmission_mean > 0.15:
        transmission_direction = "net tightening"
    elif transmission_mean < -0.15:
        transmission_direction = "net easing"
    else:
        transmission_direction = "little aggregate change"
    _, market_positive, market_available = classify_market_confirmation(
        market_confirmation
    )
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
        _,
        _,
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
        index_history_summary = f"{abs(index_change_4w):.1f} points lower"
        index_direction_note = (
            f"Down {abs(index_change_4w):.1f} index points. The underlying normalized "
            f"composite moved {normalized_change_label}, beyond the −{normalized_band_label} "
            "stability threshold."
        )
    elif direction_code == "improving":
        index_history_summary = f"{abs(index_change_4w):.1f} points higher"
        index_direction_note = (
            f"Up {abs(index_change_4w):.1f} index points. The underlying normalized "
            f"composite moved {normalized_change_label}, beyond the +{normalized_band_label} "
            "stability threshold."
        )
    else:
        index_history_summary = f"changed {abs(index_change_4w):.1f} points"
        index_direction_note = (
            f"Changed {abs(index_change_4w):.1f} index points. The underlying normalized "
            f"composite moved {normalized_change_label}, inside the ±{normalized_band_label} "
            "stability range."
        )
    percentile_value = float(liquidity["percentile"])
    render_regime_summary(
        index=float(liquidity["index"]),
        level=str(liquidity["state"]),
        trend=str(liquidity["direction"]),
        four_week_change=index_direction_note.split(". The underlying", 1)[0],
        percentile=(
            f"{format_percentile(percentile_value)} of the previous "
            f"{int(liquidity['percentile_reference_observations'])} weekly observations"
        ),
        primary_driver=weakest_layer,
        primary_driver_label=(
            "Primary drag" if weakest_contribution < 0 else "Least supportive input"
        ),
        primary_driver_note=(
            "Most negative weighted input"
            if weakest_contribution < 0
            else "Lowest weighted input"
        ),
        funding_state=funding_state,
        market_confirmation=f"{market_positive} of {market_available} supportive",
        publication_current=not bool(core_refresh_count),
    )
    if core_refresh_count:
        render_status_banner(
            "Core index held pending data refresh",
            f"{coverage_note} The last verified index remains visible for research, "
            "but it is not approved as current.",
            tone="warning",
        )
    elif refresh_count:
        render_status_banner(
            "Core index current; supplemental data update pending",
            f"{coverage_note} {supplemental_refresh_note}",
            tone="info",
        )
    if funding_stress_veto:
        render_status_banner(
            "Funding stress threshold breached",
            "At least one absolute overnight-funding threshold is in the stressed range. "
            "The 0 to 100 index remains unchanged. Treat this as an independent escalation signal.",
            tone="error",
        )
else:
    st.error(
        "The current U.S. liquidity regime could not be calculated from the verified "
        "source package. Review the data status before using this page."
    )

overview_tab, reserve_tab, funding_tab, methodology_tab = st.tabs(
    ("Dashboard", "Reserve flows", "Funding and markets", "Data and methodology")
)

with overview_tab:
    if liquidity_result is not None:
        history_column, contribution_column = st.columns((8, 4), gap="medium")
        with history_column:
            history_title_column, history_control_column = st.columns((3, 1), gap="small")
            with history_title_column:
                render_section_header(
                    "Liquidity Conditions Index",
                    "Filtered 0 to 100 index; the lighter line is the weekly estimate.",
                )
            with history_control_column:
                lookback_label = st.segmented_control(
                    "Chart history",
                    options=("1Y", "3Y", "5Y", "Max"),
                    default="3Y",
                    selection_mode="single",
                    help="Changes the historical chart window only. It does not change the model.",
                    label_visibility="collapsed",
                )
            lookback_label = lookback_label or "3Y"
            lookback_years = {
                "1Y": 1,
                "3Y": 3,
                "5Y": 5,
                "Max": None,
            }[lookback_label]
            lookback_window_text = (
                "full-history" if lookback_years is None else f"{lookback_years}-year"
            )
            _render_chart_accessibility(
                "Liquidity Conditions Index",
                f"The current filtered index is {float(liquidity['index']):.1f}, {index_history_summary} over four weeks, and in the {state_code} range.",
            )
            st.plotly_chart(
                liquidity_conditions_history_figure(liquidity_result, lookback_years),
                width="stretch",
                config={"displayModeBar": False},
            )

        with contribution_column:
            render_section_header(
                "Current index contributions",
                "Weighted standardized contributions before filtering.",
            )
            _render_chart_accessibility(
                "Contribution to the current index",
                f"{weakest_layer_accessibility} The four layers sum to {float(liquidity_result.layers['weighted_contribution'].sum()):+.2f} standardized units before filtering and transformation.",
            )
            st.plotly_chart(
                liquidity_layers_figure(liquidity_result),
                width="stretch",
                config={"displayModeBar": False},
            )

        with st.expander("View level and direction classifier map"):
            _render_chart_accessibility(
                "Current liquidity regime",
                f"The liquidity index is {float(liquidity['index']):.1f} and the four-week trend is {str(liquidity['direction']).lower()}.",
            )
            st.plotly_chart(
                liquidity_regime_map_figure(liquidity_result),
                width="stretch",
                config={"displayModeBar": False, "responsive": True},
            )

        with st.expander("View reserve-capacity inputs"):
            st.caption(
                "Reserve capacity accounts for 35% of the index. Each historical score uses "
                "only information available at that date."
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
                "<div class='ledger-header'><div>Indicator</div><div>Current level</div><div>Standardized state</div></div>"
                + "".join(capacity_rows)
                + "</div>",
                unsafe_allow_html=True,
            )

with reserve_tab:
    render_section_header(
        f"Reserve flow: {reserve_regime}",
        f"Four-week reserve flow is {format_basis_points(summary['reserve_impulse_bp'], signed=True)}, at the {format_percentile(reserve_score)} of the past five years.",
    )
    render_kpi_cards(
        (
            ("Four-week reserve flow", format_basis_points(summary["reserve_impulse_bp"], signed=True), "Negative values drain reserves."),
            ("Five-year percentile", format_percentile(reserve_score), "Previous 260 valid weeks."),
            (
                "Change versus four weeks ago",
                format_basis_points(reserve_change, signed=True),
                reserve_change_kpi_note,
            ),
            (
                "Versus seasonal pattern",
                format_basis_points(current_deviation, signed=True)
                if liquidity_result is not None
                else "Not available",
                seasonal_kpi_note,
            ),
        )
    )
    render_section_header(
        "Current reserve-flow decomposition",
        f"Five accounting contributions reconcile to net four-week reserve flow of {format_basis_points(summary['reserve_impulse_bp'], signed=True)} as of {accounting_date}.",
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
        "Reserve flow and its drivers over time",
        "The upper panel shows net reserve flow. The lower panel shows which Federal Reserve and Treasury balance-sheet drivers added or drained reserves.",
    )
    _render_chart_accessibility(
        "Historical reserve impulse and decomposition",
        f"The current four-week reserve impulse is {format_basis_points(summary['reserve_impulse_bp'], signed=True)}. The chart uses the selected {lookback_window_text} window.",
    )
    st.plotly_chart(liquidity_impulse_figure(bundle, lookback_years, live_snapshot), width="stretch", config={"displayModeBar": False})
    if liquidity_result is not None:
        render_section_header(
            "Reserve flow versus seasonal pattern",
            "Bars show net reserve flow relative to the median for nearby calendar weeks in prior years. Positive values are more supportive; negative values are less supportive. This is a calendar benchmark, not a market-consensus surprise.",
        )
        _render_chart_accessibility(
            "Reserve flow relative to its seasonal pattern",
            f"Reserve flow is {format_basis_points(abs(current_deviation))} {deviation_direction} than the prior seasonal median and {deviation_range_text}.",
        )
        st.plotly_chart(liquidity_deviation_figure(liquidity_result, lookback_years), width="stretch", config={"displayModeBar": False})
    render_section_header(
        "Current balance-sheet levels",
        "Levels and changes answer different questions. Four-week effects are measured as a share of lagged Federal Reserve assets.",
    )
    current_levels = (
        ("Reserve balances", format_usd_billions(latest["reserves_bn"]), f"Four-week effect: {format_basis_points(latest['reserve_impulse_4w_bp'], signed=True)}"),
        ("Commercial bank deposits", format_usd_billions(latest["deposits_bn"]), f"Reserves are {float(latest['reserve_deposit_pct']):.2f}% of deposits"),
        ("Treasury General Account (weekly)", format_usd_billions(latest["tga_h41_bn"]), f"Four-week effect: {format_basis_points(-float(latest['tga_change_4w_bp_assets']), signed=True)}"),
        ("Treasury General Account (daily)", format_usd_billions(latest["tga_dts_bn"]), "Latest daily Treasury level; not paired with the weekly four-week effect."),
        ("Overnight reverse repo", format_usd_billions(latest["onrrp_bn"]), f"Four-week effect: {format_basis_points(-float(latest['onrrp_change_4w_bp_assets']), signed=True)}"),
        ("Federal Reserve assets", format_usd_billions(latest["assets_bn"]), f"Four-week effect: {format_basis_points(latest['fed_asset_change_4w_bp'], signed=True)}"),
    )
    st.markdown(
        "<div class='mechanics-ledger'>"
        "<div class='ledger-header'><div>Metric</div><div>Current level</div><div>Four-week effect on reserves</div></div>"
        + "".join(
            "<div class='mechanics-row'>" f"<div><strong>{escape(item)}</strong></div>" f"<div>{escape(level)}</div>" f"<div>{escape(effect)}</div>" "</div>"
            for item, level, effect in current_levels
        ) + "</div>",
        unsafe_allow_html=True,
    )
    with st.expander("Reserve-flow mechanics"):
        st.markdown(
            "Federal Reserve asset growth generally adds reserves. A rising Treasury General Account or more currency in circulation generally drains reserves. "
            "Overnight reverse repo runoff can release cash, although it does not translate one-for-one into bank reserves. Treasury buybacks may reduce duration absorption but do not create reserves."
        )

with funding_tab:
    if liquidity_result is not None and live_snapshot is not None:
        secured_spreads = {
            "SOFR": float(latest["sofr_admin_bp"]),
            "TGCR": float(latest["tgcr_admin_bp"]),
            "BGCR": float(latest["bgcr_admin_bp"]),
        }
        _, secured_low_value = min(
            secured_spreads.items(), key=lambda item: item[1]
        )
        _, secured_high_value = max(
            secured_spreads.items(), key=lambda item: item[1]
        )
        render_section_header(
            "Overnight funding conditions",
            f"SOFR is {format_basis_points(latest['sofr_admin_bp'], signed=True)} to IORB. Secured funding is {funding_state.lower()}; pressure begins above +5 bp and stress above +10 bp.",
        )
        render_kpi_cards(
            (
                ("SOFR spread to IORB", format_basis_points(latest["sofr_admin_bp"], signed=True), f"SOFR {latest['sofr']:.2f}%; IORB {latest['iorb']:.2f}%."),
                (
                    "Secured funding range",
                    f"{secured_low_value:+.1f} to {secured_high_value:+.1f} bp".replace("-", "−"),
                    "Range across BGCR, TGCR, and SOFR relative to IORB.",
                ),
                ("Funding regime", funding_state, f"SOFR interquartile range {latest['sofr_iqr_bp']:.1f} bp; {repo_usage_clause}."),
            )
        )
        _render_chart_accessibility(
            "Overnight funding conditions",
            f"Funding is {funding_state.lower()}. SOFR is {format_basis_points(latest['sofr_admin_bp'], signed=True)} relative to IORB and EFFR is {format_basis_points(latest['effr_admin_bp'], signed=True)} relative to IORB.",
        )
        st.plotly_chart(funding_market_figure(liquidity_result, lookback_years), width="stretch", config={"displayModeBar": False})
        transmission_column, confirmation_column = st.columns((1, 1), gap="medium")
        with transmission_column:
            render_section_header(
                "Market transmission",
                "Positive values indicate easier conditions. These measures have zero index weight.",
            )
            _render_chart_accessibility(
                "Market transmission",
                f"The component signals are {conditions_state.lower()}, with {transmission_direction}. The composite tightening score is {format_normalized(transmission_mean, signed=True)}.",
            )
            st.plotly_chart(transmission_conditions_figure(live_snapshot), width="stretch", config={"displayModeBar": False})
        with confirmation_column:
            render_section_header(
                "Risk-asset confirmation",
                "Positive values indicate broader risk appetite. These measures have zero index weight.",
            )
            _render_chart_accessibility(
                "Risk-asset confirmation",
                f"{market_positive} of {market_available} measures support risk appetite. This confirmation layer does not affect the Liquidity Conditions Index.",
            )
            st.plotly_chart(
                market_confirmation_figure(
                    live_snapshot, excluded_confirmation_components
                ),
                width="stretch",
                config={"displayModeBar": False},
            )

with methodology_tab:
    render_section_header(
        "Data status",
        (
            f"{current_count} of {summary['sources_total']} required sources meet their release schedules. Last successful refresh: {last_refresh_utc} UTC. File schemas, row counts, and checksums passed. A verified unchanged observation remains current until its next expected release."
            if live_snapshot is not None
            else "Source freshness is measured against the packaged weekly anchor and each input's publication calendar."
        ),
    )
    if core_refresh_count:
        render_status_banner(
            "Core index held pending data refresh",
            f"{coverage_note} The last verified index remains visible for research, but it is not approved as current.",
            tone="warning",
        )
    elif refresh_count:
        render_status_banner(
            "Core index current; supplemental data update pending",
            f"{coverage_note} {supplemental_refresh_note}",
            tone="info",
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
            "CURRENT": "Current",
            "CURRENT · SCHEDULED LAG": "Current (scheduled release lag)",
            "CURRENT · EXPECTED RELEASE LAG": "Current (scheduled release lag)",
            "CURRENT · UNCHANGED": "Current (unchanged)",
            "CURRENT · UPDATED": "Current (updated)",
            "STALE": "Refresh required",
            "STALE · REFRESH REQUIRED": "Refresh required",
        }
    )
    source_display.loc[
        source_display["Series"].eq("Market context"), "Display value"
    ] = "18 instruments current"
    with st.expander("View source status and details"):
        source_rows = []
        for _, source in source_display.iterrows():
            if "Expected date" in source_display.columns:
                clock = (
                    f"Observed: {source['Observation date']} | "
                    f"Expected: {source['Expected date']}"
                )
            else:
                clock = (
                    f"Observed: {source['Observation date']} | "
                    f"Age: {float(source['Age now, days']):.0f} days | "
                    f"Limit: {float(source['Freshness limit, days']):.0f} days"
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
            "<div class='ledger-header'><div>Source</div><div>Freshness</div><div>Latest observation</div></div>"
            + "".join(source_rows)
            + "</div>",
            unsafe_allow_html=True,
        )

    render_section_header(
        "Model construction",
        "The index combines four weighted layers. Reserve capacity, reserve flow, and bank credit are scaled against their own prior histories. Funding conditions use absolute overnight-rate spreads. Higher scores indicate more supportive liquidity. Use the result as a discretionary macro input, not a standalone trading signal.",
    )
    methodology = (
        (
            "Reserve capacity",
            "Common-date reserves relative to bank assets, deposits, and Fedwire payments, plus aggregate large-bank and small-bank cash proxies",
            "35%; structural liquidity buffer",
        ),
        (
            "Funding conditions",
            "SOFR and EFFR relative to IORB, plus SOFR dispersion; TGCR and BGCR are diagnostic only, and total Federal Reserve overnight repo operations are an absolute stress alert",
            "25%; current funding pressure",
        ),
        (
            "Reserve flow",
            "Four-week and thirteen-week changes in reserve balances divided by lagged Fed assets",
            "30%; current reserve addition or drain",
        ),
        (
            "Bank credit growth",
            "Thirteen-week growth in Federal Reserve H.8 bank credit",
            "10%; credit expansion or contraction",
        ),
        (
            "Seasonal pattern",
            "Current reserve impulse relative to nearby calendar weeks in prior years",
            "Diagnostic only; 0% weight",
        ),
        (
            "Reserve-flow attribution",
            "Fed assets, TGA, ON RRP, currency, and other liabilities",
            "Explanatory only; 0% weight",
        ),
        (
            "Market confirmation",
            "Credit, real yields, broad dollar, breadth, high beta, crypto, EM, and volatility",
            "Confirmation only; 0% weight",
        ),
    )
    st.markdown(
        "<div class='mechanics-ledger'>"
        "<div class='ledger-header'><div>Component</div><div>What it measures</div><div>Weight and role</div></div>"
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
