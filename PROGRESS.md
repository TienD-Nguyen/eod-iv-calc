# Progress

## Current state
End-to-end EOD IV pipeline packaged and runnable from anywhere as
`uv run eod-iv -d <YYYYMMDD> -u <TICKER> [--no-viz]`. All data lives under a
consistent `data/` layout (`symbols/`, `dividends/`, `treasury/`, `viz/`).
Verified live on AAPL 2026-09-23 (|CRR − LSE IV| p50 = 0.18%, p90 = 0.94%
over 369 fresh OTM rows). Six tickers ingested so far: AAPL, NVDA, TSLA,
AMD, AVGO, META.

## Completed
- `rates.py` — Treasury curve fetch, cc conversion, cubic-spline interp, JSON
  archive per curve date (immutable, no expiry)
- `ingest.py` — SnapShooter class: regular-session bar close (early-close
  window supported), chain with absolute-expiry window (vendor dte is
  stale-trade-relative, ignored), tiered 5000-row cap handling (band →
  call/put split → per-expiry paging), Cboe weeklys-based candidate expiries,
  parity-forward spot sanity check (dividend-aware, declared-only),
  shared 5y `data/dividends/dividends.csv` with freshness skip,
  throttle + retry wrapper for all vendor calls, per-date archive with
  zero-call reruns
- `surface.py` — pricer module: CRR binomial (escrowed discrete dividends,
  recombining tree), BS kept for validation, generic brentq `implied_vol`,
  dividend forecast/PV helpers; non-payer guard (TSLA-safe)
- `eod_iv_calc.py` — pipeline: holiday/weekend check → rates → snapshot →
  build surface (CRR IV; BS IV + LSE IV validation columns) → `surface.csv`
  (grid) + `smile.csv` (native) → prune to last 5 runs per ticker →
  regenerate viewers. Package-relative imports, `main()` entry point,
  registered as the `eod-iv` console script
- `viz.py` — `data/viz/viz.html` (3D surface, ticker dropdown + date slider,
  named hover axes) and `data/viz/smiles.html` (per-ticker figures swapped by
  `<select>`, legend-click expiry toggling, hover shows expiry/DTE/strike/IV);
  lazy plotly; scans latest run per ticker; hidden-div resize fix
- `holidays.py` — Cboe calendar cached yearly; weekend/holiday exit,
  early-close mark
- Storage restructure: per-ticker archives under `data/symbols/<ticker>/<asof>/`
- Docs: `DECISIONS.md` (decision log), `README.md` (GitHub-style overview +
  replication steps), this file

## In progress
- (nothing active)

## Known issues
- `rates.py` / `holidays.py` `__main__` blocks contain stale references
  (sandbox leftovers) — pipeline imports are unaffected
- Smile viewer bounded to the retained 5 runs per ticker by design
- Early-close spot window (12:55–13:00 ET) untested on a real early-close day
- Vendor `min_dte`/`max_dte` params silently ignored server-side; filtering
  is client-side (by design now, but don't trust the params)
- Parity check misses undeclared dividends (~0.08% for AAPL, absorbed by the
  2% threshold; deliberate — see DECISIONS.md)
- 2 local commits not yet pushed (console script, symbols restructure)

## Next steps
- Push 2 pending local commits to origin/main; commit README.md
- Run a full week of EOD calcs across MAG10 tickers; watch chain-cap tiers
  (TSLA/NVDA most likely to hit Tier 1/2)
- SVI/SSVI smile fit for arbitrage-free surface when pricing off it
- Consider per-ticker HTML or JSON sidecar if viewer size grows
  (full rebuild currently ~4 MB, fine)
- Cron/scheduler for the 18:00 ET run
