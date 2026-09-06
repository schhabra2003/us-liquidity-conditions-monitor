"""Portable data contract and figures for the U.S. liquidity decision tool.

This module contains no Streamlit calls.  It is deliberately testable without a
browser and refuses to invent a directional signal when the research release has
not passed its registered validation gates.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from liquidity_monitor.liquidity_formatting import (
    UNIT_INDEX_POINTS,
    UNIT_PERCENT,
    UNIT_PERCENTAGE_POINTS,
    UNIT_USD_BILLIONS,
    UNIT_USD_PRICE,
    format_basis_points,
    format_normalized,
    format_source_value,
)
from liquidity_monitor.liquidity_live_snapshot import (
    LiveLiquiditySnapshot,
    expected_observation_date,
    runtime_expected_dates,
    snapshot_is_current,
    source_current_mask,
)
from liquidity_monitor.palette import PASTEL

BLACK = "#000000"
TEXT = "#202020"
MUTED = "#555555"
BORDER = "#bdbdbd"
GRID = "#e5e5e5"
GREEN = PASTEL["sage"]
RED = PASTEL["rose"]
GRAY = PASTEL["slate_blue"]
DRIVER_COLORS = {
    "Fed assets": PASTEL["blue"],
    "TGA": PASTEL["coral"],
    "ON RRP": PASTEL["teal"],
    "Currency": PASTEL["lavender"],
    "Other liabilities / residual": PASTEL["slate_blue"],
}

OBSERVED_LEVEL_LOWER = 40.0
OBSERVED_LEVEL_UPPER = 60.0
OBSERVED_CALIBRATION_WEEKS = 260
OBSERVED_MIN_CALIBRATION_OBS = 104
OBSERVED_TREND_STABLE_QUANTILE = 0.25

# Frozen 2026 A3 robust-transform parameters from the hash-pinned V2 research
# release (results/v2_parameters.csv SHA-256
# 4a7a111cc31ffb869ebe670c3d2ae93ea6ece41b90a701a44d7f3421654a9d30).
# They update descriptive market context without refitting or publishing the
# failed predictive overlay. Values are (lower clip, upper clip, median, IQR).
MARKET_CONTEXT_TRANSFORM_2026 = {
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

OBSERVED_REGIME_LABELS = {
    ("improving", "below_normal"): "Below-normal reserve flow, improving",
    ("improving", "near_normal"): "Typical reserve flow, improving",
    ("improving", "above_normal"): "Above-normal reserve flow, improving",
    ("stable", "below_normal"): "Below-normal reserve flow, broadly stable",
    ("stable", "near_normal"): "Typical reserve flow, broadly stable",
    ("stable", "above_normal"): "Above-normal reserve flow, broadly stable",
    ("deteriorating", "below_normal"): "Below-normal reserve flow, deteriorating",
    ("deteriorating", "near_normal"): "Typical reserve flow, deteriorating",
    ("deteriorating", "above_normal"): "Above-normal reserve flow, deteriorating",
}


@dataclass(frozen=True)
class LiquidityBundle:
    root: Path
    manifest: dict[str, object]
    weekly: pd.DataFrame
    predictions: pd.DataFrame
    current_state: pd.DataFrame
    manager_state: pd.DataFrame
    validation_metrics: pd.DataFrame
    annual_inference: pd.DataFrame
    warning_diagnostics: pd.DataFrame
    validation_gates: pd.DataFrame


FILE_MAP = {
    "weekly": "weekly_state.csv",
    "predictions": "model_predictions.csv",
    "current_state": "current_state.csv",
    "manager_state": "manager_state_card.csv",
    "validation_metrics": "validation_metrics.csv",
    "annual_inference": "annual_inference.csv",
    "warning_diagnostics": "warning_diagnostics.csv",
    "validation_gates": "validation_gates.csv",
}

EXPECTED_COLUMNS = {
    "weekly": (
        "signal_date",
        "signal_at",
        "market_asof_date",
        "spy_adj_close",
        "spy_mom60",
        "spy_dist200",
        "sector_breadth50",
        "sector_breadth50_change20",
        "reserve_impulse_4w_bp",
        "reserve_impulse_13w_bp",
        "tga_change_4w_bp_assets",
        "onrrp_change_4w_bp_assets",
        "fed_asset_change_4w_bp",
        "currency_change_4w_bp_assets",
        "accounting_known_impulse_4w_bp",
        "other_liability_residual_4w_bp",
        "baa10y",
        "baa10y_change20",
        "vix",
        "vix_change5",
        "reserves_bn",
        "assets_bn",
        "tga_dts_bn",
        "onrrp_bn",
        "currency_bn",
        "sofr",
        "iorb",
        "sofr_admin_bp",
        "reserves_bn__observation_date",
        "reserves_bn__age_days",
        "reserves_bn__stale",
        "assets_bn__observation_date",
        "assets_bn__age_days",
        "assets_bn__stale",
        "tga_dts_bn__observation_date",
        "tga_dts_bn__age_days",
        "tga_dts_bn__stale",
        "onrrp_bn__observation_date",
        "onrrp_bn__age_days",
        "onrrp_bn__stale",
        "currency_bn__observation_date",
        "currency_bn__age_days",
        "currency_bn__stale",
        "baa10y__observation_date",
        "baa10y__age_days",
        "baa10y__stale",
        "vix__observation_date",
        "vix__age_days",
        "vix__stale",
        "sofr__observation_date",
        "sofr__age_days",
        "sofr__stale",
        "iorb__observation_date",
        "iorb__age_days",
        "iorb__stale",
    ),
    "predictions": (
        "design",
        "embargo_sessions",
        "variant",
        "outer_year",
        "signal_date",
        "entry_date",
        "label_end",
        "truth",
        "raw_probability",
        "probability",
        "base_rate",
        "risk_percentile",
        "warning_threshold",
        "warning",
        "C",
        "calibration_method",
        "liquidity_column",
        "domain__T",
        "domain__C",
        "domain__B",
        "domain__V",
        "domain__F",
        "domain__D",
        "domain__I",
    ),
    "current_state": (
        "trial_id",
        "latest_signal_date",
        "state",
        "directional_inference",
        "ordinal_state_permitted",
        "decimal_probability_permitted",
        "primary_gates_pass",
        "probability_gates_pass",
        "reason",
        "lineage",
    ),
    "manager_state": (
        "as_of_anchor",
        "data_cutoff",
        "state",
        "directional_inference",
        "probability",
        "severity",
        "lead_time",
        "primary_reason",
        "data_quality",
        "model_validity",
        "next_update_condition",
    ),
    "validation_metrics": (
        "design",
        "embargo_sessions",
        "variant",
        "n",
        "positive",
        "event_rate",
        "outer_years",
        "row_brier",
        "equal_year_brier",
        "row_log_loss",
        "equal_year_log_loss",
        "row_base_brier",
        "equal_year_base_brier",
        "row_base_log_loss",
        "equal_year_base_log_loss",
        "warning_share",
    ),
    "annual_inference": (
        "design",
        "embargo_sessions",
        "comparison",
        "row_brier_improvement",
        "equal_year_brier_improvement",
        "annual_bootstrap_ci_low",
        "annual_bootstrap_ci_high",
        "exact_sign_randomization_p_one_sided",
        "exact_binomial_sign_p_one_sided",
        "positive_years",
        "outer_years",
        "complete_outer_years",
        "positive_year_share",
        "row_logloss_improvement",
        "equal_year_logloss_improvement",
    ),
    "warning_diagnostics": (
        "design",
        "embargo_sessions",
        "variant",
        "warning_budget_target",
        "realized_warning_share",
        "independent_episode_count",
        "captured_episode_count",
        "episode_recall",
        "severity_weighted_episode_recall",
        "median_first_warning_lead_sessions",
        "false_warning_clusters",
        "false_warning_clusters_per_year",
        "false_warning_definition",
    ),
    "validation_gates": ("gate_group", "gate", "passed", "value", "threshold"),
}

BOOLEAN_COLUMNS = {
    "weekly": tuple(
        f"{field}__stale"
        for field in (
            "reserves_bn",
            "assets_bn",
            "tga_dts_bn",
            "onrrp_bn",
            "currency_bn",
            "baa10y",
            "vix",
            "sofr",
            "iorb",
        )
    ),
    "current_state": (
        "ordinal_state_permitted",
        "decimal_probability_permitted",
        "primary_gates_pass",
        "probability_gates_pass",
    ),
    "validation_gates": ("passed",),
}

STRING_COLUMNS = {
    "predictions": ("design", "variant", "calibration_method", "liquidity_column"),
    "current_state": (
        "trial_id",
        "state",
        "directional_inference",
        "reason",
        "lineage",
    ),
    "manager_state": (
        "data_cutoff",
        "state",
        "directional_inference",
        "probability",
        "severity",
        "lead_time",
        "primary_reason",
        "data_quality",
        "model_validity",
        "next_update_condition",
    ),
    "validation_metrics": ("design", "variant"),
    "annual_inference": ("design", "comparison"),
    "warning_diagnostics": ("design", "variant", "false_warning_definition"),
    "validation_gates": ("gate_group", "gate", "value", "threshold"),
}

NULLABLE_STRING_COLUMNS = {"validation_gates": ("value",)}

KEY_DATE_COLUMNS = {
    "weekly": (
        "signal_date",
        "signal_at",
        "market_asof_date",
        "reserves_bn__observation_date",
        "assets_bn__observation_date",
        "tga_dts_bn__observation_date",
        "onrrp_bn__observation_date",
        "currency_bn__observation_date",
        "baa10y__observation_date",
        "vix__observation_date",
    ),
    "predictions": ("signal_date", "entry_date"),
    "current_state": ("latest_signal_date",),
    "manager_state": ("as_of_anchor",),
}

SOURCE_TTLS_DAYS = {
    # Conservative calendar-age limits. A production source monitor should
    # compare upstream publication timestamps directly; these limits prefer a
    # temporary false-stale state to a false-current publication claim.
    "reserves_bn": 7,
    "assets_bn": 7,
    "tga_dts_bn": 3,
    "onrrp_bn": 3,
    "currency_bn": 7,
    "baa10y": 3,
    "vix": 3,
    "sofr": 3,
    "iorb": 3,
}
MARKET_TRANSMISSION_TTL_DAYS = 3

EXPECTED_PATH_COLUMNS = (
    "signal_date",
    "expectation_vintage",
    "forecast_horizon_end",
    "expected_reserve_impulse_4w_bp",
    "realized_reserve_impulse_4w_bp",
    "liquidity_surprise_bp",
    "methodology_id",
)

ALLOWED_DIRECTIONAL_STATES = {"green", "yellow", "orange", "red"}
PRODUCTION_RELEASE_CLASS = "PRODUCTION_CERTIFIED"

BOUNDED_NUMERIC_COLUMNS = {
    "predictions": {
        "truth": (0.0, 1.0),
        "raw_probability": (0.0, 1.0),
        "probability": (0.0, 1.0),
        "base_rate": (0.0, 1.0),
        "risk_percentile": (0.0, 100.0),
        "warning_threshold": (0.0, 1.0),
    },
    "validation_metrics": {
        "event_rate": (0.0, 1.0),
        "row_brier": (0.0, 1.0),
        "equal_year_brier": (0.0, 1.0),
        "row_base_brier": (0.0, 1.0),
        "equal_year_base_brier": (0.0, 1.0),
        "warning_share": (0.0, 1.0),
    },
    "annual_inference": {
        "exact_sign_randomization_p_one_sided": (0.0, 1.0),
        "exact_binomial_sign_p_one_sided": (0.0, 1.0),
        "positive_year_share": (0.0, 1.0),
    },
    "warning_diagnostics": {
        "warning_budget_target": (0.0, 1.0),
        "realized_warning_share": (0.0, 1.0),
        "episode_recall": (0.0, 1.0),
        "severity_weighted_episode_recall": (0.0, 1.0),
    },
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _parse_dates(frame: pd.DataFrame) -> pd.DataFrame:
    output = frame.copy()
    for column in output.columns:
        if column.endswith("_date") or column in {
            "date",
            "signal_at",
            "label_end",
            "entry_date",
            "asset_entry_date",
            "start_date",
            "end_date",
            "as_of_anchor",
        }:
            output[column] = pd.to_datetime(
                output[column], errors="coerce", utc=(column == "signal_at")
            )
    return output


def _strict_bool(value: object) -> bool:
    """Return True only for an actual boolean True value.

    This deliberately rejects strings, integers, missing values, and other
    truthy objects so a malformed release can never fail open.
    """

    return isinstance(value, (bool, np.bool_)) and bool(value)


def _validate_frame_contract(attribute: str, frame: pd.DataFrame) -> None:
    expected = EXPECTED_COLUMNS[attribute]
    if tuple(frame.columns) != expected:
        missing = sorted(set(expected).difference(frame.columns))
        extra = sorted(set(frame.columns).difference(expected))
        raise ValueError(
            f"Schema mismatch for {FILE_MAP[attribute]}: missing={missing}, extra={extra}, "
            "or column order differs"
        )
    for column in BOOLEAN_COLUMNS.get(attribute, ()):
        if (
            not frame[column]
            .map(lambda value: isinstance(value, (bool, np.bool_)))
            .all()
        ):
            raise ValueError(f"Non-boolean value in {FILE_MAP[attribute]}:{column}")
    for column in KEY_DATE_COLUMNS.get(attribute, ()):
        if (
            not pd.api.types.is_datetime64_any_dtype(frame[column])
            or frame[column].isna().any()
        ):
            raise ValueError(
                f"Missing or invalid date in {FILE_MAP[attribute]}:{column}"
            )
    strings = set(STRING_COLUMNS.get(attribute, ()))
    booleans = set(BOOLEAN_COLUMNS.get(attribute, ()))
    dates = {
        column
        for column in frame.columns
        if pd.api.types.is_datetime64_any_dtype(frame[column])
    }
    nullable_strings = set(NULLABLE_STRING_COLUMNS.get(attribute, ()))
    for column in strings:
        non_null = frame[column].dropna()
        if not non_null.map(lambda value: isinstance(value, str)).all():
            raise ValueError(f"Non-string value in {FILE_MAP[attribute]}:{column}")
        if column not in nullable_strings and frame[column].isna().any():
            raise ValueError(f"Missing string value in {FILE_MAP[attribute]}:{column}")
    for column in set(frame.columns).difference(strings | booleans | dates):
        if not pd.api.types.is_numeric_dtype(frame[column]):
            raise ValueError(f"Non-numeric value in {FILE_MAP[attribute]}:{column}")
        observed = frame[column].dropna().astype(float)
        if not np.isfinite(observed).all():
            raise ValueError(f"Non-finite value in {FILE_MAP[attribute]}:{column}")
    for column, (lower, upper) in BOUNDED_NUMERIC_COLUMNS.get(attribute, {}).items():
        observed = frame[column].dropna().astype(float)
        if not observed.between(lower, upper, inclusive="both").all():
            raise ValueError(f"Out-of-range value in {FILE_MAP[attribute]}:{column}")


def _validate_bundle_consistency(
    manifest: dict[str, object], frames: dict[str, pd.DataFrame]
) -> None:
    weekly = frames["weekly"].sort_values("signal_date")
    predictions = frames["predictions"].sort_values("signal_date")
    current = frames["current_state"]
    manager = frames["manager_state"]
    gates = frames["validation_gates"]
    if len(current) != 1 or len(manager) != 1:
        raise ValueError(
            "Current-state and manager-state tables must each contain exactly one row"
        )
    if (
        weekly["signal_date"].duplicated().any()
        or predictions["signal_date"].duplicated().any()
    ):
        raise ValueError("Weekly and prediction signal dates must be unique")
    if gates[["gate_group", "gate"]].duplicated().any():
        raise ValueError("Validation gate identifiers must be unique")
    observed_gate_ids = sorted(
        gates["gate_group"].astype(str) + "/" + gates["gate"].astype(str)
    )
    registered_gate_ids = manifest.get("registered_gate_ids")
    if (
        int(manifest.get("registered_gate_count", -1)) != len(gates)
        or not isinstance(registered_gate_ids, list)
        or observed_gate_ids != sorted(str(value) for value in registered_gate_ids)
    ):
        raise ValueError(
            "Validation gate inventory does not match the registered release contract"
        )
    state = current.iloc[0]
    manager_row = manager.iloc[0]
    manifest_date = pd.Timestamp(manifest["latest_signal_date"])
    checks = {
        "trial_id": str(manifest["trial_id"]) == str(state["trial_id"]),
        "latest weekly date": manifest_date
        == pd.Timestamp(weekly["signal_date"].iloc[-1]),
        "latest prediction date": manifest_date
        == pd.Timestamp(predictions["signal_date"].iloc[-1]),
        "current-state date": manifest_date
        == pd.Timestamp(state["latest_signal_date"]),
        "manager-state date": manifest_date
        == pd.Timestamp(manager_row["as_of_anchor"]),
        "release state": str(manifest["release_state"]) == str(state["state"]),
        "directional inference": str(manifest["directional_inference"]).upper()
        == str(state["directional_inference"]).upper(),
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise ValueError(f"Cross-file bundle consistency failure: {', '.join(failed)}")


def _verify_parent_release(root: Path, manifest: dict[str, object]) -> None:
    parent = manifest.get("parent_release")
    if not isinstance(parent, dict):
        raise ValueError("Parent research release metadata is missing")
    required = {
        "release_id",
        "release_class",
        "manifest_file",
        "manifest_sha256",
        "known_exceptions_file",
        "known_exceptions_sha256",
    }
    if not required.issubset(parent):
        raise ValueError("Parent research release metadata is incomplete")
    for file_key, hash_key in (
        ("manifest_file", "manifest_sha256"),
        ("known_exceptions_file", "known_exceptions_sha256"),
    ):
        path = root / str(parent[file_key])
        if not path.is_file() or _sha256(path) != str(parent[hash_key]):
            raise ValueError(f"Parent release provenance check failed for {path.name}")
    parent_manifest = json.loads(
        (root / str(parent["manifest_file"])).read_text(encoding="utf-8")
    )
    artifacts = parent_manifest.get("artifacts")
    if not isinstance(artifacts, list) or int(
        parent_manifest.get("artifact_count", -1)
    ) != len(artifacts):
        raise ValueError("Parent release artifact inventory is incomplete")
    root_resolved = root.resolve()
    for artifact in artifacts:
        if not isinstance(artifact, dict) or not {
            "path",
            "bytes",
            "sha256",
        }.issubset(artifact):
            raise ValueError("Parent release artifact entry is incomplete")
        artifact_path = (root / str(artifact["path"])).resolve()
        if not artifact_path.is_relative_to(root_resolved):
            raise ValueError("Parent release artifact path is invalid")
        if not artifact_path.is_file():
            raise ValueError(
                f"Parent release artifact is missing: {artifact['path']}"
            )
        if artifact_path.stat().st_size != int(artifact["bytes"]):
            raise ValueError(
                f"Parent release artifact size mismatch: {artifact['path']}"
            )
        if _sha256(artifact_path) != str(artifact["sha256"]):
            raise ValueError(
                f"Parent release artifact checksum mismatch: {artifact['path']}"
            )
    if str(parent_manifest.get("release_id")) != str(parent["release_id"]):
        raise ValueError(
            "Parent release identifier does not match the bundled manifest"
        )
    if str(parent_manifest.get("release_class")) != str(parent["release_class"]):
        raise ValueError("Parent release class does not match the bundled manifest")
    if str(parent_manifest.get("manager_state")) != str(manifest.get("release_state")):
        raise ValueError("Packaged release state does not match the parent release")
    if (
        str(parent_manifest.get("directional_inference")).upper()
        != str(manifest.get("directional_inference")).upper()
    ):
        raise ValueError(
            "Packaged directional inference does not match the parent release"
        )
    validation = parent_manifest.get("validation", {})
    gates = pd.read_csv(root / FILE_MAP["validation_gates"])
    if int(validation.get("v2_primary_gates_total", -1)) != len(gates) or int(
        validation.get("v2_primary_gates_passed", -1)
    ) != int(gates["passed"].eq(True).sum()):
        raise ValueError(
            "Parent release gate summary does not match the packaged ledger"
        )
    gate_artifact = next(
        (
            item
            for item in artifacts
            if item.get("path") == "validation_gates.csv"
        ),
        None,
    )
    if gate_artifact is None or gate_artifact.get("sha256") != manifest.get(
        "files", {}
    ).get("validation_gates.csv", {}).get("sha256"):
        raise ValueError(
            "Validation gate ledger is not pinned to the parent research release"
        )
    exceptions_artifact = next(
        (
            item
            for item in artifacts
            if item.get("path") == "KNOWN_RELEASE_EXCEPTIONS.md"
        ),
        None,
    )
    if exceptions_artifact is None or exceptions_artifact.get("sha256") != str(
        parent.get("known_exceptions_sha256")
    ):
        raise ValueError(
            "Known-exceptions file is not pinned to the parent research release"
        )


def load_liquidity_bundle(root: Path, verify_hashes: bool = True) -> LiquidityBundle:
    root = Path(root)
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Liquidity bundle manifest not found: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != "1.0.0":
        raise ValueError(
            f"Unsupported liquidity bundle schema: {manifest.get('schema_version')}"
        )
    if verify_hashes:
        _verify_parent_release(root, manifest)

    frames: dict[str, pd.DataFrame] = {}
    for attribute, filename in FILE_MAP.items():
        path = root / filename
        if not path.is_file():
            raise FileNotFoundError(f"Liquidity bundle file not found: {path}")
        expected = manifest.get("files", {}).get(filename, {})
        if verify_hashes and expected.get("sha256") != _sha256(path):
            raise ValueError(f"Checksum mismatch for {filename}")
        frame = _parse_dates(pd.read_csv(path))
        if expected and int(expected.get("rows", len(frame))) != len(frame):
            raise ValueError(f"Row-count mismatch for {filename}")
        if expected and int(expected.get("columns", len(frame.columns))) != len(
            frame.columns
        ):
            raise ValueError(f"Column-count mismatch for {filename}")
        _validate_frame_contract(attribute, frame)
        frames[attribute] = frame
    _validate_bundle_consistency(manifest, frames)
    return LiquidityBundle(root=root, manifest=manifest, **frames)


def source_status_table(
    bundle: LiquidityBundle, current_time: pd.Timestamp | None = None
) -> pd.DataFrame:
    row = latest_weekly(bundle)
    now = pd.Timestamp(current_time or pd.Timestamp.now(tz="America/New_York"))
    if now.tzinfo is None:
        now = now.tz_localize("America/New_York")
    else:
        now = now.tz_convert("America/New_York")
    now = now.tz_localize(None)
    specs = (
        (
            "Reserve balances",
            "reserves_bn",
            UNIT_USD_BILLIONS,
            "Federal Reserve H.4.1",
            "WRBWFRBL",
            "https://fred.stlouisfed.org/series/WRBWFRBL",
            "Fed H.4.1 / WRBWFRBL",
        ),
        (
            "Federal Reserve assets",
            "assets_bn",
            UNIT_USD_BILLIONS,
            "Federal Reserve H.4.1",
            "WALCL",
            "https://fred.stlouisfed.org/series/WALCL",
            "Fed H.4.1 / WALCL",
        ),
        (
            "Treasury General Account",
            "tga_dts_bn",
            UNIT_USD_BILLIONS,
            "Daily Treasury Statement",
            "TGA_DTS level; WDTGAL decomposition",
            "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/dts/operating_cash_balance",
            "Treasury DTS / TGA_DTS + WDTGAL",
        ),
        (
            "Overnight reverse repo",
            "onrrp_bn",
            UNIT_USD_BILLIONS,
            "New York Fed",
            "RRPONTSYD",
            "https://fred.stlouisfed.org/series/RRPONTSYD",
            "NY Fed / RRPONTSYD",
        ),
        (
            "Currency in circulation",
            "currency_bn",
            UNIT_USD_BILLIONS,
            "Federal Reserve H.4.1",
            "WCURCIR",
            "https://fred.stlouisfed.org/series/WCURCIR",
            "Fed H.4.1 / WCURCIR",
        ),
        (
            "Baa minus 10-year",
            "baa10y",
            UNIT_PERCENTAGE_POINTS,
            "FRED",
            "BAA10Y",
            "https://fred.stlouisfed.org/series/BAA10Y",
            "FRED / BAA10Y",
        ),
        (
            "VIX",
            "vix",
            UNIT_INDEX_POINTS,
            "Cboe via FRED",
            "VIXCLS",
            "https://fred.stlouisfed.org/series/VIXCLS",
            "Cboe-FRED / VIXCLS",
        ),
        (
            "SOFR",
            "sofr",
            UNIT_PERCENT,
            "New York Fed",
            "SOFR_NYFED",
            "https://markets.newyorkfed.org/api/rates/secured/sofr/search.json",
            "NY Fed / SOFR",
        ),
        (
            "IORB",
            "iorb",
            UNIT_PERCENT,
            "Federal Reserve",
            "IORB",
            "https://fred.stlouisfed.org/series/IORB",
            "Fed / IORB",
        ),
    )
    records = []
    for name, field, unit, source, source_series, source_url, source_key in specs:
        packaged_stale = _strict_bool(row.get(f"{field}__stale", True))
        observation = row.get(f"{field}__observation_date")
        observation_date = (
            pd.Timestamp(observation) if pd.notna(observation) else pd.NaT
        )
        wall_clock_age = (
            (now.normalize() - observation_date.normalize()).days
            if pd.notna(observation_date)
            else np.nan
        )
        ttl = SOURCE_TTLS_DAYS[field]
        try:
            latest_value_valid = np.isfinite(float(row.get(field)))
        except (TypeError, ValueError):
            latest_value_valid = False
        operational_stale = (
            packaged_stale
            or not latest_value_valid
            or not np.isfinite(wall_clock_age)
            or wall_clock_age > ttl
        )
        records.append(
            {
                "Series": name,
                "Latest value": row.get(field),
                "Unit": unit,
                "Observation date": observation_date.date()
                if pd.notna(observation_date)
                else None,
                "Age at anchor, days": row.get(f"{field}__age_days"),
                "Age now, days": wall_clock_age,
                "Freshness limit, days": ttl,
                "Packaged status": "STALE" if packaged_stale else "AVAILABLE",
                "Live status": "STALE" if operational_stale else "CURRENT",
                "Primary source": source,
                "Source series": source_series,
                "Source URL": source_url,
                "Source key": source_key,
            }
        )
    market_observation = pd.Timestamp(row.get("market_asof_date"))
    market_age = (
        (now.normalize() - market_observation.normalize()).days
        if pd.notna(market_observation)
        else np.nan
    )
    market_fields = (
        "spy_adj_close",
        "spy_mom60",
        "spy_dist200",
        "sector_breadth50",
        "sector_breadth50_change20",
    )
    try:
        market_values_valid = np.isfinite(
            np.asarray([float(row.get(field)) for field in market_fields], dtype=float)
        ).all()
    except (TypeError, ValueError):
        market_values_valid = False
    records.append(
        {
            "Series": "Market transmission inputs",
            "Latest value": row.get("spy_adj_close"),
            "Unit": UNIT_USD_PRICE,
            "Observation date": market_observation.date()
            if pd.notna(market_observation)
            else None,
            "Age at anchor, days": (
                pd.Timestamp(row["signal_date"]).normalize()
                - market_observation.normalize()
            ).days
            if pd.notna(market_observation)
            else np.nan,
            "Age now, days": market_age,
            "Freshness limit, days": MARKET_TRANSMISSION_TTL_DAYS,
            "Packaged status": "AVAILABLE"
            if pd.notna(market_observation) and market_values_valid
            else "STALE",
            "Live status": "CURRENT"
            if np.isfinite(market_age)
            and market_age <= MARKET_TRANSMISSION_TTL_DAYS
            and market_values_valid
            else "STALE",
            "Primary source": "Market close and sector breadth",
            "Source series": "SPY + 9 sector ETFs; five derived transmission fields",
            "Source URL": "https://finance.yahoo.com/quote/SPY/history/",
            "Source key": "Market / SPY + 9 sectors",
        }
    )
    output = pd.DataFrame(records)
    output["Display value"] = output.apply(
        lambda record: format_source_value(record["Latest value"], record["Unit"]),
        axis=1,
    )
    return output


def live_source_status_table(
    snapshot: LiveLiquiditySnapshot, current_time: pd.Timestamp | None = None
) -> pd.DataFrame:
    """Normalize the current release ledger to the page's source-table contract."""

    units = {
        "USD billions": UNIT_USD_BILLIONS,
        "USD billions per business day": UNIT_USD_BILLIONS,
        "percentage points": UNIT_PERCENTAGE_POINTS,
        "index points": UNIT_INDEX_POINTS,
        "percent": UNIT_PERCENT,
        "USD price": UNIT_USD_PRICE,
    }
    wall_clock = (
        current_time
        if current_time is not None
        else pd.Timestamp.now(tz="America/New_York")
    )
    if wall_clock.tzinfo is None:
        wall_clock = wall_clock.tz_localize("America/New_York")
    else:
        wall_clock = wall_clock.tz_convert("America/New_York")
    output = snapshot.sources.copy()
    output["Observation date"] = pd.to_datetime(output["observation_date"]).dt.date
    runtime_expected = runtime_expected_dates(snapshot, now=wall_clock)
    output["Expected date"] = pd.to_datetime(runtime_expected).dt.date
    output["Verified through"] = pd.to_datetime(output["verified_through"]).dt.date
    output["Display value"] = output.apply(
        lambda row: format_source_value(row["value"], units[str(row["unit"])]), axis=1
    )
    status_labels = {
        "CURRENT_UPDATED": "CURRENT · UPDATED",
        "CURRENT_UNCHANGED": "CURRENT · UNCHANGED",
        "CURRENT_PUBLICATION_LAG": "CURRENT · SCHEDULED LAG",
        "STALE": "STALE",
    }
    output["Live status"] = output["status"].map(status_labels).fillna("UNAVAILABLE")
    current_mask = source_current_mask(snapshot, now=wall_clock)
    output.loc[~current_mask, "Live status"] = "STALE · REFRESH REQUIRED"
    for index in output.index[~current_mask]:
        expected_date, rule = expected_observation_date(
            str(output.at[index, "field"]), wall_clock
        )
        output.at[index, "status_detail"] = (
            f"Packaged observation {output.at[index, 'Observation date']} was verified "
            f"at {snapshot.manifest['information_cutoff_et']}; the runtime clock now "
            f"expects at least {expected_date.date()} under {rule}. Refresh required."
        )
    output = output.rename(
        columns={
            "series": "Series",
            "provider": "Primary source",
            "source_key": "Source series",
            "source_url": "Source URL",
            "status_detail": "Status detail",
            "retrieved_at_utc": "Retrieved at UTC",
        }
    )
    output["Source key"] = output["Primary source"] + " / " + output["Source series"]
    return output


