# Data integrity audit

The frozen operating release contains 28 required source records and 33 retained raw provider payloads. The release loader verifies source inventory, schemas, row counts, observation and release dates, freshness against source-specific clocks, current-state and source-ledger hashes, raw payload hashes, implementation hashes, finite values, rate-effective-date alignment, reserve-accounting identities, market close consistency, and deterministic model construction.

The frozen research bundle contains a compact parent provenance manifest whose two declared artifacts are both packaged, size-checked, path-contained, and hash-verified. The loader rejects missing artifacts, undeclared inventory counts, checksum or byte-count mismatches, and paths that escape the bundle directory.

The standalone repository test suite exercises success and failure states for the publication calendar, holidays, unchanged observations, future data, duplicates, stale sources, invalid denominators, malformed release calendars, atomic promotion, model calculation, formatting, accounting reconciliation, complete research-artifact packaging, path traversal, and page contracts. The current standalone run passes all 68 included tests with 83 percent branch-aware model-package coverage. A new operating refresh is not promoted unless all required source freshness checks pass.

The included last-good snapshot is dated September 4, 2026. A September 6 refresh attempt was correctly rejected because the public VIX series available to the retrieval process ended on September 3 while the release clock expected September 4. No override or synthetic value was introduced.
