"""Mechanically structured, de-duplicated U.S. liquidity conditions model.

The model separates reserve stock, relative money-market funding support, and
realized reserve flow.  Balance-sheet attribution variables and traded-market
outcomes are intentionally excluded from the structural composite.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from math import isfinite

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from liquidity_monitor.liquidity_formatting import (
    format_normalized,
    format_percent,
    format_percentage_points,
)
from liquidity_monitor.liquidity_live_snapshot import (
    FEDERAL_RESERVE_DAY,
    GOVERNMENT_SECURITIES_DAY,
    LiveLiquiditySnapshot,
    apply_federal_reserve_release_availability,
    load_federal_reserve_release_calendars,
)
from liquidity_monitor.palette import PASTEL, PRODUCT

CHART_FONT = "Arial, Helvetica, sans-serif"
CHART_INK = PRODUCT["ink"]
CHART_MUTED = PRODUCT["muted"]
CHART_GRID = PRODUCT["grid"]
CHART_NAVY = PRODUCT["navy"]
CHART_POSITIVE = PRODUCT["green"]
CHART_NEGATIVE = PRODUCT["brick"]
MARKET_CONFIRMATION_SOURCE_COMPONENTS = {
    "market": {
        "Equal weight / SPY",
        "Small caps / SPY",
        "ARKK / QQQ",
        "Biotech / QQQ",
        "Regional banks / SPY",
        "Bitcoin / SPY",
        "EM / SPY",
    },
    "vix": {"VIX risk signal"},
}


def confirmation_components_for_stale_sources(stale_fields: set[str]) -> set[str]:
    """Return zero-weight confirmation components that must be withheld."""

    return set().union(
        *(
            MARKET_CONFIRMATION_SOURCE_COMPONENTS.get(field, set())
            for field in stale_fields
        )
    )

STRUCTURAL_WEIGHTS = {
    "reserve_availability": 0.40,
    "funding_conditions": 0.30,
    "reserve_flow": 0.30,
}
CORE_SOURCE_FIELDS = {
    "reserves_bn",
    "assets_bn",
    "deposits_bn",
    "sofr",
    "iorb",
    "effr",
}
FRED_SERIES_TO_FIELD = {
    "WRBWFRBL": "reserves_bn",
    "WALCL": "assets_bn",
    "DPSACBW027SBOG": "deposits_bn",
    "IORB": "iorb",
    "EFFR": "effr",
    "BAMLH0A0HYM2": "hy_oas",
    "BAMLC0A0CM": "ig_oas",
    "DTWEXBGS": "broad_usd",
    "DFII10": "real_yield_10y",
}


@dataclass(frozen=True)
class StructuralLiquidityResult:
    history: pd.DataFrame
    current: dict[str, object]
    components: pd.DataFrame


def _fred(snapshot: LiveLiquiditySnapshot, series_id: str, scale: float = 1.0) -> pd.Series:
    path = snapshot.root / "raw" / f"fred_{series_id}.csv"
    frame = pd.read_csv(path, na_values=["."])
    frame.columns = ["date", "value"]
    frame["date"] = pd.to_datetime(frame["date"], errors="raise")
    if frame["date"].duplicated().any():
        raise ValueError(f"FRED series {series_id} contains duplicate dates")
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce") * scale
    series = (
        frame[["date", "value"]]
        .dropna()
        .set_index("date")["value"]
        .sort_index()
    )
    field = FRED_SERIES_TO_FIELD.get(series_id)
    if field is not None and field in set(snapshot.sources["field"].astype(str)):
        cutoff = pd.Timestamp(
            snapshot.sources.set_index("field").loc[field, "observation_date"]
        )
        if cutoff not in series.index:
            raise ValueError(f"{field} lacks its selected observation at {cutoff.date()}")
        series = series.loc[series.index <= cutoff]
    return series


def _sofr(snapshot: LiveLiquiditySnapshot) -> pd.Series:
    payload = json.loads((snapshot.root / "raw" / "nyfed_sofr.json").read_text(encoding="utf-8"))
    frame = pd.DataFrame(payload["refRates"])
    frame["date"] = pd.to_datetime(frame["effectiveDate"], errors="raise")
    if frame["date"].duplicated().any():
        raise ValueError("New York Fed SOFR payload contains duplicate dates")
    frame["value"] = pd.to_numeric(frame["percentRate"], errors="coerce")
    series = (
        frame[["date", "value"]]
        .dropna()
        .set_index("date")["value"]
        .sort_index()
    )
    if "sofr" in set(snapshot.sources["field"].astype(str)):
        cutoff = pd.Timestamp(
            snapshot.sources.set_index("field").loc["sofr", "observation_date"]
        )
        if cutoff not in series.index:
            raise ValueError(f"sofr lacks its selected observation at {cutoff.date()}")
        series = series.loc[series.index <= cutoff]
    return series


def _asof_series(series: pd.Series, dates: pd.DatetimeIndex) -> pd.Series:
    combined = series.reindex(series.index.union(dates)).sort_index().ffill()
    return combined.reindex(dates).astype(float)


def _next_observed_publication_series(
    series: pd.Series, calendar: pd.offsets.BaseOffset
) -> pd.Series:
    """Map an effective-dated rate to the next observed publication session."""

    output = series.copy().sort_index()
    if output.empty:
        return output
    if output.index.has_duplicates:
        raise ValueError("Reference-rate effective dates must be unique")
    publication_dates = list(output.index[1:])
    publication_dates.append(pd.Timestamp(output.index[-1]) + calendar)
    output.index = pd.DatetimeIndex(publication_dates)
    if output.index.has_duplicates or not output.index.is_monotonic_increasing:
        raise ValueError("Reference-rate publication dates must be unique and ordered")
    return output


def _safe_positive_ratio(
    numerator: pd.Series,
    denominator: pd.Series,
    *,
    label: str,
    multiplier: float = 1.0,
) -> pd.Series:
    numerator = numerator.astype(float)
    denominator = denominator.astype(float)
    numerator_finite = pd.Series(
        np.isfinite(numerator.to_numpy(dtype=float)), index=numerator.index
    )
    denominator_finite = pd.Series(
        np.isfinite(denominator.to_numpy(dtype=float)), index=denominator.index
    )
    bad = (numerator.notna() & ~numerator_finite) | (
        denominator.notna() & (~denominator_finite | denominator.le(0))
    )
    if bad.any():
        first = pd.Timestamp(bad.index[bad][0])
        raise ValueError(f"{label} has an invalid denominator at {first.date()}")
    return numerator.div(denominator).mul(multiplier)


def lagged_robust_z(
    series: pd.Series,
    *,
    window: int = 260,
    min_periods: int = 104,
    clip: float = 3.0,
) -> pd.Series:
    """Standardize against prior observations only using median and scaled MAD."""

    prior_median = series.rolling(window, min_periods=min_periods).median().shift(1)
    prior_mad = series.rolling(window, min_periods=min_periods).apply(
        lambda values: float(np.median(np.abs(values - np.median(values)))), raw=True
    ).shift(1)
    robust_scale = prior_mad * 1.4826
    fallback_scale = series.rolling(window, min_periods=min_periods).std(ddof=0).shift(1)
    scale = robust_scale.where(robust_scale.abs().gt(1e-12), fallback_scale)
    return ((series - prior_median) / scale).replace([np.inf, -np.inf], np.nan).clip(-clip, clip)


def lagged_scaled_change(
    series: pd.Series,
    *,
    window: int = 756,
    min_periods: int = 252,
    clip: float = 3.0,
) -> pd.Series:
    """Scale a change by prior volatility while preserving its economic sign."""

    prior_mad = series.rolling(window, min_periods=min_periods).apply(
        lambda values: float(np.median(np.abs(values - np.median(values)))), raw=True
    ).shift(1)
    robust_scale = prior_mad * 1.4826
    fallback_scale = series.rolling(window, min_periods=min_periods).std(ddof=0).shift(1)
    scale = robust_scale.where(robust_scale.abs().gt(1e-12), fallback_scale)
    return (series / scale).replace([np.inf, -np.inf], np.nan).clip(-clip, clip)


def percentile_against_prior(
    series: pd.Series,
    *,
    window: int = 260,
    min_periods: int = 52,
) -> pd.Series:
    """Return the current observation's percentile against a lagged rolling sample."""

    values = series.to_numpy(dtype=float)
    result = np.full(len(series), np.nan, dtype=float)
    for position, value in enumerate(values):
        if not isfinite(value):
            continue
        start = max(0, position - window)
        prior = values[start:position]
        prior = prior[np.isfinite(prior)]
        if len(prior) < min_periods:
            continue
        below = float(np.sum(prior < value))
        tied = float(np.sum(prior == value))
        result[position] = (below + 0.5 * tied) / len(prior) * 100
    return pd.Series(result, index=series.index, name="structural_percentile")


