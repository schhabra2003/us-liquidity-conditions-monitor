#!/usr/bin/env python3
"""Run the reproducible release gate for the U.S. Liquidity Conditions Monitor.

The audit is intentionally read-only except for the optional JSON report path and
the coverage data file produced by the repository's standard test command. It
reuses the production liquidity loaders for schema, arithmetic, model-code, raw
payload, and manifest checksum validation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess  # nosec B404
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PRESENTATION_SOURCES = (
    ".streamlit/config.toml",
    "pages/Liquidity_Conditions_Monitor.py",
    "liquidity_monitor/ui.py",
    "liquidity_monitor/palette.py",
    "liquidity_monitor/liquidity_signal_monitor.py",
    "liquidity_monitor/structural_liquidity.py",
    "liquidity_monitor/us_liquidity_model.py",
    "scripts/capture_liquidity_visual_audit.py",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def run(command: list[str], *, timeout: int = 900) -> dict[str, Any]:
    started = time.monotonic()
    try:
        # The command list is constructed internally and never uses a shell.
        completed = subprocess.run(  # nosec B603
            command,
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
        output = (completed.stdout + completed.stderr).strip()
        return {
            "command": command,
            "returncode": completed.returncode,
            "status": "PASS" if completed.returncode == 0 else "FAIL",
            "duration_seconds": round(time.monotonic() - started, 3),
            "output": output[-20000:],
        }
    except subprocess.TimeoutExpired as error:
        captured = "".join(
            part.decode(errors="replace") if isinstance(part, bytes) else part or ""
            for part in (error.stdout, error.stderr)
        )
        return {
            "command": command,
            "returncode": None,
            "status": "FAIL",
            "duration_seconds": round(time.monotonic() - started, 3),
            "output": f"Timed out after {timeout} seconds.\n{captured}"[-20000:],
        }


def git_value(*arguments: str) -> str | None:
    result = run(["git", *arguments], timeout=30)
    return result["output"].strip() if result["status"] == "PASS" else None


def git_identity() -> dict[str, Any]:
    status = run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        timeout=30,
    )
    dirty_entries = [line for line in status["output"].splitlines() if line]
    return {
        "status": "PASS" if status["status"] == "PASS" and not dirty_entries else "FAIL",
        "clean_worktree": status["status"] == "PASS" and not dirty_entries,
        "dirty_entries": dirty_entries,
        "branch": git_value("branch", "--show-current"),
        "commit": git_value("rev-parse", "HEAD"),
        "commit_short": git_value("rev-parse", "--short=12", "HEAD"),
        "commit_subject": git_value("show", "-s", "--format=%s", "HEAD"),
        "commit_timestamp": git_value("show", "-s", "--format=%cI", "HEAD"),
        "upstream": git_value("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"),
        "origin": git_value("remote", "get-url", "origin"),
    }


def dependency_files() -> dict[str, Any]:
    paths = ("requirements.txt", "requirements-dev.txt", "constraints.txt")
    files: dict[str, Any] = {}
    for relative in paths:
        path = ROOT / relative
        files[relative] = {
            "exists": path.is_file(),
            "sha256": sha256(path) if path.is_file() else None,
        }
    return {
        "status": "PASS" if all(item["exists"] for item in files.values()) else "FAIL",
        "files": files,
    }


def liquidity_data_integrity() -> dict[str, Any]:
    from liquidity_monitor.liquidity_live_snapshot import load_live_snapshot
    from liquidity_monitor.liquidity_signal_monitor import (
        live_source_status_table,
        load_liquidity_bundle,
    )
    from liquidity_monitor.us_liquidity_model import CORE_SOURCE_FIELDS

    live_root = ROOT / "data" / "liquidity_live_snapshot"
    research_root = ROOT / "data" / "liquidity_model_bundle"
    try:
        live = load_live_snapshot(live_root, verify_hashes=True)
        research = load_liquidity_bundle(research_root, verify_hashes=True)
        runtime_status = live_source_status_table(live)
        runtime_stale = runtime_status.loc[
            ~runtime_status["Live status"].astype(str).str.startswith("CURRENT"),
            ["field", "Series", "Observation date", "Expected date", "Live status"],
        ]
        core_stale = runtime_stale.loc[
            runtime_stale["field"].astype(str).isin(CORE_SOURCE_FIELDS)
        ]
        supplemental_stale = runtime_stale.loc[
            ~runtime_stale["field"].astype(str).isin(CORE_SOURCE_FIELDS)
        ]
        return {
            "status": "PASS",
            "live_snapshot": {
                "release_id": live.manifest["release_id"],
                "schema_version": live.manifest["schema_version"],
                "information_cutoff_et": live.manifest["information_cutoff_et"],
                "all_sources_current_at_release": bool(live.manifest["all_sources_current"]),
                "required_source_count": len(live.manifest["required_sources"]),
                "manifest": str((live_root / "manifest.json").relative_to(ROOT)),
                "manifest_sha256": sha256(live_root / "manifest.json"),
                "current_operating_status": (
                    "PASS" if core_stale.empty else "HOLD_FOR_CORE_REFRESH"
                ),
                "supplemental_operating_status": (
                    "CURRENT"
                    if supplemental_stale.empty
                    else "REFRESH_PENDING_EXCLUDED_FROM_CORE"
                ),
                "current_stale_source_count": len(runtime_stale),
                "current_core_stale_source_count": len(core_stale),
                "current_supplemental_stale_source_count": len(supplemental_stale),
                "current_stale_sources": runtime_stale.astype(str).to_dict("records"),
            },
            "research_bundle": {
                "trial_id": research.manifest["trial_id"],
                "schema_version": research.manifest["schema_version"],
                "research_cutoff": research.manifest["research_cutoff"],
                "release_state": research.manifest["release_state"],
                "directional_inference": research.manifest["directional_inference"],
                "manifest": str((research_root / "manifest.json").relative_to(ROOT)),
                "manifest_sha256": sha256(research_root / "manifest.json"),
            },
            "verification_scope": [
                "manifest and table hashes",
                "raw source payload hashes",
                "model-code hash and frozen specification",
                "schemas, row counts, source inventory, and dates",
                "finite outputs and reserve-accounting identities",
                "source-ledger, state, and parent-release reconciliation",
            ],
        }
    except Exception as error:  # release audit must report, not obscure, the gate
        return {
            "status": "FAIL",
            "error_type": type(error).__name__,
            "error": str(error),
        }


def evidence_inventory() -> dict[str, Any]:
    audit_root = ROOT / "docs" / "qa" / "liquidity_visual_audit_2026-09-06"
    visual_root = audit_root / "product_v1"
    paths = {
        "visual_audit": ROOT / "docs" / "VISUAL_AUDIT.md",
        "design_system": ROOT / "docs" / "DESIGN_SYSTEM.md",
        "data_integrity_audit": ROOT / "docs" / "DATA_INTEGRITY_AUDIT.md",
        "release_notes": ROOT / "docs" / "RELEASE_NOTES.md",
        "evidence_manifest": visual_root / "manifest.json",
    }
    files = {
        label: {
            "path": str(path.relative_to(ROOT)),
            "exists": path.is_file(),
            "sha256": sha256(path) if path.is_file() else None,
        }
        for label, path in paths.items()
    }
    checks: dict[str, bool] = {
        "required_documents_exist": all(item["exists"] for item in files.values()),
    }
    evidence_files: list[dict[str, Any]] = []
    manifest: dict[str, Any] = {}
    manifest_error: str | None = None
    if checks["required_documents_exist"]:
        try:
            manifest = json.loads(paths["evidence_manifest"].read_text(encoding="utf-8"))
            checks.update(
                {
                    "manifest_schema": manifest.get("schema_version") == "2.0.0",
                    "audit_identity": manifest.get("audit_id")
                    == "US-LIQUIDITY-PRODUCT-2026-09-06-V1",
                    "route": manifest.get("route") == "/",
                    "viewports": manifest.get("viewports")
                    == {"desktop": [1440, 900], "mobile": [390, 844], "narrow": [320, 844]},
                    "tabs": manifest.get("tabs")
                    == ["Dashboard", "Reserve flows", "Funding and markets", "Data and methodology"],
                    "source_coverage_at_capture": manifest.get("required_source_count") == 28
                    and manifest.get("all_sources_current_at_release") is True,
                }
            )
            page_source = ROOT / str(manifest.get("page_source", ""))
            live_manifest = ROOT / str(manifest.get("live_manifest", ""))
            checks["page_source_binding"] = (
                page_source.is_file()
                and sha256(page_source) == manifest.get("page_source_sha256")
            )
            checks["live_snapshot_binding"] = (
                live_manifest.is_file()
                and sha256(live_manifest) == manifest.get("live_manifest_sha256")
            )
            presentation_sources = manifest.get("presentation_sources", {})
            checks["presentation_source_inventory"] = (
                isinstance(presentation_sources, dict)
                and set(presentation_sources) == set(PRESENTATION_SOURCES)
            )
            checks["presentation_source_binding"] = bool(
                checks["presentation_source_inventory"]
                and all(
                    (ROOT / relative).is_file()
                    and sha256(ROOT / relative) == expected_hash
                    for relative, expected_hash in presentation_sources.items()
                )
            )
            aggregate = manifest.get("aggregate_results", {})
            runtime_checks = manifest.get("runtime_checks", [])
            expected_runtime_keys = {
                (surface, tab, state)
                for surface in ("desktop", "mobile", "narrow")
                for tab in ("Dashboard", "Reserve flows", "Funding and markets", "Data and methodology")
                for state in (
                    ("collapsed", "expanded")
                    if tab in {"Dashboard", "Reserve flows", "Data and methodology"}
                    else ("collapsed",)
                )
            }
            runtime_keys = {
                (item.get("surface"), item.get("tab"), item.get("state"))
                for item in runtime_checks
            }
            frame_paths = [
                str(frame)
                for item in runtime_checks
                for frame in item.get("frame_paths", [])
            ]
            checks["runtime_layout_results"] = (
                aggregate.get("route_viewport_state_combinations")
                == len(runtime_checks)
                == 21
                and aggregate.get("sequential_viewport_frames") == len(frame_paths)
                and len(frame_paths) >= 75
                and aggregate.get("runtime_exceptions") == 0
                and aggregate.get("maximum_horizontal_overflow_px") == 0
            )
            checks["runtime_check_ledger"] = (
                runtime_keys == expected_runtime_keys
                and all(item.get("runtime_exception_count") == 0 for item in runtime_checks)
                and all(item.get("horizontal_overflow_px") == 0 for item in runtime_checks)
                and all(item.get("frame_paths") for item in runtime_checks)
            )
            required_evidence = {
                "desktop_contact_sheet.png",
                "mobile_contact_sheet.png",
                "narrow_contact_sheet.png",
                "desktop_dashboard_collapsed_01.png",
                "desktop_dashboard_expanded_01.png",
                "mobile_dashboard_collapsed_01.png",
                "mobile_dashboard_expanded_01.png",
                "narrow_dashboard_collapsed_01.png",
                "narrow_dashboard_expanded_01.png",
            }
            listed_names: set[str] = set()
            root_resolved = visual_root.resolve()
            for item in manifest.get("evidence_files", []):
                relative = Path(str(item.get("path", "")))
                path = (visual_root / relative).resolve()
                within_root = path.is_relative_to(root_resolved)
                valid = (
                    within_root
                    and path.is_file()
                    and sha256(path) == item.get("sha256")
                )
                evidence_files.append(
                    {
                        "path": str(relative),
                        "exists": path.is_file() if within_root else False,
                        "hash_matches": valid,
                    }
                )
                if valid:
                    listed_names.add(relative.as_posix())
            checks["evidence_file_hashes"] = all(
                item["hash_matches"] for item in evidence_files
            )
            checks["frame_inventory"] = (
                len(frame_paths) == len(set(frame_paths))
                and set(frame_paths).issubset(listed_names)
                and len(evidence_files) == len(frame_paths) + 3
            )
            checks["required_evidence_views"] = required_evidence.issubset(listed_names)
        except Exception as error:  # evidence must fail closed
            manifest_error = f"{type(error).__name__}: {error}"
    complete = all(checks.values())
    return {
        "status": "PASS" if complete else "FAIL",
        "files": files,
        "checks": checks,
        "manifest_summary": {
            "audit_id": manifest.get("audit_id"),
            "captured_at_et": manifest.get("captured_at_et"),
            "live_release_id": manifest.get("live_release_id"),
            "information_cutoff_et": manifest.get("information_cutoff_et"),
            "evidence_file_count": len(evidence_files),
        },
        "evidence_files": evidence_files,
        "error": manifest_error,
    }


def verification_commands(python: str) -> list[tuple[str, list[str]]]:
    return [
        ("dependency_health", [python, "-m", "pip", "check"]),
        (
            "compile",
            [
                python,
                "-m",
                "compileall",
                "-q",
                "pages",
                "liquidity_monitor",
                "scripts",
                "tests",
            ],
        ),
        (
            "tests",
            [
                python,
                "-m",
                "coverage",
                "run",
                "--source=liquidity_monitor",
                "-m",
                "unittest",
                "discover",
                "-s",
                "tests",
                "-p",
                "test_*.py",
                "-q",
            ],
        ),
        (
            "coverage",
            [python, "-m", "coverage", "report", "--show-missing", "--fail-under=80"],
        ),
        (
            "lint_shared",
            [
                python,
                "-m",
                "ruff",
                "check",
                "--select",
                "E,F,I,B",
                "--ignore",
                "E501",
                "liquidity_monitor",
                "scripts",
                "tests",
            ],
        ),
        (
            "lint_pages_fatal",
            [
                python,
                "-m",
                "ruff",
                "check",
                "--select",
                "E9,F63,F7,F82",
                "pages",
            ],
        ),
    ]


def build_report(*, quick: bool) -> dict[str, Any]:
    python = sys.executable
    checks: dict[str, Any] = {}
    if not quick:
        for name, command in verification_commands(python):
            checks[name] = run(command)
    report = {
        "audit_schema_version": "1.0.0",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "repository_root": str(ROOT),
        "environment": {
            "python_executable": python,
            "python_version": platform.python_version(),
            "platform": platform.platform(),
        },
        "git": git_identity(),
        "dependency_inputs": dependency_files(),
        "liquidity_data_integrity": liquidity_data_integrity(),
        "visual_evidence": evidence_inventory(),
        "verification_commands": checks,
        "non_automatable_release_gates": [
            "Reviewed pull request and required code-owner approval",
            "Green CI run on the repository-supported Python 3.12 environment",
            "Fresh provider retrieval when a new operating snapshot is required",
            "Human visual and interaction review of every tab at desktop and mobile widths",
            "Production deployment smoke test, route check, and post-deploy source-clock review",
            "Manual review of known release exceptions and market-holiday calendar limitations",
        ],
    }
    automated_sections = [
        report["git"]["status"],
        report["dependency_inputs"]["status"],
        report["liquidity_data_integrity"]["status"],
        report["visual_evidence"]["status"],
        *(item["status"] for item in checks.values()),
    ]
    report["automated_release_decision"] = (
        "PASS" if automated_sections and all(value == "PASS" for value in automated_sections) else "FAIL"
    )
    report["quick_mode"] = quick
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional JSON report path. Use a path outside the repository for a clean-tree release gate.",
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Run identity, data-manifest, and evidence checks without compile, tests, coverage, or lint.",
    )
    args = parser.parse_args()

    report = build_report(quick=args.quick)
    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        output = args.output.expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(payload, encoding="utf-8")
        print(f"Wrote release audit to {output}")
    else:
        print(payload, end="")
    return 0 if report["automated_release_decision"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
