"""Hash-verified current-observation overlay for the liquidity monitor.

The predictive research release is intentionally immutable.  This module loads
an independently refreshed operating snapshot so current observations can be
shown without pretending that the frozen model was rerun or revalidated.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from pandas.tseries.holiday import (
    AbstractHolidayCalendar,
    GoodFriday,
    Holiday,
    USColumbusDay,
    USFederalHolidayCalendar,
    USLaborDay,
    USMartinLutherKingJr,
    USMemorialDay,
    USPresidentsDay,
    USThanksgivingDay,
    nearest_workday,
    sunday_to_monday,
)
from pandas.tseries.offsets import CustomBusinessDay

EXPECTED_RAW_FILES = {
    "fred_BAA10Y.csv", "fred_BAMLC0A0CM.csv", "fred_BAMLH0A0HYM2.csv",
    "fred_DFII10.csv", "fred_DPSACBW027SBOG.csv", "fred_DTWEXBGS.csv",
    "fred_EFFR.csv", "fred_IORB.csv", "fred_RRPONTSYD.csv", "fred_VIXCLS.csv",
    "fred_WALCL.csv", "fred_WCURCIR.csv", "fred_WDTGAL.csv", "fred_WRBWFRBL.csv",
    "market_adjusted_close.csv", "nyfed_sofr.json", "treasury_tga.json",
    "fred_CASACBW027SBOG.csv", "fred_CASLCBW027SBOG.csv", "fred_CASSCBW027SBOG.csv",
    "fred_IOER.csv", "fred_RPONTTLD.csv", "fred_TLAACBW027SBOG.csv",
    "fred_TLALCBW027SBOG.csv", "fred_TLASCBW027SBOG.csv", "fred_TOTBKCR.csv",
    "nyfed_tgcr.json", "nyfed_bgcr.json", "fedwire_monthly.html", "fedwire_monthly.txt",
    "federalreserve_h41_release_dates.json",
    "federalreserve_h8_release_dates.json",
    "federalreserve_h10_release_dates.json",
}
EXPECTED_STATE_COLUMNS = {
    "as_of_date", "retrieved_at_utc", "accounting_asof_date", "market_asof_date",
    "spy_adj_close", "spy_mom60", "spy_dist200", "sector_breadth50",
    "sector_breadth50_change20", "reserve_impulse_4w_bp", "reserve_impulse_13w_bp",
    "tga_change_4w_bp_assets", "onrrp_change_4w_bp_assets", "fed_asset_change_4w_bp",
    "currency_change_4w_bp_assets", "accounting_known_impulse_4w_bp",
    "other_liability_residual_4w_bp", "baa10y", "vix", "reserves_bn", "assets_bn",
    "tga_h41_bn", "tga_dts_bn", "onrrp_bn", "currency_bn", "sofr", "iorb", "sofr_admin_bp",
    "deposits_bn", "reserve_deposit_pct", "effr", "effr_admin_bp", "hy_oas",
    "ig_oas", "broad_usd", "real_yield_10y",
    "bank_assets_bn", "bank_cash_bn", "large_bank_assets_bn", "large_bank_cash_bn",
    "small_bank_assets_bn", "small_bank_cash_bn", "bank_credit_bn",
    "fedwire_daily_value_bn", "tgcr", "tgcr_admin_bp", "bgcr", "bgcr_admin_bp",
    "sofr_iqr_bp", "repo_add_bn",
}
EXPECTED_MODEL_WEIGHTS = {
    "reserve_capacity": 0.35,
    "funding_support": 0.25,
    "reserve_impulse": 0.30,
    "bank_credit": 0.10,
}
MODEL_IMPLEMENTATION_FILES = (
    "liquidity_monitor/liquidity_live_snapshot.py",
    "liquidity_monitor/structural_liquidity.py",
    "liquidity_monitor/us_liquidity_model.py",
)

# The Board's H.8 archive routes the December 18, 2020 release through a
# directory and release-calendar token dated December 21.  The release page
# itself identifies December 18 at 4:15 p.m. ET as the public release time.
# Normalize that one documented archive-routing exception before point-in-time
# availability is calculated.  Keep the downloaded JSON unchanged in the raw
# evidence package so the transformation remains auditable.
FEDERAL_RESERVE_RELEASE_DATE_OVERRIDES = {
    "h8": {
        pd.Timestamp("2020-12-21"): pd.Timestamp("2020-12-18"),
    }
}
CURRENT_SOURCE_STATUSES = frozenset(
    {"CURRENT_UPDATED", "CURRENT_UNCHANGED", "CURRENT_PUBLICATION_LAG"}
)

# The New York Fed schedules the ON RRP operation for 12:45-1:15 p.m. ET and
# publishes results after the operation completes.  The 2:00 p.m. checkpoint
# deliberately includes a 45-minute publication/distribution buffer before a
# same-day observation is required.
ON_RRP_PUBLICATION_CHECKPOINT_ET = (14, 0)

# FRED generally distributes the total Federal Reserve overnight repo series
# shortly after the operation window.  A 2:30 p.m. ET checkpoint leaves a
# publication buffer while keeping the absolute funding alert contemporaneous
# with the 4:30 p.m. weekly model close.
TOTAL_REPO_PUBLICATION_CHECKPOINT_ET = (14, 30)

# FRED's daily BAA-minus-10-year spread is typically refreshed shortly after
# 5:00 p.m. ET. The 5:15 p.m. checkpoint avoids declaring the official source
# stale during its normal publication and distribution interval.
BAA10Y_PUBLICATION_CHECKPOINT_ET = (17, 15)


class _FederalReserveHolidayCalendar(AbstractHolidayCalendar):
    """Federal Reserve operating holidays, including Saturday treatment."""

    rules = [
        Holiday("New Year's Day", month=1, day=1, observance=sunday_to_monday),
        USMartinLutherKingJr,
        USPresidentsDay,
        USMemorialDay,
        Holiday(
            "Juneteenth",
            month=6,
            day=19,
            start_date="2022-01-01",
            observance=sunday_to_monday,
        ),
        Holiday("Independence Day", month=7, day=4, observance=sunday_to_monday),
        USLaborDay,
        USColumbusDay,
        Holiday("Veterans Day", month=11, day=11, observance=sunday_to_monday),
        USThanksgivingDay,
        Holiday("Christmas Day", month=12, day=25, observance=sunday_to_monday),
    ]


class _GovernmentSecuritiesHolidayCalendar(AbstractHolidayCalendar):
    """Conservative SIFMA-style full closures for secured funding data."""

    rules = [
        Holiday("New Year's Day", month=1, day=1, observance=sunday_to_monday),
        USMartinLutherKingJr,
        USPresidentsDay,
        GoodFriday,
        USMemorialDay,
        Holiday(
            "Juneteenth",
            month=6,
            day=19,
            start_date="2022-01-01",
            observance=nearest_workday,
        ),
        Holiday("Independence Day", month=7, day=4, observance=nearest_workday),
        USLaborDay,
        USColumbusDay,
        Holiday("Veterans Day", month=11, day=11, observance=sunday_to_monday),
        USThanksgivingDay,
        Holiday("Christmas Day", month=12, day=25, observance=nearest_workday),
    ]


class _NYSEHolidayCalendar(AbstractHolidayCalendar):
    """Regular full-day U.S. equity-market closures used by market data."""

    rules = [
        Holiday("New Year's Day", month=1, day=1, observance=sunday_to_monday),
        USMartinLutherKingJr,
        USPresidentsDay,
        GoodFriday,
        USMemorialDay,
        Holiday(
            "Juneteenth",
            month=6,
            day=19,
            start_date="2022-01-01",
            observance=nearest_workday,
        ),
        Holiday("Independence Day", month=7, day=4, observance=nearest_workday),
        USLaborDay,
        USThanksgivingDay,
        Holiday("Christmas Day", month=12, day=25, observance=nearest_workday),
    ]


FEDERAL_RESERVE_DAY = CustomBusinessDay(calendar=_FederalReserveHolidayCalendar())
FEDERAL_GOVERNMENT_DAY = CustomBusinessDay(calendar=USFederalHolidayCalendar())
GOVERNMENT_SECURITIES_DAY = CustomBusinessDay(
    calendar=_GovernmentSecuritiesHolidayCalendar()
)
NYSE_DAY = CustomBusinessDay(calendar=_NYSEHolidayCalendar())


@dataclass(frozen=True)
class LiveLiquiditySnapshot:
    root: Path
    manifest: dict[str, object]
    state: pd.DataFrame
    sources: pd.DataFrame


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_federal_reserve_release_dates(
    payload: object, *, release: str | None = None
) -> pd.DatetimeIndex:
    """Parse and, when identified, normalize a Board release-date payload."""

    if not isinstance(payload, list):
        raise ValueError("Federal Reserve release-date payload must be a list")
    dates: list[pd.Timestamp] = []
    for year in payload:
        if not isinstance(year, dict) or not isinstance(year.get("Months"), list):
            raise ValueError("Federal Reserve release-date payload is malformed")
        for month in year["Months"]:
            if not isinstance(month, dict) or not isinstance(month.get("Dates"), list):
                raise ValueError("Federal Reserve release-date payload is malformed")
            dates.extend(
                pd.to_datetime(str(value), format="%Y%m%d", errors="raise")
                for value in month["Dates"]
            )
    if release is not None and release not in {"h41", "h8", "h10"}:
        raise ValueError(f"Unsupported Federal Reserve release calendar: {release}")
    overrides = FEDERAL_RESERVE_RELEASE_DATE_OVERRIDES.get(str(release), {})
    normalized = [overrides.get(pd.Timestamp(value), pd.Timestamp(value)) for value in dates]
    index = pd.DatetimeIndex(sorted(normalized))
    if index.empty or index.has_duplicates:
        raise ValueError("Federal Reserve release-date calendar is empty or duplicated")
    return index


def load_federal_reserve_release_calendars(
    root: Path,
) -> dict[str, pd.DatetimeIndex]:
    """Load hash-bound official release dates stored with a live snapshot."""

    calendars: dict[str, pd.DatetimeIndex] = {}
    for release in ("h41", "h8", "h10"):
        path = Path(root) / "raw" / f"federalreserve_{release}_release_dates.json"
        if not path.is_file():
            raise FileNotFoundError(
                f"Federal Reserve {release.upper()} release calendar not found: {path}"
            )
        calendars[release] = parse_federal_reserve_release_dates(
            json.loads(path.read_text(encoding="utf-8")), release=release
        )
    return calendars


def federal_reserve_release_observation_date(
    release: str, actual_release: pd.Timestamp
) -> pd.Timestamp:
    """Return the economic observation represented by an official release date."""

    actual_release = pd.Timestamp(actual_release)
    if release == "h10":
        days_since_friday = (actual_release.weekday() - 4) % 7
        if days_since_friday == 0:
            days_since_friday = 7
        nominal_friday = actual_release - pd.Timedelta(days=days_since_friday)
        return pd.Timestamp(FEDERAL_GOVERNMENT_DAY.rollback(nominal_friday))
    if release not in {"h41", "h8"}:
        raise ValueError(f"Unsupported Federal Reserve release calendar: {release}")
    days_since_wednesday = (actual_release.weekday() - 2) % 7
    if release == "h8":
        days_since_wednesday += 7
    return actual_release - pd.Timedelta(days=days_since_wednesday)


def federal_reserve_observation_release_map(
    release: str, release_dates: pd.DatetimeIndex
) -> dict[pd.Timestamp, pd.Timestamp]:
    """Map each official release's economic observation to publication date."""

    if release not in {"h41", "h8"}:
        raise ValueError(f"Unsupported Federal Reserve release calendar: {release}")
    mapping: dict[pd.Timestamp, pd.Timestamp] = {}
    for actual_release in release_dates:
        actual_release = pd.Timestamp(actual_release)
        observation = federal_reserve_release_observation_date(
            release, actual_release
        )
        if observation in mapping:
            raise ValueError(
                f"Federal Reserve {release.upper()} calendar maps two releases to "
                f"{observation.date()}"
            )
        mapping[observation] = actual_release
    return mapping


