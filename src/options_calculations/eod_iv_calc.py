"""EOD IV surface calculation for one underlying and trading date.

Flow: holiday/weekend check -> Treasury curve (rates.py) -> snapshot
(ingest.py) -> per-row CRR American IV inversion (surface.py pricers;
BS kept as a validation column) -> smile interp per expiry -> total-variance
interp across the DTE grid -> surface.csv (gridded, for the 3D viewer) +
smile.csv (native: one row per quote at its actual expiry/strike, for the
smile viewers) under data/<ticker>/<asof>/.

Run: python eod_iv_calc.py -d 20260923 -u AAPL   (after 18:00 ET)
"""
import argparse
import csv
import math
import shutil
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np

from utils import int_or_str
from holidays import holiday_weekend_check
from rates import TreasuryYieldRatesManager
from ingest import SnapShooter
from surface import (forecast_dividends, pv_dividends, bs_price, crr_price,
                     implied_vol)

MAX_DTE = 180
MONEYNESS = (0.8, 1.2)
K_GRID = np.linspace(math.log(MONEYNESS[0]), math.log(MONEYNESS[1]), 41)
DTE_GRID = [1, 7, 14, 21, 30, 45, 60, 90, 120, 150, 180]
LOCAL_DIR = Path(__file__).parent.resolve()
DATA_DIR = LOCAL_DIR / "../../data"
KEEP_RUNS = 5  # per-ticker calculation dirs retained; older ones pruned


def prune_runs(ticker_dir: Path, keep: int = KEEP_RUNS) -> None:
    """Retain only the newest `keep` calculation dirs (ISO dates sort as strings)."""
    dirs = sorted(p for p in ticker_dir.iterdir() if p.is_dir())
    for old in dirs[:-keep]:
        shutil.rmtree(old)
        print(f"pruned {old}")


def build_surface(rates: TreasuryYieldRatesManager, asof: date, spot: float,
                  chain: list[dict], divs: list[dict]):
    """Return (dte_grid, iv_matrix, validation_rows). Own CRR inversion only;
    stale rows and inversion failures are dropped, not patched over."""
    fwd_divs = forecast_dividends(divs, asof, asof + timedelta(days=MAX_DTE))

    smiles: dict[int, dict[float, float]] = {}
    validation = []
    for row in chain:
        if row["updated_at"][:10] != asof.isoformat() or not row["iv"]:
            continue  # stale row or no validation reference
        K = float(row["strike"])
        expiry = date.fromisoformat(row["expiry"])
        dte = (expiry - asof).days  # vendor dte is stale-trade-relative; recompute
        if dte < 1 or not (MONEYNESS[0] <= K / spot <= MONEYNESS[1]):
            continue
        T = dte / 365
        r = float(rates.interpolate_rate(T))
        divs_t = [((ex - asof).days / 365, amt) for ex, amt in fwd_divs if ex <= expiry]
        s_adj = spot - pv_dividends(fwd_divs, asof, expiry, r)
        F = s_adj * math.exp(r * T)
        cp = 1 if K > F else -1  # OTM only: calls above fwd, puts below
        if row["contract_type"] != ("call" if cp == 1 else "put"):
            continue
        price = float(row["last_price"])

        def crr_at(sig: float) -> float:
            """American CRR price of this row at volatility `sig`."""
            return crr_price(cp, spot, K, T, r, sig, divs_t)

        def bs_at(sig: float) -> float:
            """European BS price of this row at volatility `sig` (validation)."""
            return bs_price(cp, s_adj, K, T, r, sig)

        crr_iv = implied_vol(crr_at, price)
        bs_iv = implied_vol(bs_at, price)
        lse_iv = float(row["iv"])
        validation.append({"ticker": row["ticker"], "expiry": expiry.isoformat(),
                           "dte": dte, "strike": K,
                           "crr_iv": crr_iv, "bs_iv": bs_iv, "lse_iv": lse_iv,
                           "diff": None if crr_iv is None else crr_iv - lse_iv})
        if crr_iv is not None:
            smiles.setdefault(dte, {})[math.log(K / F)] = crr_iv

    # interpolate each smile onto K_GRID, then total variance across tenors
    dtes = sorted(d for d, s in smiles.items() if len(s) >= 3)
    w = []  # total variance rows aligned with dtes
    for d in dtes:
        ks, ivs = zip(*sorted(smiles[d].items()))
        w.append(np.interp(K_GRID, ks, ivs) ** 2 * (d / 365))
    iv_matrix = np.full((len(DTE_GRID), len(K_GRID)), np.nan)
    for i, d in enumerate(DTE_GRID):
        if dtes and dtes[0] <= d <= dtes[-1]:
            wi = np.array([np.interp(d, dtes, [wrow[j] for wrow in w]) for j in range(len(K_GRID))])
            iv_matrix[i] = np.sqrt(wi / (d / 365))
    return np.array(DTE_GRID), iv_matrix, validation