def classify_structural_regime(percentile: float, change: float, band: float) -> dict[str, str]:
    if not all(isfinite(float(value)) for value in (percentile, change, band)) or band < 0:
        return {
            "state_code": "Unavailable",
            "state": "Unavailable",
            "direction": "Unavailable",
            "regime": "Unavailable",
        }
    if percentile < 40:
        state_code = "Low"
        state = "Low versus history"
    elif percentile <= 60:
        state_code = "Typical"
        state = "Typical versus history"
    else:
        state_code = "High"
        state = "High versus history"
    if change > band:
        direction = "Improving"
    elif change < -band:
        direction = "Deteriorating"
    else:
        direction = "Stable"
    return {
        "state_code": state_code,
        "state": state,
        "direction": direction,
        "regime": f"{state}, {direction.lower()}",
    }


def classify_funding_state(sofr_iorb_bp: float, effr_iorb_bp: float) -> str:
    """Describe absolute overnight funding pressure without predicting markets."""

    if not all(isfinite(float(value)) for value in (sofr_iorb_bp, effr_iorb_bp)):
        return "Unavailable"
    maximum_spread = max(float(sofr_iorb_bp), float(effr_iorb_bp))
    if maximum_spread <= 5:
        return "Orderly"
    if maximum_spread <= 10:
        return "Pressured"
    return "Stressed"