def apply_federal_reserve_release_availability(
    values: pd.Series,
    release: str,
    release_dates: pd.DatetimeIndex,
    *,
    minimum_observation_date: pd.Timestamp | None = None,
) -> pd.Series:
    """Index weekly observations by their actual official publication date."""

    if release not in {"h41", "h8"}:
        raise ValueError(
            "Historical observation-to-release mapping supports H41 and H8 only"
        )
    output = values.copy().sort_index()
    if output.index.has_duplicates:
        raise ValueError(f"Federal Reserve {release.upper()} observations are duplicated")
    minimum_date = pd.Timestamp("2018-01-01") if minimum_observation_date is None else pd.Timestamp(minimum_observation_date)
    output = output.loc[output.index >= minimum_date]
    mapping = federal_reserve_observation_release_map(release, release_dates)
    missing = [pd.Timestamp(date) for date in output.index if pd.Timestamp(date) not in mapping]
    if missing:
        first = missing[0]
        raise ValueError(
            f"Federal Reserve {release.upper()} release calendar lacks observation "
            f"{first.date()}"
        )
    output.index = pd.DatetimeIndex([mapping[pd.Timestamp(date)] for date in output.index])
    if output.index.has_duplicates or not output.index.is_monotonic_increasing:
        raise ValueError(
            f"Federal Reserve {release.upper()} availability dates are not unique and ordered"
        )
    return output


