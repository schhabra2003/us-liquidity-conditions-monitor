# Model specification

## Decision purpose

The monitor is a point-in-time U.S. liquidity regime diagnostic for discretionary trading research. It is designed to distinguish the level, direction, composition, and transmission of liquidity without converting contemporaneous market prices into the liquidity score.

## Observation clock

The headline model is weekly. A new row is admitted only after 4:30 p.m. America/New_York on Friday, after the scheduled Federal Reserve H.8 release window. Each input is aligned by economic observation date and becomes usable only after its source-specific public release date. A weekend refresh cannot create a new weekly observation simply because the calendar advanced.

## Headline index

The filtered composite is mapped to a bounded index:

`Index = 100 / (1 + exp(-filtered_composite))`

The filter is a one-sided four-week exponential moving average. No future observation enters a historical score.

| Index | Level regime |
| ---: | --- |
| Below 35 | Restrictive |
| 35 through 65 | Balanced |
| Above 65 | Supportive |

Direction compares the filtered composite with four weeks earlier. Improving or Deteriorating requires a move larger than the lagged median absolute four-week change over the prior five years. Smaller changes are Stable. Level and direction therefore produce a transparent three-by-three regime classifier.

## Weighted layers

| Layer | Weight | Construction | Economic question |
| --- | ---: | --- | --- |
| Structural reserve capacity | 35% | Reserve-stock ratios and aggregate bank-cash ratios, lagged robust standardization, eight-week one-sided smoothing | Is aggregate balance-sheet capacity high or low relative to prior history? |
| Overnight funding support | 25% | SOFR and EFFR relative to IORB, plus SOFR interquartile range | Are reserves distributing smoothly through secured and unsecured markets? |
| Realized reserve impulse | 30% | Four-week and thirteen-week reserve changes divided by lagged Federal Reserve assets | Is reserve flow adding to or draining system liquidity? |
| Bank credit creation | 10% | Thirteen-week H.8 bank-credit growth | Is private credit transmission reinforcing or offsetting reserve conditions? |

Layer scores are clipped to plus or minus 3 before weighting. The weights sum to 100 percent. Accounting drivers explain reserve flow but receive no second vote. Market prices and the mechanical seasonal comparison receive zero index weight.

## Structural reserve capacity

The reserve-stock sublayer is the median of reserves relative to commercial-bank assets, deposits, and Fedwire average daily payment value. The bank-cash sublayer combines aggregate bank cash relative to bank assets with the lower of the large-bank and small-bank aggregate cash ratios. Structural capacity assigns 70 percent to reserve stock and 30 percent to bank cash.

Every ratio is computed only after numerator and denominator are aligned to a common economic date and the slower publication clock. Standardization is one-sided and robust: current value minus the lagged rolling median, divided by 1.4826 times the lagged rolling median absolute deviation.

## Funding support and alert

The continuous layer assigns 40 percent to SOFR minus IORB, 40 percent to EFFR minus IORB, and 20 percent to SOFR dispersion. TGCR and BGCR are displayed but receive no additional weight because they are nested inside the secured-repo complex represented by SOFR.

The independent alert is:

| State | Trigger |
| --- | --- |
| Orderly | Key spreads, dispersion, and Federal Reserve overnight repo operations remain below pressure thresholds |
| Pressured | Any key spread above 5 bp, dispersion at least 10 bp, or repo operations at least $1.00B |
| Stressed | Any key spread above 10 bp, dispersion at least 20 bp, or repo operations at least $20.00B |

A funding alert does not overwrite the numerical index. It is shown separately so a smooth composite cannot conceal a money-market dislocation.

## Reserve-flow accounting

Four-week reserve change is decomposed into Federal Reserve assets, the Treasury General Account, overnight reverse repo, currency in circulation, and other liabilities plus the accounting residual. Signs are expressed from the perspective of reserves: rising Fed assets add; rising TGA, ON RRP, or currency drain. The displayed components reconcile to net reserve change.

## Mechanical seasonality

The expected seasonal value is the one-sided median of prior ISO years near the same normalized ISO-week phase. At least three prior years are required. The current deviation is descriptive, receives zero index weight, and is not presented as a Treasury cash forecast or market consensus.

## Market confirmation

Credit spreads, broad dollar, real yields, volatility, equity breadth, equal weight, small caps, high-beta innovation, biotechnology, regional banks, Bitcoin, and emerging markets are displayed as independent transmission checks. They cannot create or improve the liquidity regime score. The operating volatility check uses Yahoo Finance `^VIX` and is dated to the latest completed U.S. equity-market close.

Publication status is separated by role. A stale required model or absolute-funding-control input holds the core index at its last verified value. These inputs include weighted index sources and the TGCR, BGCR, and Federal Reserve repo series used by the independent funding stress check. A stale zero-weight market-confirmation series does not suppress an otherwise current core index; it is excluded from the current confirmation count and identified separately in the interface.

## Frozen release parameters

- Model version: `3.0.0-research`
- Headline filter span: 4 weeks
- Structural filter span: 8 weeks
- Component clip: 3 standardized units
- Layer weights: 35%, 25%, 30%, 10%
- Index thresholds: 35 and 65
- Model observation clock: Friday 16:30 America/New_York
- Fedwire publication lag: 25 calendar days after month-end
- Deposit fallback publication lag: 9 calendar days
