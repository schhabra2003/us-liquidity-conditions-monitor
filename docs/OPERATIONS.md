# Operations and release procedure

## Standard workflow

1. Create and activate the pinned Python 3.12 environment.
2. Run `scripts/refresh_liquidity_live_snapshot.py` after the required release windows.
3. Confirm that all required sources are current or inspect the fail-closed exception.
4. Run the complete unit suite and release audit.
5. Launch the Streamlit page and inspect Dashboard, Reserve flows, Funding and markets, and Data and methodology at desktop, mobile, and narrow-mobile widths.
6. Commit the new snapshot, source payloads, manifest, and audit result together.

## Failure behavior

The refresh writes to a temporary staging directory. It validates schema, unique keys, finite values, public-release clocks, source freshness, raw and table hashes, implementation hashes, reserve accounting, rate-effective-date alignment, market close consistency, and complete model construction. Only a passing stage replaces the last-good directory. A stale provider, missing series, calendar mismatch, checksum failure, or non-finite model output aborts promotion.

## Deployment

The page can run locally or on any Python-capable host that supports Streamlit. A public web deployment should not include secrets. The current data pipeline does not require private API keys.
