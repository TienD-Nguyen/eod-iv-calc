"""Option pricers and dividend helpers.

CRR binomial (primary, American): the tree diffuses the escrowed spot
S* = S - PV(divs to expiry); at each node the exercise decision uses
S*_node + PV(remaining divs at that time), so early exercise around
ex-dates is priced while the tree stays recombining.

Black-Scholes (validation only): European, escrowed dividends via s_adj.
"""
import math
from datetime import date, timedelta

import numpy as np
from scipy.optimize import brentq
from scipy.stats import norm


def forecast_dividends(divs: list[dict], asof: date, horizon: date) -> list[tuple[date, float]]:
    """(ex_date, amount) pairs with ex-date in (asof, horizon]. Declared future
    dividends are kept as-is; beyond that, assume the last quarterly amount
    repeats every 91 days."""
    past = sorted(
        (date.fromisoformat(d["effective_date"]), float(d["dividend_amount"]))
        for d in divs if d["dividend_amount"]
    )
    if not past:
        return []  # non-dividend payer (e.g. TSLA): no declared, no continuation
    out = [(ex, amt) for ex, amt in past if asof < ex <= horizon]
    # ponytail: naive quarterly continuation; replace with declared divs when announced.
    ex, amt = past[-1]
    while (ex := ex + timedelta(days=91)) <= horizon:
        if ex > asof and ex not in {e for e, _ in out}:
            out.append((ex, amt))
    return sorted(out)


def pv_dividends(divs: list[tuple[date, float]], asof: date, expiry: date, rate: float) -> float:
    return sum(amt * math.exp(-rate * (ex - asof).days / 365)
               for ex, amt in divs if asof < ex <= expiry)


def bs_price(cp: int, s_adj: float, K: float, T: float, r: float, sigma: float) -> float:
    """European Black-Scholes on dividend-adjusted spot (validation reference)."""
    if T <= 0 or sigma <= 0:
        return max(cp * (s_adj - K), 0.0)
    d1 = (math.log(s_adj / K) + (r + sigma * sigma / 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return cp * (s_adj * norm.cdf(cp * d1) - K * math.exp(-r * T) * norm.cdf(cp * d2))


def crr_price(cp: int, S: float, K: float, T: float, r: float, sigma: float,
              divs: list[tuple[float, float]] = (), steps: int = 200) -> float:
    """American CRR binomial price. divs: (t_years, cash_amount) in (0, T].
    Escrowed model: tree on S* = S - PV(divs); exercise value at each node
    uses S* + PV(divs remaining after that node)."""
    if T <= 0 or sigma <= 0:
        return max(cp * (S - K), 0.0)
    divs = [(t, a) for t, a in divs if 0 < t <= T]
    pv_total = sum(a * math.exp(-r * t) for t, a in divs)
    S_star = max(S - pv_total, 1e-8)
    dt = T / steps
    u, d = math.exp(sigma * math.sqrt(dt)), math.exp(-sigma * math.sqrt(dt))
    p = (math.exp(r * dt) - d) / (u - d)
    disc = math.exp(-r * dt)
    # PV at level i of divs with ex-time after t_i: e^{r*t_i} * sum(a*e^{-r*t})
    times = np.arange(steps + 1) * dt
    pv_rem = np.array([
        math.exp(r * ti) * sum(a * math.exp(-r * t) for t, a in divs if t > ti + 1e-12)
        for ti in times
    ])
    j = np.arange(steps + 1)
    S_T = S_star * u ** j * d ** (steps - j)
    values = np.maximum(cp * (S_T + pv_rem[steps] - K), 0.0)
    for i in range(steps - 1, -1, -1):
        jj = np.arange(i + 1)
        S_i = S_star * u ** jj * d ** (i - jj)
        cont = disc * (p * values[1:] + (1 - p) * values[:-1])
        values = np.maximum(cont, cp * (S_i + pv_rem[i] - K))
    return float(max(values[0], 0.0))


def implied_vol(price_fn, price: float) -> float | None:
    """Invert any pricer: price_fn(sigma) -> price. None if no root."""
    def residual(sig: float) -> float:
        """Pricer value minus market price; zero at the implied vol."""
        return price_fn(sig) - price
    
    try:
        return brentq(residual, 1e-4, 5.0, xtol=1e-8)
    except (ValueError, RuntimeError):
        return None


if __name__ == "__main__":
    # CRR with no dividends on a call converges to BS (no early-exercise value)
    S, K, T, r, sig = 100.0, 105.0, 0.25, 0.04, 0.30
    crr_c = crr_price(1, S, K, T, r, sig, steps=400)
    bs_c = bs_price(1, S, K, T, r, sig)
    assert abs(crr_c - bs_c) < 0.02, (crr_c, bs_c)
    # deep ITM American put must be worth at least intrinsic (early exercise)
    put = crr_price(-1, 100.0, 140.0, 0.5, 0.04, 0.30)
    assert put >= 40.0 - 1e-6, put
    # IV roundtrip through the CRR pricer
    px = crr_price(1, S, K, T, r, sig)
    iv = implied_vol(lambda s: crr_price(1, S, K, T, r, s), px)
    assert abs(iv - sig) < 1e-3, iv
    # dividend before expiry lowers call value
    c_div = crr_price(1, S, K, T, r, sig, divs=[(0.1, 2.0)])
    assert c_div < crr_c
    # non-dividend payer: empty history -> no forecast, zero PV
    assert forecast_dividends([], date(2026, 1, 1), date(2026, 12, 31)) == []
    assert pv_dividends([], date(2026, 1, 1), date(2026, 6, 1), r) == 0.0
    print("OK")