def latest_observed_state(
    bundle: LiquidityBundle, snapshot: LiveLiquiditySnapshot | None = None
) -> pd.Series:
    """Return current observed mechanics, falling back to the frozen research anchor."""

    if snapshot is None:
        return latest_weekly(bundle)
    return snapshot.state.iloc[-1]


def _expected_path_artifact_valid(bundle: LiquidityBundle) -> bool:
    """Require a parent-pinned, point-in-time expectation and reconciled surprise."""

    if (
        str(bundle.manifest.get("expected_liquidity_path_status", "")).upper()
        != "AVAILABLE_POINT_IN_TIME"
    ):
        return False
    metadata = bundle.manifest.get("expected_liquidity_path")
    if not isinstance(metadata, dict):
        return False
    required = {"file", "sha256", "rows", "columns", "parent_artifact_path"}
    if not required.issubset(metadata):
        return False
    path = (bundle.root / str(metadata["file"])).resolve()
    if path.parent != bundle.root.resolve() or not path.is_file():
        return False
    if _sha256(path) != str(metadata["sha256"]):
        return False
    try:
        frame = pd.read_csv(path)
    except (OSError, ValueError, pd.errors.ParserError):
        return False
    if (
        tuple(frame.columns) != EXPECTED_PATH_COLUMNS
        or len(frame) != int(metadata["rows"])
        or len(frame.columns) != int(metadata["columns"])
        or frame.empty
    ):
        return False
    for column in ("signal_date", "expectation_vintage", "forecast_horizon_end"):
        frame[column] = pd.to_datetime(frame[column], errors="coerce")
    for column in (
        "expected_reserve_impulse_4w_bp",
        "realized_reserve_impulse_4w_bp",
        "liquidity_surprise_bp",
    ):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    if frame[list(EXPECTED_PATH_COLUMNS)].isna().any().any():
        return False
    expected_numeric = frame[
        [
            "expected_reserve_impulse_4w_bp",
            "realized_reserve_impulse_4w_bp",
            "liquidity_surprise_bp",
        ]
    ].to_numpy(dtype=float)
    if not np.isfinite(expected_numeric).all():
        return False
    if frame["signal_date"].duplicated().any():
        return False
    if not (frame["expectation_vintage"] < frame["signal_date"]).all():
        return False
    if not (frame["forecast_horizon_end"] == frame["signal_date"]).all():
        return False
    latest = frame.sort_values("signal_date").iloc[-1]
    if pd.Timestamp(latest["signal_date"]) != pd.Timestamp(
        bundle.manifest.get("latest_signal_date")
    ):
        return False
    weekly_latest = latest_weekly(bundle)
    if not np.isclose(
        float(latest["realized_reserve_impulse_4w_bp"]),
        float(weekly_latest["reserve_impulse_4w_bp"]),
        atol=1e-8,
    ):
        return False
    if not np.isclose(
        float(latest["liquidity_surprise_bp"]),
        float(latest["realized_reserve_impulse_4w_bp"])
        - float(latest["expected_reserve_impulse_4w_bp"]),
        atol=1e-8,
    ):
        return False
    try:
        parent_manifest = json.loads(
            (
                bundle.root / str(bundle.manifest["parent_release"]["manifest_file"])
            ).read_text(encoding="utf-8")
        )
    except (KeyError, OSError, TypeError, ValueError):
        return False
    pinned = next(
        (
            item
            for item in parent_manifest.get("artifacts", [])
            if item.get("path") == str(metadata["parent_artifact_path"])
        ),
        None,
    )
    return bool(pinned and str(pinned.get("sha256")) == str(metadata["sha256"]))


