"""Pricer math: CRR correctness, early exercise, dividends, IV inversion.

Pure computation — the highest-value, zero-mock tests in the suite.
"""
from datetime import date, timedelta

import pytest

from options_calculations.surface import (bs_price, crr_price, implied_vol,
                                          forecast_dividends, pv_dividends)

S, K, T, R, SIG = 100.0, 105.0, 0.25, 0.04, 0.30


def test_crr_call_converges_to_bs_without_dividends():
    # no early-exercise value on a call with no dividends -> CRR ~ European
    assert crr_price(1, S, K, T, R, SIG, steps=400) == pytest.approx(
        bs_price(1, S, K, T, R, SIG), abs=0.02)


def test_deep_itm_put_worth_at_least_intrinsic():
    # American early exercise: put can be exercised now for K - S
    assert crr_price(-1, 100.0, 140.0, 0.5, R, SIG) >= 40.0 - 1e-6


def test_implied_vol_roundtrip_through_crr():
    price = crr_price(1, S, K, T, R, SIG)
    iv = implied_vol(lambda s: crr_price(1, S, K, T, R, s), price)
    assert iv == pytest.approx(SIG, abs=1e-3)


def test_implied_vol_returns_none_when_no_root():
    assert implied_vol(lambda s: 1.0, price=-5.0) is None  # never crosses zero


def test_dividend_before_expiry_lowers_call():
    assert crr_price(1, S, K, T, R, SIG, divs=[(0.1, 2.0)]) < crr_price(1, S, K, T, R, SIG)


def test_expired_option_is_intrinsic():
    assert crr_price(1, 110.0, 100.0, 0.0, R, SIG) == 10.0
    assert crr_price(-1, 110.0, 100.0, 0.0, R, SIG) == 0.0


def test_forecast_dividends_empty_history_is_safe():
    assert forecast_dividends([], date(2026, 1, 1), date(2026, 12, 31)) == []
    assert pv_dividends([], date(2026, 1, 1), date(2026, 6, 1), R) == 0.0


def test_forecast_dividends_continues_last_quarterly():
    asof, horizon = date(2026, 1, 1), date(2026, 12, 31)
    divs = [{"effective_date": "2025-11-10", "dividend_amount": "0.25"}]
    out = forecast_dividends(divs, asof, horizon)
    assert all(amt == 0.25 for _, amt in out) and len(out) >= 3
    gaps = [((b - a).days) for (a, _), (b, _) in zip(out, out[1:])]
    assert all(g == 91 for g in gaps)


def test_forecast_dividends_keeps_declared_in_window():
    asof = date(2026, 1, 1)
    divs = [{"effective_date": "2025-11-10", "dividend_amount": "0.25"},
            {"effective_date": "2026-02-10", "dividend_amount": "0.30"}]
    out = forecast_dividends(divs, asof, asof + timedelta(days=120))
    assert (date(2026, 2, 10), 0.30) in out  # declared kept as-is


def test_pv_dividends_discounts():
    asof = date(2026, 1, 1)
    divs = [(date(2027, 1, 1), 1.0)]
    assert pv_dividends(divs, asof, date(2027, 6, 1), 0.0) == 1.0
    assert pv_dividends(divs, asof, date(2027, 6, 1), 0.10) < 1.0
