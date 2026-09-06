#!/usr/bin/env python3
"""Build an atomic, source-dated current U.S. liquidity observation release."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import shutil
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests
import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from liquidity_monitor.liquidity_live_snapshot import (  # noqa: E402
    CURRENT_SOURCE_STATUSES,
    MODEL_IMPLEMENTATION_FILES,
    expected_observation_date,
    load_live_snapshot,
    parse_federal_reserve_release_dates,
)
from liquidity_monitor.us_liquidity_model import (  # noqa: E402
    LIQUIDITY_LAYER_WEIGHTS,
    MODEL_VERSION,
    build_us_liquidity_model,
)

DEFAULT_OUTPUT = ROOT / "data" / "liquidity_live_snapshot"
FRED = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"
TREASURY = "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/dts/operating_cash_balance"
NYFED_RATE = "https://markets.newyorkfed.org/api/rates/secured/{rate}/search.json"
FEDWIRE_PAGE = "https://www.frbservices.org/resources/financial-services/wires/volume-value-stats/monthly-stats.html"
FEDERAL_RESERVE_RELEASE_DATES = {
    "h41": "https://www.federalreserve.gov/releases/h41/releaseDates.json",
    "h8": "https://www.federalreserve.gov/releases/h8/releaseDates.json",
    "h10": "https://www.federalreserve.gov/releases/h10/releaseDates.json",
}
SECTORS = ["XLB", "XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY"]
MARKET_CONFIRMATION = ["QQQ", "RSP", "IWM", "ARKK", "XBI", "KRE", "BTC-USD", "EEM"]

SPECS = {
    "reserves_bn": ("Reserve balances", "WRBWFRBL", "Federal Reserve H.4.1", "USD billions", 0.001),
    "assets_bn": ("Federal Reserve assets", "WALCL", "Federal Reserve H.4.1", "USD billions", 0.001),
    "tga_h41_bn": ("TGA accounting driver (weekly)", "WDTGAL", "Federal Reserve H.4.1", "USD billions", 0.001),
    "currency_bn": ("Currency in circulation", "WCURCIR", "Federal Reserve H.4.1", "USD billions", 0.001),
    "onrrp_bn": ("Overnight reverse repo", "RRPONTSYD", "New York Fed via FRED", "USD billions", 1.0),
    "baa10y": ("Baa minus 10-year", "BAA10Y", "FRED", "percentage points", 1.0),
    "vix": ("VIX", "VIXCLS", "Cboe via FRED", "index points", 1.0),
    "iorb": ("IORB", "IORB", "Federal Reserve via FRED", "percent", 1.0),
    "deposits_bn": (
        "Commercial bank deposits",
        "DPSACBW027SBOG",
        "Federal Reserve H.8 via FRED",
        "USD billions",
        1.0,
    ),
    "bank_assets_bn": ("Commercial bank assets", "TLAACBW027SBOG", "Federal Reserve H.8 via FRED", "USD billions", 1.0),
    "bank_cash_bn": ("Commercial bank cash assets", "CASACBW027SBOG", "Federal Reserve H.8 via FRED", "USD billions", 1.0),
    "large_bank_assets_bn": ("Large-bank assets", "TLALCBW027SBOG", "Federal Reserve H.8 via FRED", "USD billions", 1.0),
    "large_bank_cash_bn": ("Large-bank cash assets", "CASLCBW027SBOG", "Federal Reserve H.8 via FRED", "USD billions", 1.0),
    "small_bank_assets_bn": ("Small-bank assets", "TLASCBW027SBOG", "Federal Reserve H.8 via FRED", "USD billions", 1.0),
    "small_bank_cash_bn": ("Small-bank cash assets", "CASSCBW027SBOG", "Federal Reserve H.8 via FRED", "USD billions", 1.0),
    "bank_credit_bn": ("Commercial bank credit", "TOTBKCR", "Federal Reserve H.8 via FRED", "USD billions", 1.0),
    "repo_add_bn": ("Federal Reserve overnight repo operations", "RPONTTLD", "New York Fed via FRED", "USD billions", 1.0),
    "effr": ("Effective federal funds rate", "EFFR", "New York Fed via FRED", "percent", 1.0),
    "hy_oas": ("High yield option-adjusted spread", "BAMLH0A0HYM2", "ICE BofA via FRED", "percentage points", 1.0),
    "ig_oas": ("Investment grade option-adjusted spread", "BAMLC0A0CM", "ICE BofA via FRED", "percentage points", 1.0),
    "broad_usd": ("Broad U.S. dollar index", "DTWEXBGS", "Federal Reserve via FRED", "index points", 1.0),
    "real_yield_10y": ("10-year real yield", "DFII10", "Federal Reserve via FRED", "percent", 1.0),
}
REFERENCE_SPECS = {"IOER": ("Interest on excess reserves", "Federal Reserve via FRED", "percent")}


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def get(url: str, *, params: dict | None = None) -> requests.Response:
    last_error: requests.RequestException | None = None
    for attempt in range(3):
        try:
            response = requests.get(
                url,
                params=params,
                timeout=(15, 120),
                headers={"User-Agent": "U.S.-Liquidity-Monitor/1.0"},
            )
            response.raise_for_status()
            return response
        except requests.RequestException as error:
            last_error = error
            if attempt < 2:
                time.sleep(2 ** attempt)
    if last_error is None:
        raise RuntimeError("HTTP retrieval failed without an exception")
    raise last_error


def status_for(
    field: str,
    observation: pd.Timestamp,
    values: pd.Series,
    as_of: pd.Timestamp,
    *,
    release_calendars: dict[str, pd.DatetimeIndex] | None = None,
) -> tuple[str, str]:
    expected, rule = expected_observation_date(
        field, as_of, release_calendars=release_calendars
    )
    if observation.normalize() < expected.normalize():
        return "STALE", f"Observed {observation.date()}; expected at least {expected.date()} under {rule}"
    unchanged = len(values.dropna()) >= 2 and float(values.dropna().iloc[-1]) == float(values.dropna().iloc[-2])
    if observation.normalize() < as_of.normalize().tz_localize(None):
        return "CURRENT_PUBLICATION_LAG", f"Current under {rule}"
    return ("CURRENT_UNCHANGED" if unchanged else "CURRENT_UPDATED"), ("Verified through today; value unchanged" if unchanged else "Verified through today; new observation")


def fred_series(series: str, raw: Path) -> tuple[pd.Series, dict]:
    url = FRED.format(series=series)
    response = get(url)
    content = response.content
    (raw / f"fred_{series}.csv").write_bytes(content)
    frame = pd.read_csv(io.BytesIO(content), na_values=["."])
    frame.columns = ["date", "value"]
    frame["date"] = pd.to_datetime(frame["date"], errors="raise")
    if frame["date"].duplicated().any():
        raise ValueError(f"FRED series {series} contains duplicate dates")
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    valid = frame.dropna()
    series_data = valid.set_index("date")["value"].sort_index()
    return series_data, {"url": url, "http_date": None, "raw_sha256": sha256_bytes(content)}


def asof_value(series: pd.Series, date: pd.Timestamp) -> float:
    eligible = series.loc[series.index <= date]
    if eligible.empty:
        raise ValueError(f"No observation available by {date.date()}")
    return float(eligible.iloc[-1])


def matched_admin_spread_bp(
    reference_rate: pd.Series, administered_rate: pd.Series
) -> float:
    """Return the latest reference-rate spread to the same-date admin rate.

    Reference rates are published after their effective date.  Pairing the
    latest published reference rate with a newer administered rate can create a
    false one-day funding signal around a policy change, so the administered
    rate is selected as of the reference rate's effective date.
    """

    reference = reference_rate.dropna().sort_index()
    administered = administered_rate.dropna().sort_index()
    if reference.empty or administered.empty:
        raise ValueError("Reference and administered rates must contain observations")
    effective_date = pd.Timestamp(reference.index[-1])
    return float(
        (float(reference.iloc[-1]) - asof_value(administered, effective_date)) * 100
    )


def _adjusted_close_frame(download: pd.DataFrame, tickers: list[str]) -> pd.DataFrame:
    if download.empty:
        return pd.DataFrame()
    if isinstance(download.columns, pd.MultiIndex):
        if "Adj Close" not in download.columns.get_level_values(0):
            return pd.DataFrame()
        adjusted = download["Adj Close"].copy()
    elif "Adj Close" in download.columns and len(tickers) == 1:
        adjusted = download[["Adj Close"]].rename(columns={"Adj Close": tickers[0]})
    else:
        return pd.DataFrame()
    if isinstance(adjusted, pd.Series):
        adjusted = adjusted.to_frame(name=tickers[0])
    adjusted.index = pd.to_datetime(adjusted.index, errors="coerce").tz_localize(None)
    return adjusted.loc[adjusted.index.notna()].sort_index()


def download_adjusted_close(
    tickers: list[str], *, start: object, end: object, attempts: int = 3
) -> pd.DataFrame:
    """Download a complete market panel with bounded batch and symbol retries."""

    collected = pd.DataFrame()
    transport_errors: list[str] = []
    for attempt in range(attempts):
        try:
            batch = yf.download(
                tickers,
                start=start,
                end=end,
                auto_adjust=False,
                progress=False,
                threads=False,
            )
            candidate = _adjusted_close_frame(batch, tickers)
            if not candidate.empty:
                collected = candidate.combine_first(collected)
        except Exception as error:  # yfinance exposes several transport exception types
            transport_errors.append(f"batch attempt {attempt + 1}: {type(error).__name__}")

        missing = [
            ticker
            for ticker in tickers
            if ticker not in collected or collected[ticker].dropna().empty
        ]
        for ticker in missing:
            try:
                single = yf.download(
                    ticker,
                    start=start,
                    end=end,
                    auto_adjust=False,
                    progress=False,
                    threads=False,
                )
                frame = _adjusted_close_frame(single, [ticker])
                if not frame.empty:
                    collected = frame.combine_first(collected)
            except Exception as error:
                transport_errors.append(
                    f"{ticker} attempt {attempt + 1}: {type(error).__name__}"
                )
        if not [
            ticker
            for ticker in tickers
            if ticker not in collected or collected[ticker].dropna().empty
        ]:
            return collected.reindex(columns=tickers).sort_index()
        if attempt < attempts - 1:
            time.sleep(2**attempt)
    missing = [
        ticker
        for ticker in tickers
        if ticker not in collected or collected[ticker].dropna().empty
    ]
    error_detail = "; ".join(transport_errors[-5:]) or "no provider exception detail"
    raise ValueError(
        f"Market download is incomplete after retries: {', '.join(missing)}. "
        f"Recent provider errors: {error_detail}"
    )


def build(as_of_text: str, output: Path) -> None:
    as_of = pd.Timestamp(as_of_text, tz="America/New_York")
    retrieved_at = datetime.now(timezone.utc)
    retrieved = retrieved_at.isoformat()
    retrieved_et = pd.Timestamp(retrieved_at).tz_convert("America/New_York")
    if as_of > retrieved_et + pd.Timedelta(minutes=5):
        raise ValueError("Information cutoff cannot be later than the actual retrieval time")
    stage = Path(tempfile.mkdtemp(prefix="liquidity-liquidity-live-", dir=output.parent))
    raw = stage / "raw"
    raw.mkdir(parents=True)
    source_rows: list[dict] = []
    histories: dict[str, pd.Series] = {}
    try:
        release_calendars: dict[str, pd.DatetimeIndex] = {}
        for release, url in FEDERAL_RESERVE_RELEASE_DATES.items():
            print(f"Fetching official {release.upper()} release calendar", flush=True)
            response = get(url)
            (raw / f"federalreserve_{release}_release_dates.json").write_bytes(
                response.content
            )
            release_calendars[release] = parse_federal_reserve_release_dates(
                response.json(), release=release
            )

        def expected(field: str) -> tuple[pd.Timestamp, str]:
            return expected_observation_date(
                field, as_of, release_calendars=release_calendars
            )

        def current_status(
            field: str, observation: pd.Timestamp, values: pd.Series
        ) -> tuple[str, str]:
            return status_for(
                field,
                observation,
                values,
                as_of,
                release_calendars=release_calendars,
            )

        for field, (label, series_id, provider, unit, scale) in SPECS.items():
            print(f"Fetching {series_id} for {field}", flush=True)
            history, metadata = fred_series(series_id, raw)
            cutoff = expected(field)[0]
            history = history.loc[history.index <= cutoff].mul(scale)
            if history.empty:
                raise ValueError(
                    f"{field} has no observation by its publication-clock cutoff"
                )
            histories[field] = history
            observation = pd.Timestamp(history.index[-1])
            status, note = current_status(field, observation, history)
            source_rows.append({
                "field": field, "series": label, "source_key": series_id, "provider": provider,
                "value": float(history.iloc[-1]), "unit": unit, "observation_date": observation.date(),
                "expected_observation_date": expected(field)[0].date(), "verified_through": as_of.date(),
                "retrieved_at_utc": retrieved, "status": status, "status_detail": note, "source_url": metadata["url"],
                "raw_sha256": metadata["raw_sha256"],
            })

        for series_id in REFERENCE_SPECS:
            print(f"Fetching {series_id} reference history", flush=True)
            fred_series(series_id, raw)

        treasury_response = get(TREASURY, params={
            "filter": f"record_date:gte:{(as_of - pd.Timedelta(days=45)).date()},record_date:lte:{as_of.date()}",
            "sort": "record_date,src_line_nbr", "page[size]": 1000,
        })
        (raw / "treasury_tga.json").write_bytes(treasury_response.content)
        treasury_rows = treasury_response.json()["data"]
        treasury = pd.DataFrame(treasury_rows)
        treasury = treasury.loc[treasury["account_type"].eq("Treasury General Account (TGA) Closing Balance")].copy()
        treasury["record_date"] = pd.to_datetime(treasury["record_date"])
        treasury["value"] = pd.to_numeric(treasury["open_today_bal"], errors="raise") * 0.001
        if treasury["record_date"].duplicated().any():
            raise ValueError("Daily Treasury Statement TGA contains duplicate dates")
        tga = treasury.sort_values("record_date").set_index("record_date")["value"]
        observation = pd.Timestamp(tga.index[-1])
        status, note = current_status("tga_dts_bn", observation, tga)
        histories["tga_dts_bn"] = tga
        source_rows.append({
            "field": "tga_dts_bn", "series": "Treasury cash balance (daily)", "source_key": "TGA_DTS",
            "provider": "U.S. Treasury Daily Treasury Statement", "value": float(tga.iloc[-1]), "unit": "USD billions",
            "observation_date": observation.date(), "expected_observation_date": expected("tga_dts_bn")[0].date(),
            "verified_through": as_of.date(), "retrieved_at_utc": retrieved, "status": status, "status_detail": note,
            "source_url": treasury_response.url, "raw_sha256": sha256_bytes(treasury_response.content),
        })

        for rate_name in ("sofr", "tgcr", "bgcr"):
            rate_response = get(
                NYFED_RATE.format(rate=rate_name),
                params={
                    "startDate": (as_of - pd.Timedelta(days=3653)).date(),
                    "endDate": as_of.date(),
                },
            )
            (raw / f"nyfed_{rate_name}.json").write_bytes(rate_response.content)
            rate_frame = pd.DataFrame(rate_response.json()["refRates"])
            rate_frame["date"] = pd.to_datetime(rate_frame["effectiveDate"])
            rate_frame["value"] = pd.to_numeric(rate_frame["percentRate"])
            if rate_frame["date"].duplicated().any():
                raise ValueError(
                    f"New York Fed {rate_name.upper()} payload contains duplicate dates"
                )
            rate_series = rate_frame.sort_values("date").set_index("date")["value"]
            rate_series = rate_series.loc[rate_series.index <= expected(rate_name)[0]]
            observation = pd.Timestamp(rate_series.index[-1])
            status, note = current_status(rate_name, observation, rate_series)
            histories[rate_name] = rate_series
            source_rows.append({
                "field": rate_name, "series": rate_name.upper(), "source_key": f"{rate_name.upper()}_NYFED",
                "provider": "Federal Reserve Bank of New York", "value": float(rate_series.iloc[-1]),
                "unit": "percent", "observation_date": observation.date(),
                "expected_observation_date": expected(rate_name)[0].date(), "verified_through": as_of.date(),
                "retrieved_at_utc": retrieved, "status": status, "status_detail": note,
                "source_url": rate_response.url, "raw_sha256": sha256_bytes(rate_response.content),
            })

        fedwire_page = get(FEDWIRE_PAGE)
        (raw / "fedwire_monthly.html").write_bytes(fedwire_page.content)
        link_match = pd.Series(
            __import__("re").findall(r'href="([^"]*monthly[^"?]*ascii\.txt)"', fedwire_page.text, flags=__import__("re").I)
        )
        if link_match.empty:
            raise ValueError("Fedwire monthly-statistics page does not expose the ASCII source")
        fedwire_url = requests.compat.urljoin(FEDWIRE_PAGE, str(link_match.iloc[0]))
        fedwire_response = get(fedwire_url)
        (raw / "fedwire_monthly.txt").write_bytes(fedwire_response.content)
        month_numbers = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12}
        fedwire_records = []
        for line in fedwire_response.text.splitlines():
            match = __import__("re").match(r"^\s*(\d{4}):\s*([A-Za-z]+)\s+(.+)$", line)
            if not match:
                continue
            month = month_numbers.get(match.group(2).lower()[:4], month_numbers.get(match.group(2).lower()[:3]))
            values = __import__("re").findall(r"\(?-?[\d,]+(?:\.\d+)?\)?", match.group(3))
            if month and len(values) >= 2:
                value_bn = float(values[-1].replace(",", "").strip("()")) * 0.001
                date = pd.Timestamp(year=int(match.group(1)), month=month, day=1) + pd.offsets.MonthEnd(0)
                fedwire_records.append((date, value_bn))
        if not fedwire_records:
            raise ValueError("Fedwire monthly source has no parseable observations")
        fedwire_dates = [date for date, _value in fedwire_records]
        if len(fedwire_dates) != len(set(fedwire_dates)):
            raise ValueError("Fedwire monthly source contains duplicate months")
        fedwire = pd.Series(dict(fedwire_records)).sort_index()
        fedwire = fedwire.loc[fedwire.index <= expected("fedwire_daily_value_bn")[0]]
        observation = pd.Timestamp(fedwire.index[-1])
        status, note = current_status("fedwire_daily_value_bn", observation, fedwire)
        histories["fedwire_daily_value_bn"] = fedwire
        source_rows.append({
            "field": "fedwire_daily_value_bn", "series": "Fedwire average daily payment value",
            "source_key": "FEDWIRE_MONTHLY_FUNDS", "provider": "Federal Reserve Financial Services",
            "value": float(fedwire.iloc[-1]), "unit": "USD billions per business day",
            "observation_date": observation.date(), "expected_observation_date": expected("fedwire_daily_value_bn")[0].date(),
            "verified_through": as_of.date(), "retrieved_at_utc": retrieved, "status": status,
            "status_detail": note, "source_url": fedwire_url,
            "raw_sha256": sha256_bytes(fedwire_response.content),
        })

        tickers = ["SPY", *SECTORS, *MARKET_CONFIRMATION]
        adjusted = download_adjusted_close(
            tickers,
            start=(as_of - pd.Timedelta(days=3653)).date(),
            end=(as_of + pd.Timedelta(days=1)).date(),
        )
        adjusted = adjusted.dropna(how="all").sort_index()
        if adjusted.index.has_duplicates:
            raise ValueError("Market download contains duplicate session dates")
        adjusted = adjusted.loc[adjusted.index <= expected("market")[0]]
        if adjusted.empty or set(tickers).difference(adjusted.columns):
            raise ValueError("Market download is incomplete")
        adjusted.to_csv(raw / "market_adjusted_close.csv", index_label="date")
        complete_adjusted = adjusted.dropna(subset=tickers)
        if complete_adjusted.empty:
            raise ValueError("Market instruments do not share a complete close date")
        market_date = pd.Timestamp(complete_adjusted.index[-1])
        market_status, market_note = current_status("market", market_date, adjusted["SPY"])
        market_raw_hash = sha256_file(raw / "market_adjusted_close.csv")
        source_rows.append({
            "field": "market", "series": "Market context inputs", "source_key": "18 instruments; legacy 9-sector breadth",
            "provider": "Yahoo Finance", "value": float(adjusted.loc[market_date, "SPY"]), "unit": "USD price",
            "observation_date": market_date.date(), "expected_observation_date": expected("market")[0].date(),
            "verified_through": as_of.date(), "retrieved_at_utc": retrieved, "status": market_status,
            "status_detail": market_note + f"; all {len(tickers)} instruments share the same close date",
            "source_url": "https://finance.yahoo.com/quote/SPY/history/", "raw_sha256": market_raw_hash,
        })

        reference_date = pd.Timestamp(histories["reserves_bn"].index[-1])
        assets_lag_4 = asof_value(histories["assets_bn"], reference_date - pd.Timedelta(days=28))
        assets_lag_13 = asof_value(histories["assets_bn"], reference_date - pd.Timedelta(days=91))
        def change(field: str, days: int) -> float:
            series = histories[field]
            # Every contribution uses the reserve observation's common clock.
            # Faster series can still display a newer current level, but they
            # must not leak an extra day into the accounting decomposition.
            return float(
                asof_value(series, reference_date)
                - asof_value(series, reference_date - pd.Timedelta(days=days))
            )
        reserve4 = change("reserves_bn", 28) / assets_lag_4 * 10000
        reserve13 = change("reserves_bn", 91) / assets_lag_13 * 10000
        fed4 = change("assets_bn", 28) / assets_lag_4 * 10000
        tga4 = change("tga_h41_bn", 28) / assets_lag_4 * 10000
        rrp4 = change("onrrp_bn", 28) / assets_lag_4 * 10000
        currency4 = change("currency_bn", 28) / assets_lag_4 * 10000
        known4 = fed4 - tga4 - rrp4 - currency4
        sector_px = complete_adjusted[SECTORS]
        sector_breadth = float((sector_px.loc[market_date] > sector_px.rolling(50).mean().loc[market_date]).mean())
        breadth_history = (sector_px > sector_px.rolling(50).mean()).mean(axis=1)
        sofr_payload = pd.DataFrame(json.loads((raw / "nyfed_sofr.json").read_text(encoding="utf-8"))["refRates"])
        sofr_payload["date"] = pd.to_datetime(sofr_payload["effectiveDate"])
        sofr_payload = sofr_payload.loc[sofr_payload["date"].le(pd.Timestamp(histories["sofr"].index[-1]))].sort_values("date")
        sofr_iqr_bp = float(
            (pd.to_numeric(sofr_payload.iloc[-1]["percentPercentile75"]) - pd.to_numeric(sofr_payload.iloc[-1]["percentPercentile25"])) * 100
        )
        state = pd.DataFrame([{
            "as_of_date": as_of.date(), "retrieved_at_utc": retrieved,
            "accounting_asof_date": reference_date.date(), "market_asof_date": market_date.date(),
            "spy_adj_close": float(complete_adjusted.loc[market_date, "SPY"]),
            "spy_mom60": float((complete_adjusted["SPY"].iloc[-1] / complete_adjusted["SPY"].iloc[-61] - 1) * 100),
            "spy_dist200": float((complete_adjusted["SPY"].iloc[-1] / complete_adjusted["SPY"].rolling(200).mean().iloc[-1] - 1) * 100),
            "sector_breadth50": sector_breadth,
            "sector_breadth50_change20": float(sector_breadth - breadth_history.iloc[-21]),
            "reserve_impulse_4w_bp": reserve4, "reserve_impulse_13w_bp": reserve13,
            "tga_change_4w_bp_assets": tga4, "onrrp_change_4w_bp_assets": rrp4,
            "fed_asset_change_4w_bp": fed4, "currency_change_4w_bp_assets": currency4,
            "accounting_known_impulse_4w_bp": known4,
            "other_liability_residual_4w_bp": reserve4 - known4,
            "baa10y": float(histories["baa10y"].iloc[-1]), "vix": float(histories["vix"].iloc[-1]),
            "reserves_bn": float(histories["reserves_bn"].iloc[-1]), "assets_bn": float(histories["assets_bn"].iloc[-1]),
            "tga_h41_bn": float(histories["tga_h41_bn"].iloc[-1]),
            "tga_dts_bn": float(histories["tga_dts_bn"].iloc[-1]), "onrrp_bn": float(histories["onrrp_bn"].iloc[-1]),
            "currency_bn": float(histories["currency_bn"].iloc[-1]), "sofr": float(histories["sofr"].iloc[-1]),
            "iorb": float(histories["iorb"].iloc[-1]),
            "sofr_admin_bp": matched_admin_spread_bp(histories["sofr"], histories["iorb"]),
            "deposits_bn": float(histories["deposits_bn"].iloc[-1]),
            "reserve_deposit_pct": float(histories["reserves_bn"].iloc[-1] / histories["deposits_bn"].iloc[-1] * 100),
            "bank_assets_bn": float(histories["bank_assets_bn"].iloc[-1]),
            "bank_cash_bn": float(histories["bank_cash_bn"].iloc[-1]),
            "large_bank_assets_bn": float(histories["large_bank_assets_bn"].iloc[-1]),
            "large_bank_cash_bn": float(histories["large_bank_cash_bn"].iloc[-1]),
            "small_bank_assets_bn": float(histories["small_bank_assets_bn"].iloc[-1]),
            "small_bank_cash_bn": float(histories["small_bank_cash_bn"].iloc[-1]),
            "bank_credit_bn": float(histories["bank_credit_bn"].iloc[-1]),
            "fedwire_daily_value_bn": float(histories["fedwire_daily_value_bn"].iloc[-1]),
            "effr": float(histories["effr"].iloc[-1]),
            "effr_admin_bp": matched_admin_spread_bp(histories["effr"], histories["iorb"]),
            "tgcr": float(histories["tgcr"].iloc[-1]),
            "tgcr_admin_bp": matched_admin_spread_bp(histories["tgcr"], histories["iorb"]),
            "bgcr": float(histories["bgcr"].iloc[-1]),
            "bgcr_admin_bp": matched_admin_spread_bp(histories["bgcr"], histories["iorb"]),
            "sofr_iqr_bp": sofr_iqr_bp,
            "repo_add_bn": float(histories["repo_add_bn"].iloc[-1]),
            "hy_oas": float(histories["hy_oas"].iloc[-1]),
            "ig_oas": float(histories["ig_oas"].iloc[-1]),
            "broad_usd": float(histories["broad_usd"].iloc[-1]),
            "real_yield_10y": float(histories["real_yield_10y"].iloc[-1]),
        }])
        source_frame = pd.DataFrame(source_rows).sort_values("field")
        state.to_csv(stage / "current_state.csv", index=False)
        source_frame.to_csv(stage / "source_status.csv", index=False)
        required = [
            "reserves_bn", "assets_bn", "tga_h41_bn", "tga_dts_bn", "onrrp_bn",
            "currency_bn", "baa10y", "vix", "sofr", "iorb", "deposits_bn",
            "effr", "hy_oas", "ig_oas", "broad_usd", "real_yield_10y", "market",
            "bank_assets_bn", "bank_cash_bn", "large_bank_assets_bn", "large_bank_cash_bn",
            "small_bank_assets_bn", "small_bank_cash_bn", "bank_credit_bn",
            "fedwire_daily_value_bn", "tgcr", "bgcr", "repo_add_bn",
        ]
        implementation_files = {
            relative_path: sha256_file(ROOT / relative_path)
            for relative_path in MODEL_IMPLEMENTATION_FILES
        }
        implementation_bundle_sha256 = sha256_bytes(
            json.dumps(
                sorted(implementation_files.items()), separators=(",", ":")
            ).encode("utf-8")
        )
        manifest = {
            "schema_version": "3.0.0", "release_id": f"US-LIQ-LIVE-{as_of.date()}",
            "as_of_et": as_of.isoformat(), "information_cutoff_et": as_of.isoformat(),
            "retrieved_at_utc": retrieved,
            "purpose": "point-in-time U.S. liquidity conditions release for discretionary regime monitoring; not a standalone trading model",
            "required_sources": required,
            "all_sources_current": bool(
                source_frame["status"].isin(CURRENT_SOURCE_STATUSES).all()
            ),
            "model_spec": {
                "version": MODEL_VERSION,
                "model_code_sha256": implementation_files[
                    "liquidity_monitor/us_liquidity_model.py"
                ],
                "implementation_files": implementation_files,
                "implementation_bundle_sha256": implementation_bundle_sha256,
                "weights": dict(LIQUIDITY_LAYER_WEIGHTS),
                "component_clip": 3.0,
                "index_thresholds": [35.0, 65.0],
                "deposit_publication_lag_days": 9,
                "fedwire_publication_lag_days": 25,
                "headline_filter_span_weeks": 4,
                "model_observation_clock": "Friday 16:30 America/New_York",
            },
            "files": {},
        }
        if not manifest["all_sources_current"]:
            stale = source_frame.loc[
                ~source_frame["status"].isin(CURRENT_SOURCE_STATUSES),
                ["field", "observation_date", "expected_observation_date", "status"],
            ]
            raise ValueError(
                "Refusing to replace the last-good liquidity snapshot because required "
                f"sources are not current: {stale.to_dict('records')}"
            )
        for filename in ("current_state.csv", "source_status.csv"):
            path = stage / filename
            frame = pd.read_csv(path)
            manifest["files"][filename] = {"sha256": sha256_file(path), "rows": len(frame), "columns": len(frame.columns)}
        manifest["raw_files"] = [{"path": str(path.relative_to(stage)), "sha256": sha256_file(path)} for path in sorted(raw.iterdir())]
        (stage / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        staged_snapshot = load_live_snapshot(stage, verify_hashes=True)
        build_us_liquidity_model(staged_snapshot)
        backup = output.with_name(output.name + ".previous")
        if backup.exists():
            shutil.rmtree(backup)
        if output.exists():
            output.rename(backup)
        stage.rename(output)
        if backup.exists():
            shutil.rmtree(backup)
        print(json.dumps({"release_id": manifest["release_id"], "all_sources_current": manifest["all_sources_current"], "source_status": source_frame[["field", "observation_date", "status"]].to_dict("records")}, indent=2, default=str))
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--as-of",
        default=pd.Timestamp.now(tz="America/New_York").strftime("%Y-%m-%d %H:%M:%S"),
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    build(args.as_of, args.output)