def expected_path_snapshot(bundle: LiquidityBundle) -> dict[str, object]:
    """Return the latest validated expectation and surprise, or an unavailable state."""

    if not _expected_path_artifact_valid(bundle):
        return {
            "available": False,
            "expected_path_state": "No point-in-time expectation",
            "surprise_state": "Unavailable",
            "expected_reserve_impulse_bp": float("nan"),
            "liquidity_surprise_bp": float("nan"),
            "reason": "Point-in-time expected liquidity path is not yet packaged",
        }
    metadata = bundle.manifest["expected_liquidity_path"]
    frame = pd.read_csv(bundle.root / str(metadata["file"]))
    latest = frame.sort_values("signal_date").iloc[-1]
    expected = float(latest["expected_reserve_impulse_4w_bp"])
    surprise = float(latest["liquidity_surprise_bp"])
    surprise_state = (
        "Positive" if surprise > 0 else "Negative" if surprise < 0 else "In line"
    )
    return {
        "available": True,
        "expected_path_state": "Available",
        "surprise_state": surprise_state,
        "expected_reserve_impulse_bp": expected,
        "liquidity_surprise_bp": surprise,
        "reason": (
            f"{format_basis_points(surprise, signed=True)} versus the frozen "
            "expected reserve path"
        ),
    }


