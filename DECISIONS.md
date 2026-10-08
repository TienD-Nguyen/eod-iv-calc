# Decisions

Design decisions and why they were made. Newest last. (Dates approximate.)

## 2026-09-16 — Disk archive for Treasury curves, JSON per date
Past curves are immutable, so write-once files never expire and no
invalidation logic is needed. `lru_cache` kept as in-process layer only —
it dies with the process.

## 2026-09-16 — Exact-date match for Treasury curve, no fallback
Deliberately simple: raises on weekends/holidays, caller passes the last
weekday. Fallback logic deferred until actually needed.

## 2026-09-16 — CSV/JSON archives, not parquet
Parquet needs pyarrow (~100 MB dep) to save ~1 MB/day; chains are ~5k rows
where columnar gains don't apply, and CSV stays greppable when debugging.

## 2026-09-17 — Spot from last regular-session 1m/1s bar, not the 1d candle
LSE's daily candle includes extended-hours prints and mismatched the
official 16:00 ET close. Windowed 15:55–16:00 ET bars (12:55–13:00 on early
closes) match other sources.

## 2026-09-17 — Live tick capture rejected
Expired/stale chain rows are fixable by filtering; a websocket collector
adds a market-hours daemon, gaps, and misses illiquid contracts. Revisit
only for intraday surfaces.

## 2026-09-17 — Filter chain on absolute expiry dates, not vendor dte
LSE's dte/min_dte/max_dte are relative to each row's last trade date, so
expired contracts look live. Window on `asof <= expiry <= asof + 93d`;
recompute DTE downstream from `expiry - asof`.

## 2026-09-17 — Parity-forward spot sanity check
Chain quotes are an independent witness of where the stock traded; fit
C−P = a + b·K per expiry, compare F + PV(divs) vs spot, warn past 2%.
Ratio F = −a/b used (not intercept directly) because a/b fit errors cancel
— intercept alone false-alarmed (+9.9%) on 1-DTE rows.

## 2026-09-23 — Sanity check uses declared dividends only (not forecast)
Undeclared-but-due dividends inside the expiry window are a known blind
spot (dev biased low by ~PV(div)/S ≈ 0.08% for AAPL; 2% threshold absorbs
it). Accepted deliberately: the check stays factual and independent —
forecast dividends are assumptions that would false-alarm on their own.
The pricing path is unaffected: build_surface uses forecast_dividends
(declared + quarterly continuation) for CRR. Revisit if a high-yield
ticker (~1%/quarter) ever eats the threshold.

## 2026-09-18 — Tiered handling of the 5,000-row chain cap
Band call → split by call/put → page by expected expiries. A capped page
is never complete data. Strike-band split (Tier 3) deferred.

## 2026-09-18 — Candidate expiries from Cboe available-weeklys + generated monthlies
Weeklies/Mon–Thu dailies are only listed shortly ahead, so the Cboe CSV
(cached weekly in config/) covers the near end with real listed dates;
3rd-Friday monthlies (holiday-shifted via config/holiday.txt) cover the
rest. Candidates are a query schedule, not ground truth; empty pages OK.

## 2026-09-18 — Shared dividends store: one CSV for all tickers, 5y window
Consumers read a single file; a ticker's rows refresh only when the vendor
has newer ex-dates, and the vendor call is skipped entirely when the latest
ex-date on file is fresh (< 30–60 days).

## 2026-09-18 — Throttle + retry wrapper for all LSE calls
1.5 s minimum spacing; retry only 429/5xx with 2/4/8 s backoff; other 4xx
raise immediately (our bug, retrying just hammers the endpoint).

## 2026-09-23 — CRR binomial as primary pricer, BS kept for validation
Options are American: CRR prices early exercise (escrowed discrete
dividends on a recombining tree — exercise decision uses S* + PV of
remaining divs per node). BS retained as a European reference column in
smile.csv.

## 2026-09-23 — Grid interpolation: linear across strikes, total-variance across tenors
Linear in strike can't overshoot between tight listed strikes. Across
tenors, interpolating w = IV²·T (not IV) keeps the surface monotone in
expiry and avoids calendar arbitrage. Out-of-range stays NaN, not clamped.

## 2026-09-23 — Two outputs: gridded surface.csv + native smile.csv
Grid exists for the 3D viewer; smile.csv is the same quotes at actual
expiry/strike with zero interpolation — the honest surface. supersedes
validation.csv (same rows + expiry).

## 2026-09-23+ — Multi-ticker viz: dropdown=visibility, slider=data
The two controls touch disjoint trace attributes so they compose. Smiles
are per-ticker figures swapped by HTML select (legend clicks toggle
expiries); hidden figures need Plotly.Plots.resize when shown.

## 2026-09-23+ — Viewers rebuilt after each calc; retain last 5 runs per ticker
Graphs always current; latest-run-only scan keeps rebuild cheap. Pruning
bounds history by design (5 days on the sliders). Lazy plotly import keeps
the calc path fast; viz failure never fails the calc (--no-viz to skip).
