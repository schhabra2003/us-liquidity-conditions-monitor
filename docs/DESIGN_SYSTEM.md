# Interface and visual design system

## Product objective

The interface is a professional U.S. macro research monitor for a discretionary manager. Its first screen must answer five questions without requiring chart interpretation:

1. What is the current Liquidity Conditions Index?
2. Is the level Restrictive, Balanced, or Supportive?
3. Is the four-week direction Improving, Stable, or Deteriorating?
4. What is the principal driver of the current reading?
5. Are funding conditions and risk assets confirming or contradicting the liquidity state?

Detailed accounting, market diagnostics, data provenance, and methodology remain available after the primary decision view. They must not compete with the headline regime.

## Information hierarchy

The application uses the following order on desktop:

1. Product identity and observation dates
2. Six-part decision rail
3. Supplemental data exception, when applicable
4. Analytical navigation
5. Liquidity Conditions Index history
6. Current weighted contributions
7. Classifier detail and component diagnostics

At mobile widths, the decision rail prioritizes the index level, combined regime, principal driver, funding state, and risk confirmation before any chart. Detailed content follows in the same analytical order as desktop.

## Visual grammar

Each visual form has one analytical role.

| Data relationship | Required display | Reason |
| --- | --- | --- |
| Current level and direction | Categorical regime classifier with numerical summary | Level and direction have separate trading implications |
| Historical evolution | Time-series line | Preserves sequence, persistence, and turning points |
| Independent standardized readings | Zero-centered lollipop plot | Shows sign and distance from neutral without implying additivity |
| Components that reconcile to a total | Equal-thickness horizontal contribution bars | Bar length communicates magnitude and the components have a true accounting sum |
| Exact current readings | Compact numerical cells | Provides precise values without crowding charts |
| Provenance and release controls | Table or concise status notice | Preserves auditability without dominating the manager view |

Bars must not be used for independent standardized scores. A waterfall or contribution bar may be used only when the displayed components reconcile mathematically to a defined total.

## Chart standards

- Every standardized-score plot is centered on zero.
- Positive values appear to the right of zero and negative values to the left.
- Independent signals use equal stem weight and equal endpoint-marker size.
- Additive decompositions use equal bar thickness. Length alone represents magnitude.
- Exact latest values are shown in the decision rail, numerical cells, fixed value columns, or hover text. They are not placed over time-series lines.
- Aggregate or net series use navy. Supportive contributions use teal. Restrictive contributions use brick. Cautions use amber. Historical context uses gray.
- Red and green are never the sole conveyors of meaning. Direction is also stated in words or numbers.
- Plotly mode bars are hidden in the manager-facing application.
- Axes show units in their titles or tick labels. Unexplained normalized units are not mixed with dollars, percentages, or basis points.
- Chart titles state the quantity being shown. Subtitles state the horizon, transformation, or interpretation when necessary.

## Typography

Arial is the common typeface for Streamlit, HTML, and Plotly. Helvetica and generic sans-serif are fallbacks. The interface uses tabular numerals for scores, dates, basis points, percentages, and monetary values.

Hierarchy is conveyed through size, weight, spacing, and placement rather than decorative typefaces:

- Product title: largest interface text
- Regime conclusion: prominent analytical result
- Section heading: primary content divider
- Chart title: local analytical question
- Body copy: interpretation and qualifications
- Caption: source, date, unit, and methodology detail

All headings use sentence case. Acronyms retain their standard capitalization.

## Color system

| Role | Color family | Meaning |
| --- | --- | --- |
| Primary and aggregate | Navy | Index, net result, primary series, or institutional emphasis |
| Supportive | Teal | Easier liquidity, reserve addition, or constructive confirmation |
| Restrictive | Brick | Tighter liquidity, reserve drain, or adverse confirmation |
| Caution | Amber | Mixed state, exception, or condition requiring attention |
| Secondary | Gray | Historical comparator, context, unavailable information, or zero-weight diagnostic |

Color saturation is restrained. Gradients, decorative shadows, and unrelated categorical colors are not used.

## Surfaces and spacing

- The application uses a white research canvas.
- Panels are flat with square or minimally softened edges.
- Borders are thin and neutral.
- Decorative shadows and consumer-style cards are excluded.
- Related metrics share a common container or baseline.
- Section spacing must distinguish analytical groups without creating empty screens.
- The first desktop viewport must contain the regime assessment and the beginning of the supporting evidence.

## Number formatting

The backend stores monetary observations in USD billions. The interface applies a common formatter:

- Trillions: `0.00T`
- Billions: `0.0B` or `0.00B` where the source precision requires it
- Millions: `0M` or `0.0M` where the source precision requires it
- Basis points: one decimal place
- Percentages: two decimal places for rates and one decimal place for broad changes unless finer precision is analytically necessary
- Index readings: one decimal place in detailed views and whole-number emphasis where additional precision would be false precision
- Standardized scores: two decimal places with an explicit sign
- Percentiles: whole-number ordinal labels

Units may not switch within a visual unless each value is explicitly labeled.

## Responsive behavior

The supported review widths are desktop at 1440 pixels, mobile at 390 pixels, and narrow mobile at 320 pixels.

At mobile widths:

- The decision rail becomes a compact ordered stack.
- The level and direction combine into one regime statement.
- Tab navigation uses a two-by-two layout.
- Reserve-flow numerical cells use a two-by-two grid.
- Chart labels must remain inside the plot or in a fixed value column.
- No horizontal overflow is permitted.
- Detailed diagnostic disclosures may extend vertically but must preserve heading and chart order.

## Language standards

Manager-facing language must identify direction and magnitude before methodology. The preferred terms are:

- Restrictive, Balanced, Supportive for the index level
- Improving, Stable, Deteriorating for four-week direction
- Orderly, Pressured, Stressed for the independent funding state
- Confirming, Mixed, Diverging for market confirmation when the evidence is available

Terms such as predictive overlay, model risk score, fragility score, and publication-control state are excluded from the primary interface unless they correspond to a governed and decision-relevant output. Technical terms may appear in methodology sections when they are defined at first use.

## Accessibility and failure behavior

- Every principal chart has a concise non-visual interpretation.
- Text and critical marks maintain readable contrast on a white background.
- Color-coded results also include a word, sign, or numerical value.
- A failed core release suppresses the official regime and explains the failed control.
- A stale zero-weight diagnostic is excluded from confirmation and disclosed as supplemental. It does not suppress a current core index.
- Unavailable data is never silently replaced with a synthetic value.

## Release acceptance criteria

A presentation release is acceptable only when all of the following are true:

- Every manager-facing tab has been captured at desktop, mobile, and narrow-mobile widths.
- Collapsed and expanded disclosures have been reviewed where applicable.
- Runtime exceptions equal zero.
- Manager-facing software alerts equal zero.
- Horizontal overflow equals zero pixels.
- Presentation-source hashes match the visual-evidence manifest.
- The live data manifest used during capture matches the audited release.
- Typography, terminology, units, colors, chart roles, and number formats conform to this document.
- A human reviewer has inspected the sequential screenshots, not only the contact sheets.

## Change-control rule

Future visual changes should be accepted only when they improve decision speed, analytical accuracy, accessibility, or responsive behavior. Novelty alone is not a sufficient reason to add a visual element. Any change to a presentation source requires new source-bound visual evidence and a new release audit.