def _manager_card_parent_pinned(bundle: LiquidityBundle) -> bool:
    """Verify that the packaged manager card is hash-pinned by the parent release."""

    parent = bundle.manifest.get("parent_release", {})
    if (
        not isinstance(parent, dict)
        or str(parent.get("manager_state_card_status", "")).upper()
        != "PARENT_HASH_PINNED"
    ):
        return False
    manager_path = bundle.root / FILE_MAP["manager_state"]
    try:
        parent_manifest = json.loads(
            (bundle.root / str(parent["manifest_file"])).read_text(encoding="utf-8")
        )
    except (KeyError, OSError, TypeError, ValueError):
        return False
    pinned = next(
        (
            item
            for item in parent_manifest.get("artifacts", [])
            if item.get("path") == "results/manager_state_card.csv"
        ),
        None,
    )
    return bool(
        manager_path.is_file()
        and pinned
        and str(pinned.get("sha256")) == _sha256(manager_path)
    )


def _signal_critical_values_valid(bundle: LiquidityBundle) -> bool:
    """Reject missing or non-finite latest observations on the publication path."""

    weekly = latest_weekly(bundle)
    prediction = latest_prediction(bundle)
    weekly_columns = (
        "spy_adj_close",
        "sector_breadth50",
        "reserve_impulse_4w_bp",
        "reserve_impulse_13w_bp",
        "tga_change_4w_bp_assets",
        "onrrp_change_4w_bp_assets",
        "fed_asset_change_4w_bp",
        "currency_change_4w_bp_assets",
        "other_liability_residual_4w_bp",
        "baa10y",
        "vix",
        "reserves_bn",
        "assets_bn",
        "tga_dts_bn",
        "onrrp_bn",
        "currency_bn",
        "sofr",
        "iorb",
    )
    prediction_columns = (
        "raw_probability",
        "probability",
        "base_rate",
        "risk_percentile",
        "warning_threshold",
        "C",
        "domain__T",
        "domain__C",
        "domain__B",
        "domain__V",
        "domain__F",
        "domain__D",
        "domain__I",
    )
    try:
        values = np.asarray(
            [float(weekly[column]) for column in weekly_columns]
            + [float(prediction[column]) for column in prediction_columns],
            dtype=float,
        )
    except (KeyError, TypeError, ValueError):
        return False
    return bool(np.isfinite(values).all())


