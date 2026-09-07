# Inputs and data dictionary

## Required operating inputs

| Field | Unit | Frequency | Model role |
| --- | --- | --- | --- |
| `reserves_bn` | USD billions | Weekly | Structural ratios and reserve impulse |
| `assets_bn` | USD billions | Weekly | Reserve-impulse denominator and accounting driver |
| `tga_h41_bn` | USD billions | Weekly | Reserve accounting |
| `tga_dts_bn` | USD billions | Daily | Timely Treasury cash diagnostic |
| `onrrp_bn` | USD billions | Daily | Reserve accounting |
| `currency_bn` | USD billions | Weekly | Reserve accounting |
| `sofr`, `tgcr`, `bgcr`, `effr`, `iorb` | Percent | Daily | Funding spreads and diagnostics |
| `sofr_iqr_bp` | Basis points | Daily | Funding dispersion |
| `repo_add_bn` | USD billions | Daily | Absolute funding alert |
| `deposits_bn`, `bank_assets_bn`, `bank_cash_bn` | USD billions | Weekly | Structural capacity |
| `large_bank_assets_bn`, `large_bank_cash_bn` | USD billions | Weekly | Large-bank cash ratio |
| `small_bank_assets_bn`, `small_bank_cash_bn` | USD billions | Weekly | Small-bank cash ratio |
| `bank_credit_bn` | USD billions | Weekly | Credit-creation layer |
| `fedwire_daily_value_bn` | USD billions | Monthly | Structural reserve-intensity denominator |
| `baa10y`, `hy_oas`, `ig_oas` | Percentage points | Daily | Zero-weight credit diagnostics |
| `broad_usd` | Index | Daily | Zero-weight dollar diagnostic |
| `real_yield_10y` | Percent | Daily | Zero-weight real-rate diagnostic |
| `vix` | Index points | Daily | Zero-weight volatility diagnostic sourced from Yahoo Finance `^VIX` |
| `market` | Adjusted prices | Daily | Zero-weight transmission diagnostics |

The source ledger records field, provider, series, observation date, release date, expected observation date, retrieval timestamp, freshness status, unit, raw value, normalized value, and raw payload path. Monetary values are normalized to USD billions in the backend. The UI applies a shared T, B, or M formatter and fixed decimal conventions.

## Release artifacts

`current_state.csv` contains the latest source values and derived fields. `source_status.csv` is the authoritative coverage and freshness ledger. `manifest.json` binds both tables, every raw payload, and the three calculation modules with SHA-256 hashes.