def save(day_dir: Path, dte_grid, iv_matrix, validation) -> None:
    day_dir.mkdir(parents=True, exist_ok=True)
    with open(day_dir / "surface.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["dte"] + [f"{k:.4f}" for k in K_GRID])
        for d, row in zip(dte_grid, iv_matrix):
            w.writerow([d] + ["" if math.isnan(v) else f"{v:.6f}" for v in row])
    # native long-format surface: every quote at its actual expiry/strike
    with open(day_dir / "smile.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["ticker", "expiry", "dte", "strike", "crr_iv",
                                          "bs_iv", "lse_iv", "diff"])
        w.writeheader()
        w.writerows(validation)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Calculating EOD Options' Volatility Surfaces")
    parser.add_argument("-d", "--date", type=str, help="Date for the calculation in 'YYYYMMDD' format (e.g. 20260101).")
    parser.add_argument("-u", "--underlying", type=str, help="Underlying US ticker for the calculation (e.g. AAPL).")
    parser.add_argument("--no-viz", action="store_true", help="Skip regenerating the HTML viewers.")
    args = parser.parse_args()

    if not args.underlying:
        raise ValueError("No input underlying ticker received. Please entering an underlying US equity ticker for the calculation.")

    input_date = datetime.strptime(args.date, "%Y%m%d").date() if args.date else datetime.now(tz=ZoneInfo("US/Eastern")).date()
    underlying_ticker = args.underlying

    schedule_mark = holiday_weekend_check(input_date)
    is_early_close = (schedule_mark == 2)

    treasury_yield_mgr = TreasuryYieldRatesManager()
    treasury_yield_mgr.fetch_curve(input_date)
    asof, spot, divs, chain = SnapShooter().snapshot(
        ticker=underlying_ticker, trading_date=input_date, is_early_close=is_early_close)

    dte_grid, iv_matrix, validation = build_surface(
        treasury_yield_mgr, asof, spot, chain, divs)
    day_dir = DATA_DIR / underlying_ticker / asof.isoformat()
    save(day_dir, dte_grid, iv_matrix, validation)
    prune_runs(DATA_DIR / underlying_ticker)

    if not args.no_viz:
        try:
            from viz import regenerate  # lazy: keeps plotly off the calc path
            regenerate()
        except (Exception, SystemExit) as e:  # viz must never fail the calc
            print(f"viz update skipped: {e}", file=sys.stderr)

    finite = iv_matrix[np.isfinite(iv_matrix)]
    diffs = sorted(abs(v["diff"]) for v in validation if v["diff"] is not None)
    print(f"{day_dir}: surface {iv_matrix.shape}, iv range [{finite.min():.3f}, {finite.max():.3f}]")
    if diffs:
        print(f"validation: n={len(diffs)}, |crr-lse| p50={diffs[len(diffs)//2]:.4f} "
              f"p90={diffs[int(len(diffs) * .9)]:.4f}")
    assert 0.02 < finite.min() and finite.max() < 2.0, "surface IVs out of sane range"
    print("OK")