def model_output_permitted(
    bundle: LiquidityBundle, current_time: pd.Timestamp | None = None
) -> bool:
    """Fail-closed permission check for any directional regime output."""

    row = bundle.current_state.iloc[-1]
    manager = bundle.manager_state.iloc[-1]
    parent = bundle.manifest.get("parent_release", {})
    gate_values = bundle.validation_gates["passed"]
    gates_are_boolean = gate_values.map(
        lambda value: isinstance(value, (bool, np.bool_))
    ).all()
    all_gates_pass = gates_are_boolean and bool(gate_values.map(_strict_bool).all())
    observed_gate_ids = sorted(
        bundle.validation_gates["gate_group"].astype(str)
        + "/"
        + bundle.validation_gates["gate"].astype(str)
    )
    registered_gate_ids = bundle.manifest.get("registered_gate_ids", [])
    exact_gate_inventory = (
        isinstance(registered_gate_ids, list)
        and len(observed_gate_ids)
        == int(bundle.manifest.get("registered_gate_count", -1))
        and observed_gate_ids == sorted(str(value) for value in registered_gate_ids)
    )
    sources_current = (
        source_status_table(bundle, current_time)["Live status"].eq("CURRENT").all()
    )
    state = str(row.get("state", "")).strip().lower()
    direction = str(row.get("directional_inference", "")).strip().upper()
    return bool(
        _strict_bool(row.get("ordinal_state_permitted"))
        and _strict_bool(row.get("primary_gates_pass"))
        and all_gates_pass
        and exact_gate_inventory
        and sources_current
        and _signal_critical_values_valid(bundle)
        and _expected_path_artifact_valid(bundle)
        and str(parent.get("release_class", "")).upper() == PRODUCTION_RELEASE_CLASS
        and _manager_card_parent_pinned(bundle)
        and str(manager.get("model_validity", "")).upper() == "PASSED_PREDICTIVE_GATE"
        and str(manager.get("data_quality", "")).upper() == "PASS"
        and str(manager.get("state", "")).strip().lower() == state
        and str(manager.get("directional_inference", "")).strip().upper() == direction
        and str(bundle.manifest.get("release_state", "")).strip().lower() == state
        and str(bundle.manifest.get("directional_inference", "")).strip().upper()
        == direction
        and state in ALLOWED_DIRECTIONAL_STATES
        and direction not in {"", "SUPPRESSED", "UNAVAILABLE", "GRAY"}
    )


