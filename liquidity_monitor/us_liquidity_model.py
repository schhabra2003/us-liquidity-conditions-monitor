"""Layered, point-in-time-aware U.S. liquidity conditions model.

The model separates four economically distinct index layers:

1. structural reserve capacity;
2. overnight funding support;
3. realized reserve impulse;
4. bank-credit creation.

A mechanical seasonal deviation is retained as a diagnostic, but it receives
no second index weight because it is derived from the reserve-impulse layer.

Traded asset prices are intentionally excluded from the liquidity index.  They
remain a separate transmission check in the manager-facing application.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from math import isfinite

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from liquidity_monitor.liquidity_formatting import (
    format_basis_points,
    format_normalized,
)
from liquidity_monitor.liquidity_live_snapshot import (
    FEDERAL_RESERVE_DAY,
    GOVERNMENT_SECURITIES_DAY,
    LiveLiquiditySnapshot,
    apply_federal_reserve_release_availability,
    load_federal_reserve_release_calendars,
)
from liquidity_monitor.palette import PRODUCT
from liquidity_monitor.structural_liquidity import (
    lagged_robust_z,
    percentile_against_prior,
)

MODEL_VERSION = "3.0.0-research"
MODEL_WEEKLY_CLOSE_ET = (16, 30)
CHART_FONT = "Arial, Helvetica, sans-serif"
CHART_INK = PRODUCT["ink"]
CHART_MUTED = PRODUCT["muted"]
CHART_GRID = PRODUCT["grid"]
CHART_NAVY = PRODUCT["navy"]
CHART_POSITIVE = PRODUCT["green"]
CHART_NEGATIVE = PRODUCT["brick"]
LIQUIDITY_LAYER_WEIGHTS = {
    "reserve_capacity": 0.35,
    "funding_support": 0.25,
    "reserve_impulse": 0.30,
    "bank_credit": 0.10,
}
CORE_SOURCE_FIELDS = {
    "reserves_bn",
    "assets_bn",
    "deposits_bn",
    "bank_assets_bn",
    "bank_cash_bn",
    "large_bank_assets_bn",
    "large_bank_cash_bn",
    "small_bank_assets_bn",
    "small_bank_cash_bn",
    "bank_credit_bn",
    "fedwire_daily_value_bn",
    "sofr",
    "tgcr",
    "bgcr",
    "effr",
    "iorb",
    "repo_add_bn",
}


@dataclass(frozen=True)
class USLiquidityResult:
    history: pd.DataFrame
    current: dict[str, object]
    layers: pd.DataFrame
    capacity_components: pd.DataFrame
    funding_components: pd.DataFrame


def _fred(
    snapshot: LiveLiquiditySnapshot,
    series_id: str,
    *,
    field: str | None = None,
    scale: float = 1.0,
) -> pd.Series:
    path = snapshot.root / "raw" / f"fred_{series_id}.csv"
    frame = pd.read_csv(path, na_values=["."])
    frame.columns = ["date", "value"]
    frame["date"] = pd.to_datetime(frame["date"], errors="raise")
    if frame["date"].duplicated().any():
        raise ValueError(f"FRED series {series_id} contains duplicate dates")
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce") * scale
    valid = frame.dropna()
    series = valid.set_index("date")["value"].sort_index()
    if field and field in set(snapshot.sources["field"].astype(str)):
        cutoff = pd.Timestamp(
            snapshot.sources.set_index("field").loc[field, "observation_date"]
        )
        if cutoff not in series.index:
            raise ValueError(
                f"{field} lacks its selected observation at {cutoff.date()}"
            )
        series = series.loc[series.index <= cutoff]
    return series


def _availability_lag(series: pd.Series, days: int) -> pd.Series:
    output = series.copy()
    output.index = output.index + pd.Timedelta(days=days)
    return output


def _reference_rate_publication_availability(
    values: pd.Series | pd.DataFrame, calendar: pd.offsets.BaseOffset
) -> pd.Series | pd.DataFrame:
    """Put effective-dated rates on a conservative publication-time clock.

    Historical New York Fed payloads expose effective dates, not a separate
    publication timestamp.  A rate for one effective session is normally
    published on the next session.  Using the *observed* next effective date
    captures historical holiday and exceptional-session calendars without
    imposing a modern rule on old data.  Only the final observation, for which
    there is no later effective date in the payload, uses the relevant published
    business-day calendar.

    If a historical observation is missing from the payload, this convention
    delays availability to the next observed session.  That is conservative for
    point-in-time analysis and cannot introduce a rate before it was observable.
    """

    output = values.copy().sort_index()
    if output.empty:
        return output
    if not isinstance(output.index, pd.DatetimeIndex):
        output.index = pd.DatetimeIndex(output.index)
    if output.index.has_duplicates:
        raise ValueError("Reference-rate effective dates must be unique")
    availability = list(output.index[1:])
    availability.append(pd.Timestamp(output.index[-1]) + calendar)
    publication_index = pd.DatetimeIndex(availability)
    if publication_index.has_duplicates or not publication_index.is_monotonic_increasing:
        raise ValueError("Reference-rate publication dates must be unique and ordered")
    output.index = publication_index
    return output


def _asof(series: pd.Series, dates: pd.DatetimeIndex) -> pd.Series:
    combined = series.reindex(series.index.union(dates)).sort_index().ffill()
    return combined.reindex(dates).astype(float)


def _administered_rate(snapshot: LiveLiquiditySnapshot) -> pd.Series:
    ioer = _fred(snapshot, "IOER")
    iorb = _fred(snapshot, "IORB", field="iorb")
    return pd.concat([ioer, iorb]).sort_index().groupby(level=0).last()


def _nyfed_rate(snapshot: LiveLiquiditySnapshot, rate: str, field: str) -> pd.DataFrame:
    payload = json.loads(
        (snapshot.root / "raw" / f"nyfed_{rate.lower()}.json").read_text(
            encoding="utf-8"
        )
    )
    frame = pd.DataFrame(payload["refRates"])
    frame["date"] = pd.to_datetime(frame["effectiveDate"], errors="raise")
    if frame["date"].duplicated().any():
        raise ValueError(f"New York Fed {rate.upper()} payload contains duplicate dates")
    frame["rate"] = pd.to_numeric(frame["percentRate"], errors="coerce")
    for source, target in (
        ("percentPercentile25", "p25"),
        ("percentPercentile75", "p75"),
        ("volumeInBillions", "volume_bn"),
    ):
        frame[target] = pd.to_numeric(frame.get(source), errors="coerce")
    frame = frame.dropna(subset=["date", "rate"])
    frame = frame.set_index("date").sort_index()
    cutoff = pd.Timestamp(
        snapshot.sources.set_index("field").loc[field, "observation_date"]
    )
    if cutoff not in frame.index:
        raise ValueError(f"{field} lacks its selected observation at {cutoff.date()}")
    return frame.loc[frame.index <= cutoff]


def _fedwire_monthly(snapshot: LiveLiquiditySnapshot) -> pd.Series:
    text = (snapshot.root / "raw" / "fedwire_monthly.txt").read_text(
        encoding="utf-8", errors="replace"
    )
    month_map = {
        "jan": 1, "january": 1,
        "feb": 2, "february": 2, "feburary": 2,
        "mar": 3, "march": 3,
        "apr": 4, "april": 4,
        "may": 5,
        "jun": 6, "june": 6,
        "jul": 7, "july": 7,
        "aug": 8, "august": 8,
        "sep": 9, "sept": 9, "september": 9,
        "oct": 10, "october": 10,
        "nov": 11, "november": 11,
        "dec": 12, "december": 12,
    }
    records: list[tuple[pd.Timestamp, float]] = []
    row_pattern = re.compile(r"^\s*(\d{4}):\s*([A-Za-z]+)\s+(.+)$")
    number_pattern = re.compile(r"\(?-?[\d,]+(?:\.\d+)?\)?")
    for line in text.splitlines():
        match = row_pattern.match(line)
        if not match:
            continue
        year = int(match.group(1))
        month = month_map.get(match.group(2).strip().lower())
        if month is None:
            continue
        values = number_pattern.findall(match.group(3))
        if len(values) < 2:
            continue
        average_daily_value_millions = float(values[-1].replace(",", "").strip("()"))
        date = pd.Timestamp(year=year, month=month, day=1) + pd.offsets.MonthEnd(0)
        records.append((date, average_daily_value_millions * 0.001))
    if not records:
        raise ValueError("Fedwire monthly source contains no parseable observations")
    series = pd.Series(dict(records), name="fedwire_daily_value_bn").sort_index()
    cutoff = pd.Timestamp(
        snapshot.sources.set_index("field").loc[
            "fedwire_daily_value_bn", "observation_date"
        ]
    )
    if cutoff not in series.index:
        raise ValueError(
            "fedwire_daily_value_bn lacks its selected monthly observation"
        )
    return series.loc[series.index <= cutoff]


def _prior_seasonal_expectation(
    series: pd.Series,
    *,
    week_radius: int = 2,
    minimum_prior_years: int = 3,
) -> pd.Series:
    """One-sided seasonal median using prior ISO years and comparable week phase."""

    output = pd.Series(np.nan, index=series.index, dtype=float)
    iso_calendar = series.index.isocalendar()
    weeks = pd.Series(
        iso_calendar.week.to_numpy(dtype=int), index=series.index, dtype=int
    )
    iso_years = pd.Series(
        iso_calendar.year.to_numpy(dtype=int), index=series.index, dtype=int
    )
    weeks_in_year = iso_years.map(
        lambda year: int(pd.Timestamp(year=int(year), month=12, day=28).isocalendar().week)
    )
    phases = (weeks.astype(float) - 0.5) / weeks_in_year.astype(float)
    for position, (date, value) in enumerate(series.items()):
        if not isfinite(float(value)):
            continue
        target_phase = float(phases.iloc[position])
        target_iso_year = int(iso_years.iloc[position])
        prior = series.iloc[:position]
        prior_phases = phases.iloc[:position]
        prior_years = iso_years.iloc[:position]
        phase_distance = (prior_phases - target_phase).abs()
        circular_distance = np.minimum(
            phase_distance, 1.0 - phase_distance
        ) * 52.0
        eligible = prior.loc[
            prior_years.lt(target_iso_year) & circular_distance.le(week_radius)
        ].dropna()
        eligible_years = prior_years.reindex(eligible.index)
        if eligible_years.nunique() >= minimum_prior_years:
            output.loc[date] = float(eligible.median())
    return output


def _smooth(series: pd.Series, span: int) -> pd.Series:
    smoothed = series.ewm(span=span, adjust=False, min_periods=1).mean()
    return smoothed.where(series.notna())


def _safe_positive_ratio(
    numerator: pd.Series,
    denominator: pd.Series,
    *,
    label: str,
    multiplier: float = 1.0,
) -> pd.Series:
    """Divide only when the populated inputs and denominator are economically valid."""

    numerator = numerator.astype(float)
    denominator = denominator.astype(float)
    numerator_finite = pd.Series(
        np.isfinite(numerator.to_numpy(dtype=float)), index=numerator.index
    )
    denominator_finite = pd.Series(
        np.isfinite(denominator.to_numpy(dtype=float)), index=denominator.index
    )
    bad = (
        (numerator.notna() & ~numerator_finite)
        | (denominator.notna() & (~denominator_finite | denominator.le(0)))
    )
    if bad.any():
        first = pd.Timestamp(bad.index[bad][0])
        raise ValueError(
            f"{label} contains a missing, non-finite, or non-positive denominator at {first.date()}"
        )
    return numerator.div(denominator).mul(multiplier)


def _require_latest_finite(
    history: pd.DataFrame,
    columns: list[str],
    *,
    date: pd.Timestamp,
    stage: str,
) -> None:
    values = history.loc[date, columns].astype(float)
    invalid = [name for name, value in values.items() if not isfinite(float(value))]
    if invalid:
        raise ValueError(
            f"U.S. liquidity {stage} is incomplete at {date.date()}: "
            + ", ".join(invalid)
        )


def _index_from_z(series: pd.Series) -> pd.Series:
    return 50.0 + 50.0 * np.tanh(series / 2.0)


def _completed_weekly_model_date(snapshot: LiveLiquiditySnapshot) -> pd.Timestamp:
    """Return the latest completed Friday model observation at the ET cutoff.

    The composite is a weekly model: its changes, standardization windows, and
    exponential filters are all expressed in weekly observations.  Appending a
    Saturday or midweek snapshot as another row would shorten the stated
    four-week and thirteen-week horizons and could move the filtered index even
    when no input changed.  The separate funding and reserve-mechanics panels
    remain free to display newer source observations between model closes.
    """

    cutoff_value = snapshot.manifest.get("information_cutoff_et")
    if cutoff_value is None:
        raise ValueError("Live liquidity snapshot lacks an information cutoff")
    cutoff = pd.Timestamp(cutoff_value)
    if cutoff.tzinfo is None:
        cutoff = cutoff.tz_localize("America/New_York")
    else:
        cutoff = cutoff.tz_convert("America/New_York")

    state_date = pd.Timestamp(snapshot.state.iloc[0]["as_of_date"]).normalize()
    cutoff_date = cutoff.normalize().tz_localize(None)
    effective_date = min(state_date, cutoff_date)
    days_since_friday = (effective_date.weekday() - 4) % 7
    completed_friday = effective_date - pd.Timedelta(days=days_since_friday)
    if (
        effective_date.weekday() == 4
        and cutoff_date == effective_date
        and (cutoff.hour, cutoff.minute) < MODEL_WEEKLY_CLOSE_ET
    ):
        completed_friday -= pd.Timedelta(days=7)
    return completed_friday


def _classify_direction(change: float, band: float) -> str:
    if (
        not isfinite(float(change))
        or not isfinite(float(band))
        or float(band) < 0
    ):
        return "Unavailable"
    if change > band:
        return "Improving"
    if change < -band:
        return "Deteriorating"
    return "Stable"


def _classify_liquidity_state(index_value: float) -> tuple[str, str]:
    if not isfinite(float(index_value)):
        return "unavailable", "Unavailable"
    if index_value < 35:
        return "restrictive", "Restrictive"
    if index_value <= 65:
        return "balanced", "Balanced"
    return "supportive", "Supportive"


def classify_liquidity_regime(
    index_value: float, direction: str, funding_state: str
) -> dict[str, object]:
    """Keep the numerical index state separate from an absolute funding alert."""

    state_code, state = _classify_liquidity_state(index_value)
    return {
        "state_code": state_code,
        "state": state,
        "regime": f"{state}, {direction.lower()}",
        "funding_stress_veto": funding_state == "Stressed",
    }


def classify_absolute_funding(
    sofr_iorb_bp: float,
    tgcr_iorb_bp: float,
    bgcr_iorb_bp: float,
    effr_iorb_bp: float,
    sofr_iqr_bp: float,
    repo_add_bn: float,
) -> str:
    values = (
        sofr_iorb_bp,
        tgcr_iorb_bp,
        bgcr_iorb_bp,
        effr_iorb_bp,
        sofr_iqr_bp,
        repo_add_bn,
    )
    if not all(isfinite(float(value)) for value in values):
        return "Unavailable"
    if float(sofr_iqr_bp) < 0 or float(repo_add_bn) < 0:
        return "Unavailable"
    maximum_spread = max(
        float(sofr_iorb_bp),
        float(tgcr_iorb_bp),
        float(bgcr_iorb_bp),
        float(effr_iorb_bp),
    )
    if maximum_spread > 10 or float(sofr_iqr_bp) >= 20 or float(repo_add_bn) >= 20:
        return "Stressed"
    if maximum_spread > 5 or float(sofr_iqr_bp) >= 10 or float(repo_add_bn) >= 1:
        return "Pressured"
    return "Orderly"


def _layer_state(value: float, threshold: float = 0.35) -> str:
    if value > threshold:
        return "Supportive"
    if value < -threshold:
        return "Restrictive"
    return "Neutral"


def build_us_liquidity_model(snapshot: LiveLiquiditySnapshot) -> USLiquidityResult:
    release_calendars = load_federal_reserve_release_calendars(snapshot.root)
    reserves_observed = _fred(
        snapshot, "WRBWFRBL", field="reserves_bn", scale=0.001
    )
    reserves = apply_federal_reserve_release_availability(
        reserves_observed, "h41", release_calendars["h41"]
    )
    fed_assets = apply_federal_reserve_release_availability(
        _fred(snapshot, "WALCL", field="assets_bn", scale=0.001),
        "h41",
        release_calendars["h41"],
    )
    h8 = {
        "deposits_bn": "DPSACBW027SBOG",
        "bank_assets_bn": "TLAACBW027SBOG",
        "bank_cash_bn": "CASACBW027SBOG",
        "large_bank_assets_bn": "TLALCBW027SBOG",
        "large_bank_cash_bn": "CASLCBW027SBOG",
        "small_bank_assets_bn": "TLASCBW027SBOG",
        "small_bank_cash_bn": "CASSCBW027SBOG",
        "bank_credit_bn": "TOTBKCR",
    }
    h8_observed = {
        field: _fred(snapshot, series_id, field=field)
        for field, series_id in h8.items()
    }
    h8_series = {
        field: apply_federal_reserve_release_availability(
            series, "h8", release_calendars["h8"]
        )
        for field, series in h8_observed.items()
    }
    admin = _administered_rate(snapshot)
    effr = _fred(snapshot, "EFFR", field="effr")
    rates = {
        name: _nyfed_rate(snapshot, name, name)
        for name in ("sofr", "tgcr", "bgcr")
    }
    rate_available = {
        name: _reference_rate_publication_availability(
            frame, GOVERNMENT_SECURITIES_DAY
        )
        for name, frame in rates.items()
    }
    repo_add = _fred(snapshot, "RPONTTLD", field="repo_add_bn")
    fedwire_observed = _fedwire_monthly(snapshot)
    fedwire = _availability_lag(fedwire_observed, 25)

    start = pd.Timestamp("2018-04-06")
    end = _completed_weekly_model_date(snapshot)
    dates = pd.date_range(start=start, end=end, freq="W-FRI")
    if len(dates) < 200:
        raise ValueError("U.S. liquidity history is too short for robust calibration")

    history = pd.DataFrame(index=dates)
    history.index.name = "date"
    history["reserves_bn"] = _asof(reserves, dates)
    history["fed_assets_bn"] = _asof(fed_assets, dates)
    for field, series in h8_series.items():
        history[field] = _asof(series, dates)
    history["fedwire_daily_value_bn"] = _asof(fedwire, dates)
    history["repo_add_bn"] = _asof(repo_add, dates)

    reserve_assets_observed = _safe_positive_ratio(
        _asof(reserves_observed, h8_observed["bank_assets_bn"].index),
        h8_observed["bank_assets_bn"],
        label="Reserves relative to bank assets",
        multiplier=100,
    )
    reserve_deposits_observed = _safe_positive_ratio(
        _asof(reserves_observed, h8_observed["deposits_bn"].index),
        h8_observed["deposits_bn"],
        label="Reserves relative to deposits",
        multiplier=100,
    )
    reserve_fedwire_observed = _safe_positive_ratio(
        _asof(reserves_observed, fedwire_observed.index),
        fedwire_observed,
        label="Reserves relative to Fedwire payments",
    )
    history["reserve_assets_pct"] = _asof(
        apply_federal_reserve_release_availability(
            reserve_assets_observed, "h8", release_calendars["h8"]
        ),
        dates,
    )
    history["reserve_deposit_pct"] = _asof(
        apply_federal_reserve_release_availability(
            reserve_deposits_observed, "h8", release_calendars["h8"]
        ),
        dates,
    )
    history["reserve_fedwire_ratio"] = _asof(
        _availability_lag(reserve_fedwire_observed, 25), dates
    )
    history["bank_cash_assets_pct"] = _safe_positive_ratio(
        history["bank_cash_bn"],
        history["bank_assets_bn"],
        label="Aggregate bank cash relative to bank assets",
        multiplier=100,
    )
    history["large_bank_cash_assets_pct"] = _safe_positive_ratio(
        history["large_bank_cash_bn"],
        history["large_bank_assets_bn"],
        label="Large-bank cash relative to assets",
        multiplier=100,
    )
    history["small_bank_cash_assets_pct"] = _safe_positive_ratio(
        history["small_bank_cash_bn"],
        history["small_bank_assets_bn"],
        label="Small-bank cash relative to assets",
        multiplier=100,
    )
    history["distribution_floor_pct"] = history[
        ["large_bank_cash_assets_pct", "small_bank_cash_assets_pct"]
    ].min(axis=1, skipna=False)

    history["reserve_impulse_4w_bp"] = _safe_positive_ratio(
        history["reserves_bn"].diff(4),
        history["fed_assets_bn"].shift(4),
        label="Four-week reserve impulse",
        multiplier=10_000,
    )
    history["reserve_impulse_13w_bp"] = _safe_positive_ratio(
        history["reserves_bn"].diff(13),
        history["fed_assets_bn"].shift(13),
        label="Thirteen-week reserve impulse",
        multiplier=10_000,
    )
    history["bank_credit_change_13w_pct"] = (
        _safe_positive_ratio(
            history["bank_credit_bn"],
            history["bank_credit_bn"].shift(13),
            label="Thirteen-week bank-credit growth",
        )
        .sub(1.0)
        .mul(100)
    )

    for name in rate_available:
        effective_frame = rates[name]
        effective_admin = _asof(admin, effective_frame.index)
        available_spread = (effective_frame["rate"] - effective_admin) * 100
        available_spread = _reference_rate_publication_availability(
            available_spread, GOVERNMENT_SECURITIES_DAY
        )
        history[f"{name}_iorb_bp"] = _asof(available_spread, dates)
    effr_admin = _asof(admin, effr.index)
    effr_spread = (effr - effr_admin) * 100
    effr_spread = _reference_rate_publication_availability(
        effr_spread, FEDERAL_RESERVE_DAY
    )
    history["effr_iorb_bp"] = _asof(effr_spread, dates)
    history["sofr_iqr_bp"] = (
        _asof(rate_available["sofr"]["p75"], dates)
        - _asof(rate_available["sofr"]["p25"], dates)
    ) * 100

    for column in (
        "reserve_assets_pct",
        "reserve_deposit_pct",
        "reserve_fedwire_ratio",
        "bank_cash_assets_pct",
        "distribution_floor_pct",
    ):
        history[f"{column}_z"] = lagged_robust_z(history[column])
    history["reserve_sufficiency_measurement_z"] = history[
        [
            "reserve_assets_pct_z",
            "reserve_deposit_pct_z",
            "reserve_fedwire_ratio_z",
        ]
    ].median(axis=1, skipna=False)
    history["bank_buffer_measurement_z"] = history[
        ["bank_cash_assets_pct_z", "distribution_floor_pct_z"]
    ].mean(axis=1, skipna=False)
    history["reserve_capacity_measurement_z"] = (
        0.70 * history["reserve_sufficiency_measurement_z"]
        + 0.30 * history["bank_buffer_measurement_z"]
    )
    history["reserve_capacity_z"] = _smooth(
        history["reserve_capacity_measurement_z"], 8
    )

    funding_score_columns: dict[str, str] = {}
    for column in ("sofr_iorb_bp", "tgcr_iorb_bp", "bgcr_iorb_bp", "effr_iorb_bp"):
        score_column = f"{column}_support_score"
        # Absolute spreads carry the economic meaning. A zero spread is orderly,
        # a positive spread is pressure, and a modest negative spread is support.
        # This avoids labeling a normal zero spread as stressed merely because an
        # earlier sample happened to trade below IORB.
        history[score_column] = (-history[column] / 5.0).clip(-3.0, 1.0)
        funding_score_columns[column] = score_column
    history["sofr_dispersion_support_score"] = (
        (5.0 - history["sofr_iqr_bp"]) / 10.0
    ).clip(-3.0, 0.5)
    # SOFR is the representative secured rate and already incorporates the
    # BGCR markets plus FICC DVP activity. TGCR and BGCR remain diagnostics, but
    # including all three in the index would triple-count closely nested repo
    # markets. EFFR adds an unsecured transmission channel and the IQR adds a
    # distribution measure. Absolute funding thresholds remain a separate veto.
    history["funding_measurement_score"] = (
        0.40 * history[funding_score_columns["sofr_iorb_bp"]]
        + 0.40 * history[funding_score_columns["effr_iorb_bp"]]
        + 0.20 * history["sofr_dispersion_support_score"]
    )
    history["funding_support_score"] = _smooth(
        history["funding_measurement_score"], 4
    )

    history["reserve_impulse_4w_z"] = lagged_robust_z(history["reserve_impulse_4w_bp"])
    history["reserve_impulse_13w_z"] = lagged_robust_z(history["reserve_impulse_13w_bp"])
    history["reserve_impulse_measurement_z"] = (
        0.60 * history["reserve_impulse_4w_z"]
        + 0.40 * history["reserve_impulse_13w_z"]
    )
    history["reserve_impulse_z"] = _smooth(history["reserve_impulse_measurement_z"], 3)

    history["bank_credit_measurement_z"] = lagged_robust_z(
        history["bank_credit_change_13w_pct"]
    )
    history["bank_credit_z"] = _smooth(history["bank_credit_measurement_z"], 8)

    history["expected_reserve_impulse_4w_bp"] = _prior_seasonal_expectation(
        history["reserve_impulse_4w_bp"]
    )
    history["mechanical_deviation_bp"] = (
        history["reserve_impulse_4w_bp"]
        - history["expected_reserve_impulse_4w_bp"]
    )
    history["mechanical_deviation_measurement_z"] = lagged_robust_z(
        history["mechanical_deviation_bp"], min_periods=52
    )
    history["mechanical_deviation_z"] = _smooth(
        history["mechanical_deviation_measurement_z"], 3
    )

    _require_latest_finite(
        history,
        [
            "reserve_assets_pct",
            "reserve_deposit_pct",
            "reserve_fedwire_ratio",
            "bank_cash_assets_pct",
            "large_bank_cash_assets_pct",
            "small_bank_cash_assets_pct",
            "distribution_floor_pct",
            "sofr_iorb_bp",
            "tgcr_iorb_bp",
            "bgcr_iorb_bp",
            "effr_iorb_bp",
            "sofr_iqr_bp",
            "repo_add_bn",
            "reserve_impulse_4w_bp",
            "reserve_impulse_13w_bp",
            "bank_credit_change_13w_pct",
            "reserve_capacity_measurement_z",
            "funding_measurement_score",
            "reserve_impulse_measurement_z",
            "bank_credit_measurement_z",
            "mechanical_deviation_measurement_z",
        ],
        date=end,
        stage="input set",
    )

    history["liquidity_score_raw"] = sum(
        LIQUIDITY_LAYER_WEIGHTS[key] * history[column]
        for key, column in (
            ("reserve_capacity", "reserve_capacity_z"),
            ("funding_support", "funding_support_score"),
            ("reserve_impulse", "reserve_impulse_z"),
            ("bank_credit", "bank_credit_z"),
        )
    )
    history["liquidity_score"] = _smooth(history["liquidity_score_raw"], 4)
    history["liquidity_conditions_index"] = _index_from_z(history["liquidity_score"])
    history["liquidity_raw_index"] = _index_from_z(history["liquidity_score_raw"])
    history["liquidity_percentile"] = percentile_against_prior(
        history["liquidity_score"], min_periods=52
    )
    history["liquidity_change_4w"] = history["liquidity_score"].diff(4)
    history["direction_band"] = (
        history["liquidity_change_4w"]
        .abs()
        .rolling(260, min_periods=52)
        .quantile(0.50)
        .shift(1)
    )

    _require_latest_finite(
        history,
        [
            "reserve_capacity_z",
            "funding_support_score",
            "reserve_impulse_z",
            "bank_credit_z",
            "liquidity_score_raw",
            "liquidity_score",
            "liquidity_conditions_index",
            "liquidity_percentile",
            "liquidity_change_4w",
            "direction_band",
        ],
        date=end,
        stage="current output",
    )

    required = [
        "liquidity_score",
        "liquidity_conditions_index",
        "liquidity_percentile",
        "liquidity_change_4w",
        "direction_band",
    ]
    valid = history.dropna(subset=required)
    if valid.empty:
        raise ValueError("U.S. liquidity model has no fully calibrated observation")
    if valid.index[-1] != end:
        raise ValueError("U.S. liquidity model did not produce the current completed week")
    row = valid.iloc[-1]
    direction = _classify_direction(
        float(row["liquidity_change_4w"]), float(row["direction_band"])
    )
    funding_state = classify_absolute_funding(
        float(row["sofr_iorb_bp"]),
        float(row["tgcr_iorb_bp"]),
        float(row["bgcr_iorb_bp"]),
        float(row["effr_iorb_bp"]),
        float(row["sofr_iqr_bp"]),
        float(row["repo_add_bn"]),
    )
    if funding_state == "Unavailable":
        raise ValueError("U.S. liquidity funding state has invalid current inputs")
    regime_metadata = classify_liquidity_regime(
        float(row["liquidity_conditions_index"]), direction, funding_state
    )

    accepted = {"CURRENT_UPDATED", "CURRENT_UNCHANGED", "CURRENT_PUBLICATION_LAG"}
    source_status = snapshot.sources.set_index("field")["status"].astype(str)
    complete = CORE_SOURCE_FIELDS.issubset(source_status.index)
    current_sources = complete and source_status.reindex(sorted(CORE_SOURCE_FIELDS)).isin(accepted).all()
    source_coverage = "Complete" if current_sources else "Incomplete"

    layer_spec = (
        ("Structural reserve capacity", "reserve_capacity", "reserve_capacity_z", "Eight-week filtered state score"),
        ("Overnight funding support", "funding_support", "funding_support_score", "SOFR and EFFR support plus SOFR dispersion"),
        ("Realized reserve impulse", "reserve_impulse", "reserve_impulse_z", "Four-week and thirteen-week reserve flow"),
        ("Bank credit creation", "bank_credit", "bank_credit_z", "Thirteen-week H.8 bank-credit growth"),
    )
    layers = pd.DataFrame(
        [
            {
                "layer": label,
                "key": key,
                "score": float(row[column]),
                "weight": LIQUIDITY_LAYER_WEIGHTS[key],
                "weighted_contribution": float(row[column]) * LIQUIDITY_LAYER_WEIGHTS[key],
                "state": _layer_state(float(row[column])),
                "method": method,
            }
            for label, key, column, method in layer_spec
        ]
    )
    capacity_components = pd.DataFrame(
        [
            ("Reserves relative to bank assets", row["reserve_assets_pct_z"], row["reserve_assets_pct"], "%"),
            ("Reserves relative to deposits", row["reserve_deposit_pct_z"], row["reserve_deposit_pct"], "%"),
            ("Reserves relative to Fedwire payments", row["reserve_fedwire_ratio_z"], row["reserve_fedwire_ratio"], "x"),
            ("Aggregate bank cash buffer", row["bank_cash_assets_pct_z"], row["bank_cash_assets_pct"], "%"),
            ("Lower large-bank or small-bank aggregate cash ratio", row["distribution_floor_pct_z"], row["distribution_floor_pct"], "%"),
        ],
        columns=["component", "score_z", "raw_value", "unit"],
    )
    funding_components = pd.DataFrame(
        [
            ("SOFR minus IORB", row["sofr_iorb_bp"], row["sofr_iorb_bp_support_score"], "Index input"),
            ("TGCR minus IORB", row["tgcr_iorb_bp"], row["tgcr_iorb_bp_support_score"], "Diagnostic only"),
            ("BGCR minus IORB", row["bgcr_iorb_bp"], row["bgcr_iorb_bp_support_score"], "Diagnostic only"),
            ("EFFR minus IORB", row["effr_iorb_bp"], row["effr_iorb_bp_support_score"], "Index input"),
            ("SOFR interquartile range", row["sofr_iqr_bp"], row["sofr_dispersion_support_score"], "Index input"),
        ],
        columns=["component", "raw_bp", "support_score", "index_role"],
    )
    deviation_z = float(row["mechanical_deviation_z"])
    if deviation_z > 0.75:
        deviation_state = "More supportive than seasonal norm"
    elif deviation_z < -0.75:
        deviation_state = "More restrictive than seasonal norm"
    else:
        deviation_state = "Near seasonal norm"
    current: dict[str, object] = {
        "date": valid.index[-1],
        "state_code": regime_metadata["state_code"],
        "state": regime_metadata["state"],
        "direction": direction,
        "regime": regime_metadata["regime"],
        "funding_stress_veto": regime_metadata["funding_stress_veto"],
        "score": float(row["liquidity_score"]),
        "index": float(row["liquidity_conditions_index"]),
        "percentile": float(row["liquidity_percentile"]),
        "change_4w": float(row["liquidity_change_4w"]),
        "direction_band": float(row["direction_band"]),
        "funding_state": funding_state,
        "reserve_capacity_state": _layer_state(float(row["reserve_capacity_z"])),
        "reserve_impulse_state": _layer_state(float(row["reserve_impulse_z"])),
        "bank_credit_state": _layer_state(float(row["bank_credit_z"])),
        "mechanical_deviation_state": deviation_state,
        "source_coverage": source_coverage,
        "calibration_start": valid.index[0],
        "calibration_observations": int(len(valid)),
        "percentile_reference_observations": int(
            history.loc[history.index < valid.index[-1], "liquidity_score"]
            .tail(260)
            .notna()
            .sum()
        ),
        "weights": dict(LIQUIDITY_LAYER_WEIGHTS),
    }
    return USLiquidityResult(
        history=history,
        current=current,
        layers=layers,
        capacity_components=capacity_components,
        funding_components=funding_components,
    )


def liquidity_layers_figure(result: USLiquidityResult) -> go.Figure:
    frame = result.layers.copy()
    display_labels = {
        "Structural reserve capacity": "Reserve capacity · 35%",
        "Overnight funding support": "Funding conditions · 25%",
        "Realized reserve impulse": "Reserve flow · 30%",
        "Bank credit creation": "Bank credit growth · 10%",
    }
    frame["display_layer"] = frame["layer"].replace(display_labels)
    colors = [
        CHART_POSITIVE if value >= 0 else CHART_NEGATIVE
        for value in frame["weighted_contribution"]
    ]
    hover_data = np.column_stack(
        [
            [format_normalized(value, signed=True) for value in frame["weighted_contribution"]],
            [format_normalized(value, signed=True) for value in frame["score"]],
            [f"{float(value):.0%}" for value in frame["weight"]],
            frame["state"].astype(str),
            frame["method"].astype(str),
        ]
    )
    # Preserve space between long category labels and negative endpoint values
    # when the chart is rendered at narrow widths.
    maximum = max(1.3, float(frame["weighted_contribution"].abs().max()) * 1.5)
    figure = go.Figure()
    for (_, row), color, hover_row in zip(
        frame.iterrows(), colors, hover_data, strict=True
    ):
        value = float(row["weighted_contribution"])
        label = str(row["display_layer"])
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
                marker={
                    "color": color,
                    "size": 9,
                    "line": {"color": "#FFFFFF", "width": 1.5},
                },
                text=[f"{value:+.2f}".replace("-", "−")],
                textposition="top center",
                textfont={"family": CHART_FONT, "size": 11, "color": CHART_INK},
                cliponaxis=False,
                customdata=[hover_row],
                hovertemplate=(
                    "%{y}<br>Weighted contribution: %{customdata[0]}"
                    "<br>Layer score: %{customdata[1]} standardized"
                    "<br>Model weight: %{customdata[2]}"
                    "<br>State: %{customdata[3]}"
                    "<br>%{customdata[4]}<extra></extra>"
                ),
                showlegend=False,
            )
        )
    figure.add_vline(x=0, line={"color": CHART_NAVY, "width": 1.25})
    figure.update_layout(
        height=270,
        margin={"l": 18, "r": 38, "t": 20, "b": 34},
        paper_bgcolor="#ffffff",
        plot_bgcolor="#ffffff",
        font={"family": CHART_FONT, "color": CHART_INK, "size": 11},
        showlegend=False,
        xaxis={"title": None, "range": [-maximum, maximum], "gridcolor": CHART_GRID, "zeroline": False, "tickfont": {"color": CHART_MUTED}},
        yaxis={"title": None, "showgrid": False, "automargin": True},
    )
    return figure


def liquidity_regime_map_figure(result: USLiquidityResult) -> go.Figure:
    """Show the current level and model-classified four-week trend together."""

    current_index = float(result.current["index"])
    current_change = float(result.current["change_4w"])
    band = float(result.current["direction_band"])
    direction = str(result.current["direction"])
    level = str(result.current["state"])
    y_extent = max(0.75, abs(current_change) * 1.8, band * 3.0)
    figure = go.Figure()
    for lower, upper, color in (
        (0, 35, "#FEF1F1"),
        (35, 65, "#F4F6F8"),
        (65, 100, "#EAF7F2"),
    ):
        figure.add_vrect(x0=lower, x1=upper, fillcolor=color, line_width=0, layer="below")
    figure.add_hrect(
        y0=-band,
        y1=band,
        fillcolor="rgba(100,116,139,0.10)",
        line_width=0,
        layer="below",
    )
    figure.add_vline(x=35, line={"color": "#CBD5E1", "width": 1, "dash": "dot"})
    figure.add_vline(x=65, line={"color": "#CBD5E1", "width": 1, "dash": "dot"})
    figure.add_hline(y=band, line={"color": "#CBD5E1", "width": 1, "dash": "dot"})
    figure.add_hline(y=-band, line={"color": "#CBD5E1", "width": 1, "dash": "dot"})
    figure.add_trace(
        go.Scatter(
            x=[current_index],
            y=[current_change],
            mode="markers",
            marker={"color": CHART_NAVY, "size": 15, "line": {"color": "#FFFFFF", "width": 3}},
            customdata=[[level, direction, f"{current_change:+.2f}".replace("-", "−")]],
            hovertemplate=(
                "Liquidity index: %{x:.1f}<br>Level: %{customdata[0]}"
                "<br>Four-week trend: %{customdata[1]}"
                "<br>Standardized change: %{customdata[2]}<extra></extra>"
            ),
            showlegend=False,
            cliponaxis=False,
        )
    )
    figure.update_layout(
        height=270,
        margin={"l": 76, "r": 18, "t": 22, "b": 42},
        paper_bgcolor="#FFFFFF",
        plot_bgcolor="#FFFFFF",
        font={"family": CHART_FONT, "color": CHART_INK, "size": 11},
        hovermode="closest",
        xaxis={
            "title": "Liquidity level (0 to 100)",
            "range": [0, 100],
            "tickvals": [0, 20, 35, 50, 65, 80, 100],
            "gridcolor": CHART_GRID,
            "zeroline": False,
        },
        yaxis={
            "title": "Four-week change (standardized)",
            "range": [-y_extent, y_extent],
            "tickvals": [-band * 1.6, 0, band * 1.6],
            "ticktext": ["Deteriorating", "Stable", "Improving"],
            "gridcolor": CHART_GRID,
            "zeroline": False,
        },
    )
    return figure


def liquidity_conditions_history_figure(
    result: USLiquidityResult, years: int | None = 5
) -> go.Figure:
    frame = result.history.dropna(subset=["liquidity_conditions_index"]).copy()
    if years is not None and not frame.empty:
        frame = frame.loc[frame.index >= frame.index.max() - pd.DateOffset(years=years)]
    figure = go.Figure()
    figure.add_hrect(y0=0, y1=35, fillcolor="#FEF1F1", line_width=0, layer="below")
    figure.add_hrect(y0=35, y1=65, fillcolor="#F4F6F8", line_width=0, layer="below")
    figure.add_hrect(y0=65, y1=100, fillcolor="#EAF7F2", line_width=0, layer="below")
    figure.add_trace(
        go.Scatter(
            x=frame.index,
            y=frame["liquidity_raw_index"],
            mode="lines",
            name="Weekly model estimate",
            line={"color": "#A8B4C3", "width": 1.2},
            opacity=0.72,
            customdata=[f"{value:.0f}" for value in frame["liquidity_raw_index"]],
            hovertemplate="Weekly model estimate<br>%{x|%d %b %Y}<br>%{customdata}<extra></extra>",
        )
    )
    figure.add_trace(
        go.Scatter(
            x=frame.index,
            y=frame["liquidity_conditions_index"],
            mode="lines",
            name="Filtered liquidity index",
            line={"color": CHART_NAVY, "width": 3},
            customdata=[f"{value:.0f}" for value in frame["liquidity_conditions_index"]],
            hovertemplate="Filtered index<br>%{x|%d %b %Y}<br>%{customdata}<extra></extra>",
        )
    )
    if not frame.empty:
        current = float(frame["liquidity_conditions_index"].iloc[-1])
        prior = float(frame["liquidity_conditions_index"].iloc[-5]) if len(frame) >= 5 else current
        prior_date = frame.index[-5] if len(frame) >= 5 else frame.index[-1]
        figure.add_trace(
            go.Scatter(
                x=[prior_date, frame.index[-1]],
                y=[prior, current],
                mode="lines+markers",
                line={"color": PRODUCT["blue"], "width": 3.5},
                marker={
                    "color": ["#FFFFFF", CHART_NAVY],
                    "size": [7, 10],
                    "line": {"color": CHART_NAVY, "width": 2},
                },
                name="Latest four weeks",
                hoverinfo="skip",
                showlegend=False,
            )
        )
        figure.add_trace(
            go.Scatter(
                x=[frame.index[-1]],
                y=[current],
                mode="markers",
                name="Current",
                marker={"color": CHART_NAVY, "size": 10, "line": {"color": "#FFFFFF", "width": 2}},
                customdata=[f"{current:.1f}"],
                hovertemplate="Current index: %{customdata}<extra></extra>",
                showlegend=False,
            )
        )
    figure.add_hline(y=35, line={"color": "#A8B4C3", "width": 1, "dash": "dot"})
    figure.add_hline(y=65, line={"color": "#A8B4C3", "width": 1, "dash": "dot"})
    for label, y_value in (("Restrictive", 17.5), ("Balanced", 50.0), ("Supportive", 82.5)):
        figure.add_annotation(
            x=0.995,
            y=y_value,
            xref="paper",
            yref="y",
            text=label,
            showarrow=False,
            xanchor="right",
            font={"family": CHART_FONT, "size": 11, "color": CHART_MUTED},
        )
    figure.update_layout(
        height=315,
        margin={"l": 54, "r": 20, "t": 26, "b": 38},
        paper_bgcolor="#ffffff",
        plot_bgcolor="#ffffff",
        font={"family": CHART_FONT, "color": CHART_INK, "size": 11},
        showlegend=False,
        hovermode="x unified",
        xaxis={"title": None, "showgrid": False, "linecolor": "#CBD5E1", "tickfont": {"color": CHART_MUTED}},
        yaxis={"title": "Liquidity Conditions Index", "range": [0, 100], "tickvals": [0, 20, 35, 50, 65, 80, 100], "gridcolor": CHART_GRID, "zeroline": False, "tickfont": {"color": CHART_MUTED}},
    )
    return figure


def funding_market_figure(result: USLiquidityResult, years: int | None = 3) -> go.Figure:
    columns = ["sofr_iorb_bp", "tgcr_iorb_bp", "bgcr_iorb_bp", "effr_iorb_bp"]
    frame = result.history[columns].dropna(how="all").copy()
    if years is not None and not frame.empty:
        frame = frame.loc[frame.index >= frame.index.max() - pd.DateOffset(years=years)]
    secured = frame[["sofr_iorb_bp", "tgcr_iorb_bp", "bgcr_iorb_bp"]]
    frame["secured_low"] = secured.min(axis=1)
    frame["secured_high"] = secured.max(axis=1)
    figure = go.Figure()
    figure.add_trace(
        go.Scatter(
            x=frame.index,
            y=frame["secured_low"],
            mode="lines",
            line={"color": "rgba(62,108,136,0)", "width": 0},
            hoverinfo="skip",
            showlegend=False,
        )
    )
    figure.add_trace(
        go.Scatter(
            x=frame.index,
            y=frame["secured_high"],
            mode="lines",
            name="Secured funding range",
            line={"color": "rgba(62,108,136,0)", "width": 0},
            fill="tonexty",
            fillcolor="rgba(62,108,136,0.16)",
            hoverinfo="skip",
        )
    )
    hover_data = np.column_stack(
        [
            [format_basis_points(value, signed=True) for value in frame["tgcr_iorb_bp"]],
            [format_basis_points(value, signed=True) for value in frame["bgcr_iorb_bp"]],
            [format_basis_points(value, signed=True) for value in frame["secured_low"]],
            [format_basis_points(value, signed=True) for value in frame["secured_high"]],
        ]
    )
    figure.add_trace(
        go.Scatter(
            x=frame.index,
            y=frame["sofr_iorb_bp"],
            mode="lines",
            name="SOFR spread to IORB",
            line={"color": CHART_NAVY, "width": 2.6},
            customdata=hover_data,
            hovertemplate=(
                "SOFR: %{y:+.1f} bp<br>TGCR: %{customdata[0]}"
                "<br>BGCR: %{customdata[1]}<br>Secured range: "
                "%{customdata[2]} to %{customdata[3]}<extra></extra>"
            ),
        )
    )
    figure.add_trace(
        go.Scatter(
            x=frame.index,
            y=frame["effr_iorb_bp"],
            mode="lines",
            name="EFFR spread to IORB",
            line={"color": CHART_MUTED, "width": 2, "dash": "dash"},
            customdata=[format_basis_points(value, signed=True) for value in frame["effr_iorb_bp"]],
            hovertemplate="EFFR: %{customdata}<extra></extra>",
        )
    )
    figure.add_hline(y=0, line={"color": CHART_NAVY, "width": 1})
    figure.add_hline(y=5, line={"color": PRODUCT["amber"], "width": 1, "dash": "dot"})
    figure.add_hline(y=10, line={"color": CHART_NEGATIVE, "width": 1, "dash": "dot"})
    figure.update_layout(
        height=315,
        margin={"l": 54, "r": 22, "t": 52, "b": 38},
        paper_bgcolor="#ffffff",
        plot_bgcolor="#ffffff",
        font={"family": CHART_FONT, "color": CHART_INK, "size": 11},
        legend={"orientation": "h", "x": 0, "y": 1.18, "xanchor": "left", "yanchor": "top", "font": {"size": 11}},
        hovermode="x unified",
        xaxis={"title": None, "showgrid": False, "linecolor": "#CBD5E1", "tickfont": {"color": CHART_MUTED}},
        yaxis={"title": "Spread to IORB (bp)", "gridcolor": CHART_GRID, "zeroline": False, "tickfont": {"color": CHART_MUTED}},
    )
    return figure


def liquidity_deviation_figure(result: USLiquidityResult, years: int | None = 5) -> go.Figure:
    frame = result.history[["reserve_impulse_4w_bp", "expected_reserve_impulse_4w_bp", "mechanical_deviation_bp"]].dropna().copy()
    if years is not None and not frame.empty:
        frame = frame.loc[frame.index >= frame.index.max() - pd.DateOffset(years=years)]
    colors = [CHART_POSITIVE if value >= 0 else CHART_NEGATIVE for value in frame["mechanical_deviation_bp"]]
    figure = go.Figure()
    custom = np.column_stack(
        [
            [format_basis_points(value, signed=True) for value in frame["reserve_impulse_4w_bp"]],
            [format_basis_points(value, signed=True) for value in frame["expected_reserve_impulse_4w_bp"]],
            [format_basis_points(value, signed=True) for value in frame["mechanical_deviation_bp"]],
        ]
    )
    figure.add_trace(
        go.Bar(
            x=frame.index,
            y=frame["mechanical_deviation_bp"],
            name="Deviation from seasonal pattern",
            marker={"color": colors},
            customdata=custom,
            hovertemplate=(
                "%{x|%d %b %Y}<br>Reserve flow: %{customdata[0]}"
                "<br>Seasonal median: %{customdata[1]}"
                "<br>Deviation: %{customdata[2]}<extra></extra>"
            ),
        )
    )
    if not frame.empty:
        figure.add_trace(
            go.Scatter(
                x=[frame.index[-1]],
                y=[frame["mechanical_deviation_bp"].iloc[-1]],
                mode="markers",
                marker={"color": CHART_NAVY, "size": 9, "line": {"color": "#FFFFFF", "width": 2}},
                customdata=[format_basis_points(frame["mechanical_deviation_bp"].iloc[-1], signed=True)],
                hovertemplate="Latest deviation: %{customdata}<extra></extra>",
                showlegend=False,
            )
        )
    figure.add_hline(y=0, line={"color": CHART_NAVY, "width": 1})
    figure.update_layout(
        height=260,
        margin={"l": 54, "r": 20, "t": 24, "b": 38},
        paper_bgcolor="#ffffff",
        plot_bgcolor="#ffffff",
        font={"family": CHART_FONT, "color": CHART_INK, "size": 11},
        showlegend=False,
        hovermode="x unified",
        xaxis={"title": None, "showgrid": False, "linecolor": "#CBD5E1", "tickfont": {"color": CHART_MUTED}},
        yaxis={"title": "Difference from seasonal median (bp)", "gridcolor": CHART_GRID, "zeroline": False, "tickfont": {"color": CHART_MUTED}},
    )
    return figure
