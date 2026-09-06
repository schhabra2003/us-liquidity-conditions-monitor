# Known release-process exceptions and nonconformities

**Recorded:** 2026-09-03  
**Scope:** final V2 conditional-liquidity research, SPY/QQQ economic backtest, dashboard, and four-page report  
**Manager state:** `GRAY / UNAVAILABLE`  
**Effect on current decision:** none of these findings can promote the failed model; all restrict future deployment.

## 1. Full isolated end-to-end replay not completed

`audit/RELEASE_TEST_PLAN.md` section 6 requires a new temporary-directory rebuild from immutable raw inputs through the point-in-time panel, V1 and V2 models, signal ledgers, visuals, dashboard, and report. The completed `197/197` V2 recomputation is an artifact, saved-model, split, and arithmetic replay. The SPY/QQQ QA independently recomputes retained ledgers. Neither is a complete raw-input-to-report rebuild.

No environment lockfile exists for the recorded scikit-learn 1.9.0 model environment, and the bundled document runtime lacks scikit-learn. A true clean replay is therefore **NOT SATISFIED** in this release. This blocks production/deployment certification. It does not change the research decision because the predictive gates already fail and the issued state is Gray.

## 2. V2 freeze-clock metadata are internally inconsistent

The economic specification and implementation hashes were in place before the retained result files based on relative file chronology, but the declared UTC fields are not credible:

- `research/V2_IMPLEMENTATION_FREEZE.md` declares `2026-09-03 21:40 UTC`; filesystem modification time is approximately `19:07 UTC`.
- `audit/v2_pre_run_freeze.json` declares `2026-09-03T21:45:00Z` and a `22:05Z` revision; filesystem modification time is approximately `19:12 UTC`.
- retained `results/v2_predictions.csv` followed at approximately `19:21 UTC`.

The relative order supports a pre-result economic freeze, but the absolute declared timestamps are wrong and cannot be used as confirmatory preregistration evidence. V2 was already classified as developmental pseudo-out-of-sample because its design followed the V1 null; it remains so.

The economic specification itself declares `2026-09-03 20:15 UTC`, while host/file chronology places its creation at approximately `18:57 UTC`. This is another instance of the same absolute-clock defect; it does not change the relative pre-result ordering or the developmental status.

## 3. Hypothetical all-gates-pass state issuance is not implemented

`src/run_free_public_v2.py` correctly calculates `ordinal_state_permitted` and `decimal_probability_permitted`, but the emitted top-line `state` and `directional_inference` are hardcoded to `Gray / unavailable` and `SUPPRESSED`. This is safe for the current failed run, but the runner would not issue the specification's hypothetical Watch/High-risk path if every gate passed.

No current output changes: V2 fails seven primary gates, so Gray is required. Before any future prospective deployment, the state machine must be implemented, independently unit-tested on synthetic pass/fail fixtures, frozen, and shadow-run. The historical failed result must not be refit merely to repair this latent branch.

## 4. Primary crisis-leaveout gate reads across both embargo designs

The runner constructs the `all_major_crisis_leaveouts` primary gate from a table containing both the registered 20-session embargo and the 60-session sensitivity, without filtering the gate to the primary embargo. The published gate value is therefore the cross-design minimum, `+0.001288864439`, which comes from the 60-session sensitivity. The correct minimum for the primary 20-session design alone is `+0.001296026622`.

Both values exceed zero, so the gate remains a pass and the aggregate result remains 15 of 22 gates. No prediction, coefficient, interval, state, or release decision changes. The contamination is a provenance/labeling defect and must be repaired in a separately versioned runner before any prospective reuse.

## 5. Backtest precision p-value is descriptive only

The one-sided binomial p-value of 0.3845 uses seven initiating SELL entries and compares them with an 18.6% event rate estimated from the same 500 overlapping weekly anchors. It is not dependence-aware and is not a fixed ex-ante null. The point estimate, wide Wilson interval, independent-episode recall, and annual block results are already non-supportive. The p-value is retained only as a labeled descriptive diagnostic.

## 6. Public-data point-in-time boundary

The panel passes deterministic availability and lineage checks but remains `PSEUDO_PIT_ONLY`. Several FRED histories are current revised values with conservative release lags rather than complete ALFRED vintages. Primary-dealer and OFR histories also have explicit schema/publication-clock limits. These limitations prevent a production-grade vintage claim and remain visible in the data-integrity reports.

## 7. V2 manifest path convention and recomputation scope

`audit/v2_run_manifest.json` records the SPY input as `liquidity_timing_2026/market/SPY.csv`, while `audit/spy_qqq_signal_backtest_manifest.json` records both SPY and QQQ with the same project-parent-relative convention. The underlying sibling files exist and all three retained hashes verify when that convention is applied, but a uniform project-root verifier reports those entries missing. These are noncanonical lineage-path defects that must be corrected in separately versioned manifests.

The `197/197` result verifies retained output-artifact hashes, saved-model behavior, splits, and reported arithmetic. It does **not** independently traverse and hash every raw input and code dependency, and it is not the isolated end-to-end replay required for production certification. The count must therefore be described as an output-artifact and arithmetic recomputation, not a complete provenance audit.

## 8. Data-gate assertions are not counterfactual replay tests

The V2 runner emits `optional_modern_fields_excluded`, `backward_fill`, and `future_append` data gates as passed assertions. Current retained-ledger timestamps and availability fields show no detected release-date or backward-fill violation, but no counterfactual future-append invariance replay was executed. The correct claim is: **no violation was found in the current retained ledger; future-append invariance was not tested.** These assertions cannot substitute for the clean replay and mutation tests specified in the release plan.

## Release decision

The deliverable is complete as a **research-only negative result with disclosed release exceptions**. It is not production-certified, does not issue a trade, and must not be represented as a validated SPY/QQQ market-timing system. The recommended next research trial is a separately frozen recovery/bottoming model, not a post-result rescue of V2.