def latest_prediction(bundle: LiquidityBundle) -> pd.Series:
    return bundle.predictions.sort_values("signal_date").iloc[-1]


def latest_weekly(bundle: LiquidityBundle) -> pd.Series:
    return bundle.weekly.sort_values("signal_date").iloc[-1]


def market_context_domains(
    bundle: LiquidityBundle,
    live_snapshot: LiveLiquiditySnapshot | None = None,
) -> pd.Series:
    """Return comparable descriptive market-context domains at the live clock."""

    if live_snapshot is None:
        return latest_prediction(bundle)

    state = live_snapshot.state.iloc[-1]
    current_date = pd.Timestamp(state["market_asof_date"])
    weekly = bundle.weekly.sort_values("signal_date")

    def lagged_weekly(column: str, calendar_days: int) -> float:
        eligible = weekly.loc[
            weekly["signal_date"].le(current_date - pd.Timedelta(days=calendar_days))
        ]
        if eligible.empty:
            raise ValueError(f"No lagged market context is available for {column}")
        return float(eligible.iloc[-1][column])

    raw = {
        "spy_mom60": float(state["spy_mom60"]),
        "spy_dist200": float(state["spy_dist200"]),
        "sector_breadth50": float(state["sector_breadth50"]),
        "sector_breadth50_change20": float(state["sector_breadth50_change20"]),
        "baa10y": float(state["baa10y"]),
        "baa10y_change20": float(state["baa10y"])
        - lagged_weekly("baa10y", 28),
        "vix": float(state["vix"]),
        "vix_change5": float(state["vix"]) - lagged_weekly("vix", 7),
        "reserve_impulse_4w_bp": float(state["reserve_impulse_4w_bp"]),
    }

    normalized = {}
    for field, value in raw.items():
        lower, upper, median, scale = MARKET_CONTEXT_TRANSFORM_2026[field]
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
    return pd.Series(
        {
            "domain__T": trend,
            "domain__C": credit,
            "domain__B": breadth,
            "domain__V": volatility,
            "domain__F": fragility,
            "domain__D": drain,
            "domain__I": interaction,
        }
    )


def percentile_of_last(values: Iterable[float]) -> float:
    series = pd.to_numeric(pd.Series(values), errors="coerce").dropna()
    if series.empty:
        return float("nan")
    current = series.iloc[-1]
    return float(100 * (series.le(current).sum() - 0.5) / len(series))


def percentile_against_prior(value: float, prior_values: Iterable[float]) -> float:
    """Return a midrank percentile using only observations preceding ``value``."""

    prior = pd.to_numeric(pd.Series(prior_values), errors="coerce").dropna()
    current = float(value)
    if prior.empty or not np.isfinite(current):
        return float("nan")
    less = int(prior.lt(current).sum())
    equal = int(prior.eq(current).sum())
    return float(100 * (less + 0.5 * equal) / len(prior))


def observed_regime_classifier(
    reserve_percentile: float,
    reserve_impulse_change_4w_bp: float,
    trend_stability_band_bp: float,
) -> dict[str, object]:
    """Classify observed reserve mechanics without making a market forecast.

    The horizontal state is the current four-week reserve impulse's historical
    percentile. The vertical state is the change in that impulse versus four
    weeks earlier. The symmetric stability band is supplied by a lagged,
    five-year empirical calibration so that small changes are not presented as
    turns. These rules are descriptive and are not a substitute for the
    separately governed predictive regime.
    """
    level_value = float(reserve_percentile)
    trend_value = float(reserve_impulse_change_4w_bp)
    band_value = float(trend_stability_band_bp)
    if (
        not np.isfinite(level_value)
        or not np.isfinite(trend_value)
        or not np.isfinite(band_value)
        or band_value <= 0
    ):
        return {
            "available": False,
            "level_code": "unavailable",
            "level_label": "Unavailable",
            "trend_code": "unavailable",
            "trend_label": "Unavailable",
            "regime_label": "Unavailable",
            "plain_english": "Observed reserve mechanics cannot be classified.",
        }

    if level_value < OBSERVED_LEVEL_LOWER:
        level_code, level_label = "below_normal", "Below normal versus history"
    elif level_value <= OBSERVED_LEVEL_UPPER:
        level_code, level_label = "near_normal", "Typical versus history"
    else:
        level_code, level_label = "above_normal", "Above normal versus history"

    if trend_value > band_value:
        trend_code, trend_label = "improving", "Improving"
    elif trend_value < -band_value:
        trend_code, trend_label = "deteriorating", "Deteriorating"
    else:
        trend_code, trend_label = "stable", "Broadly stable"

    regime_label = OBSERVED_REGIME_LABELS[(trend_code, level_code)]
    plain_english = (
        f"Reserve flow is {level_label.lower()} and {trend_label.lower()} "
        "versus four weeks ago."
    )

    return {
        "available": True,
        "level_code": level_code,
        "level_label": level_label,
        "trend_code": trend_code,
        "trend_label": trend_label,
        "regime_label": regime_label,
        "plain_english": plain_english,
        "trend_stability_band_bp": band_value,
    }