def classify_transmission_state(frame: pd.DataFrame) -> str:
    """Summarize a context panel while retaining every component separately."""

    average = float(frame["tightening_score_z"].mean())
    if average > 0.35:
        return "Tightening pressure"
    if average < -0.35:
        return "Easing pressure"
    return "Mixed"


def classify_market_confirmation(frame: pd.DataFrame) -> tuple[str, int, int]:
    """Return a transparent positive-component count and breadth label."""

    available = int(len(frame))
    positive = int(frame["response_score_z"].gt(0).sum())
    if not available:
        return "Unavailable", 0, 0
    return f"{positive} of {available} positive", positive, available


def build_structural_liquidity(snapshot: LiveLiquiditySnapshot) -> StructuralLiquidityResult:
    release_calendars = load_federal_reserve_release_calendars(snapshot.root)
    reserves = _fred(snapshot, "WRBWFRBL", 0.001)
    assets = _fred(snapshot, "WALCL", 0.001)
    deposits_observed = _fred(snapshot, "DPSACBW027SBOG")
    deposits = apply_federal_reserve_release_availability(
        deposits_observed, "h8", release_calendars["h8"]
    )
    iorb = _fred(snapshot, "IORB")
    effr = _fred(snapshot, "EFFR")
    sofr = _sofr(snapshot)

    reserves_available = apply_federal_reserve_release_availability(
        reserves, "h41", release_calendars["h41"]
    )
    assets_available = apply_federal_reserve_release_availability(
        assets, "h41", release_calendars["h41"]
    )
    sofr_spread_available = _next_observed_publication_series(
        (sofr - _asof_series(iorb, sofr.index)) * 100,
        GOVERNMENT_SECURITIES_DAY,
    )
    effr_spread_available = _next_observed_publication_series(
        (effr - _asof_series(iorb, effr.index)) * 100,
        FEDERAL_RESERVE_DAY,
    )
    start = max(
        pd.Timestamp("2018-04-03"), deposits.index.min(), sofr_spread_available.index.min()
    )
    cutoff = pd.Timestamp(snapshot.manifest["information_cutoff_et"])
    end = cutoff.tz_localize(None) if cutoff.tzinfo is not None else cutoff
    end = end.normalize()
    dates = pd.DatetimeIndex(
        reserves_available.loc[
            (reserves_available.index >= start) & (reserves_available.index <= end)
        ].index
    )
    if len(dates) < 110:
        raise ValueError("Structural liquidity history is too short for lagged calibration")

    history = pd.DataFrame(index=dates)
    history.index.name = "date"
    history["reserves_bn"] = _asof_series(reserves_available, dates)
    history["assets_bn"] = _asof_series(assets_available, dates)
    history["deposits_bn"] = _asof_series(deposits, dates)
    reserve_deposit_observed = _safe_positive_ratio(
        _asof_series(reserves, deposits_observed.index),
        deposits_observed,
        label="Legacy reserves relative to deposits",
        multiplier=100,
    )
    history["reserve_deposit_pct"] = _asof_series(
        apply_federal_reserve_release_availability(
            reserve_deposit_observed, "h8", release_calendars["h8"]
        ),
        dates,
    )
    history["reserve_impulse_4w_bp"] = _safe_positive_ratio(
        history["reserves_bn"].diff(4),
        history["assets_bn"].shift(4),
        label="Legacy four-week reserve impulse",
        multiplier=10_000,
    )
    history["sofr_iorb_bp"] = _asof_series(sofr_spread_available, dates)
    history["effr_iorb_bp"] = _asof_series(effr_spread_available, dates)

    history["reserve_availability_z"] = lagged_robust_z(history["reserve_deposit_pct"])
    history["sofr_support_z"] = lagged_robust_z(-history["sofr_iorb_bp"])
    history["effr_support_z"] = lagged_robust_z(-history["effr_iorb_bp"])
    history["funding_conditions_z"] = history[["sofr_support_z", "effr_support_z"]].mean(
        axis=1, skipna=False
    )
    history["reserve_flow_z"] = lagged_robust_z(history["reserve_impulse_4w_bp"])
    history["structural_score_z"] = (
        STRUCTURAL_WEIGHTS["reserve_availability"] * history["reserve_availability_z"]
        + STRUCTURAL_WEIGHTS["funding_conditions"] * history["funding_conditions_z"]
        + STRUCTURAL_WEIGHTS["reserve_flow"] * history["reserve_flow_z"]
    )
    history["structural_percentile"] = percentile_against_prior(history["structural_score_z"])
    history["structural_change_4w_z"] = history["structural_score_z"].diff(4)
    history["direction_band_z"] = (
        history["structural_change_4w_z"]
        .abs()
        .rolling(260, min_periods=52)
        .quantile(0.25)
        .shift(1)
    )

    valid = history.dropna(
        subset=["structural_score_z", "structural_percentile", "structural_change_4w_z", "direction_band_z"]
    )
    if valid.empty:
        raise ValueError("Structural liquidity model has no fully calibrated observation")
    if valid.index[-1] != dates[-1]:
        raise ValueError("Legacy structural diagnostic lacks a current complete observation")
    row = valid.iloc[-1]
    regime = classify_structural_regime(
        float(row["structural_percentile"]),
        float(row["structural_change_4w_z"]),
        float(row["direction_band_z"]),
    )

    source_status = snapshot.sources.set_index("field")["status"].astype(str)
    accepted = {"CURRENT_UPDATED", "CURRENT_UNCHANGED", "CURRENT_PUBLICATION_LAG"}
    core_complete = CORE_SOURCE_FIELDS.issubset(source_status.index)
    core_current = core_complete and source_status.reindex(sorted(CORE_SOURCE_FIELDS)).isin(accepted).all()
    confidence = "Complete" if core_current else "Incomplete"

    components = pd.DataFrame(
        [
            {
                "component": "Reserve stock relative to deposits",
                "score_z": float(row["reserve_availability_z"]),
                "weight": STRUCTURAL_WEIGHTS["reserve_availability"],
                "weighted_contribution": float(row["reserve_availability_z"])
                * STRUCTURAL_WEIGHTS["reserve_availability"],
                "raw_value": float(row["reserve_deposit_pct"]),
                "raw_label": "Reserves as a share of deposits",
                "raw_unit": "%",
                "secondary_label": "",
                "secondary_value": np.nan,
                "secondary_unit": "",
                "secondary_detail": "Single-input sleeve",
            },
            {
                "component": "Relative funding support",
                "score_z": float(row["funding_conditions_z"]),
                "weight": STRUCTURAL_WEIGHTS["funding_conditions"],
                "weighted_contribution": float(row["funding_conditions_z"])
                * STRUCTURAL_WEIGHTS["funding_conditions"],
                "raw_value": float(row["sofr_iorb_bp"]),
                "raw_label": "SOFR minus IORB",
                "raw_unit": "bp",
                "secondary_label": "EFFR minus IORB",
                "secondary_value": float(row["effr_iorb_bp"]),
                "secondary_unit": "bp",
                "secondary_detail": f"EFFR minus IORB: {float(row['effr_iorb_bp']):+.2f} bp",
            },
            {
                "component": "Realized reserve flow",
                "score_z": float(row["reserve_flow_z"]),
                "weight": STRUCTURAL_WEIGHTS["reserve_flow"],
                "weighted_contribution": float(row["reserve_flow_z"])
                * STRUCTURAL_WEIGHTS["reserve_flow"],
                "raw_value": float(row["reserve_impulse_4w_bp"]),
                "raw_label": "Four-week reserve impulse",
                "raw_unit": "bp",
                "secondary_label": "",
                "secondary_value": np.nan,
                "secondary_unit": "",
                "secondary_detail": "Single-input sleeve",
            },
        ]
    )
    current: dict[str, object] = {
        **regime,
        "date": valid.index[-1],
        "score_z": float(row["structural_score_z"]),
        "percentile": float(row["structural_percentile"]),
        "change_4w_z": float(row["structural_change_4w_z"]),
        "direction_band_z": float(row["direction_band_z"]),
        "source_coverage": confidence,
        "calibration_start": valid.index[0],
        "calibration_observations": int(len(valid)),
        "percentile_reference_observations": int(
            history.loc[history.index < valid.index[-1], "structural_score_z"]
            .tail(260)
            .notna()
            .sum()
        ),
        "weights": dict(STRUCTURAL_WEIGHTS),
    }
    return StructuralLiquidityResult(history=history, current=current, components=components)


