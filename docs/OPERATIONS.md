# Operations and release procedure

## Standard workflow

1. Create and activate the pinned Python 3.12 environment.
2. Run `scripts/refresh_liquidity_live_snapshot.py` after the required release windows.
3. Confirm that all required sources are current or inspect the fail-closed exception.
4. Run the complete unit suite and release audit.
5. Launch the Streamlit page and inspect Dashboard, Reserve flows, Funding and markets, and Data and methodology at desktop, mobile, and narrow-mobile widths.
6. Confirm that the interface conforms to `docs/DESIGN_SYSTEM.md` and that the visual-evidence manifest is bound to every presentation source.
7. Commit the new snapshot, source payloads, manifest, documentation, and audit evidence together.
8. Push the exact commit and require the GitHub Actions quality workflow to pass before identifying it as a release.
9. Tag the verified commit with a unique release version.

## Failure behavior

The refresh writes to a temporary staging directory. It validates schema, unique keys, finite values, public-release clocks, source freshness, raw and table hashes, implementation hashes, reserve accounting, rate-effective-date alignment, market close consistency, and complete model construction. Only a passing stage replaces the last-good directory. A stale provider, missing series, calendar mismatch, checksum failure, or non-finite model output aborts promotion.

## Deployment

The page can run locally or on any Python-capable host that supports Streamlit. A public web deployment should not include secrets. The current data pipeline does not require private API keys.

## Presentation change control

Any change to the Streamlit page, shared UI, palette, formatting, or chart-construction modules invalidates the prior presentation evidence. Capture a new desktop, mobile, and narrow-mobile evidence set and rerun `scripts/audit_liquidity_release.py` before release. Documentation-only changes do not alter the rendered interface, but they must remain consistent with the frozen model and current visual evidence.
