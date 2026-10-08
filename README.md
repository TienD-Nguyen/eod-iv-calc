# EOD Implied-Volatility Surface

Daily end-of-day implied-volatility surfaces for US equity options (MAG10
universe), priced with an American CRR binomial model and rendered as
interactive HTML viewers.

## What it does

One command per trading day:

```bash
uv run eod-iv -d 20260923 -u AAPL
```

runs the full pipeline:

1. **Rates** — US Treasury daily par yield curve → continuously-compounded
   rates, cubic-spline interpolated to any tenor (`rates.py`)
2. **Snapshot** — option chain, spot, dividends from LondonStrategicEdge
   (`ingest.py`), with a put-call-parity spot sanity check
3. **Surface** — per-quote CRR implied-vol inversion, per-expiry smile
   interpolation, total-variance interpolation across tenors
   (`surface.py` + `eod_iv_calc.py`)
4. **Viewers** — regenerates `data/viz/viz.html` (3D surface, date slider)
   and `data/viz/smiles.html` (per-expiry smiles at actual strikes)

## Assumptions

- Run after **18:00 ET** (Treasury curve and EOD data published)
- Exact trading-date match only; weekends/holidays are rejected, not
  backfilled
- Spot = last regular-session bar (15:55–16:00 ET); the vendor's daily
  candle contains extended-hours prints and is not used
- Only fresh, OTM quotes in the 0.8–1.2 moneyness band feed the surface
- Dividends: declared + naive quarterly continuation for pricing; the spot
  sanity check uses declared dividends only (independence over precision)
- All archives are write-once and immutable; reruns of a date never re-hit
  the vendors

## Methods

- **Pricing**: CRR binomial tree (200 steps), American early exercise at
  every node; discrete dividends via the escrowed model (tree on
  S\* = S − PV(divs), exercise value uses S\* + PV(remaining divs)).
  Black-Scholes kept as a European validation reference
- **IV inversion**: Brent's method per quote
- **Interpolation**: linear across strikes; linear in total variance
  (w = IV²·T) across tenors to avoid calendar arbitrage; out-of-range grid
  points stay NaN rather than clamped
- **Validation**: per-quote own-IV vs vendor-IV reported in `smile.csv`;
  parity-forward spot check at ingest (warns past 2%)

## Data layout

```
data/
  symbols/<ticker>/<asof>/   spot.json, chain.csv, surface.csv, smile.csv
                             (last 5 runs per ticker retained)
  dividends/dividends.csv    shared store, all tickers, 5y window
  treasury/<date>.json       one file per curve date
  viz/                       viz.html, smiles.html
```

## Replicate

```bash
git clone <repo> && cd eod-iv-calc
uv sync
echo 'LSE_API_KEY=<your key from londonstrategicedge.com/data>' > .env
uv run eod-iv -d 20260923 -u AAPL   # then open data/viz/viz.html
```

Python ≥ 3.14. Deps: lse-data, numpy, scipy, plotly, python-dotenv
(see `pyproject.toml`).

## Docs

- `DECISIONS.md` — design decisions and their rationale, chronological
- `PROGRESS.md` — current state, known issues, next steps