def structural_history_figure(result: StructuralLiquidityResult, years: int | None = 5) -> go.Figure:
    frame = result.history.dropna(subset=["structural_percentile"]).copy()
    if years is not None and not frame.empty:
        frame = frame.loc[frame.index >= frame.index.max() - pd.DateOffset(years=years)]
    figure = go.Figure()
    for lower, upper, color in ((0, 40, "#f8eaea"), (40, 60, "#f6f4ed"), (60, 100, "#eaf2e7")):
        figure.add_hrect(y0=lower, y1=upper, fillcolor=color, line_width=0, layer="below")
    figure.add_trace(
        go.Scatter(
            x=frame.index,
            y=frame["structural_percentile"],
            mode="lines",
            name="Structural liquidity percentile",
            line={"color": "#111111", "width": 2.5},
            hovertemplate="%{x|%d %b %Y}<br>%{y:.0f}th percentile<extra></extra>",
        )
    )
    if not frame.empty:
        current_percentile = float(frame["structural_percentile"].iloc[-1])
        figure.add_trace(
            go.Scatter(
                x=[frame.index[-1]],
                y=[current_percentile],
                mode="markers",
                name="Current",
                marker={"color": "#111111", "size": 8},
                customdata=[f"{current_percentile:.0f}th percentile"],
                hovertemplate="Current: %{customdata}<extra></extra>",
                showlegend=False,
            )
        )
    figure.add_hline(y=40, line={"color": "#aaaaaa", "width": 1, "dash": "dot"})
    figure.add_hline(y=60, line={"color": "#aaaaaa", "width": 1, "dash": "dot"})
    figure.update_layout(
        height=390,
        margin={"l": 58, "r": 24, "t": 34, "b": 48},
        paper_bgcolor="#ffffff",
        plot_bgcolor="#ffffff",
        font={"family": "Arial, Helvetica, sans-serif", "color": "#202020"},
        showlegend=False,
        hovermode="x unified",
        xaxis={"title": None, "showgrid": False, "linecolor": "#aaaaaa"},
        yaxis={
            "title": "Historical percentile",
            "range": [0, 100],
            "tickvals": [0, 20, 40, 60, 80, 100],
            "gridcolor": "#e5e5e5",
            "zeroline": False,
        },
    )
    return figure


