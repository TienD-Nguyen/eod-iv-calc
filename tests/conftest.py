"""Shared fixtures: stubbed vendor client, tmp-path SnapShooter, sample rows.

Unit tests never touch the network, the real data/ tree, or the throttle
clock. Dates are always injected, never taken from the wall clock.
"""
from datetime import date
from pathlib import Path

import pytest

from options_calculations import ingest
from options_calculations.ingest import SnapShooter

ASOF = date(2026, 9, 23)


def chain_row(expiry: str, strike: float = 100.0, cp: str = "call",
              price: float = 1.0, traded: str = "2026-09-23T14:00:00Z") -> dict:
    return {"ticker": "TEST", "expiry": expiry, "strike": strike,
            "contract_type": cp, "last_price": price, "last_trade_at": traded,
            "iv": 0.25, "updated_at": traded}


@pytest.fixture
def snapshooter(tmp_path, monkeypatch) -> SnapShooter:
    """SnapShooter with no vendor client, tmp dividend store, no throttle."""
    monkeypatch.setattr(ingest, "CALL_INTERVAL", 0)
    s = SnapShooter.__new__(SnapShooter)
    s.ticker = "TEST"
    s.data_path = tmp_path / "symbols"
    s.divs_path = tmp_path / "dividends"
    s._last_call = 0.0
    return s
