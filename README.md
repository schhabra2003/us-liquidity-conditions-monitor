# U.S. Liquidity Monitor

An independently developed, public-data monitor of U.S. dollar liquidity conditions for discretionary macroeconomic research.

The application separates four questions that are often mixed together:

1. Is structural reserve capacity abundant or scarce relative to its own history?
2. Are secured and unsecured overnight funding markets transmitting smoothly?
3. Is realized reserve flow adding to or draining system liquidity?
4. Is bank credit creation reinforcing or offsetting those conditions?

It produces a 0 to 100 Liquidity Conditions Index, a level regime, a four-week direction, an independent funding-stress alert, a reserve-flow decomposition, a mechanical seasonal comparison, and zero-weight market-confirmation diagnostics. The interface is designed as a restrained institutional macro research product with one decision hierarchy across desktop and mobile. It does not issue trades and it is not represented as a validated standalone market-timing model.

## Run locally

Python 3.12 is recommended.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt -r requirements-dev.txt
python -m streamlit run pages/Liquidity_Conditions_Monitor.py
```

On macOS, you can also double-click `run_local.command`. The first launch creates the virtual environment and installs dependencies.

## Refresh public data

```bash
source .venv/bin/activate
python scripts/refresh_liquidity_live_snapshot.py
```

Refreshes are staged and promoted atomically only when required-source freshness, schemas, dates, raw-payload hashes, accounting identities, and model construction all pass. An invalid refresh leaves the last-good release intact. The operating volatility confirmation uses Yahoo Finance `^VIX` on the latest-completed-market-close clock.

## Verify a release

```bash
source .venv/bin/activate
python -m unittest discover -s tests -p 'test_*.py' -q
python scripts/audit_liquidity_release.py --output /tmp/liquidity-release-audit.json
```

GitHub Actions runs the Python 3.12 compile, test, coverage, and lint gates on every push and pull request through `.github/workflows/quality.yml`.

## Repository map

| Path | Purpose |
| --- | --- |
| `pages/Liquidity_Conditions_Monitor.py` | Manager-facing Streamlit application |
| `liquidity_monitor/` | Model, publication-clock, accounting, chart, formatting, and UI code |
| `scripts/refresh_liquidity_live_snapshot.py` | Public-source acquisition and atomic release builder |
| `scripts/audit_liquidity_release.py` | Reproducible data, code, test, lint, and evidence release gate |
| `data/liquidity_live_snapshot/` | Hash-bound last-good operating snapshot and raw source payloads |
| `data/liquidity_model_bundle/` | Frozen research and validation context used by the interface |
| `tests/` | Model logic, source-clock, formatting, accounting, and failure-mode tests |
| `docs/` | Full specification, source inventory, operations, and limitations |

## Documentation

- [Model specification](docs/MODEL_SPECIFICATION.md)
- [Interface and visual design system](docs/DESIGN_SYSTEM.md)
- [Inputs and data dictionary](docs/DATA_DICTIONARY.md)
- [Public data sources](docs/PUBLIC_DATA_SOURCES.md)
- [Operating and release procedure](docs/OPERATIONS.md)
- [Validation and limitations](docs/VALIDATION_AND_LIMITATIONS.md)
- [Final release notes](docs/RELEASE_NOTES.md)

## Independence and use

This repository is independently authored and standalone. It contains no third-party application code, brand assets, navigation, repository history, credentials, or private data. All observations are acquired from public sources listed in the source documentation. The software is research tooling, not investment advice. Public visibility does not grant an open-source license; see [COPYRIGHT.md](COPYRIGHT.md).