def structural_components_figure(result: StructuralLiquidityResult) -> go.Figure:
    frame = result.components.iloc[::-1].copy()
    colors = [PASTEL["rose"] if value < 0 else PASTEL["sage"] for value in frame["weighted_contribution"]]
    labels = [f"{value:+.2f}".replace("-", "−") for value in frame["weighted_contribution"]]
    figure = go.Figure(
        go.Bar(
            x=frame["weighted_contribution"],
            y=frame["component"],
            orientation="h",
            marker={"color": colors},
            text=labels,
            textposition="outside",
            cliponaxis=False,
            customdata=np.column_stack(
                [
                    frame["score_z"],
                    frame["weight"],
                    frame["raw_label"],
                    frame["raw_value"],
                    frame["raw_unit"],
                    frame["secondary_detail"],
                ]
            ),
            hovertemplate=(
                "%{y}<br>Weighted contribution: %{x:.2f}"
                "<br>Standardized sleeve score: %{customdata[0]:.2f}"
                "<br>Model weight: %{customdata[1]:.0%}"
                "<br>%{customdata[2]}: %{customdata[3]:.2f} %{customdata[4]}"
                "<br>%{customdata[5]}<extra></extra>"
            ),
        )
    )
    figure.add_vline(x=0, line={"color": "#111111", "width": 1})
    figure.update_layout(
        height=285,
        margin={"l": 30, "r": 54, "t": 16, "b": 48},
        paper_bgcolor="#ffffff",
        plot_bgcolor="#ffffff",
        font={"family": "Arial, Helvetica, sans-serif", "color": "#202020"},
        showlegend=False,
        xaxis={
            "title": "Weighted structural contribution",
            "range": [-1.35, 1.35],
            "gridcolor": "#e5e5e5",
            "zeroline": False,
        },
        yaxis={"title": None, "showgrid": False, "automargin": True},
    )
    return figure


