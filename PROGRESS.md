# Progress

## Current state
End-to-end EOD IV pipeline working: Treasury rates → LSE snapshot → CRR
American IV inversion → gridded surface + native smile CSVs → auto-regenerated
Plotly viewers. Verified live on AAPL 2026-09-23 (|CRR − LSE IV| p50 = 0.18%,
p90 = 0.94% over 369 fresh OTM rows). Multi-ticker ready (AAPL/NVDA/TSLA dirs
exist).

## Completed
- `rates.py` — Treasury curve fetch, cc conversion, cubic-spline interp, JSON
  archive per curve date (immutable, no expiry)
- `ingest.py` — SnapShooter class: 1s-bar close at 15:55–16:00 ET (early-close
  window supported), chain with absolute-expiry window (vendor dte is
  stale-trade-relative, ignored), tiered 5000-row cap handling (band →
  call/put split → per-expiry paging), Cboe weeklys-based candidate expiries,
  parity-forward spot sanity check (dividend-aware), shared 5y
  `data/dividends/dividends.csv` with 30d freshness skip, throttle + retry
  wrapper for all vendor calls, per-date archive with zero-call reruns
- `surface.py` — pricer module: CRR binomial (escrowed discrete dividends,
  recombining tree), BS kept for validation, generic brentq `implied_vol`,
  dividend forecast/PV helpers; non-payer guard (TSLA-safe)
- `eod_iv_calc.py` — CLI pipeline (`-d YYYYMMDD -u TICKER [--no-viz]`):
  holiday/weekend check → rates → snapshot → build surface (CRR IV; BS IV +
  LSE IV as validation columns) → `surface.csv` (grid) + `smile.csv` (native
  quotes) → prune to last 5 runs per ticker → regenerate viewers
- `viz.py` — `viz.html` (3D surface, ticker dropdown + date slider, named
  hover axes) and `smiles.html` (per-ticker figures swapped by `<select>`,
  legend-click expiry toggling, hover shows expiry/DTE/strike/IV); lazy
  plotly import; output to `data/viz/`; scans latest run per ticker
- `holidays.py` — Cboe calendar cached yearly; weekend/holiday exit,
  early-close mark

## In progress
- (nothing active)

## Known issues
- Flat imports (`from ingest import ...`) → pipeline must run from
  `src/options_calculations/`; `python -m` style is broken for eod_iv_calc
- `rates.py` / `holidays.py` `__main__` blocks contain stale references
  (sandbox leftovers) — pipeline imports are unaffected
- Smile viewer bounded to the retained 5 runs per ticker by design
- Early-close spot window (12:55–13:00 ET) untested on a real early-close day
- Vendor `min_dte`/`max_dte` params silently ignored server-side; filtering
  is client-side (by design now, but don't trust the params)
- Parity check misses undeclared dividends (absorbed by 2% threshold)
- README.md partially stale (validation.csv → smile.csv, CRR, data/viz)

## Next steps
- Push 3 pending local commits to origin/main
- Run a full week of EOD calcs across MAG10 tickers; watch chain-cap tiers
  (TSLA/NVDA most likely to hit Tier 1/2)
- Commit/refresh README.md (or fold into PROGRESS.md)
- SVI/SSVI smile fit for arbitrage-free surface when pricing off it
- Consider per-ticker HTML or JSON sidecar if viewer size grows
  (full rebuild currently ~4 MB, fine)
- Cron/scheduler for the 18:00 ET run
