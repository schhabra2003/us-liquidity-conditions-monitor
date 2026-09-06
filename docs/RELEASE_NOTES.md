# Final release notes

## Version 1.0.0

Release date: September 6, 2026

This release establishes the standalone U.S. Liquidity Monitor as a complete institutional macro research product. It replaces the earlier mixed card and chart presentation with one governed decision hierarchy across desktop and mobile.

## Manager-facing result

The opening view now communicates:

- Liquidity Conditions Index level
- Level regime
- Four-week direction
- Principal weighted driver
- Independent funding state
- Current risk-asset confirmation
- Information cutoff and source status

The primary conclusion is followed by index history, weighted contributions, reserve-flow accounting, funding and market diagnostics, and data methodology.

## Final presentation changes

- Independent standardized signals use a common zero-centered lollipop plot.
- Horizontal bars are reserved for genuine additive decompositions.
- Reserve-flow bars use equal thickness, common sign conventions, and aligned values.
- Time-series endpoint labels no longer collide with lines or regime annotations.
- The first desktop viewport uses a compact decision rail instead of equal-priority cards.
- Mobile uses a dedicated hierarchy at 390-pixel and 320-pixel widths.
- Typography, number formats, units, semantic colors, chart margins, captions, and section spacing are standardized.
- Supplemental data exceptions are subordinate to the core regime conclusion.
- Non-decision outputs such as a predictive overlay, model risk score, and fragility score are absent from the primary interface.

## Model and data integrity

The visual redesign does not change the numerical model. The committed release reproduces the prior baseline output exactly.

The final release gate verifies:

- Python 3.12 dependency health
- Source compilation
- 70 unit and integration tests
- 84 percent branch-aware package coverage
- Ruff static analysis
- Raw payload, table, manifest, and implementation hashes
- Source-specific release clocks and freshness roles
- Reserve-accounting identities
- Deterministic model construction
- Source-bound visual evidence

The operating snapshot is `US-LIQ-LIVE-2026-09-04`. One September 3 VIX observation was stale relative to the September 4 market-close expectation. VIX has zero index weight, is excluded from the current confirmation count, and does not suppress the verified core index.

## Visual verification

The retained evidence package is `docs/qa/liquidity_visual_audit_2026-09-06/product_v1`.

- 21 viewport, tab, and disclosure-state combinations
- 90 sequential screenshots
- 93 retained evidence files
- 0 runtime exceptions
- 0 manager-facing software alerts
- 0 pixels of horizontal overflow
- Desktop, 390-pixel mobile, and 320-pixel narrow-mobile review

The evidence manifest binds the screenshots to the presentation sources and the live operating release used during capture.

## Intended use

The monitor is a governed input for discretionary macro and equity research. It is designed to identify the current U.S. liquidity regime, its direction, its composition, funding exceptions, and disagreement with market transmission. It is not presented as a standalone causal model, return forecast, or automated trade instruction.

## Release boundary

Version 1.0.0 is the frozen presentation baseline. Future changes to model logic, source roles, thresholds, weights, terminology, chart structure, or responsive behavior require a new test run, new source-bound visual evidence, a clean release audit, and a separately identified release.