def funding_conditions_figure(
    result: StructuralLiquidityResult, years: int | None = 3
) -> go.Figure:
    frame = result.history[["sofr_iorb_bp", "effr_iorb_bp"]].dropna().copy()
    if years is not None and not frame.empty:
        frame = frame.loc[frame.index >= frame.index.max() - pd.DateOffset(years=years)]
    figure = go.Figure()
    for column, label, color in (
        ("sofr_iorb_bp", "SOFR minus IORB", "#4472C4"),
        ("effr_iorb_bp", "EFFR minus IORB", "#4BACC6"),
    ):
        figure.add_trace(
            go.Scatter(
                x=frame.index,
                y=frame[column],
                mode="lines",
                name=label,
                line={"color": color, "width": 2},
                hovertemplate=f"{label}<br>%{{x|%d %b %Y}}<br>%{{y:+.1f}} bp<extra></extra>",
            )
        )
    figure.add_hline(y=0, line={"color": "#111111", "width": 1})
    figure.update_layout(
        height=340,
        margin={"l": 58, "r": 24, "t": 44, "b": 48},
        paper_bgcolor="#ffffff",
        plot_bgcolor="#ffffff",
        font={"family": "Arial, Helvetica, sans-serif", "color": "#202020", "size": 11},
        legend={"orientation": "h", "x": 0, "y": 1.14, "xanchor": "left", "yanchor": "top"},
        hovermode="x unified",
        xaxis={"title": None, "showgrid": False, "linecolor": "#aaaaaa"},
        yaxis={"title": "Spread to IORB (bp)", "gridcolor": "#e5e5e5", "zeroline": False},
    )
    return figure


def transmission_snapshot(snapshot: LiveLiquiditySnapshot) -> pd.DataFrame:
    """Current 20-session changes scaled by prior volatility with sign preserved."""

    inputs = (
        ("HY OAS", _fred(snapshot, "BAMLH0A0HYM2"), "spread", "pp"),
        ("IG OAS", _fred(snapshot, "BAMLC0A0CM"), "spread", "pp"),
        ("Broad U.S. dollar", _fred(snapshot, "DTWEXBGS"), "return", "index"),
        ("10-year real yield", _fred(snapshot, "DFII10"), "spread", "%"),
    )
    rows: list[dict[str, object]] = []
    for label, series, transform, unit in inputs:
        series = series.dropna().sort_index()
        change = series.pct_change(20) * 100 if transform == "return" else series.diff(20)
        z = lagged_scaled_change(change, window=756, min_periods=252)
        valid = pd.concat({"level": series, "change": change, "score": z}, axis=1).dropna()
        if valid.empty:
            continue
        row = valid.iloc[-1]
        rows.append(
            {
                "component": label,
                "tightening_score_z": float(row["score"]),
                "level": float(row["level"]),
                "change_20": float(row["change"]),
                "unit": unit,
                "date": valid.index[-1],
            }
        )
    return pd.DataFrame(rows)


