#!/usr/bin/env python3
"""Capture hash-bound responsive evidence for the Liquidity Conditions Monitor.

The script preserves every sequential viewport frame instead of relying on a
browser full-page screenshot of Streamlit's internally scrolling main region.
It captures each tab in collapsed and available expanded states, records
runtime layout checks, creates review contact sheets, and atomically promotes
the evidence only when the page is free of alerts, exceptions, and overflow.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw
from playwright.sync_api import Browser, Page, Playwright, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_URL = "http://127.0.0.1:8777"
DEFAULT_OUTPUT = (
    ROOT / "docs" / "qa" / "liquidity_visual_audit_2026-09-04" / "final_v2"
)
PAGE_SOURCE = ROOT / "pages" / "Liquidity_Conditions_Monitor.py"
LIVE_MANIFEST = ROOT / "data" / "liquidity_live_snapshot" / "manifest.json"
VIEWPORTS = {
    "desktop": (1440, 900),
    "mobile": (390, 844),
    "narrow": (320, 844),
}
TABS = ("Overview", "Reserve mechanics", "Funding and markets", "Data and methods")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def browser_executable(explicit: str | None) -> str | None:
    candidates = (
        explicit,
        os.environ.get("U.S._BROWSER_EXECUTABLE"),
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
    )
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    return None


def launch_browser(playwright: Playwright, executable: str | None) -> Browser:
    options: dict[str, Any] = {"headless": True, "args": ["--no-sandbox"]}
    if executable:
        options["executable_path"] = executable
    return playwright.chromium.launch(**options)


def normalize_expander_label(value: str) -> str:
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    icons = {"keyboard_arrow_right", "keyboard_arrow_down"}
    return " ".join(line for line in lines if line not in icons)


def scroll_positions(scroll_height: int, client_height: int) -> list[int]:
    bottom = max(0, scroll_height - client_height)
    step = max(400, int(client_height * 0.82))
    positions = list(range(0, max(1, bottom + 1), step))
    if not positions or positions[-1] != bottom:
        positions.append(bottom)
    return sorted(set(positions))


def set_expanders(page: Page, *, expanded: bool) -> list[str]:
    summaries = page.locator('[data-testid="stExpander"] summary:visible')
    labels = [normalize_expander_label(value) for value in summaries.all_inner_texts()]
    for index in range(summaries.count()):
        summary = summaries.nth(index)
        is_expanded = summary.get_attribute("aria-expanded") == "true"
        if is_expanded != expanded:
            summary.click()
            page.wait_for_timeout(300)
    return labels


def capture_sequence(
    page: Page,
    output: Path,
    *,
    surface: str,
    tab_name: str,
    state: str,
) -> dict[str, Any]:
    main = page.locator('[data-testid="stMain"]')
    dimensions = main.evaluate(
        "(element) => ({scrollHeight: element.scrollHeight, "
        "clientHeight: element.clientHeight, scrollWidth: element.scrollWidth, "
        "clientWidth: element.clientWidth})"
    )
    tab_slug = tab_name.lower().replace(" ", "_")
    frame_paths: list[str] = []
    for frame_number, position in enumerate(
        scroll_positions(dimensions["scrollHeight"], dimensions["clientHeight"]),
        start=1,
    ):
        main.evaluate("(element, y) => element.scrollTo(0, y)", position)
        page.wait_for_timeout(350)
        filename = f"{surface}_{tab_slug}_{state}_{frame_number:02d}.png"
        page.screenshot(path=str(output / filename), animations="disabled")
        frame_paths.append(filename)
    main.evaluate("(element) => element.scrollTo(0, 0)")
    page.wait_for_timeout(250)
    return {
        "surface": surface,
        "tab": tab_name,
        "state": state,
        "scroll_height_px": dimensions["scrollHeight"],
        "client_height_px": dimensions["clientHeight"],
        "horizontal_overflow_px": max(
            0, dimensions["scrollWidth"] - dimensions["clientWidth"]
        ),
        "runtime_exception_count": page.locator('[data-testid="stException"]').count(),
        "alert_text": page.locator('[data-testid="stAlert"]').all_inner_texts(),
        "frame_paths": frame_paths,
    }


def make_contact_sheet(output: Path, surface: str, records: list[dict[str, Any]]) -> str:
    frames = [
        output / filename
        for record in records
        if record["surface"] == surface
        for filename in record["frame_paths"]
    ]
    target_width = 360 if surface == "desktop" else 260
    columns = 3 if surface == "desktop" else 4
    thumbnails: list[Image.Image] = []
    for path in frames:
        with Image.open(path) as source:
            image = source.convert("RGB")
            ratio = target_width / image.width
            thumbnail = image.resize(
                (target_width, max(1, int(image.height * ratio))),
                Image.Resampling.LANCZOS,
            )
        canvas = Image.new("RGB", (target_width + 20, thumbnail.height + 50), "white")
        canvas.paste(thumbnail, (10, 34))
        ImageDraw.Draw(canvas).text((10, 10), path.stem, fill="black")
        thumbnails.append(canvas)
    cell_width = max(image.width for image in thumbnails)
    cell_height = max(image.height for image in thumbnails)
    rows = math.ceil(len(thumbnails) / columns)
    sheet = Image.new(
        "RGB", (columns * cell_width, rows * cell_height), (236, 236, 236)
    )
    for index, image in enumerate(thumbnails):
        sheet.paste(image, ((index % columns) * cell_width, (index // columns) * cell_height))
    filename = f"{surface}_contact_sheet.png"
    sheet.save(output / filename, optimize=True)
    return filename


def evidence_file_ledger(output: Path) -> list[dict[str, Any]]:
    records = []
    for path in sorted(output.glob("*.png")):
        with Image.open(path) as image:
            width, height = image.size
        records.append(
            {
                "path": path.name,
                "sha256": sha256(path),
                "width_px": width,
                "height_px": height,
            }
        )
    return records


def build_manifest(
    output: Path,
    records: list[dict[str, Any]],
    *,
    page_hash: str,
    data_hash: str,
) -> dict[str, Any]:
    live_manifest = json.loads(LIVE_MANIFEST.read_text(encoding="utf-8"))
    return {
        "schema_version": "2.0.0",
        "audit_id": "U.S.-LIQ-VISUAL-2026-09-04-FINAL-V2",
        "captured_at_et": datetime.now().astimezone().isoformat(timespec="seconds"),
        "route": "/",
        "page_source": str(PAGE_SOURCE.relative_to(ROOT)),
        "page_source_sha256": page_hash,
        "live_manifest": str(LIVE_MANIFEST.relative_to(ROOT)),
        "live_manifest_sha256": data_hash,
        "live_release_id": live_manifest["release_id"],
        "information_cutoff_et": live_manifest["information_cutoff_et"],
        "required_source_count": len(live_manifest["required_sources"]),
        "all_sources_current_at_release": bool(live_manifest["all_sources_current"]),
        "viewports": {name: list(size) for name, size in VIEWPORTS.items()},
        "tabs": list(TABS),
        "runtime_checks": records,
        "aggregate_results": {
            "route_viewport_state_combinations": len(records),
            "sequential_viewport_frames": sum(
                len(record["frame_paths"]) for record in records
            ),
            "runtime_exceptions": sum(
                record["runtime_exception_count"] for record in records
            ),
            "manager_alerts": sum(len(record["alert_text"]) for record in records),
            "maximum_horizontal_overflow_px": max(
                record["horizontal_overflow_px"] for record in records
            ),
        },
        "evidence_files": evidence_file_ledger(output),
    }


def capture(url: str, output: Path, executable: str | None) -> dict[str, Any]:
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{output.name}-", dir=output.parent))
    page_hash_before = sha256(PAGE_SOURCE)
    data_hash_before = sha256(LIVE_MANIFEST)
    records: list[dict[str, Any]] = []
    try:
        with sync_playwright() as playwright:
            browser = launch_browser(playwright, executable)
            for surface, (width, height) in VIEWPORTS.items():
                context = browser.new_context(
                    viewport={"width": width, "height": height},
                    device_scale_factor=1,
                )
                page = context.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=120_000)
                page.locator("h1").first.wait_for(timeout=120_000)
                page.wait_for_timeout(4_500)
                for tab_name in TABS:
                    page.get_by_role("tab", name=tab_name, exact=True).click()
                    page.wait_for_timeout(1_200)
                    expander_labels = set_expanders(page, expanded=False)
                    collapsed = capture_sequence(
                        page,
                        stage,
                        surface=surface,
                        tab_name=tab_name,
                        state="collapsed",
                    )
                    collapsed["expanded_sections"] = expander_labels
                    records.append(collapsed)
                    if expander_labels:
                        set_expanders(page, expanded=True)
                        expanded = capture_sequence(
                            page,
                            stage,
                            surface=surface,
                            tab_name=tab_name,
                            state="expanded",
                        )
                        expanded["expanded_sections"] = expander_labels
                        records.append(expanded)
                        set_expanders(page, expanded=False)
                context.close()
            browser.close()
        for surface in VIEWPORTS:
            make_contact_sheet(stage, surface, records)
        page_hash_after = sha256(PAGE_SOURCE)
        data_hash_after = sha256(LIVE_MANIFEST)
        if page_hash_before != page_hash_after or data_hash_before != data_hash_after:
            raise RuntimeError("Page source or live-data manifest changed during capture")
        manifest = build_manifest(
            stage,
            records,
            page_hash=page_hash_after,
            data_hash=data_hash_after,
        )
        aggregate = manifest["aggregate_results"]
        if (
            aggregate["runtime_exceptions"]
            or aggregate["maximum_horizontal_overflow_px"]
            or not manifest["all_sources_current_at_release"]
        ):
            raise RuntimeError(f"Visual evidence failed runtime checks: {aggregate}")
        (stage / "manifest.json").write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )
        backup = output.with_name(f"{output.name}.previous")
        if backup.exists():
            shutil.rmtree(backup)
        if output.exists():
            output.rename(backup)
        stage.rename(output)
        if backup.exists():
            shutil.rmtree(backup)
        return manifest
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--browser-executable")
    arguments = parser.parse_args()
    executable = browser_executable(arguments.browser_executable)
    result = capture(arguments.url, arguments.output, executable)
    print(
        json.dumps(
            {
                "audit_id": result["audit_id"],
                "captured_at_et": result["captured_at_et"],
                "live_release_id": result["live_release_id"],
                "aggregate_results": result["aggregate_results"],
                "evidence_file_count": len(result["evidence_files"]),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