def load_live_snapshot(root: Path, verify_hashes: bool = True) -> LiveLiquiditySnapshot:
    root = Path(root)
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Live liquidity manifest not found: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != "3.0.0":
        raise ValueError("Unsupported live liquidity snapshot schema")
    if manifest.get("information_cutoff_et") != manifest.get("as_of_et"):
        raise ValueError("Live liquidity information cutoff does not reconcile")
    try:
        information_cutoff = pd.Timestamp(manifest["information_cutoff_et"])
        retrieved_at = pd.Timestamp(manifest["retrieved_at_utc"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Live liquidity manifest contains invalid timestamps") from exc
    if information_cutoff.tzinfo is None or retrieved_at.tzinfo is None:
        raise ValueError("Live liquidity manifest timestamps must be timezone aware")
    cutoff_et = information_cutoff.tz_convert("America/New_York")
    cutoff_date = cutoff_et.tz_localize(None).normalize()
    retrieval_lag = retrieved_at.tz_convert("UTC") - information_cutoff.tz_convert("UTC")
    if retrieval_lag < -pd.Timedelta(minutes=5) or retrieval_lag > pd.Timedelta(minutes=5):
        raise ValueError("Live liquidity retrieval time is not aligned to its information cutoff")
    model_spec = manifest.get("model_spec", {})
    if model_spec.get("version") != "3.0.0-research":
        raise ValueError("Unsupported U.S. liquidity model specification")
    if model_spec.get("weights") != EXPECTED_MODEL_WEIGHTS:
        raise ValueError("U.S. liquidity model weights do not match the release")
    repository_root = Path(__file__).resolve().parents[1]
    implementation_hashes = model_spec.get("implementation_files", {})
    if not isinstance(implementation_hashes, dict) or set(
        implementation_hashes
    ) != set(MODEL_IMPLEMENTATION_FILES):
        raise ValueError("U.S. liquidity implementation-file inventory is incomplete")
    canonical_implementation = json.dumps(
        sorted(implementation_hashes.items()), separators=(",", ":")
    ).encode("utf-8")
    implementation_bundle_sha256 = hashlib.sha256(canonical_implementation).hexdigest()
    if (
        model_spec.get("implementation_bundle_sha256")
        != implementation_bundle_sha256
    ):
        raise ValueError("U.S. liquidity implementation bundle does not reconcile")
    main_model_hash = implementation_hashes["liquidity_monitor/us_liquidity_model.py"]
    if model_spec.get("model_code_sha256") != main_model_hash:
        raise ValueError("U.S. liquidity primary model checksum does not reconcile")
    if verify_hashes:
        for relative_path, declared_hash in implementation_hashes.items():
            implementation_path = (repository_root / relative_path).resolve()
            if repository_root not in implementation_path.parents:
                raise ValueError("U.S. liquidity implementation path is invalid")
            if not implementation_path.is_file() or _sha256(implementation_path) != str(
                declared_hash
            ):
                raise ValueError(
                    f"U.S. liquidity implementation checksum mismatch: {relative_path}"
                )
    frames: dict[str, pd.DataFrame] = {}
    for key, filename in (("state", "current_state.csv"), ("sources", "source_status.csv")):
        path = root / filename
        metadata = manifest.get("files", {}).get(filename, {})
        if not path.is_file():
            raise FileNotFoundError(f"Live liquidity file not found: {path}")
        if verify_hashes and metadata.get("sha256") != _sha256(path):
            raise ValueError(f"Live liquidity checksum mismatch: {filename}")
        frame = pd.read_csv(path)
        if int(metadata.get("rows", -1)) != len(frame):
            raise ValueError(f"Live liquidity row-count mismatch: {filename}")
        frames[key] = frame
    if len(frames["state"]) != 1:
        raise ValueError("Live liquidity state must contain exactly one row")
    if set(frames["state"].columns) != EXPECTED_STATE_COLUMNS:
        raise ValueError("Live liquidity current-state schema mismatch")
    required_sources = set(manifest.get("required_sources", []))
    observed_sources = set(frames["sources"]["field"].astype(str))
    if required_sources != observed_sources:
        raise ValueError("Live liquidity source inventory is incomplete")
    if frames["sources"]["field"].duplicated().any():
        raise ValueError("Live liquidity source identifiers are not unique")
    required_source_columns = {
        "field", "series", "source_key", "provider", "value", "unit",
        "observation_date", "expected_observation_date", "verified_through",
        "retrieved_at_utc", "status", "status_detail", "source_url", "raw_sha256",
    }
    if set(frames["sources"].columns) != required_source_columns:
        raise ValueError("Live liquidity source schema mismatch")
    if frames["sources"].isna().any().any():
        raise ValueError("Live liquidity source ledger contains missing values")
    observed_dates = pd.to_datetime(frames["sources"]["observation_date"], errors="coerce")
    expected_dates = pd.to_datetime(frames["sources"]["expected_observation_date"], errors="coerce")
    verified_dates = pd.to_datetime(frames["sources"]["verified_through"], errors="coerce")
    if observed_dates.isna().any() or expected_dates.isna().any() or verified_dates.isna().any():
        raise ValueError("Live liquidity source ledger contains invalid dates")
    if observed_dates.gt(verified_dates).any():
        raise ValueError("A source observation occurs after its verification date")
    if observed_dates.gt(cutoff_date).any() or verified_dates.gt(cutoff_date).any():
        raise ValueError("Live liquidity source ledger contains a future-dated record")
    release_calendars = load_federal_reserve_release_calendars(root)
    recomputed_expected = pd.Series(
        [
            expected_observation_date(
                str(field), cutoff_et, release_calendars=release_calendars
            )[0]
            for field in frames["sources"]["field"]
        ],
        index=frames["sources"].index,
    )
    if not expected_dates.eq(recomputed_expected).all():
        raise ValueError("Live liquidity source clock does not reconcile to model rules")
    state_retrieved = pd.to_datetime(
        frames["state"]["retrieved_at_utc"], utc=True, errors="coerce"
    )
    source_retrieved = pd.to_datetime(
        frames["sources"]["retrieved_at_utc"], utc=True, errors="coerce"
    )
    manifest_retrieved = retrieved_at.tz_convert("UTC")
    if (
        state_retrieved.isna().any()
        or source_retrieved.isna().any()
        or not state_retrieved.eq(manifest_retrieved).all()
        or not source_retrieved.eq(manifest_retrieved).all()
    ):
        raise ValueError("Live liquidity retrieval timestamps do not reconcile")
    derived_current = bool(
        frames["sources"]["status"].isin(CURRENT_SOURCE_STATUSES).all()
        and observed_dates.ge(expected_dates).all()
    )
    if bool(manifest.get("all_sources_current")) != derived_current:
        raise ValueError("Live liquidity currentness flag does not reconcile")
    if verify_hashes:
        raw_items = manifest.get("raw_files", [])
        if not isinstance(raw_items, list) or {
            Path(str(item.get("path", ""))).name for item in raw_items
        } != EXPECTED_RAW_FILES:
            raise ValueError("Live liquidity raw-file inventory is incomplete")
        raw_hashes: set[str] = set()
        for item in raw_items:
            path = (root / str(item.get("path", ""))).resolve()
            raw_root = (root / "raw").resolve()
            if raw_root not in path.parents or not path.is_file():
                raise ValueError("Live liquidity raw-file inventory contains an invalid path")
            if _sha256(path) != str(item.get("sha256", "")):
                raise ValueError(f"Live liquidity raw checksum mismatch: {path.name}")
            raw_hashes.add(str(item.get("sha256", "")))
        if not set(frames["sources"]["raw_sha256"].astype(str)).issubset(raw_hashes):
            raise ValueError("Source ledger raw hashes do not reconcile to the manifest")
    numeric = frames["state"].select_dtypes(include="number").to_numpy(dtype=float)
    if numeric.size and not np.isfinite(numeric).all():
        raise ValueError("Live liquidity state contains non-finite numeric values")
    state = frames["state"].iloc[0]
    reconstructed = (
        float(state["fed_asset_change_4w_bp"])
        - float(state["tga_change_4w_bp_assets"])
        - float(state["onrrp_change_4w_bp_assets"])
        - float(state["currency_change_4w_bp_assets"])
        + float(state["other_liability_residual_4w_bp"])
    )
    if not np.isclose(reconstructed, float(state["reserve_impulse_4w_bp"]), atol=1e-8):
        raise ValueError("Live liquidity accounting identity does not reconcile")
    if pd.Timestamp(state["as_of_date"]).date() != pd.Timestamp(manifest["as_of_et"]).date():
        raise ValueError("Live liquidity state date does not match its manifest")
    source_values = frames["sources"].set_index("field")["value"].astype(float)
    for field in (
        "reserves_bn", "assets_bn", "tga_h41_bn", "tga_dts_bn", "onrrp_bn", "currency_bn",
        "baa10y", "vix", "sofr", "iorb", "deposits_bn", "effr", "hy_oas",
        "ig_oas", "broad_usd", "real_yield_10y",
        "bank_assets_bn", "bank_cash_bn", "large_bank_assets_bn", "large_bank_cash_bn",
        "small_bank_assets_bn", "small_bank_cash_bn", "bank_credit_bn",
        "fedwire_daily_value_bn", "tgcr", "bgcr", "repo_add_bn",
    ):
        if not np.isclose(float(state[field]), source_values[field], atol=1e-10):
            raise ValueError(f"Live state does not reconcile to source ledger: {field}")
    derived = {
        "reserve_deposit_pct": float(state["reserves_bn"]) / float(state["deposits_bn"]) * 100,
    }
    for field, value in derived.items():
        if not np.isclose(float(state[field]), value, atol=1e-10):
            raise ValueError(f"Live derived state does not reconcile: {field}")
    _validate_raw_recomputations(root, frames["state"].iloc[0], frames["sources"])
    return LiveLiquiditySnapshot(root=root, manifest=manifest, **frames)


def expected_observation_date(
    field: str,
    as_of: pd.Timestamp,
    *,
    release_calendars: dict[str, pd.DatetimeIndex] | None = None,
) -> tuple[pd.Timestamp, str]:
    """Return the source-aware expected date and rule at an ET information cutoff.

    This is the single publication-clock implementation used both while a
    snapshot is built and when its freshness is reevaluated later.  Keeping one
    implementation prevents a release from being certified with a different
    clock than the runtime monitor uses.
    """

    if as_of.tzinfo is None:
        as_of = as_of.tz_localize("America/New_York")
    else:
        as_of = as_of.tz_convert("America/New_York")
    day = as_of.normalize().tz_localize(None)

    def completed_official_release(
        release: str, hour: int, minute: int
    ) -> pd.Timestamp:
        if release_calendars is None or release not in release_calendars:
            raise ValueError("Official release calendar is unavailable")
        release_dates = release_calendars[release]
        cutoffs = release_dates.tz_localize("America/New_York") + pd.Timedelta(
            hours=hour, minutes=minute
        )
        eligible = release_dates[cutoffs <= as_of]
        if eligible.empty:
            raise ValueError(f"No completed official {release.upper()} release is available")
        actual_release = pd.Timestamp(eligible[-1])
        return federal_reserve_release_observation_date(release, actual_release)

    def completed_weekly_release(
        weekday: int,
        hour: int,
        minute: int,
        *,
        holiday_direction: str = "next",
    ) -> pd.Timestamp:
        """Return the nominal date for the most recent completed weekly release."""

        nominal = day - pd.Timedelta(days=(day.weekday() - weekday) % 7)

        def actual_release_date(value: pd.Timestamp) -> pd.Timestamp:
            if FEDERAL_GOVERNMENT_DAY.is_on_offset(value):
                return value
            if holiday_direction == "previous":
                return FEDERAL_GOVERNMENT_DAY.rollback(value)
            return FEDERAL_GOVERNMENT_DAY.rollforward(value)

        candidates = [
            nominal - pd.Timedelta(days=7),
            nominal,
            nominal + pd.Timedelta(days=7),
        ]
        completed = []
        for candidate in candidates:
            actual = actual_release_date(candidate)
            actual_cutoff = (
                actual.tz_localize("America/New_York")
                + pd.Timedelta(hours=hour, minutes=minute)
            )
            if actual_cutoff <= as_of:
                completed.append((actual_cutoff, candidate))
        if not completed:
            raise ValueError("No completed weekly release is available")
        return max(completed, key=lambda item: item[0])[1]

    def is_session(value: pd.Timestamp, calendar: CustomBusinessDay) -> bool:
        return bool(calendar.is_on_offset(value))

    def latest_same_day_observation(
        calendar: CustomBusinessDay, checkpoint: tuple[int, int]
    ) -> pd.Timestamp:
        if is_session(day, calendar):
            if (as_of.hour, as_of.minute) >= checkpoint:
                return day
            return day - calendar
        return calendar.rollback(day)

    def lagged_daily_observation(
        calendar: CustomBusinessDay, checkpoint: tuple[int, int]
    ) -> pd.Timestamp:
        if is_session(day, calendar):
            periods = 1 if (as_of.hour, as_of.minute) >= checkpoint else 2
        else:
            periods = 2
        return day - periods * calendar

    if field in {"reserves_bn", "assets_bn", "tga_h41_bn", "currency_bn"}:
        if release_calendars is not None:
            return (
                completed_official_release("h41", 16, 30),
                "latest completed official H.4.1 release / Wednesday observation",
            )
        return (
            completed_weekly_release(3, 16, 30) - pd.Timedelta(days=1),
            "completed H.4.1 release / Wednesday observation",
        )
    if field in {"deposits_bn", "bank_assets_bn", "bank_cash_bn", "large_bank_assets_bn", "large_bank_cash_bn", "small_bank_assets_bn", "small_bank_cash_bn", "bank_credit_bn"}:
        if release_calendars is not None:
            return (
                completed_official_release("h8", 16, 15),
                "latest completed official H.8 release / lagged-Wednesday observation",
            )
        return (
            completed_weekly_release(
                4, 16, 15, holiday_direction="previous"
            )
            - pd.Timedelta(days=9),
            "completed H.8 release / lagged-Wednesday observation",
        )
    if field == "broad_usd":
        if release_calendars is not None:
            return (
                completed_official_release("h10", 16, 15),
                "latest completed official H.10 release / prior business-week observation",
            )
        nominal_friday = completed_weekly_release(0, 16, 15) - pd.Timedelta(days=3)
        return (
            pd.Timestamp(FEDERAL_GOVERNMENT_DAY.rollback(nominal_friday)),
            "latest completed weekly H.10 distribution",
        )
    if field == "onrrp_bn":
        return (
            latest_same_day_observation(
                GOVERNMENT_SECURITIES_DAY, ON_RRP_PUBLICATION_CHECKPOINT_ET
            ),
            "latest completed New York Fed operation under its operating-day calendar and 2:00 p.m. ET publication checkpoint",
        )
    if field == "market":
        return (
            latest_same_day_observation(NYSE_DAY, (16, 30)),
            "latest completed U.S. equity-market close under the exchange holiday calendar",
        )
    if field in {"sofr", "tgcr", "bgcr"}:
        return (
            lagged_daily_observation(GOVERNMENT_SECURITIES_DAY, (8, 0)),
            "latest completed next-morning secured reference-rate publication under the government-securities holiday calendar",
        )
    if field == "effr":
        return (
            lagged_daily_observation(FEDERAL_RESERVE_DAY, (9, 0)),
            "latest completed next-morning EFFR publication under the New York Fed holiday calendar",
        )
    if field == "vix":
        return (
            day - NYSE_DAY if is_session(day, NYSE_DAY) else NYSE_DAY.rollback(day),
            "latest scheduled prior-session publication under the exchange holiday calendar",
        )
    if field == "iorb":
        return (
            day
            if is_session(day, FEDERAL_RESERVE_DAY)
            else FEDERAL_RESERVE_DAY.rollback(day),
            "latest effective administered rate under the Federal Reserve holiday calendar",
        )
    if field == "fedwire_daily_value_bn":
        prior_month = day.replace(day=1) - pd.Timedelta(days=1)
        if prior_month + pd.Timedelta(days=25) > day:
            prior_month = prior_month.replace(day=1) - pd.Timedelta(days=1)
        return (
            prior_month,
            "monthly Fedwire statistics with conservative 25-day publication lag",
        )
    if field == "baa10y":
        return (
            lagged_daily_observation(
                GOVERNMENT_SECURITIES_DAY, BAA10Y_PUBLICATION_CHECKPOINT_ET
            ),
            "latest completed FRED interest-rate-spread publication after the 5:15 p.m. ET checkpoint",
        )
    if field == "repo_add_bn":
        return (
            latest_same_day_observation(
                GOVERNMENT_SECURITIES_DAY, TOTAL_REPO_PUBLICATION_CHECKPOINT_ET
            ),
            "latest completed total Federal Reserve overnight repo publication under the government-securities calendar",
        )
    if field in {"tga_dts_bn", "hy_oas", "ig_oas", "real_yield_10y"}:
        calendar = (
            FEDERAL_GOVERNMENT_DAY
            if field == "tga_dts_bn"
            else GOVERNMENT_SECURITIES_DAY
        )
        return (
            lagged_daily_observation(calendar, (17, 0)),
            "latest conservatively completed daily publication under its source holiday calendar",
        )
    return day, "same-day scheduled observation"


def source_current_mask(
    snapshot: LiveLiquiditySnapshot, now: pd.Timestamp | None = None
) -> pd.Series:
    observed = pd.to_datetime(snapshot.sources["observation_date"], errors="coerce")
    verified = pd.to_datetime(snapshot.sources["verified_through"], errors="coerce")
    packaged_expected = pd.to_datetime(
        snapshot.sources["expected_observation_date"], errors="coerce"
    )
    wall_clock = now if now is not None else pd.Timestamp.now(tz="America/New_York")
    if wall_clock.tzinfo is None:
        wall_clock = wall_clock.tz_localize("America/New_York")
    else:
        wall_clock = wall_clock.tz_convert("America/New_York")
    expected = runtime_expected_dates(snapshot, now=wall_clock)
    package_cutoff = pd.Timestamp(snapshot.manifest["information_cutoff_et"])
    if package_cutoff.tzinfo is None:
        package_cutoff = package_cutoff.tz_localize("America/New_York")
    else:
        package_cutoff = package_cutoff.tz_convert("America/New_York")
    package_date = package_cutoff.tz_localize(None).normalize()
    runtime_date = wall_clock.tz_localize(None).normalize()
    return (
        snapshot.sources["status"].isin(CURRENT_SOURCE_STATUSES)
        & observed.notna()
        & verified.notna()
        & packaged_expected.notna()
        & expected.notna()
        & observed.ge(expected)
        & observed.le(package_date)
        & observed.le(runtime_date)
        & verified.le(package_date)
        & verified.le(runtime_date)
        & packaged_expected.le(package_date)
    )


def runtime_expected_dates(
    snapshot: LiveLiquiditySnapshot, now: pd.Timestamp | None = None
) -> pd.Series:
    """Return each source's expected observation date at the current ET wall clock."""

    wall_clock = now if now is not None else pd.Timestamp.now(tz="America/New_York")
    if wall_clock.tzinfo is None:
        wall_clock = wall_clock.tz_localize("America/New_York")
    else:
        wall_clock = wall_clock.tz_convert("America/New_York")
    package_cutoff = pd.Timestamp(snapshot.manifest["information_cutoff_et"])
    if package_cutoff.tzinfo is None:
        package_cutoff = package_cutoff.tz_localize("America/New_York")
    else:
        package_cutoff = package_cutoff.tz_convert("America/New_York")
    # The bundled official calendars certify the release itself at the frozen
    # information cutoff.  Once wall time advances beyond that cutoff, use the
    # conservative recurring schedule so a static package cannot appear current
    # merely because its archived calendar contains no future release dates.
    release_calendars = (
        load_federal_reserve_release_calendars(snapshot.root)
        if wall_clock <= package_cutoff + pd.Timedelta(minutes=5)
        else None
    )
    return pd.Series(
        [
            expected_observation_date(
                str(field), wall_clock, release_calendars=release_calendars
            )[0]
            for field in snapshot.sources["field"]
        ],
        index=snapshot.sources.index,
    )


def snapshot_is_current(
    snapshot: LiveLiquiditySnapshot, now: pd.Timestamp | None = None
) -> bool:
    wall_clock = now if now is not None else pd.Timestamp.now(tz="America/New_York")
    if wall_clock.tzinfo is None:
        wall_clock = wall_clock.tz_localize("America/New_York")
    else:
        wall_clock = wall_clock.tz_convert("America/New_York")
    return bool(
        source_current_mask(snapshot, now=wall_clock).all()
        and pd.Timestamp(snapshot.manifest["as_of_et"]) <= wall_clock + pd.Timedelta(minutes=5)
    )


def _fred_raw(root: Path, series_id: str, scale: float) -> pd.Series:
    frame = pd.read_csv(root / "raw" / f"fred_{series_id}.csv", na_values=["."])
    frame.columns = ["date", "value"]
    frame["date"] = pd.to_datetime(frame["date"], errors="raise")
    if frame["date"].duplicated().any():
        raise ValueError(f"FRED series {series_id} contains duplicate dates")
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce") * scale
    valid = frame.dropna()
    return valid.set_index("date")["value"].sort_index()


def _asof(series: pd.Series, date: pd.Timestamp) -> float:
    eligible = series.loc[series.index <= date]
    if eligible.empty:
        raise ValueError("Raw recomputation lacks a required prior observation")
    return float(eligible.iloc[-1])


def _validate_raw_recomputations(
    root: Path, state: pd.Series, sources: pd.DataFrame
) -> None:
    """Independently rebuild key mechanics so a forced residual cannot mask clock errors."""

    source_rows = sources.set_index("field")
    fred_fields = {
        "reserves_bn": ("WRBWFRBL", 0.001),
        "assets_bn": ("WALCL", 0.001),
        "tga_h41_bn": ("WDTGAL", 0.001),
        "onrrp_bn": ("RRPONTSYD", 1.0),
        "currency_bn": ("WCURCIR", 0.001),
        "baa10y": ("BAA10Y", 1.0),
        "vix": ("VIXCLS", 1.0),
        "iorb": ("IORB", 1.0),
        "deposits_bn": ("DPSACBW027SBOG", 1.0),
        "effr": ("EFFR", 1.0),
        "hy_oas": ("BAMLH0A0HYM2", 1.0),
        "ig_oas": ("BAMLC0A0CM", 1.0),
        "broad_usd": ("DTWEXBGS", 1.0),
        "real_yield_10y": ("DFII10", 1.0),
        "bank_assets_bn": ("TLAACBW027SBOG", 1.0),
        "bank_cash_bn": ("CASACBW027SBOG", 1.0),
        "large_bank_assets_bn": ("TLALCBW027SBOG", 1.0),
        "large_bank_cash_bn": ("CASLCBW027SBOG", 1.0),
        "small_bank_assets_bn": ("TLASCBW027SBOG", 1.0),
        "small_bank_cash_bn": ("CASSCBW027SBOG", 1.0),
        "bank_credit_bn": ("TOTBKCR", 1.0),
        "repo_add_bn": ("RPONTTLD", 1.0),
    }
    for field, (series_id, scale) in fred_fields.items():
        source = source_rows.loc[field]
        observation = pd.Timestamp(source["observation_date"])
        raw_series = _fred_raw(root, series_id, scale)
        if observation not in raw_series.index:
            raise ValueError(f"Raw source lacks the selected observation: {field}")
        if not np.isclose(
            float(source["value"]), float(raw_series.loc[observation]), atol=1e-10
        ):
            raise ValueError(f"Source ledger does not reconcile to raw input: {field}")

    iorb_raw = _fred_raw(root, "IORB", 1.0)

    effr_row = source_rows.loc["effr"]
    effr_date = pd.Timestamp(effr_row["observation_date"])
    effr_spread_bp = (
        float(effr_row["value"]) - _asof(iorb_raw, effr_date)
    ) * 100
    if not np.isclose(
        float(state["effr_admin_bp"]), effr_spread_bp, atol=1e-10
    ):
        raise ValueError("EFFR spread does not reconcile on its effective-date clock")

    for rate_name in ("sofr", "tgcr", "bgcr"):
        rate_payload = json.loads((root / "raw" / f"nyfed_{rate_name}.json").read_text(encoding="utf-8"))
        rate_frame = pd.DataFrame(rate_payload["refRates"])
        rate_frame["date"] = pd.to_datetime(rate_frame["effectiveDate"], errors="raise")
        rate_frame["value"] = pd.to_numeric(rate_frame["percentRate"], errors="raise")
        if rate_frame["date"].duplicated().any():
            raise ValueError(
                f"New York Fed {rate_name.upper()} payload contains duplicate dates"
            )
        rate_raw = rate_frame.set_index("date")["value"]
        rate_row = source_rows.loc[rate_name]
        rate_date = pd.Timestamp(rate_row["observation_date"])
        if rate_date not in rate_raw.index or not np.isclose(
            float(rate_row["value"]), float(rate_raw.loc[rate_date]), atol=1e-10
        ):
            raise ValueError(f"{rate_name.upper()} source ledger does not reconcile to the raw payload")
        spread_field = f"{rate_name}_admin_bp"
        matched_spread_bp = (
            float(rate_raw.loc[rate_date]) - _asof(iorb_raw, rate_date)
        ) * 100
        if not np.isclose(
            float(state[spread_field]), matched_spread_bp, atol=1e-10
        ):
            raise ValueError(
                f"{rate_name.upper()} spread does not reconcile on its effective-date clock"
            )
        if rate_name == "sofr":
            selected = rate_frame.set_index("date").loc[rate_date]
            raw_iqr_bp = (
                float(selected["percentPercentile75"])
                - float(selected["percentPercentile25"])
            ) * 100
            if not np.isclose(float(state["sofr_iqr_bp"]), raw_iqr_bp, atol=1e-10):
                raise ValueError("SOFR dispersion does not reconcile to the raw payload")

    fedwire_row = source_rows.loc["fedwire_daily_value_bn"]
    fedwire_text = (root / "raw" / "fedwire_monthly.txt").read_text(
        encoding="utf-8", errors="replace"
    )
    target_date = pd.Timestamp(fedwire_row["observation_date"])
    month_tokens = {
        1: {"jan", "january"}, 2: {"feb", "february"}, 3: {"mar", "march"},
        4: {"apr", "april"}, 5: {"may"}, 6: {"jun", "june"},
        7: {"jul", "july"}, 8: {"aug", "august"},
        9: {"sep", "sept", "september"}, 10: {"oct", "october"},
        11: {"nov", "november"}, 12: {"dec", "december"},
    }
    fedwire_value = None
    for line in fedwire_text.splitlines():
        match = re.match(r"^\s*(\d{4}):\s*([A-Za-z]+)\s+(.+)$", line)
        if not match or int(match.group(1)) != target_date.year:
            continue
        if match.group(2).lower() not in month_tokens[target_date.month]:
            continue
        values = re.findall(r"\(?-?[\d,]+(?:\.\d+)?\)?", match.group(3))
        if values:
            fedwire_value = float(values[-1].replace(",", "").strip("()")) * 0.001
            break
    if fedwire_value is None or not np.isclose(
        float(fedwire_row["value"]), fedwire_value, atol=1e-10
    ):
        raise ValueError("Fedwire source ledger does not reconcile to the raw payload")

    treasury_payload = json.loads(
        (root / "raw" / "treasury_tga.json").read_text(encoding="utf-8")
    )
    treasury = pd.DataFrame(treasury_payload["data"])
    treasury = treasury.loc[
        treasury["account_type"].eq("Treasury General Account (TGA) Closing Balance")
    ].copy()
    treasury["date"] = pd.to_datetime(treasury["record_date"], errors="raise")
    treasury["value"] = pd.to_numeric(treasury["open_today_bal"], errors="raise") * 0.001
    if treasury["date"].duplicated().any():
        raise ValueError("Daily Treasury Statement TGA contains duplicate dates")
    treasury_raw = treasury.set_index("date")["value"]
    treasury_row = source_rows.loc["tga_dts_bn"]
    treasury_date = pd.Timestamp(treasury_row["observation_date"])
    if treasury_date not in treasury_raw.index or not np.isclose(
        float(treasury_row["value"]), float(treasury_raw.loc[treasury_date]), atol=1e-10
    ):
        raise ValueError("Treasury source ledger does not reconcile to the raw payload")

    reference = pd.Timestamp(state["accounting_asof_date"])
    start4 = reference - pd.Timedelta(days=28)
    start13 = reference - pd.Timedelta(days=91)
    histories = {
        "reserves": _fred_raw(root, "WRBWFRBL", 0.001),
        "assets": _fred_raw(root, "WALCL", 0.001),
        "tga": _fred_raw(root, "WDTGAL", 0.001),
        "onrrp": _fred_raw(root, "RRPONTSYD", 1.0),
        "currency": _fred_raw(root, "WCURCIR", 0.001),
    }
    denominator4 = _asof(histories["assets"], start4)
    denominator13 = _asof(histories["assets"], start13)
    changes4 = {
        key: (_asof(series, reference) - _asof(series, start4)) / denominator4 * 10000
        for key, series in histories.items()
    }
    expected = {
        "reserve_impulse_4w_bp": changes4["reserves"],
        "reserve_impulse_13w_bp": (
            _asof(histories["reserves"], reference) - _asof(histories["reserves"], start13)
        ) / denominator13 * 10000,
        "fed_asset_change_4w_bp": changes4["assets"],
        "tga_change_4w_bp_assets": changes4["tga"],
        "onrrp_change_4w_bp_assets": changes4["onrrp"],
        "currency_change_4w_bp_assets": changes4["currency"],
    }
    expected["accounting_known_impulse_4w_bp"] = (
        expected["fed_asset_change_4w_bp"]
        - expected["tga_change_4w_bp_assets"]
        - expected["onrrp_change_4w_bp_assets"]
        - expected["currency_change_4w_bp_assets"]
    )
    expected["other_liability_residual_4w_bp"] = (
        expected["reserve_impulse_4w_bp"] - expected["accounting_known_impulse_4w_bp"]
    )
    for field, value in expected.items():
        if not np.isclose(float(state[field]), value, atol=1e-8):
            raise ValueError(f"Live raw recomputation failed: {field}")

    market = pd.read_csv(
        root / "raw" / "market_adjusted_close.csv", parse_dates=["date"]
    )
    if market["date"].duplicated().any():
        raise ValueError("Market input contains duplicate session dates")
    market = market.set_index("date")
    tickers = [
        "SPY", "XLB", "XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY",
        "QQQ", "RSP", "IWM", "ARKK", "XBI", "KRE", "BTC-USD", "EEM",
    ]
    complete = market.dropna(subset=tickers)
    if complete.empty or complete.index[-1].date() != pd.Timestamp(state["market_asof_date"]).date():
        raise ValueError("Live market constituent date does not reconcile")
    if not np.isclose(float(state["spy_adj_close"]), float(complete["SPY"].iloc[-1]), atol=1e-10):
        raise ValueError("Live SPY close does not reconcile")
    sectors = ["XLB", "XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY"]
    breadth = (complete[sectors] > complete[sectors].rolling(50).mean()).mean(axis=1)
    market_expected = {
        "spy_mom60": (complete["SPY"].iloc[-1] / complete["SPY"].iloc[-61] - 1) * 100,
        "spy_dist200": (complete["SPY"].iloc[-1] / complete["SPY"].rolling(200).mean().iloc[-1] - 1) * 100,
        "sector_breadth50": breadth.iloc[-1],
        "sector_breadth50_change20": breadth.iloc[-1] - breadth.iloc[-21],
    }
    for field, value in market_expected.items():
        if not np.isclose(float(state[field]), float(value), atol=1e-10):
            raise ValueError(f"Live market recomputation failed: {field}")