def diagnostic_summary(
    bundle: LiquidityBundle,
    current_time: pd.Timestamp | None = None,
    live_snapshot: LiveLiquiditySnapshot | None = None,
) -> dict[str, object]:
    weekly_history = bundle.weekly.sort_values("signal_date")
    prediction_history = bundle.predictions.sort_values("signal_date")
    latest = latest_observed_state(bundle, live_snapshot)
    pred = prediction_history.iloc[-1]
    context = market_context_domains(bundle, live_snapshot)
    transition_lag = min(4, len(weekly_history) - 1, len(prediction_history) - 1)
    if live_snapshot is None:
        comparison = weekly_history.iloc[-1 - transition_lag]
    else:
        observed_as_of = pd.Timestamp(latest["as_of_date"])
        eligible = weekly_history.loc[
            weekly_history["signal_date"].le(observed_as_of - pd.Timedelta(days=28))
        ]
        comparison = eligible.iloc[-1] if not eligible.empty else weekly_history.iloc[0]
    reserve_change = float(
        latest["reserve_impulse_4w_bp"] - comparison["reserve_impulse_4w_bp"]
    )
    fragility_change = float(
        context["domain__F"]
        - prediction_history.iloc[-1 - transition_lag]["domain__F"]
    )
    observed_as_of = pd.Timestamp(latest.get("as_of_date", latest.get("signal_date")))
    calibration_history = weekly_history.loc[
        weekly_history["signal_date"].lt(observed_as_of)
    ].copy()
    level_calibration = calibration_history.tail(OBSERVED_CALIBRATION_WEEKS)[
        "reserve_impulse_4w_bp"
    ]
    reserve_pct = percentile_against_prior(
        float(latest["reserve_impulse_4w_bp"]), level_calibration
    )
    historical_changes = weekly_history.assign(
        reserve_impulse_change_4w_bp=weekly_history["reserve_impulse_4w_bp"].diff(4)
    )
    trend_calibration = (
        historical_changes.loc[
            historical_changes["signal_date"].lt(observed_as_of),
            "reserve_impulse_change_4w_bp",
        ]
        .dropna()
        .tail(OBSERVED_CALIBRATION_WEEKS)
    )
    trend_stability_band = (
        float(trend_calibration.abs().quantile(OBSERVED_TREND_STABLE_QUANTILE))
        if len(trend_calibration) >= OBSERVED_MIN_CALIBRATION_OBS
        else float("nan")
    )
    fragility_pct = percentile_against_prior(
        float(context["domain__F"]), bundle.predictions["domain__F"]
    )
    if reserve_pct <= 20:
        reserve_read = "Adverse tail"
    elif reserve_pct >= 80:
        reserve_read = "Supportive tail"
    else:
        reserve_read = "Middle range"
    if fragility_pct >= 75:
        transmission_read = "Elevated fragility"
    elif fragility_pct <= 25:
        transmission_read = "Benign fragility"
    else:
        transmission_read = "Mixed fragility"
    gates = bundle.validation_gates["passed"].map(_strict_bool)
    state = bundle.current_state.iloc[-1]
    source_status = (
        live_source_status_table(live_snapshot, current_time=current_time)
        if live_snapshot is not None
        else source_status_table(bundle, current_time)
    )
    expected = expected_path_snapshot(bundle)
    output_permitted = model_output_permitted(bundle, current_time)
    observed_regime = observed_regime_classifier(
        reserve_pct, reserve_change, trend_stability_band
    )
    return {
        "state": str(state["state"]),
        "direction": str(state["directional_inference"]),
        "output_permitted": output_permitted,
        "latest_signal_date": pd.Timestamp(weekly_history.iloc[-1]["signal_date"]),
        "market_as_of": pd.Timestamp(
            latest.get("market_asof_date", latest.get("signal_date"))
        ),
        "observed_as_of": pd.Timestamp(
            latest.get("as_of_date", latest.get("signal_date"))
        ),
        "accounting_as_of": pd.Timestamp(
            latest.get("accounting_asof_date", latest.get("signal_date"))
        ),
        "research_cutoff": str(bundle.manifest["research_cutoff"]),
        "reserve_impulse_bp": float(latest["reserve_impulse_4w_bp"]),
        "reserve_percentile": reserve_pct,
        "reserve_read": reserve_read,
        "mechanical_direction": (
            "Reserve-additive"
            if float(latest["reserve_impulse_4w_bp"]) > 0
            else "Reserve-draining"
        ),
        "fragility": float(context["domain__F"]),
        "fragility_percentile": fragility_pct,
        "transmission_read": transmission_read,
        "transition_read": "Unvalidated / descriptive",
        "reserve_impulse_change_4w_bp": reserve_change,
        "observed_regime_available": bool(observed_regime["available"]),
        "observed_regime_level": str(observed_regime["level_label"]),
        "observed_regime_level_code": str(observed_regime["level_code"]),
        "observed_regime_trend": str(observed_regime["trend_label"]),
        "observed_regime_trend_code": str(observed_regime["trend_code"]),
        "observed_regime_label": str(observed_regime["regime_label"]),
        "observed_regime_explanation": str(observed_regime["plain_english"]),
        "observed_regime_trend_band_bp": trend_stability_band,
        "observed_regime_calibration_observations": int(len(trend_calibration)),
        "observed_regime_near_trend_boundary": bool(
            np.isfinite(trend_stability_band)
            and abs(abs(reserve_change) - trend_stability_band)
            <= 0.05 * trend_stability_band
        ),
        "fragility_change_4w": fragility_change,
        "risk_percentile": float(pred["risk_percentile"]),
        "risk_probability": float(pred["probability"]),
        "risk_base_rate": float(pred["base_rate"]),
        "risk_warning_threshold": float(pred["warning_threshold"]),
        "risk_warning": bool(pred["warning"]),
        "gates_passed": int(gates.sum()),
        "gates_total": int(len(gates)),
        "data_quality": str(bundle.manager_state.iloc[-1]["data_quality"]),
        "model_validity": str(bundle.manager_state.iloc[-1]["model_validity"]),
        "release_class": str(bundle.manifest["parent_release"]["release_class"]),
        "release_id": str(bundle.manifest["parent_release"]["release_id"]),
        "sources_current": bool(
            snapshot_is_current(live_snapshot, now=current_time)
            if live_snapshot is not None
            else source_status["Live status"].eq("CURRENT").all()
        ),
        "sources_stale": int(
            (~source_current_mask(live_snapshot, now=current_time)).sum()
            if live_snapshot is not None
            else source_status["Live status"].eq("STALE").sum()
        ),
        "sources_total": int(len(source_status)),
        "expected_path_available": bool(expected["available"]),
        "expected_path_state": str(expected["expected_path_state"]),
        "expected_reserve_impulse_bp": float(expected["expected_reserve_impulse_bp"]),
        "liquidity_surprise_bp": float(expected["liquidity_surprise_bp"]),
        "surprise_state": str(expected["surprise_state"]),
        "surprise_reason": str(expected["reason"]),
        "predictive_validation_passed": bool(gates.all()),
        "parent_production_certified": str(
            bundle.manifest["parent_release"]["release_class"]
        ).upper()
        == PRODUCTION_RELEASE_CLASS,
        "manager_card_parent_pinned": _manager_card_parent_pinned(bundle),
    }


def _base_layout(
    fig: go.Figure, height: int, *, hovermode: str = "x unified"
) -> go.Figure:
    fig.update_layout(
        template="plotly_white",
        height=height,
        margin=dict(l=58, r=36, t=28, b=70),
        paper_bgcolor="#ffffff",
        plot_bgcolor="#ffffff",
        font=dict(family="Arial, Helvetica, sans-serif", color=TEXT, size=12),
        hovermode=hovermode,
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.01,
            xanchor="left",
            x=0,
            font=dict(size=10),
        ),
    )
    fig.update_xaxes(showgrid=False, linecolor=BORDER, zeroline=False)
    fig.update_yaxes(gridcolor=GRID, linecolor=BORDER, zeroline=False)
    return fig


def filter_lookback(
    frame: pd.DataFrame, years: int | None, date_column: str
) -> pd.DataFrame:
    output = frame.sort_values(date_column).copy()
    if years is None or output.empty:
        return output
    cutoff = output[date_column].max() - pd.DateOffset(years=int(years))
    return output.loc[output[date_column].ge(cutoff)].copy()