def transmission_conditions_figure(snapshot: LiveLiquiditySnapshot) -> go.Figure:
    frame = transmission_snapshot(snapshot).iloc[::-1].copy()
    frame["support_score_z"] = -frame["tightening_score_z"]
    colors = [CHART_POSITIVE if value > 0 else CHART_NEGATIVE for value in frame["support_score_z"]]
    level_display = []
    change_display = []
    for _, row in frame.iterrows():
        unit = str(row["unit"])
        level = float(row["level"])
        change = float(row["change_20"])
        if unit == "pp":
            level_display.append(format_percentage_points(level))
            change_display.append(format_percentage_points(change, signed=True))
        elif unit == "%":
            level_display.append(format_percent(level))
            change_display.append(format_percentage_points(change, signed=True))
        else:
            level_display.append(f"{level:.2f} index points")
            change_display.append(format_percent(change, signed=True))
    hover_data = np.column_stack(
        [
            [format_normalized(value, signed=True) for value in frame["support_score_z"]],
            [format_normalized(value, signed=True) for value in frame["tightening_score_z"]],
            level_display,
            change_display,
            [pd.Timestamp(value).strftime("%d %b %Y") for value in frame["date"]],
        ]
    )
    max_abs = max(1.0, float(frame["support_score_z"].abs().max()) * 1.35)
    figure = go.Figure()
    for (_, row), color, hover_row in zip(
        frame.iterrows(), colors, hover_data, strict=True
    ):
        value = float(row["support_score_z"])
        label = str(row["component"])
        figure.add_trace(
            go.Scatter(
                x=[0.0, value],
                y=[label, label],
                mode="lines",
                line={"color": color, "width": 4},
                hoverinfo="skip",
                showlegend=False,
            )
        )
        figure.add_trace(
            go.Scatter(
                x=[value],
                y=[label],
                mode="markers+text",
                marker={"color": color, "size": 9, "line": {"color": "#FFFFFF", "width": 1.5}},
                text=[f"{value:+.2f}".replace("-", "−")],
                textposition="top center",
                textfont={"family": CHART_FONT, "size": 11, "color": CHART_INK},
                cliponaxis=False,
                customdata=[hover_row],
                hovertemplate=(
                    "%{y}<br>Support-oriented score: %{customdata[0]}"
                    "<br>Original tightening score: %{customdata[1]}"
                    "<br>Level: %{customdata[2]}"
                    "<br>20-session change: %{customdata[3]}"
                    "<br>%{customdata[4]}<extra></extra>"
                ),
                showlegend=False,
            )
        )
    figure.add_vline(x=0, line={"color": CHART_NAVY, "width": 1})
    figure.update_layout(
        height=310,
        margin={"l": 20, "r": 44, "t": 14, "b": 38},
        paper_bgcolor="#ffffff",
        plot_bgcolor="#ffffff",
        font={"family": CHART_FONT, "color": CHART_INK, "size": 11},
        showlegend=False,
        xaxis={
            "title": None,
            "range": [-max_abs, max_abs],
            "gridcolor": CHART_GRID,
            "zeroline": False,
        },
        yaxis={"title": None, "showgrid": False, "automargin": True},
    )
    return figure


def market_confirmation_snapshot(
    snapshot: LiveLiquiditySnapshot,
    excluded_components: set[str] | None = None,
) -> pd.DataFrame:
    excluded = excluded_components or set()
    market = pd.read_csv(
        snapshot.root / "raw" / "market_adjusted_close.csv", parse_dates=["date"]
    ).set_index("date")
    market_cutoff = pd.Timestamp(
        snapshot.sources.set_index("field").loc["market", "observation_date"]
    )
    market = market.loc[market.index <= market_cutoff]
    ratios = (
        ("Equal weight / SPY", "RSP", "SPY"),
        ("Small caps / SPY", "IWM", "SPY"),
        ("ARKK / QQQ", "ARKK", "QQQ"),
        ("Biotech / QQQ", "XBI", "QQQ"),
        ("Regional banks / SPY", "KRE", "SPY"),
        ("Bitcoin / SPY", "BTC-USD", "SPY"),
        ("EM / SPY", "EEM", "SPY"),
    )
    rows: list[dict[str, object]] = []
    for label, numerator, denominator in ratios:
        if label in excluded:
            continue
        ratio = (market[numerator] / market[denominator]).dropna()
        response = ratio.pct_change(20) * 100
        z = lagged_scaled_change(response, window=756, min_periods=252)
        valid = pd.concat({"ratio": ratio, "response": response, "score": z}, axis=1).dropna()
        if valid.empty:
            continue
        row = valid.iloc[-1]
        rows.append(
            {
                "component": label,
                "response_score_z": float(row["score"]),
                "change_20_pct": float(row["response"]),
                "date": valid.index[-1],
            }
        )
    vix_cutoff = pd.Timestamp(
        snapshot.sources.set_index("field").loc["vix", "observation_date"]
    )
    if "^VIX" not in market.columns:
        raise ValueError("Yahoo Finance market history lacks ^VIX")
    vix = market.loc[market.index <= vix_cutoff, "^VIX"].dropna()
    vix_change = -(vix.diff(20))
    vix_z = lagged_scaled_change(vix_change, window=756, min_periods=252)
    vix_valid = pd.concat({"response": vix_change, "score": vix_z}, axis=1).dropna()
    if not vix_valid.empty and "VIX risk signal" not in excluded:
        row = vix_valid.iloc[-1]
        rows.append(
            {
                "component": "VIX risk signal",
                "response_score_z": float(row["score"]),
                "change_20_pct": float(row["response"]),
                "date": vix_valid.index[-1],
            }
        )
    return pd.DataFrame(rows)


