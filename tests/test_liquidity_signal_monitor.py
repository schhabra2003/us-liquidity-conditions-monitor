"""Release tests for the liquidity decision tool and its signed data bundle."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd
from streamlit.testing.v1 import AppTest

from liquidity_monitor.liquidity_live_snapshot import (
    FEDERAL_RESERVE_DAY,
    GOVERNMENT_SECURITIES_DAY,
    MODEL_IMPLEMENTATION_FILES,
    load_live_snapshot,
    snapshot_is_current,
)
from liquidity_monitor.liquidity_signal_monitor import (
    current_mechanics_figure,
    diagnostic_summary,
    domain_diagnostic_figure,
    liquidity_impulse_figure,
    live_source_status_table,
    load_liquidity_bundle,
    model_output_permitted,
    observed_regime_classifier,
    source_status_table,
)
from liquidity_monitor.structural_liquidity import (
    STRUCTURAL_WEIGHTS,
    build_structural_liquidity,
    classify_structural_regime,
    funding_conditions_figure,
    market_confirmation_figure,
    market_confirmation_snapshot,
    structural_components_figure,
    structural_history_figure,
    transmission_conditions_figure,
    transmission_snapshot,
)
from liquidity_monitor.us_liquidity_model import (
    LIQUIDITY_LAYER_WEIGHTS,
    _classify_direction,
    _prior_seasonal_expectation,
    _reference_rate_publication_availability,
    _require_latest_finite,
    _safe_positive_ratio,
    _smooth,
    build_us_liquidity_model,
    classify_absolute_funding,
    classify_liquidity_regime,
    funding_market_figure,
    liquidity_conditions_history_figure,
    liquidity_deviation_figure,
    liquidity_layers_figure,
)

ROOT = Path(__file__).resolve().parents[1]
BUNDLE_ROOT = ROOT / "data" / "liquidity_model_bundle"
LIVE_ROOT = ROOT / "data" / "liquidity_live_snapshot"

# Independent test oracle copied from the frozen, hash-pinned 2026 calibration.
# Do not import the production transform: this test must fail if production
# coefficients, clipping, signs, or aggregation change unexpectedly.
REFERENCE_MARKET_CONTEXT_TRANSFORM_2026 = {
    "baa10y": (1.41935, 5.861300000000002, 2.26, 0.9625),
    "baa10y_change20": (
        -0.7299999999999995,
        1.1013000000000015,
        -0.0100000000000002,
        0.1699999999999996,
    ),
    "sector_breadth50": (0.0, 1.0, 0.7777777777777778, 0.4444444444444444),
    "sector_breadth50_change20": (
        -1.0,
        0.8961111111111171,
        0.0,
        0.4444444444444444,
    ),
    "spy_dist200": (
        -28.222736936122384,
        18.48441332111313,
        5.77742572982406,
        7.535797614813812,
    ),
    "spy_mom60": (
        -26.526989976726775,
        22.17994028963968,
        3.762237452751072,
        7.765360166842891,
    ),
    "vix": (
        9.86635,
        63.69560000000001,
        16.685000000000002,
        8.092499999999998,
    ),
    "vix_change5": (
        -10.015200000000004,
        15.2192000000002,
        -0.1750000000000007,
        2.5850000000000013,
    ),
    "reserve_impulse_4w_bp": (
        -702.135156907704,
        1844.1813220890847,
        7.54160315296838,
        220.4015575992641,
    ),
}


def _raw_fred_series(root: Path, series_id: str, scale: float = 1.0) -> pd.Series:
    frame = pd.read_csv(root / "raw" / f"fred_{series_id}.csv", na_values=["."])
    frame.columns = ["date", "value"]
    frame["date"] = pd.to_datetime(frame["date"], errors="raise")
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce") * scale
    return (
        frame.dropna().drop_duplicates("date").set_index("date")["value"].sort_index()
    )


def _asof_value(series: pd.Series, date: pd.Timestamp) -> float:
    eligible = series.loc[series.index <= date]
    if eligible.empty:
        raise AssertionError(f"No source observation is available by {date.date()}")
    return float(eligible.iloc[-1])


def _independent_accounting_reference(snapshot) -> dict[str, float]:
    reference = pd.Timestamp(snapshot.state.iloc[0]["accounting_asof_date"])
    start_4w = reference - pd.Timedelta(days=28)
    histories = {
        "reserves": _raw_fred_series(snapshot.root, "WRBWFRBL", 0.001),
        "assets": _raw_fred_series(snapshot.root, "WALCL", 0.001),
        "tga": _raw_fred_series(snapshot.root, "WDTGAL", 0.001),
        "onrrp": _raw_fred_series(snapshot.root, "RRPONTSYD"),
        "currency": _raw_fred_series(snapshot.root, "WCURCIR", 0.001),
    }
    denominator = _asof_value(histories["assets"], start_4w)
    changes = {
        name: (_asof_value(series, reference) - _asof_value(series, start_4w))
        / denominator
        * 10_000
        for name, series in histories.items()
    }
    known = changes["assets"] - changes["tga"] - changes["onrrp"] - changes["currency"]
    return {
        "reserve_impulse_4w_bp": changes["reserves"],
        "fed_asset_change_4w_bp": changes["assets"],
        "tga_change_4w_bp_assets": changes["tga"],
        "onrrp_change_4w_bp_assets": changes["onrrp"],
        "currency_change_4w_bp_assets": changes["currency"],
        "accounting_known_impulse_4w_bp": known,
        "other_liability_residual_4w_bp": changes["reserves"] - known,
    }


def _independent_market_reference(snapshot) -> dict[str, object]:
    tickers = [
        "SPY",
        "XLB",
        "XLE",
        "XLF",
        "XLI",
        "XLK",
        "XLP",
        "XLU",
        "XLV",
        "XLY",
        "QQQ",
        "RSP",
        "IWM",
        "ARKK",
        "XBI",
        "KRE",
        "BTC-USD",
        "EEM",
    ]
    market = pd.read_csv(
        snapshot.root / "raw" / "market_adjusted_close.csv", parse_dates=["date"]
    ).set_index("date")
    cutoff = pd.Timestamp(
        snapshot.sources.set_index("field").loc["market", "observation_date"]
    )
    complete = market.loc[market.index <= cutoff].dropna(subset=tickers)
    if complete.empty or complete.index[-1] != cutoff:
        raise AssertionError(
            "Market reference lacks a complete row at the release cutoff"
        )
    sectors = ["XLB", "XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY"]
    breadth = (complete[sectors] > complete[sectors].rolling(50).mean()).mean(axis=1)
    return {
        "date": cutoff,
        "spy_adj_close": float(complete["SPY"].iloc[-1]),
        "spy_mom60": float(
            (complete["SPY"].iloc[-1] / complete["SPY"].iloc[-61] - 1) * 100
        ),
        "spy_dist200": float(
            (
                complete["SPY"].iloc[-1] / complete["SPY"].rolling(200).mean().iloc[-1]
                - 1
            )
            * 100
        ),
        "sector_breadth50": float(breadth.iloc[-1]),
        "sector_breadth50_change20": float(breadth.iloc[-1] - breadth.iloc[-21]),
    }


def _independent_market_context_vector(bundle, snapshot) -> np.ndarray:
    market = _independent_market_reference(snapshot)
    current_date = pd.Timestamp(market["date"])
    weekly = bundle.weekly.sort_values("signal_date")

    def lagged_weekly(column: str, calendar_days: int) -> float:
        eligible = weekly.loc[
            weekly["signal_date"].le(current_date - pd.Timedelta(days=calendar_days))
        ]
        if eligible.empty:
            raise AssertionError(f"No lagged reference is available for {column}")
        return float(eligible.iloc[-1][column])

    source_rows = snapshot.sources.set_index("field")
    baa_date = pd.Timestamp(source_rows.loc["baa10y", "observation_date"])
    vix_date = pd.Timestamp(source_rows.loc["vix", "observation_date"])
    baa10y = float(_raw_fred_series(snapshot.root, "BAA10Y").loc[baa_date])
    vix = float(_raw_fred_series(snapshot.root, "VIXCLS").loc[vix_date])
    raw = {
        "spy_mom60": float(market["spy_mom60"]),
        "spy_dist200": float(market["spy_dist200"]),
        "sector_breadth50": float(market["sector_breadth50"]),
        "sector_breadth50_change20": float(market["sector_breadth50_change20"]),
        "baa10y": baa10y,
        "baa10y_change20": baa10y - lagged_weekly("baa10y", 28),
        "vix": vix,
        "vix_change5": vix - lagged_weekly("vix", 7),
        "reserve_impulse_4w_bp": _independent_accounting_reference(snapshot)[
            "reserve_impulse_4w_bp"
        ],
    }
    normalized = {}
    for field, value in raw.items():
        lower, upper, median, scale = REFERENCE_MARKET_CONTEXT_TRANSFORM_2026[field]
        normalized[field] = (np.clip(value, lower, upper) - median) / scale
    trend = -np.mean([normalized["spy_mom60"], normalized["spy_dist200"]])
    credit = np.mean([normalized["baa10y"], normalized["baa10y_change20"]])
    breadth = -np.mean(
        [
            normalized["sector_breadth50"],
            normalized["sector_breadth50_change20"],
        ]
    )
    volatility = np.mean([normalized["vix"], normalized["vix_change5"]])
    fragility = np.mean([trend, credit, breadth, volatility])
    drain = -normalized["reserve_impulse_4w_bp"]
    interaction = max(drain, 0.0) * max(fragility, 0.0)
    return np.asarray(
        [trend, credit, breadth, volatility, fragility, drain, interaction],
        dtype=float,
    )


class LiquidityBundleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.bundle = load_liquidity_bundle(BUNDLE_ROOT, verify_hashes=True)

    def test_bundle_is_complete_and_checksum_verified(self) -> None:
        self.assertEqual(self.bundle.manifest["schema_version"], "1.0.0")
        self.assertEqual(len(self.bundle.validation_gates), 22)
        self.assertGreaterEqual(len(self.bundle.weekly), 500)
        expected_tables = {
            "annual_inference.csv",
            "current_state.csv",
            "manager_state_card.csv",
            "model_predictions.csv",
            "validation_gates.csv",
            "validation_metrics.csv",
            "warning_diagnostics.csv",
            "weekly_state.csv",
        }
        self.assertEqual(set(self.bundle.manifest["files"]), expected_tables)
        self.assertEqual(
            {path.name for path in BUNDLE_ROOT.glob("*.csv")}, expected_tables
        )
        self.assertEqual(
            self.bundle.manifest["expected_liquidity_path_status"], "NOT_PACKAGED"
        )

    def test_failed_release_suppresses_directional_output(self) -> None:
        self.assertFalse(model_output_permitted(self.bundle))
        summary = diagnostic_summary(self.bundle)
        self.assertFalse(summary["output_permitted"])
        self.assertEqual(summary["direction"], "SUPPRESSED")
        self.assertEqual(summary["gates_passed"], 15)
        self.assertEqual(summary["gates_total"], 22)

    def test_observed_regime_classifier_covers_all_nine_states(self) -> None:
        expected = {
            (20.0, 20.0): (
                "below_normal",
                "improving",
                "Below-normal reserve flow, improving",
            ),
            (50.0, 20.0): (
                "near_normal",
                "improving",
                "Typical reserve flow, improving",
            ),
            (80.0, 20.0): (
                "above_normal",
                "improving",
                "Above-normal reserve flow, improving",
            ),
            (20.0, 0.0): (
                "below_normal",
                "stable",
                "Below-normal reserve flow, broadly stable",
            ),
            (50.0, 0.0): (
                "near_normal",
                "stable",
                "Typical reserve flow, broadly stable",
            ),
            (80.0, 0.0): (
                "above_normal",
                "stable",
                "Above-normal reserve flow, broadly stable",
            ),
            (20.0, -20.0): (
                "below_normal",
                "deteriorating",
                "Below-normal reserve flow, deteriorating",
            ),
            (50.0, -20.0): (
                "near_normal",
                "deteriorating",
                "Typical reserve flow, deteriorating",
            ),
            (80.0, -20.0): (
                "above_normal",
                "deteriorating",
                "Above-normal reserve flow, deteriorating",
            ),
        }
        for inputs, outputs in expected.items():
            with self.subTest(inputs=inputs):
                result = observed_regime_classifier(*inputs, 10.0)
                self.assertTrue(result["available"])
                self.assertEqual(
                    (
                        result["level_code"],
                        result["trend_code"],
                        result["regime_label"],
                    ),
                    outputs,
                )

    def test_observed_regime_classifier_boundaries_and_invalid_values(self) -> None:
        self.assertEqual(
            observed_regime_classifier(39.99, 10.01, 10.0)["level_code"], "below_normal"
        )
        self.assertEqual(
            observed_regime_classifier(40.0, 10.0, 10.0)["level_code"], "near_normal"
        )
        self.assertEqual(
            observed_regime_classifier(60.0, -10.0, 10.0)["level_code"], "near_normal"
        )
        self.assertEqual(
            observed_regime_classifier(60.01, -10.01, 10.0)["level_code"],
            "above_normal",
        )
        self.assertEqual(
            observed_regime_classifier(50.0, 10.0, 10.0)["trend_code"], "stable"
        )
        self.assertEqual(
            observed_regime_classifier(50.0, -10.0, 10.0)["trend_code"], "stable"
        )
        self.assertFalse(observed_regime_classifier(np.nan, 0.0, 10.0)["available"])
        self.assertFalse(observed_regime_classifier(50.0, 0.0, np.nan)["available"])

    def test_permission_check_rejects_truthy_strings_and_truncated_gate_ledgers(
        self,
    ) -> None:
        current = self.bundle.current_state.copy()
        current["ordinal_state_permitted"] = current["ordinal_state_permitted"].astype(
            object
        )
        current["primary_gates_pass"] = current["primary_gates_pass"].astype(object)
        current.loc[:, "ordinal_state_permitted"] = "False"
        current.loc[:, "primary_gates_pass"] = "False"
        malformed = replace(self.bundle, current_state=current)
        self.assertFalse(model_output_permitted(malformed))

        truncated = replace(
            self.bundle, validation_gates=self.bundle.validation_gates.iloc[:1].copy()
        )
        self.assertFalse(model_output_permitted(truncated))

    def test_permission_requires_passing_manager_controls(self) -> None:
        current = self.bundle.current_state.copy()
        for column in ("ordinal_state_permitted", "primary_gates_pass"):
            current[column] = True
        current.loc[:, "state"] = "Green"
        current.loc[:, "directional_inference"] = "RISK_ON"
        gates = self.bundle.validation_gates.copy()
        gates.loc[:, "passed"] = True
        manager = self.bundle.manager_state.copy()
        manager.loc[:, "state"] = "Green"
        manager.loc[:, "directional_inference"] = "RISK_ON"
        manager.loc[:, "model_validity"] = "PASSED_PREDICTIVE_GATE"
        manager.loc[:, "data_quality"] = "PASS"
        manifest = dict(self.bundle.manifest)
        manifest["parent_release"] = dict(manifest["parent_release"])
        manifest["parent_release"]["release_class"] = "PRODUCTION_CERTIFIED"
        manifest["parent_release"]["manager_state_card_status"] = "PARENT_HASH_PINNED"
        manifest["release_state"] = "Green"
        manifest["directional_inference"] = "RISK_ON"
        manifest["expected_liquidity_path_status"] = "AVAILABLE_POINT_IN_TIME"
        candidate = replace(
            self.bundle,
            manifest=manifest,
            current_state=current,
            validation_gates=gates,
            manager_state=manager,
        )
        as_of = pd.Timestamp("2026-08-27")
        self.assertFalse(model_output_permitted(candidate, current_time=as_of))

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "bundle"
            shutil.copytree(BUNDLE_ROOT, target)
            realized = float(
                self.bundle.weekly.sort_values("signal_date").iloc[-1][
                    "reserve_impulse_4w_bp"
                ]
            )
            expected_path = target / "expected_liquidity_path.csv"
            pd.DataFrame(
                [
                    {
                        "signal_date": "2026-08-27",
                        "expectation_vintage": "2026-08-20",
                        "forecast_horizon_end": "2026-08-27",
                        "expected_reserve_impulse_4w_bp": -50.0,
                        "realized_reserve_impulse_4w_bp": realized,
                        "liquidity_surprise_bp": realized + 50.0,
                        "methodology_id": "frozen-test-v1",
                    }
                ]
            ).to_csv(expected_path, index=False)
            expected_hash = hashlib.sha256(expected_path.read_bytes()).hexdigest()
            manager_path = target / "manager_state_card.csv"
            manager_hash = hashlib.sha256(manager_path.read_bytes()).hexdigest()
            parent_path = target / "parent_release_manifest.json"
            parent_manifest = json.loads(parent_path.read_text(encoding="utf-8"))
            parent_manifest["artifacts"].extend(
                [
                    {
                        "path": "results/expected_liquidity_path.csv",
                        "sha256": expected_hash,
                    },
                    {
                        "path": "results/manager_state_card.csv",
                        "sha256": manager_hash,
                    },
                ]
            )
            parent_path.write_text(json.dumps(parent_manifest), encoding="utf-8")
            manifest["expected_liquidity_path"] = {
                "file": expected_path.name,
                "sha256": expected_hash,
                "rows": 1,
                "columns": 7,
                "parent_artifact_path": "results/expected_liquidity_path.csv",
            }
            fully_pinned = replace(candidate, root=target, manifest=manifest)
            self.assertTrue(model_output_permitted(fully_pinned, current_time=as_of))
            published = diagnostic_summary(fully_pinned, current_time=as_of)
            self.assertTrue(published["output_permitted"])
            self.assertTrue(published["expected_path_available"])
            self.assertEqual(published["surprise_state"], "Positive")
            self.assertAlmostEqual(published["liquidity_surprise_bp"], realized + 50.0)

            manager.loc[:, "model_validity"] = "FAILED_PREDICTIVE_GATE"
            failed_manager = replace(fully_pinned, manager_state=manager)
            self.assertFalse(model_output_permitted(failed_manager, current_time=as_of))

            manager.loc[:, "model_validity"] = "PASSED_PREDICTIVE_GATE"
            corrupted = pd.read_csv(expected_path)
            for column in (
                "expected_reserve_impulse_4w_bp",
                "realized_reserve_impulse_4w_bp",
                "liquidity_surprise_bp",
            ):
                corrupted.loc[:, column] = np.inf
            corrupted.to_csv(expected_path, index=False)
            corrupted_hash = hashlib.sha256(expected_path.read_bytes()).hexdigest()
            manifest["expected_liquidity_path"]["sha256"] = corrupted_hash
            for artifact in parent_manifest["artifacts"]:
                if artifact.get("path") == "results/expected_liquidity_path.csv":
                    artifact["sha256"] = corrupted_hash
            parent_path.write_text(json.dumps(parent_manifest), encoding="utf-8")
            non_finite = replace(candidate, root=target, manifest=manifest)
            self.assertFalse(model_output_permitted(non_finite, current_time=as_of))

    def test_manifest_column_count_is_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "bundle"
            shutil.copytree(BUNDLE_ROOT, target)
            manifest_path = target / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["files"]["weekly_state.csv"]["columns"] = 999
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Column-count mismatch"):
                load_liquidity_bundle(target, verify_hashes=False)

    def test_parent_release_artifact_inventory_is_fully_packaged(self) -> None:
        parent_path = BUNDLE_ROOT / "parent_release_manifest.json"
        parent = json.loads(parent_path.read_text(encoding="utf-8"))
        self.assertEqual(parent["artifact_count"], len(parent["artifacts"]))
        for artifact in parent["artifacts"]:
            path = BUNDLE_ROOT / artifact["path"]
            self.assertTrue(path.is_file(), msg=f"Missing {artifact['path']}")
            self.assertEqual(path.stat().st_size, artifact["bytes"])
            self.assertEqual(
                hashlib.sha256(path.read_bytes()).hexdigest(), artifact["sha256"]
            )

    def test_loader_rejects_parent_artifact_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "bundle"
            shutil.copytree(BUNDLE_ROOT, target)
            parent_path = target / "parent_release_manifest.json"
            parent = json.loads(parent_path.read_text(encoding="utf-8"))
            parent["artifacts"][0]["path"] = "../validation_gates.csv"
            parent_path.write_text(json.dumps(parent), encoding="utf-8")
            manifest_path = target / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["parent_release"]["manifest_sha256"] = hashlib.sha256(
                parent_path.read_bytes()
            ).hexdigest()
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "artifact path is invalid"):
                load_liquidity_bundle(target, verify_hashes=True)

    def test_loader_rejects_text_and_infinite_numeric_values(self) -> None:
        for bad_value, message in (
            ("not-a-number", "Non-numeric"),
            (np.inf, "Non-finite"),
        ):
            with (
                self.subTest(bad_value=bad_value),
                tempfile.TemporaryDirectory() as tmp,
            ):
                target = Path(tmp) / "bundle"
                shutil.copytree(BUNDLE_ROOT, target)
                weekly_path = target / "weekly_state.csv"
                weekly = pd.read_csv(weekly_path)
                if isinstance(bad_value, str):
                    weekly["reserve_impulse_4w_bp"] = weekly[
                        "reserve_impulse_4w_bp"
                    ].astype(object)
                weekly.loc[weekly.index[-1], "reserve_impulse_4w_bp"] = bad_value
                weekly.to_csv(weekly_path, index=False)
                manifest_path = target / "manifest.json"
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                manifest["files"]["weekly_state.csv"]["sha256"] = hashlib.sha256(
                    weekly_path.read_bytes()
                ).hexdigest()
                manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, message):
                    load_liquidity_bundle(target, verify_hashes=True)

    def test_source_status_has_effective_dates(self) -> None:
        status = source_status_table(self.bundle)
        self.assertEqual(len(status), 10)
        self.assertTrue(status["Observation date"].notna().all())
        self.assertTrue(status["Primary source"].str.len().gt(0).all())
        self.assertTrue(status["Source series"].str.len().gt(0).all())
        self.assertTrue(status["Source URL"].str.startswith("https://").all())
        self.assertTrue(status["Source key"].str.len().between(1, 36).all())
        self.assertTrue(status["Live status"].isin({"CURRENT", "STALE"}).all())
        self.assertEqual(
            dict(zip(status["Series"], status["Display value"], strict=True)),
            {
                "Reserve balances": "$2.92T",
                "Federal Reserve assets": "$6.73T",
                "Treasury General Account": "$959.44B",
                "Overnight reverse repo": "$456.00M",
                "Currency in circulation": "$2.48T",
                "Baa minus 10-year": "1.61 pp",
                "VIX": "14.51",
                "SOFR": "3.64%",
                "IORB": "3.65%",
                "Market transmission inputs": "$771.10",
            },
        )
        anchor_status = source_status_table(
            self.bundle, current_time=pd.Timestamp("2026-08-27")
        )
        market = anchor_status.loc[
            anchor_status["Series"].eq("Market transmission inputs")
        ].iloc[0]
        self.assertEqual(market["Live status"], "CURRENT")
        stale_market = source_status_table(
            self.bundle, current_time=pd.Timestamp("2026-09-03")
        ).loc[lambda frame: frame["Series"].eq("Market transmission inputs")]
        self.assertEqual(stale_market.iloc[0]["Live status"], "STALE")

        utc_evening = source_status_table(
            self.bundle, current_time=pd.Timestamp("2026-08-28 00:30:00+00:00")
        )
        utc_market = utc_evening.loc[
            utc_evening["Series"].eq("Market transmission inputs")
        ].iloc[0]
        self.assertEqual(utc_market["Age now, days"], 0)

        broken_weekly = self.bundle.weekly.copy()
        broken_weekly.loc[broken_weekly.index[-1], "spy_mom60"] = np.nan
        broken = replace(self.bundle, weekly=broken_weekly)
        invalid_market = source_status_table(
            broken, current_time=pd.Timestamp("2026-08-27")
        )
        self.assertEqual(
            invalid_market.loc[
                invalid_market["Series"].eq("Market transmission inputs"),
                "Live status",
            ].iloc[0],
            "STALE",
        )

    def test_historical_accounting_contributions_reconcile_to_reserves(self) -> None:
        weekly = self.bundle.weekly
        reconstructed = (
            weekly["fed_asset_change_4w_bp"]
            - weekly["tga_change_4w_bp_assets"]
            - weekly["onrrp_change_4w_bp_assets"]
            - weekly["currency_change_4w_bp_assets"]
            + weekly["other_liability_residual_4w_bp"]
        )
        error = (reconstructed - weekly["reserve_impulse_4w_bp"]).abs().max()
        self.assertLess(error, 1e-6)

    def test_live_release_is_hash_verified_current_and_reconciled(self) -> None:
        live = load_live_snapshot(LIVE_ROOT, verify_hashes=True)
        self.assertEqual(live.manifest["release_id"], "US-LIQ-LIVE-2026-09-04")
        release_clock = pd.Timestamp(live.manifest["as_of_et"])
        self.assertEqual(release_clock.date().isoformat(), "2026-09-04")
        self.assertTrue(
            snapshot_is_current(live, now=release_clock + pd.Timedelta(minutes=1))
        )
        self.assertFalse(
            snapshot_is_current(
                live, now=pd.Timestamp("2026-09-11 18:00", tz="America/New_York")
            )
        )
        self.assertEqual(live.manifest["schema_version"], "3.0.0")
        self.assertEqual(
            live.manifest["information_cutoff_et"], live.manifest["as_of_et"]
        )
        self.assertEqual(len(live.sources), 28)
        self.assertEqual(len(live.manifest["required_sources"]), 28)
        self.assertEqual(len(live.manifest["raw_files"]), 33)
        self.assertEqual(
            set(live.manifest["required_sources"]), set(live.sources["field"])
        )
        model_code_hash = hashlib.sha256(
            (ROOT / "liquidity_monitor" / "us_liquidity_model.py").read_bytes()
        ).hexdigest()
        self.assertEqual(
            live.manifest["model_spec"]["model_code_sha256"], model_code_hash
        )
        implementation_files = live.manifest["model_spec"]["implementation_files"]
        self.assertEqual(set(implementation_files), set(MODEL_IMPLEMENTATION_FILES))
        for relative_path in MODEL_IMPLEMENTATION_FILES:
            with self.subTest(implementation_file=relative_path):
                self.assertEqual(
                    implementation_files[relative_path],
                    hashlib.sha256((ROOT / relative_path).read_bytes()).hexdigest(),
                )
        state = live.state.iloc[0]
        accounting_reference = _independent_accounting_reference(live)
        reconstructed = (
            state["fed_asset_change_4w_bp"]
            - state["tga_change_4w_bp_assets"]
            - state["onrrp_change_4w_bp_assets"]
            - state["currency_change_4w_bp_assets"]
            + state["other_liability_residual_4w_bp"]
        )
        self.assertAlmostEqual(reconstructed, state["reserve_impulse_4w_bp"], places=9)
        for field, expected in accounting_reference.items():
            with self.subTest(accounting_field=field):
                self.assertAlmostEqual(float(state[field]), expected, places=8)
        market_reference = _independent_market_reference(live)
        for field in (
            "spy_adj_close",
            "spy_mom60",
            "spy_dist200",
            "sector_breadth50",
            "sector_breadth50_change20",
        ):
            with self.subTest(market_field=field):
                self.assertAlmostEqual(
                    float(state[field]),
                    float(market_reference[field]),
                    places=10,
                    msg=field,
                )
        self.assertEqual(str(state["market_asof_date"]), "2026-09-04")
        self.assertEqual(str(state["accounting_asof_date"]), "2026-09-02")
        self.assertAlmostEqual(
            float(state["tga_h41_bn"]),
            float(live.sources.set_index("field").loc["tga_h41_bn", "value"]),
            places=10,
        )
        source_dates = (
            live.sources.set_index("field")["observation_date"].astype(str).to_dict()
        )
        self.assertEqual(source_dates["onrrp_bn"], "2026-09-04")
        self.assertEqual(source_dates["market"], "2026-09-04")
        for field in (
            "deposits_bn",
            "bank_assets_bn",
            "bank_cash_bn",
            "large_bank_assets_bn",
            "large_bank_cash_bn",
            "small_bank_assets_bn",
            "small_bank_cash_bn",
            "bank_credit_bn",
        ):
            with self.subTest(h8_field=field):
                self.assertEqual(source_dates[field], "2026-08-26")

    def test_live_source_clocks_distinguish_unchanged_and_scheduled_lag(self) -> None:
        live = load_live_snapshot(LIVE_ROOT, verify_hashes=True)
        release_clock = pd.Timestamp(live.manifest["as_of_et"])
        status = live_source_status_table(
            live, current_time=release_clock + pd.Timedelta(minutes=1)
        )
        self.assertTrue(status["Live status"].str.startswith("CURRENT").all())
        iorb = status.loc[status["Series"].eq("IORB")].iloc[0]
        self.assertEqual(iorb["Live status"], "CURRENT · UNCHANGED")
        self.assertEqual(str(iorb["Observation date"]), "2026-09-04")
        reserves = status.loc[status["Series"].eq("Reserve balances")].iloc[0]
        self.assertEqual(reserves["Live status"], "CURRENT · SCHEDULED LAG")
        self.assertEqual(str(reserves["Expected date"]), "2026-09-02")
        deposits = status.loc[status["Series"].eq("Commercial bank deposits")].iloc[0]
        self.assertEqual(deposits["Live status"], "CURRENT · SCHEDULED LAG")
        self.assertEqual(str(deposits["Expected date"]), "2026-08-26")
        onrrp = status.loc[status["Series"].eq("Overnight reverse repo")].iloc[0]
        self.assertEqual(onrrp["Live status"], "CURRENT · UPDATED")
        self.assertEqual(str(onrrp["Observation date"]), "2026-09-04")
        self.assertEqual(str(onrrp["Expected date"]), "2026-09-04")

    def test_live_loader_rejects_raw_payload_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "live"
            shutil.copytree(LIVE_ROOT, target)
            raw = next((target / "raw").iterdir())
            raw.write_bytes(raw.read_bytes() + b"tampered")
            with self.assertRaisesRegex(ValueError, "raw checksum mismatch"):
                load_live_snapshot(target, verify_hashes=True)

    def test_live_summary_uses_current_mechanics_without_relabeling_model(self) -> None:
        live = load_live_snapshot(LIVE_ROOT, verify_hashes=True)
        summary = diagnostic_summary(
            self.bundle,
            current_time=pd.Timestamp(live.manifest["as_of_et"])
            + pd.Timedelta(minutes=1),
            live_snapshot=live,
        )
        self.assertEqual(str(summary["observed_as_of"].date()), "2026-09-04")
        self.assertTrue(summary["sources_current"])
        state = live.state.iloc[0]
        self.assertAlmostEqual(
            summary["reserve_impulse_bp"], float(state["reserve_impulse_4w_bp"])
        )
        self.assertFalse(summary["output_permitted"])
        self.assertEqual(str(summary["latest_signal_date"].date()), "2026-08-27")
        self.assertEqual(
            summary["market_as_of"].date(),
            pd.Timestamp(state["market_asof_date"]).date(),
        )
        self.assertEqual(str(summary["market_as_of"].date()), "2026-09-04")
        self.assertEqual(str(summary["accounting_as_of"].date()), "2026-09-02")
        weekly = self.bundle.weekly.sort_values("signal_date")
        observed_as_of = pd.Timestamp(state["as_of_date"])
        prior_levels = (
            weekly.loc[
                weekly["signal_date"].lt(observed_as_of), "reserve_impulse_4w_bp"
            ]
            .dropna()
            .tail(260)
        )
        current_impulse = float(state["reserve_impulse_4w_bp"])
        expected_percentile = (
            100
            * (
                int(prior_levels.lt(current_impulse).sum())
                + 0.5 * int(prior_levels.eq(current_impulse).sum())
            )
            / len(prior_levels)
        )
        historical_changes = weekly["reserve_impulse_4w_bp"].diff(4)
        trend_calibration = (
            historical_changes.loc[weekly["signal_date"].lt(observed_as_of)]
            .dropna()
            .tail(260)
        )
        expected_band = float(trend_calibration.abs().quantile(0.25))
        comparison = weekly.loc[
            weekly["signal_date"].le(observed_as_of - pd.Timedelta(days=28))
        ].iloc[-1]
        expected_change = current_impulse - float(comparison["reserve_impulse_4w_bp"])
        expected_regime = observed_regime_classifier(
            expected_percentile, expected_change, expected_band
        )
        self.assertAlmostEqual(summary["reserve_percentile"], expected_percentile)
        self.assertAlmostEqual(summary["observed_regime_trend_band_bp"], expected_band)
        self.assertAlmostEqual(summary["reserve_impulse_change_4w_bp"], expected_change)
        self.assertEqual(
            summary["observed_regime_label"], expected_regime["regime_label"]
        )
        self.assertEqual(
            summary["observed_regime_level"], expected_regime["level_label"]
        )
        self.assertEqual(
            summary["observed_regime_trend"], expected_regime["trend_label"]
        )
        self.assertEqual(
            summary["observed_regime_near_trend_boundary"],
            abs(abs(expected_change) - expected_band) <= 0.05 * expected_band,
        )
        self.assertAlmostEqual(summary["risk_probability"], 0.1643662163)
        self.assertAlmostEqual(summary["risk_base_rate"], 0.1795626577)
        self.assertFalse(summary["risk_warning"])

    def test_release_figures_construct_without_external_calls(self) -> None:
        history = liquidity_impulse_figure(self.bundle, 3)
        current = current_mechanics_figure(self.bundle)
        domains = domain_diagnostic_figure(self.bundle)
        figures = (history, current, domains)
        self.assertTrue(all(len(figure.data) >= 1 for figure in figures))
        self.assertTrue(
            all(
                str(value).endswith(" bp")
                for trace in history.data
                for value in trace.customdata
            )
        )
        self.assertEqual(
            list(current.data[0].text),
            ["−10.8 bp", "+16.3 bp", "+0.9 bp", "−7.7 bp", "−39.9 bp"],
        )
        self.assertTrue(
            all(
                len(str(value).removeprefix("+").removeprefix("−").split(".")[-1]) == 2
                for value in domains.data[0].text
                if value
            )
        )
        self.assertEqual(
            list(domains.data[0].textfont.color),
            [
                "#ffffff" if position == "inside" and value > 0 else "#202020"
                for position, value in zip(
                    domains.data[0].textposition, domains.data[0].x, strict=True
                )
            ],
        )
        self.assertEqual(current.data[0].textangle, 0)
        self.assertEqual(domains.data[0].textangle, 0)
        self.assertEqual(
            list(domains.data[0].y),
            [
                "Equity trend stress",
                "Credit stress",
                "Sector breadth stress",
                "Volatility stress",
                "Aggregate market stress",
                "Reserve liquidity pressure",
                "Liquidity stress interaction",
            ],
        )
        self.assertEqual(
            domains.layout.xaxis.title.text,
            "Standardized stress score<br>(positive values indicate greater stress)",
        )
        self.assertIn(
            "0.00", [annotation.text for annotation in domains.layout.annotations]
        )

    def test_live_market_context_matches_independent_release_reference(self) -> None:
        live = load_live_snapshot(LIVE_ROOT, verify_hashes=True)
        domains = domain_diagnostic_figure(self.bundle, live)
        actual = np.asarray(domains.data[0].x, dtype=float)
        expected = _independent_market_context_vector(self.bundle, live)
        self.assertEqual(str(live.state.iloc[0]["market_asof_date"]), "2026-09-04")
        self.assertEqual(actual.shape, (7,))
        self.assertTrue(np.isfinite(actual).all())
        self.assertTrue(np.isfinite(expected).all())
        np.testing.assert_allclose(actual, expected, rtol=0.0, atol=1e-10)

    def test_streamlit_page_renders_all_decision_tabs(self) -> None:
        page = ROOT / "pages" / "Liquidity_Conditions_Monitor.py"
        app = AppTest.from_file(str(page)).run(timeout=180)
        self.assertEqual(list(app.exception), [])
        self.assertEqual(
            [tab.label for tab in app.tabs],
            [
                "Overview",
                "Reserve mechanics",
                "Funding and markets",
                "Data and methods",
            ],
        )
        self.assertEqual(len(app.get("plotly_chart")), 8)
        self.assertEqual(len(app.get("dataframe")), 0)
        self.assertEqual(len(app.get("number_input")), 0)
        self.assertEqual(len(app.get("radio")), 0)
        markdown_values = "\n".join(str(item.value) for item in app.markdown)
        live = load_live_snapshot(LIVE_ROOT, verify_hashes=True)
        liquidity_result = build_us_liquidity_model(live)
        index_history = liquidity_result.history["liquidity_conditions_index"].dropna()
        index_change_4w = float(index_history.iloc[-1] - index_history.iloc[-5])
        if liquidity_result.current["direction"] == "Deteriorating":
            expected_change_copy = (
                f"down {abs(index_change_4w):.1f} index points over four weeks"
            )
        elif liquidity_result.current["direction"] == "Improving":
            expected_change_copy = (
                f"up {abs(index_change_4w):.1f} index points over four weeks"
            )
        else:
            expected_change_copy = (
                f"changed {abs(index_change_4w):.1f} index points over four weeks"
            )
        self.assertIn("Current liquidity read", markdown_values)
        self.assertIn(
            "U.S. liquidity is restrictive and deteriorating", markdown_values
        )
        self.assertIn(expected_change_copy, markdown_values)
        self.assertIn("Liquidity conditions", markdown_values)
        self.assertIn("Historical position", markdown_values)
        self.assertIn("Funding state", markdown_values)
        self.assertIn("Reserve-draining, broadly stable", markdown_values)
        self.assertIn("How the U.S. liquidity classifier is built", markdown_values)
        self.assertIn("Treasury General Account, H.4.1", markdown_values)
        self.assertNotIn("Predictive overlay", markdown_values)
        self.assertNotIn("Liquidity surprise", markdown_values)
        self.assertNotIn("SPY 20-session", markdown_values)
        forbidden_characters = tuple(
            chr(codepoint)
            for codepoint in (0x2014, 0x2192, 0x2190, 0x21D2, 0x279C, 0x27F6, 0x2194)
        )
        for forbidden_character in forbidden_characters:
            with self.subTest(forbidden_character=forbidden_character):
                self.assertNotIn(forbidden_character, markdown_values)

    def test_reference_rate_availability_uses_observed_session_sequence(self) -> None:
        secured = pd.Series(
            [1.0, 2.0, 3.0],
            index=pd.to_datetime(["2026-07-02", "2026-07-06", "2026-07-07"]),
        )
        unsecured = pd.Series(
            [1.0, 2.0, 3.0, 4.0],
            index=pd.to_datetime(
                ["2026-07-02", "2026-07-03", "2026-07-06", "2026-07-07"]
            ),
        )

        secured_available = _reference_rate_publication_availability(
            secured, GOVERNMENT_SECURITIES_DAY
        )
        unsecured_available = _reference_rate_publication_availability(
            unsecured, FEDERAL_RESERVE_DAY
        )

        self.assertEqual(secured_available.index[0], pd.Timestamp("2026-07-06"))
        self.assertEqual(unsecured_available.index[0], pd.Timestamp("2026-07-03"))
        self.assertTrue(secured_available.index.is_unique)
        self.assertTrue(unsecured_available.index.is_unique)

    def test_reference_rate_availability_has_no_veterans_day_collision(self) -> None:
        rates = pd.Series(
            [1.0, 2.0, 3.0],
            index=pd.to_datetime(["2023-11-09", "2023-11-10", "2023-11-13"]),
        )
        available = _reference_rate_publication_availability(
            rates, GOVERNMENT_SECURITIES_DAY
        )
        self.assertEqual(
            list(available.index[:2]),
            [pd.Timestamp("2023-11-10"), pd.Timestamp("2023-11-13")],
        )
        self.assertTrue(available.index.is_unique)

    def test_model_rejects_duplicate_raw_reference_rate_dates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "live"
            shutil.copytree(LIVE_ROOT, target)
            payload_path = target / "raw" / "nyfed_sofr.json"
            payload = json.loads(payload_path.read_text(encoding="utf-8"))
            payload["refRates"].append(dict(payload["refRates"][0]))
            payload_path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(
                ValueError, "SOFR payload contains duplicate dates"
            ):
                load_live_snapshot(target, verify_hashes=False)

    def test_loader_rejects_fred_duplicate_even_when_one_value_is_missing(self) -> None:
        for duplicate_value in (".", "not-a-number"):
            with self.subTest(duplicate_value=duplicate_value):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp) / "live"
                    shutil.copytree(LIVE_ROOT, target)
                    raw_path = target / "raw" / "fred_WRBWFRBL.csv"
                    frame = pd.read_csv(raw_path, dtype=str)
                    duplicate = frame.iloc[[0]].copy()
                    duplicate.iloc[0, 1] = duplicate_value
                    pd.concat([frame, duplicate], ignore_index=True).to_csv(
                        raw_path, index=False
                    )
                    with self.assertRaisesRegex(
                        ValueError, "WRBWFRBL contains duplicate dates"
                    ):
                        load_live_snapshot(target, verify_hashes=False)

    def test_streamlit_page_suppresses_output_when_live_release_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            live_root = Path(tmp) / "invalid-live"
            shutil.copytree(LIVE_ROOT, live_root)
            manifest_path = live_root / "manifest.json"
            manifest = json.loads(manifest_path.read_text())
            manifest["model_spec"]["model_code_sha256"] = "0" * 64
            manifest_path.write_text(json.dumps(manifest))

            with mock.patch.dict(
                os.environ,
                {"US_LIQUIDITY_LIVE_ROOT": str(live_root)},
            ):
                app = AppTest.from_file(
                    str(ROOT / "pages" / "Liquidity_Conditions_Monitor.py")
                ).run(timeout=30)

            self.assertEqual(len(app.exception), 0)
            self.assertTrue(
                any(
                    "Current liquidity regime unavailable" in str(item.value)
                    for item in app.error
                )
            )
            rendered = "\n".join(str(item.value) for item in app.markdown)
            self.assertIn("suppressed the regime", rendered)
            self.assertNotIn("Restrictive, deteriorating", rendered)

    def test_structural_liquidity_is_de_duplicated_and_reproducible(self) -> None:
        live = load_live_snapshot(LIVE_ROOT, verify_hashes=True)
        result = build_structural_liquidity(live)
        self.assertEqual(sum(STRUCTURAL_WEIGHTS.values()), 1.0)
        self.assertEqual(
            list(result.components["component"]),
            [
                "Reserve stock relative to deposits",
                "Relative funding support",
                "Realized reserve flow",
            ],
        )
        self.assertEqual(result.current["state"], "Low versus history")
        self.assertEqual(result.current["direction"], "Stable")
        self.assertEqual(result.current["source_coverage"], "Complete")
        current_date = pd.Timestamp(result.current["date"])
        current_score = float(result.current["score_z"])
        prior_scores = (
            result.history.loc[
                result.history.index < current_date, "structural_score_z"
            ]
            .dropna()
            .tail(260)
        )
        expected_percentile = (
            float(prior_scores.lt(current_score).sum())
            + 0.5 * float(prior_scores.eq(current_score).sum())
        ) / len(prior_scores) * 100
        self.assertAlmostEqual(
            float(result.current["percentile"]), expected_percentile
        )
        self.assertGreaterEqual(
            int(result.current["percentile_reference_observations"]), 150
        )
        weighted = float(result.components["weighted_contribution"].sum())
        self.assertAlmostEqual(weighted, float(result.current["score_z"]))
        probe_date = pd.Timestamp("2026-09-03")
        deposits = _raw_fred_series(live.root, "DPSACBW027SBOG")
        available_deposits = deposits.copy()
        available_deposits.index = available_deposits.index + pd.Timedelta(days=9)
        eligible = available_deposits.loc[available_deposits.index <= probe_date]
        self.assertFalse(eligible.empty)
        self.assertEqual(
            (eligible.index[-1] - pd.Timedelta(days=9)).date().isoformat(),
            "2026-08-19",
        )
        self.assertAlmostEqual(
            float(result.history.loc[probe_date, "deposits_bn"]),
            float(eligible.iloc[-1]),
        )
        self.assertNotIn("tga", result.components["component"].str.lower().str.cat())
        self.assertNotIn("Market confirmation", set(result.components["component"]))

    def test_structural_regime_boundaries_and_figures(self) -> None:
        self.assertEqual(
            classify_structural_regime(39.9, 0.3, 0.2)["regime"],
            "Low versus history, improving",
        )
        self.assertEqual(
            classify_structural_regime(50.0, 0.0, 0.2)["regime"],
            "Typical versus history, stable",
        )
        self.assertEqual(
            classify_structural_regime(60.1, -0.3, 0.2)["regime"],
            "High versus history, deteriorating",
        )
        live = load_live_snapshot(LIVE_ROOT, verify_hashes=True)
        result = build_structural_liquidity(live)
        figures = (
            structural_components_figure(result),
            structural_history_figure(result),
            funding_conditions_figure(result),
            transmission_conditions_figure(live),
            market_confirmation_figure(live),
        )
        self.assertTrue(all(len(figure.data) >= 1 for figure in figures))
        component_x = np.asarray(figures[0].data[0].x, dtype=float)
        expected_x = result.components.iloc[::-1]["weighted_contribution"].to_numpy()
        np.testing.assert_allclose(component_x, expected_x)
        conditions = transmission_snapshot(live)
        market = market_confirmation_snapshot(live)
        np.testing.assert_array_equal(
            np.sign(conditions["tightening_score_z"]), np.sign(conditions["change_20"])
        )
        np.testing.assert_array_equal(
            np.sign(market["response_score_z"]), np.sign(market["change_20_pct"])
        )

    def test_us_liquidity_model_is_hierarchical_stable_and_reproducible(self) -> None:
        live = load_live_snapshot(LIVE_ROOT, verify_hashes=True)
        result = build_us_liquidity_model(live)
        self.assertAlmostEqual(sum(LIQUIDITY_LAYER_WEIGHTS.values()), 1.0)
        self.assertEqual(
            list(result.layers["layer"]),
            [
                "Structural reserve capacity",
                "Overnight funding support",
                "Realized reserve impulse",
                "Bank credit creation",
            ],
        )
        self.assertEqual(result.current["state"], "Restrictive")
        self.assertEqual(result.current["direction"], "Deteriorating")
        self.assertEqual(result.current["funding_state"], "Orderly")
        self.assertEqual(result.current["source_coverage"], "Complete")
        self.assertGreaterEqual(int(result.current["calibration_observations"]), 150)
        history = result.history.dropna(
            subset=["liquidity_conditions_index", "direction_band"]
        )
        self.assertGreater(
            float(history["liquidity_conditions_index"].autocorr()), 0.95
        )
        self.assertLess(
            float(history["liquidity_conditions_index"].diff().abs().quantile(0.90)),
            5.0,
        )
        self.assertTrue(history["liquidity_conditions_index"].between(0, 100).all())
        figures = (
            liquidity_layers_figure(result),
            liquidity_conditions_history_figure(result),
            funding_market_figure(result),
            liquidity_deviation_figure(result),
        )
        self.assertTrue(all(len(figure.data) >= 1 for figure in figures))

    def test_us_liquidity_model_fails_closed_on_invalid_denominators(self) -> None:
        dates = pd.date_range("2026-08-28", periods=3, freq="W-FRI")
        numerator = pd.Series([10.0, 11.0, 12.0], index=dates)
        for invalid in (0.0, np.inf):
            with self.subTest(invalid=invalid):
                denominator = pd.Series([100.0, 100.0, invalid], index=dates)
                with self.assertRaisesRegex(ValueError, "2026-09-11"):
                    _safe_positive_ratio(
                        numerator,
                        denominator,
                        label="Test liquidity denominator",
                    )
        warmup_denominator = pd.Series([np.nan, 100.0, 100.0], index=dates)
        warmup_ratio = _safe_positive_ratio(
            numerator,
            warmup_denominator,
            label="Warm-up liquidity denominator",
        )
        self.assertTrue(np.isnan(float(warmup_ratio.iloc[0])))

        latest_missing = pd.DataFrame(
            {"model_input": [1.0, 2.0, np.nan]}, index=dates
        )
        with self.assertRaisesRegex(ValueError, "model_input"):
            _require_latest_finite(
                latest_missing,
                ["model_input"],
                date=dates[-1],
                stage="test input set",
            )

    def test_us_liquidity_smoothing_does_not_carry_missing_current_input(self) -> None:
        series = pd.Series([0.2, 0.4, np.nan], dtype=float)
        smoothed = _smooth(series, 4)
        self.assertTrue(np.isfinite(float(smoothed.iloc[1])))
        self.assertTrue(np.isnan(float(smoothed.iloc[2])))

    def test_us_liquidity_model_does_not_create_irregular_calendar_rows(self) -> None:
        live = load_live_snapshot(LIVE_ROOT, verify_hashes=True)
        baseline = build_us_liquidity_model(live)
        baseline_index = float(baseline.current["index"])
        baseline_date = pd.Timestamp(baseline.current["date"])

        # Identical source cutoffs on a weekend, midweek, or before the next
        # Friday model close must preserve the completed weekly observation.
        for cutoff in (
            "2026-09-05T12:00:00-04:00",
            "2026-09-07T17:00:00-04:00",
            "2026-09-10T17:00:00-04:00",
            "2026-09-11T16:29:59-04:00",
        ):
            with self.subTest(cutoff=cutoff):
                timestamp = pd.Timestamp(cutoff)
                state = live.state.copy(deep=True)
                state.loc[state.index[0], "as_of_date"] = timestamp.date().isoformat()
                manifest = dict(live.manifest)
                manifest["as_of_et"] = cutoff
                manifest["information_cutoff_et"] = cutoff
                synthetic = replace(live, state=state, manifest=manifest)
                result = build_us_liquidity_model(synthetic)
                self.assertEqual(pd.Timestamp(result.current["date"]), baseline_date)
                self.assertAlmostEqual(float(result.current["index"]), baseline_index)
                self.assertEqual(result.current["direction"], baseline.current["direction"])

    def test_funding_stress_is_a_separate_veto_not_an_index_relabel(self) -> None:
        funding_state = classify_absolute_funding(
            sofr_iorb_bp=11.0,
            tgcr_iorb_bp=0.0,
            bgcr_iorb_bp=0.0,
            effr_iorb_bp=0.0,
            sofr_iqr_bp=2.0,
            repo_add_bn=0.0,
        )
        regime = classify_liquidity_regime(
            index_value=80.0,
            direction="Improving",
            funding_state=funding_state,
        )
        self.assertEqual(funding_state, "Stressed")
        self.assertEqual(regime["state_code"], "supportive")
        self.assertEqual(regime["state"], "Supportive")
        self.assertEqual(regime["regime"], "Supportive, improving")
        self.assertTrue(bool(regime["funding_stress_veto"]))

    def test_liquidity_classifiers_fail_closed_on_invalid_inputs(self) -> None:
        self.assertEqual(_classify_direction(0.0, -0.1), "Unavailable")
        self.assertEqual(_classify_direction(np.nan, 0.1), "Unavailable")
        self.assertEqual(
            classify_absolute_funding(
                np.nan, np.nan, np.nan, np.nan, np.nan, np.nan
            ),
            "Unavailable",
        )
        self.assertEqual(
            classify_absolute_funding(0.0, 0.0, 0.0, 0.0, -1.0, 0.0),
            "Unavailable",
        )
        self.assertEqual(
            classify_absolute_funding(0.0, 0.0, 0.0, 0.0, 1.0, -1.0),
            "Unavailable",
        )

    def test_us_liquidity_model_suppresses_an_unavailable_funding_state(self) -> None:
        live = load_live_snapshot(LIVE_ROOT, verify_hashes=True)
        with mock.patch(
            "liquidity_monitor.us_liquidity_model.classify_absolute_funding",
            return_value="Unavailable",
        ):
            with self.assertRaisesRegex(ValueError, "invalid current inputs"):
                build_us_liquidity_model(live)

    def test_seasonal_expectation_keeps_iso_week_53_in_its_iso_year(self) -> None:
        series = pd.Series(
            [10.0, 20.0, 30.0],
            index=pd.to_datetime(["2019-12-27", "2020-12-25", "2021-01-01"]),
        )
        expected = _prior_seasonal_expectation(
            series, week_radius=2, minimum_prior_years=1
        )

        # January 1, 2021 belongs to ISO year 2020. The December 25, 2020
        # observation is therefore the same seasonal cycle and cannot enter the
        # prior-year expectation. The comparable ISO-2019 value remains valid.
        self.assertAlmostEqual(float(expected.iloc[-1]), 10.0)


if __name__ == "__main__":
    unittest.main()
