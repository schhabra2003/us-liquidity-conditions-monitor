#!/usr/bin/env python3
"""Rebind copied public-data releases to the standalone implementation.

This is a packaging operation only. It does not alter any observations, raw
provider payloads, calculated tables, model parameters, or point-in-time dates.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def rebind_live_release() -> None:
    manifest_path = ROOT / "data" / "liquidity_live_snapshot" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    implementation_paths = (
        "liquidity_monitor/liquidity_live_snapshot.py",
        "liquidity_monitor/structural_liquidity.py",
        "liquidity_monitor/us_liquidity_model.py",
    )
    implementation_files = {
        relative: sha256(ROOT / relative) for relative in implementation_paths
    }
    canonical = json.dumps(
        sorted(implementation_files.items()), separators=(",", ":")
    ).encode("utf-8")
    model_spec = manifest["model_spec"]
    model_spec["implementation_files"] = implementation_files
    model_spec["implementation_bundle_sha256"] = hashlib.sha256(canonical).hexdigest()
    model_spec["model_code_sha256"] = implementation_files[
        "liquidity_monitor/us_liquidity_model.py"
    ]
    manifest["release_id"] = str(manifest["release_id"]).replace("U.S.-", "US-")
    write_json(manifest_path, manifest)


def rebind_research_release() -> None:
    root = ROOT / "data" / "liquidity_model_bundle"
    manifest_path = root / "manifest.json"
    parent_path = root / "parent_release_manifest.json"
    exceptions_path = root / "KNOWN_RELEASE_EXCEPTIONS.md"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    parent_manifest = json.loads(parent_path.read_text(encoding="utf-8"))
    release_id = str(parent_manifest["release_id"]).replace("U.S.-", "US-")
    parent_manifest["release_id"] = release_id
    write_json(parent_path, parent_manifest)
    parent = manifest["parent_release"]
    parent["release_id"] = release_id
    parent["manifest_sha256"] = sha256(parent_path)
    parent["known_exceptions_sha256"] = sha256(exceptions_path)
    manifest["source_release"] = "standalone_liquidity_research"
    write_json(manifest_path, manifest)


def main() -> None:
    rebind_live_release()
    rebind_research_release()
    print("Standalone release manifests rebound without changing source data.")


if __name__ == "__main__":
    main()
