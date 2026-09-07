# Public data sources

| Institution | Dataset or endpoint | Use |
| --- | --- | --- |
| Federal Reserve Board and FRED | H.4.1, H.8, H.10, reserve balances, total assets, TGA, currency, bank balance sheets, bank credit, administered and market rates | Core balance-sheet, structural, credit, and release-calendar inputs |
| U.S. Treasury FiscalData | Daily Treasury Statement operating cash balance | Timely TGA diagnostic |
| Federal Reserve Bank of New York | SOFR, TGCR, BGCR rates and percentiles; repo and reverse-repo operations | Secured funding and operations diagnostics |
| Federal Reserve Financial Services | Fedwire Funds annual and monthly statistics | Payment-value denominator for structural reserve intensity |
| ICE BofA series distributed through FRED | Investment-grade and high-yield option-adjusted spreads | Zero-weight market confirmation |
| Yahoo Finance | Liquid public market proxies, including `^VIX` | Zero-weight cross-asset transmission and volatility confirmation |

Exact provider URLs, source identifiers, retrieval timestamps, and retained payload paths are recorded in `data/liquidity_live_snapshot/source_status.csv` and `data/liquidity_live_snapshot/raw/`.