def market_confirmation_figure(
    snapshot: LiveLiquiditySnapshot,
    excluded_components: set[str] | None = None,
) -> go.Figure:
    frame = market_confirmation_snapshot(snapshot, excluded_components).iloc[::-1].copy()
    display_labels = {
        "Equal weight / SPY": "Equal weight",
        "Small caps / SPY": "Small caps",
        "ARKK / QQQ": "Speculative growth",
        "Biotech / QQQ": "Biotech",
        "Regional banks / SPY": "Regional banks",
        "Bitcoin / SPY": "Crypto",
        "EM / SPY": "Emerging markets",
        "VIX risk signal": "Volatility",
    }
    frame["display_component"] = frame["component"].replace(display_labels)
    colors = [CHART_POSITIVE if value > 0 else CHART_NEGATIVE for value in frame["response_score_z"]]
    change_display = [
        f"{float(value):+.2f} VIX points".replace("-", "−")
        if component == "VIX risk signal"
        else format_percent(value, signed=True)
        for component, value in zip(
            frame["component"], frame["change_20_pct"], strict=True
        )
    ]
    hover_data = np.column_stack(
        [
            [format_normalized(value, signed=True) for value in frame["response_score_z"]],
            change_display,
            [pd.Timestamp(value).strftime("%d %b %Y") for value in frame["date"]],
        ]
    )
    max_abs = max(1.0, float(frame["response_score_z"].abs().max()) * 1.35)
    figure = go.Figure()
    for (_, row), color, hover_row in zip(
        frame.iterrows(), colors, hover_data, strict=True
    ):
        value = float(row["response_score_z"])
        label = str(row["display_component"])
        figure.add_trace(
            go.Scatter(
                x=[0.0, value],
                y=[label, label],
                mode="lines",
                line={"color": color, "width": 4},
                hoverinfo="skip",
                showlegend=False,
            )
        )
        figure.add_trace(
            go.Scatter(
                x=[value],
                y=[label],
                mode="markers+text",
                marker={"color": color, "size": 9, "line": {"color": "#FFFFFF", "width": 1.5}},
                text=[f"{value:+.2f}".replace("-", "−")],
                textposition="top center",
                textfont={"family": CHART_FONT, "size": 11, "color": CHART_INK},
                cliponaxis=False,
                customdata=[hover_row],
                hovertemplate=(
                    "%{y}<br>Standardized risk-appetite change: %{customdata[0]}"
                    "<br>20-session change: %{customdata[1]}"
                    "<br>%{customdata[2]}<extra></extra>"
                ),
                showlegend=False,
            )
        )
    figure.add_vline(x=0, line={"color": CHART_NAVY, "width": 1})
    figure.update_layout(
        height=310,
        margin={"l": 20, "r": 44, "t": 14, "b": 38},
        paper_bgcolor="#ffffff",
        plot_bgcolor="#ffffff",
        font={"family": CHART_FONT, "color": CHART_INK, "size": 11},
        showlegend=False,
        xaxis={
            "title": None,
            "range": [-max_abs, max_abs],
            "gridcolor": CHART_GRID,
            "zeroline": False,
        },
        yaxis={"title": None, "showgrid": False, "automargin": True},
    )
    return figure
