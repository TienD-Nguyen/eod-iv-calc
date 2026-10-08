# AGENT.md — working on this project

## What this is

Daily EOD implied-volatility surface pipeline for US equity options (MAG10
universe). One command per trading day (`uv run eod-iv -d <YYYYMMDD> -u
<TICKER>`) pulls Treasury rates + LSE option chain/spot/dividends, inverts
American CRR IVs, and writes gridded + native surface CSVs and interactive
HTML viewers. Read `README.md` for the overview, `DECISIONS.md` for *why*
things are the way they are, `PROGRESS.md` for *where* things stand.

## Start-up tasks (new session)

1. `git log --oneline -5` and `git status` — see where the last session ended
2. Read `PROGRESS.md` — current state, known issues, next steps
3. Skim `DECISIONS.md` before touching anything that looks odd — most odd
   things are deliberate and recorded there (vendor dte distrust, exact-date
   Treasury match, declared-only parity check, 5-run retention)
4. `uv run pytest -q` — suite must start green (21 unit tests, ~4 s)
5. Check `data/symbols/<ticker>/<asof>/` for what's already archived —
   reruns of archived dates are free (zero vendor calls)

## Conventions that matter

- **Never trust vendor `dte`/`min_dte`/`max_dte`** — they're relative to each
  row's last trade date. Window on absolute expiry dates.
- **All archives are write-once, immutable, keyed by data date** — no TTL, no
  invalidation. Vendor calls go through `_lse_call` (throttle + 429/5xx retry)
- **Paths are `LOCAL_DIR`-relative** (`data/`, `config/`), never cwd-relative
- **Flat imports are banned** — package-relative (`from .rates import ...`);
  run via `uv run eod-iv` or `python -m options_calculations.<module>`
- **Pricer changes live in `surface.py`**; orchestration in `eod_iv_calc.py`;
  vendor interaction only in `ingest.py`; curves only in `rates.py`
- Dates are always injected (`asof`/`trading_date`), never `today()` in logic
- Ponytail mode: smallest working change, stdlib first, no speculative
  abstraction; mark deliberate shortcuts with a `# ponytail:` comment

## Definition of done (a feature is done when)

1. The pipeline runs green: `uv run eod-iv -d <recent trading day> -u AAPL`
2. `uv run pytest -q` passes, including new tests for the change
   (one behavior-level test, no coverage chasing; floats via `pytest.approx`)
3. Unit tests touch no network and no real `data/` (tmp_path + stubbed client)
4. Rerunning the same date performs **zero** vendor calls (archive hit)
5. A vendor failure in the new path can't corrupt existing archives
6. If a design choice was made, it's appended to `DECISIONS.md` (what/why/when)

## Clock-out tasks (end of session)

1. Update `PROGRESS.md`: move finished items to Completed, refresh Known
   issues and Next steps
2. Append any design decisions to `DECISIONS.md`
3. Commit with one-line message (what + why) and trailer
   `Co-authored-by: Kimi <noreply@moonshot.ai>`; push only when the user asks
4. Leave the suite green and the working tree intentional (no stray edits)
