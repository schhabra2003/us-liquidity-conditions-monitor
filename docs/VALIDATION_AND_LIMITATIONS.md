# Validation and limitations

## What is validated

- Source-specific point-in-time publication clocks and expected dates
- Complete required-source inventory and freshness status
- Raw payload, table, model-file, and manifest SHA-256 reconciliation
- Reserve-accounting signs and identities
- Deterministic model output and stable classification thresholds
- Failure on future-dated data, invalid denominators, duplicates, missing inputs, non-finite values, and stale required sources
- Separation of weighted liquidity inputs from seasonal and traded-market diagnostics
- Responsive UI behavior, standardized units, and consistent number formats

## What the model does not prove

1. It is not a standalone causal or return-prediction model.
2. Most public histories are current-vintage histories, not complete real-time vintage archives.
3. Aggregate public data cannot observe reserve distribution at every institution, intraday dealer constraints, or every private funding channel.
4. Correlated structural measures triangulate one state; they are not independent alpha signals.
5. Filtering intentionally creates persistence and delays some turning points.
6. Weights and thresholds are transparent economic priors, not parameters optimized against SPY, QQQ, Bitcoin, or another traded asset.
7. Mechanical seasonality is descriptive and is not an expected Treasury cash path.
8. Market confirmation is contemporaneous and does not establish that liquidity caused the price move.

The appropriate use is as one governed input in a discretionary process: identify liquidity regime, direction, composition, funding exceptions, and disagreement with market transmission, then combine that evidence with price action, positioning, valuation, catalysts, and risk management.

