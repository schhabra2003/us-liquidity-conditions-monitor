"""Create the portable research bundle used by the liquidity monitor.

The Streamlit application must not depend on an analyst's local research folder.
This exporter reduces the full research release to the exact, reviewable tables the
application is allowed to display.  It intentionally excludes fitted model objects,
raw vendor data, and the 294-column development panel.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path

import pandas as pd

WEEKLY_COLUMNS = (
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
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_csv(frame: pd.DataFrame, path: Path) -> None:
    frame.to_csv(path, index=False, float_format="%.10g")


def _require_hash(path: Path, expected: str, label: str) -> None:
    observed = _sha256(path)
    if observed != expected:
        raise ValueError(
            f"Parent-release hash mismatch for {label}: {observed} != {expected}"
        )


def export_bundle(research_root: Path, output_dir: Path) -> dict[str, object]:
    results = research_root / "results"
    audit = research_root / "audit"
    parent_manifest_path = audit / "release_manifest.json"
    parent_exceptions_path = audit / "KNOWN_RELEASE_EXCEPTIONS.md"
    required = (
        parent_manifest_path,
        parent_exceptions_path,
        results / "weekly_feature_label_panel.csv",
        results / "v2_predictions.csv",
        results / "v2_current_state.csv",
        results / "v2_metrics.csv",
        results / "v2_annual_inference.csv",
        results / "v2_warning_diagnostics.csv",
        audit / "v2_primary_gates.csv",
        results / "manager_state_card.csv",
    )
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError(
            "Missing research release files:\n" + "\n".join(missing)
        )

    weekly_full = pd.read_csv(results / "weekly_feature_label_panel.csv")
    absent = sorted(set(WEEKLY_COLUMNS).difference(weekly_full.columns))
    if absent:
        raise ValueError(f"Weekly panel is missing required columns: {absent}")
    weekly = weekly_full.loc[:, WEEKLY_COLUMNS].copy()
    weekly = weekly.loc[pd.to_datetime(weekly["signal_date"]).ge("2017-01-01")]

    predictions = pd.read_csv(results / "v2_predictions.csv")
    predictions = predictions.loc[
        predictions["design"].eq("primary")
        & predictions["embargo_sessions"].eq(20)
        & predictions["variant"].eq("A3")
    ].copy()

    frames = {
        "weekly_state.csv": weekly,
        "model_predictions.csv": predictions,
        "current_state.csv": pd.read_csv(results / "v2_current_state.csv"),
        "manager_state_card.csv": pd.read_csv(results / "manager_state_card.csv"),
        "validation_metrics.csv": pd.read_csv(results / "v2_metrics.csv"),
        "annual_inference.csv": pd.read_csv(results / "v2_annual_inference.csv"),
        "warning_diagnostics.csv": pd.read_csv(results / "v2_warning_diagnostics.csv"),
        "validation_gates.csv": pd.read_csv(audit / "v2_primary_gates.csv"),
    }
    parent_manifest = json.loads(parent_manifest_path.read_text(encoding="utf-8"))
    parent_artifacts = {
        str(item["path"]): str(item["sha256"])
        for item in parent_manifest.get("artifacts", [])
    }
    parent_pinned_sources = (
        "results/v2_predictions.csv",
        "results/v2_current_state.csv",
        "results/v2_metrics.csv",
        "results/v2_annual_inference.csv",
        "results/v2_warning_diagnostics.csv",
        "audit/v2_primary_gates.csv",
        "audit/KNOWN_RELEASE_EXCEPTIONS.md",
    )
    for relative in parent_pinned_sources:
        if relative not in parent_artifacts:
            raise ValueError(f"Parent release does not pin required source: {relative}")
        _require_hash(research_root / relative, parent_artifacts[relative], relative)

    manager_relative = "results/manager_state_card.csv"
    manager_state_card_status = "CONTENT_RECONCILED_NOT_PARENT_HASH_PINNED"
    manager_hash_pin_count = 0
    if manager_relative in parent_artifacts:
        _require_hash(
            research_root / manager_relative,
            parent_artifacts[manager_relative],
            manager_relative,
        )
        manager_state_card_status = "PARENT_HASH_PINNED"
        manager_hash_pin_count = 1

    v2_manifest_relative = "audit/v2_run_manifest.json"
    if v2_manifest_relative not in parent_artifacts:
        raise ValueError("Parent release does not pin the V2 run manifest")
    v2_manifest_path = research_root / v2_manifest_relative
    _require_hash(
        v2_manifest_path, parent_artifacts[v2_manifest_relative], v2_manifest_relative
    )
    v2_manifest = json.loads(v2_manifest_path.read_text(encoding="utf-8"))
    weekly_relative = "results/weekly_feature_label_panel.csv"
    weekly_expected = v2_manifest.get("inputs", {}).get(weekly_relative)
    if not weekly_expected:
        raise ValueError("V2 run manifest does not pin the weekly feature panel")
    _require_hash(
        research_root / weekly_relative, str(weekly_expected), weekly_relative
    )

    state = frames["current_state.csv"].iloc[0]
    manager = frames["manager_state_card.csv"].iloc[0]
    if str(state["state"]) != str(parent_manifest["manager_state"]):
        raise ValueError("Current state does not match the parent release")
    if (
        str(state["directional_inference"]).upper()
        != str(parent_manifest["directional_inference"]).upper()
    ):
        raise ValueError("Current direction does not match the parent release")
    parent_cutoff = pd.Timestamp(parent_manifest["research_cutoff"])
    expected_cutoff_prefix = parent_cutoff.strftime("%Y-%m-%d %H:%M")
    if not str(manager["data_cutoff"]).startswith(expected_cutoff_prefix):
        raise ValueError("Manager-state cutoff does not match the parent release")
    if str(manager["state"]).strip().lower() not in str(state["state"]).strip().lower():
        raise ValueError("Manager-state label does not reconcile to the parent state")
    if (
        str(parent_manifest["release_class"]).upper() != "PRODUCTION_CERTIFIED"
        and str(manager["model_validity"]).upper() == "PASSED_PREDICTIVE_GATE"
    ):
        raise ValueError(
            "Manager-state validity conflicts with a non-production parent release"
        )
    if str(parent_manifest["release_class"]).upper() == "PRODUCTION_CERTIFIED" and (
        str(manager["model_validity"]).upper() != "PASSED_PREDICTIVE_GATE"
        or str(manager["data_quality"]).upper() != "PASS"
    ):
        raise ValueError(
            "Production parent release lacks passing manager-state controls"
        )

    output_dir.parent.mkdir(parents=True, exist_ok=True)
    staging_dir = Path(
        tempfile.mkdtemp(prefix=f".{output_dir.name}-staging-", dir=output_dir.parent)
    )
    backup_dir = output_dir.with_name(f".{output_dir.name}-previous")
    try:
        for filename, frame in frames.items():
            _write_csv(frame, staging_dir / filename)

        bundled_parent_manifest = staging_dir / "parent_release_manifest.json"
        bundled_exceptions = staging_dir / "KNOWN_RELEASE_EXCEPTIONS.md"
        shutil.copyfile(parent_manifest_path, bundled_parent_manifest)
        shutil.copyfile(parent_exceptions_path, bundled_exceptions)
        exception_titles = [
            line.removeprefix("## ").strip()
            for line in parent_exceptions_path.read_text(encoding="utf-8").splitlines()
            if line.startswith("## ")
            and line.removeprefix("## ").strip() != "Release decision"
        ]

        manifest: dict[str, object] = {
            "schema_version": "1.0.0",
            "trial_id": str(state["trial_id"]),
            "latest_signal_date": str(state["latest_signal_date"]),
            "research_cutoff": str(manager["data_cutoff"]),
            "release_state": str(state["state"]),
            "directional_inference": str(state["directional_inference"]),
            "source_release": research_root.name,
            "expected_liquidity_path_status": "NOT_PACKAGED",
            "registered_gate_count": int(len(frames["validation_gates.csv"])),
            "registered_gate_ids": sorted(
                frames["validation_gates.csv"]["gate_group"].astype(str)
                + "/"
                + frames["validation_gates.csv"]["gate"].astype(str)
            ),
            "parent_release": {
                "release_id": str(parent_manifest["release_id"]),
                "release_class": str(parent_manifest["release_class"]),
                "decision": str(parent_manifest["decision"]),
                "clean_raw_input_to_report_replay": str(
                    parent_manifest["validation"]["clean_raw_input_to_report_replay"]
                ),
                "manifest_file": bundled_parent_manifest.name,
                "manifest_sha256": _sha256(bundled_parent_manifest),
                "known_exceptions_file": bundled_exceptions.name,
                "known_exceptions_sha256": _sha256(bundled_exceptions),
                "known_exception_count": len(exception_titles),
                "known_exception_titles": exception_titles,
                "verified_source_hash_count": len(parent_pinned_sources)
                + manager_hash_pin_count
                + 2,
                "manager_state_card_status": manager_state_card_status,
            },
            "files": {},
        }
        for filename, frame in frames.items():
            path = staging_dir / filename
            manifest["files"][filename] = {
                "rows": int(len(frame)),
                "columns": int(len(frame.columns)),
                "sha256": _sha256(path),
            }
        (staging_dir / "manifest.json").write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )

        if backup_dir.exists():
            shutil.rmtree(backup_dir)
        if output_dir.exists():
            os.replace(output_dir, backup_dir)
        try:
            os.replace(staging_dir, output_dir)
        except Exception:
            if backup_dir.exists() and not output_dir.exists():
                os.replace(backup_dir, output_dir)
            raise
        if backup_dir.exists():
            shutil.rmtree(backup_dir)
        return manifest
    finally:
        if staging_dir.exists():
            shutil.rmtree(staging_dir)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("research_root", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "data" / "liquidity_model_bundle",
    )
    args = parser.parse_args()
    manifest = export_bundle(args.research_root.resolve(), args.output.resolve())
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