def liquidity_impulse_figure(
    bundle: LiquidityBundle,
    years: int | None,
    live_snapshot: LiveLiquiditySnapshot | None = None,
) -> go.Figure:
    history = bundle.weekly.copy()
    if live_snapshot is not None:
        live = live_snapshot.state.copy()
        live["signal_date"] = pd.to_datetime(live["as_of_date"])
        shared = [column for column in history.columns if column in live.columns]
        history = pd.concat([history, live[shared]], ignore_index=True, sort=False)
    frame = filter_lookback(history, years, "signal_date")
    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.10,
        row_heights=(0.38, 0.62),
        subplot_titles=(
            "Realized reserve impulse",
            "Reserve-accounting contribution by driver",
        ),
    )
    fig.add_trace(
        go.Scatter(
            x=frame["signal_date"],
            y=frame["reserve_impulse_4w_bp"],
            name="Realized reserves",
            line=dict(color=BLACK, width=2.5),
            customdata=[
                format_basis_points(value, signed=True)
                for value in frame["reserve_impulse_4w_bp"]
            ],
            hovertemplate="Realized: %{customdata}<extra></extra>",
            showlegend=False,
        ),
        row=1,
        col=1,
    )
    if live_snapshot is not None:
        live_date = pd.Timestamp(live_snapshot.state.iloc[-1]["as_of_date"])
        live_value = float(live_snapshot.state.iloc[-1]["reserve_impulse_4w_bp"])
        fig.add_trace(
            go.Scatter(
                x=[live_date],
                y=[live_value],
                mode="markers",
                name="Current release",
                marker=dict(
                    color=BLACK, size=8, symbol="circle-open", line=dict(width=2)
                ),
                customdata=[format_basis_points(live_value, signed=True)],
                hovertemplate="Current release: %{customdata}<extra></extra>",
                showlegend=False,
            ),
            row=1,
            col=1,
        )
    contributions = (
        ("Fed assets", frame["fed_asset_change_4w_bp"], ""),
        ("TGA", -frame["tga_change_4w_bp_assets"], "/"),
        ("ON RRP", -frame["onrrp_change_4w_bp_assets"], "\\"),
        ("Currency", -frame["currency_change_4w_bp_assets"], "x"),
        (
            "Other liabilities / residual",
            frame["other_liability_residual_4w_bp"],
            ".",
        ),
    )
    for name, values, pattern in contributions:
        fig.add_trace(
            go.Bar(
                x=frame["signal_date"],
                y=values,
                name=name,
                marker=dict(
                    color=DRIVER_COLORS[name],
                    pattern=dict(shape=pattern, solidity=0.22),
                    line=dict(color="#ffffff", width=0.35),
                ),
                opacity=0.80,
                customdata=[
                    format_basis_points(value, signed=True) for value in values
                ],
                hovertemplate=f"{name}: %{{customdata}}<extra></extra>",
            ),
            row=2,
            col=1,
        )
    fig.add_hline(y=0, line_color=MUTED, line_width=1, row=1, col=1)
    fig.add_hline(y=0, line_color=MUTED, line_width=1, row=2, col=1)
    fig.update_layout(barmode="relative", bargap=0.08)
    fig.update_annotations(
        font=dict(family="Arial, Helvetica, sans-serif", color=TEXT, size=12)
    )
    # Keep the axis unit compact so the two vertical labels remain legible on
    # narrow manager screens; the surrounding section copy defines the basis.
    fig.update_yaxes(title_text="bp", row=1, col=1)
    fig.update_yaxes(title_text="bp", row=2, col=1)
    fig = _base_layout(fig, 560)
    fig.update_layout(
        margin=dict(l=58, r=36, t=92, b=60),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.14,
            xanchor="left",
            x=0,
            font=dict(size=10),
        ),
    )
    return fig


def current_mechanics_figure(
    bundle: LiquidityBundle, live_snapshot: LiveLiquiditySnapshot | None = None
) -> go.Figure:
    """Show the latest reserve-accounting contribution by driver."""

    row = latest_observed_state(bundle, live_snapshot)
    labels = (
        "Fed assets",
        "TGA",
        "ON RRP",
        "Currency",
        "Other liabilities",
    )
    values = (
        float(row["fed_asset_change_4w_bp"]),
        -float(row["tga_change_4w_bp_assets"]),
        -float(row["onrrp_change_4w_bp_assets"]),
        -float(row["currency_change_4w_bp_assets"]),
        float(row["other_liability_residual_4w_bp"]),
    )
    limit = max(abs(value) for value in values) * 1.25
    fig = go.Figure(
        go.Bar(
            x=values,
            y=labels,
            orientation="h",
            marker_color=[
                DRIVER_COLORS[
                    "Other liabilities / residual"
                    if label == "Other liabilities"
                    else label
                ]
                for label in labels
            ],
            text=[format_basis_points(value, signed=True) for value in values],
            textposition="auto",
            textangle=0,
            textfont=dict(color=BLACK, size=12),
            cliponaxis=False,
            customdata=[format_basis_points(value, signed=True) for value in values],
            hovertemplate="%{y}: %{customdata}<extra></extra>",
        )
    )
    fig.add_vline(x=0, line_color=BLACK, line_width=1)
    fig.update_xaxes(
        title="Reserve contribution<br>(bp of lagged Fed assets)",
        range=[-limit * 1.15, limit * 1.15],
        automargin=True,
    )
    fig.update_yaxes(autorange="reversed", automargin=True)
    fig.update_layout(showlegend=False)
    return _base_layout(fig, 360, hovermode="closest")


def domain_diagnostic_figure(
    bundle: LiquidityBundle,
    live_snapshot: LiveLiquiditySnapshot | None = None,
) -> go.Figure:
    row = market_context_domains(bundle, live_snapshot)
    labels = [
        "Equity trend stress",
        "Credit stress",
        "Sector breadth stress",
        "Volatility stress",
        "Aggregate market stress",
        "Reserve liquidity pressure",
        "Liquidity stress interaction",
    ]
    columns = [
        "domain__T",
        "domain__C",
        "domain__B",
        "domain__V",
        "domain__F",
        "domain__D",
        "domain__I",
    ]
    values = [float(row[column]) for column in columns]
    colors = [RED if value > 0 else GREEN for value in values]
    magnitude = max(abs(value) for value in values)
    text_positions = [
        "outside" if abs(value) < 0.30 * magnitude else "inside" for value in values
    ]
    text_colors = [
        "#ffffff" if position == "inside" and value > 0 else TEXT
        for position, value in zip(text_positions, values, strict=True)
    ]
    limit = max(abs(value) for value in values) * 1.35
    fig = go.Figure(
        go.Bar(
            x=values,
            y=labels,
            orientation="h",
            marker_color=colors,
            text=[
                "" if abs(value) < 1e-12 else format_normalized(value, signed=True)
                for value in values
            ],
            textposition=text_positions,
            textangle=0,
            insidetextanchor="end",
            textfont=dict(color=text_colors, size=11),
            customdata=[format_normalized(value, signed=True) for value in values],
            hovertemplate="%{y}: %{customdata}<extra></extra>",
        )
    )
    fig.add_vline(x=0, line_color=BLACK, line_width=1)
    for label, value in zip(labels, values, strict=True):
        if abs(value) < 1e-12:
            fig.add_annotation(
                x=0,
                y=label,
                text=format_normalized(value),
                showarrow=False,
                xshift=18,
                font=dict(color=TEXT, size=11),
            )
    fig.update_xaxes(
        title="Standardized stress score<br>(positive values indicate greater stress)",
        range=[-limit * 1.08, limit * 1.08],
        automargin=True,
    )
    fig.update_yaxes(autorange="reversed", automargin=True)
    return _base_layout(fig, 365, hovermode="closest")


def validation_inference_figure(bundle: LiquidityBundle) -> go.Figure:
    frame = bundle.annual_inference.sort_values("embargo_sessions")
    x = [f"{int(value)} sessions" for value in frame["embargo_sessions"]]
    mean = 10_000 * frame["equal_year_brier_improvement"].astype(float)
    low = 10_000 * frame["annual_bootstrap_ci_low"].astype(float)
    high = 10_000 * frame["annual_bootstrap_ci_high"].astype(float)
    fig = go.Figure(
        go.Scatter(
            x=x,
            y=mean,
            mode="markers",
            marker=dict(color=BLACK, size=11),
            error_y=dict(
                type="data",
                symmetric=False,
                array=(high - mean),
                arrayminus=(mean - low),
                color=MUTED,
                thickness=1.5,
                width=8,
            ),
            customdata=[format_basis_points(value, signed=True) for value in mean],
            hovertemplate="Improvement: %{customdata}<extra></extra>",
        )
    )
    fig.add_hline(y=0, line_color=RED, line_dash="dash")
    fig.update_xaxes(automargin=True)
    fig.update_yaxes(title="A3 Brier-loss improvement vs A1, bp", automargin=True)
    return _base_layout(fig, 315, hovermode="closest")
