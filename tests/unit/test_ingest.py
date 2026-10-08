"""Ingest logic: tiered chain fetch, expiry window, dividends store, parity check.

All vendor responses stubbed; dividend store redirected to tmp_path.
"""
import csv
import warnings
from datetime import date

import pytest

from options_calculations import ingest
from conftest import ASOF, chain_row


def _client(responder):
    return type("C", (), {"options": responder, "dividends": lambda self, t: []})()


class TestChainTiers:
    def test_tier0_single_band_call_under_cap(self, snapshooter):
        s = snapshooter
        s.client = _client(lambda self, **kw: [chain_row("2026-10-16")] * 100)
        pages = s._chain_pages(s.ticker, (80, 120), ASOF)
        assert len(pages) == 1 and len(pages[0]) == 100

    def test_tier1_splits_by_type_when_capped(self, snapshooter):
        calls = []
        def respond(self, **kw):
            calls.append(kw.get("type"))
            return [chain_row("2026-10-16")] * (5000 if "type" not in kw else 100)
        s = snapshooter
        s.client = _client(respond)
        pages = s._chain_pages(s.ticker, (80, 120), ASOF)
        assert calls == [None, "call", "put"] and len(pages) == 2

    def test_tier2_pages_expected_expiries(self, snapshooter, monkeypatch):
        expiries = ["2026-09-25", "2026-10-02", "2026-10-16"]
        monkeypatch.setattr(ingest, "expected_expiries",
                            lambda asof: [date.fromisoformat(e) for e in expiries])
        def respond(self, **kw):
            if kw.get("expiry"):
                return [chain_row(kw["expiry"])] * 50
            return [chain_row("2026-10-16")] * 5000  # capped at band and type level
        s = snapshooter
        s.client = _client(respond)
        pages = s._chain_pages(s.ticker, (80, 120), ASOF)
        assert len(pages) == 3  # one page per expected expiry

    def test_single_expiry_cap_raises(self, snapshooter, monkeypatch):
        monkeypatch.setattr(ingest, "expected_expiries", lambda asof: [date(2026, 10, 16)])
        s = snapshooter
        s.client = _client(lambda self, **kw: [chain_row("2026-10-16")] * 5000)
        with pytest.raises(RuntimeError, match="split the strike band"):
            s._chain_pages(s.ticker, (80, 120), ASOF)


def test_fetch_chain_windows_on_absolute_expiry(snapshooter):
    s = snapshooter
    s.client = _client(lambda self, **kw: [
        chain_row("2026-10-16"),           # in window
        chain_row("2027-06-18"),           # beyond 3 months
        chain_row("2026-09-01"),           # expired
    ])
    live = s._fetch_chain(s.ticker, 100.0, ASOF)
    assert [r["expiry"] for r in live] == ["2026-10-16"]


class TestDividendsStore:
    FRESH = [{"symbol": "TEST", "effective_date": "2026-09-10", "dividend_amount": "0.25"}]
    STALE = [{"symbol": "TEST", "effective_date": "2026-06-01", "dividend_amount": "0.25"}]
    DIVS = FRESH

    def _write(self, path, rows):
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)

    def test_fresh_file_skips_vendor_call(self, snapshooter):
        s = snapshooter
        self._write(s.divs_path / "dividends.csv", self.FRESH)
        s.client = type("C", (), {"dividends": lambda self, t: pytest.fail("vendor called")})()
        rows = s._fetch_dividends("TEST", ASOF)  # ex-date < 30d old -> file served
        assert [d["symbol"] for d in rows] == ["TEST"]

    def test_empty_vendor_return_writes_nothing(self, snapshooter):
        s = snapshooter
        s.client = type("C", (), {"dividends": lambda self, t: []})()
        assert s._fetch_dividends("TEST", ASOF) == []
        assert not (s.divs_path / "dividends.csv").exists()

    def test_stale_file_refreshes_and_keeps_other_tickers(self, snapshooter):
        s = snapshooter
        other = [{"symbol": "AAPL", "effective_date": "2026-09-10", "dividend_amount": "0.27"}]
        self._write(s.divs_path / "dividends.csv",
                    other + [{"symbol": "TEST", "effective_date": "2020-01-01",
                              "dividend_amount": "0.10"}])
        s.client = type("C", (), {"dividends": lambda self, t, d=self.FRESH: d})()
        rows = s._fetch_dividends("TEST", ASOF)
        on_file = list(csv.DictReader(open(s.divs_path / "dividends.csv")))
        assert {d["symbol"] for d in on_file} == {"AAPL", "TEST"}
        assert rows == self.FRESH


class TestParityCheck:
    def _chain(self, spot=100.0):
        # synthetic parity-consistent rows: C - P = S - K for matched strikes
        rows = []
        for k in (90.0, 95.0, 100.0, 105.0, 110.0):
            rows.append(chain_row("2026-10-16", k, "call", max(spot - k, 0.5)))
            rows.append(chain_row("2026-10-16", k, "put", max(k - spot, 0.5)))
        return rows

    def test_matching_spot_stays_silent(self, snapshooter):
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            snapshooter._sanity_check_spot(100.0, self._chain(100.0), [], ASOF)

    def test_wrong_spot_warns(self, snapshooter):
        with pytest.warns(UserWarning, match="parity-implied"):
            snapshooter._sanity_check_spot(90.0, self._chain(100.0), [], ASOF)

    def test_dividend_in_window_shifts_implied_spot(self, snapshooter):
        divs = [{"effective_date": "2026-10-01", "dividend_amount": "1.00",
                 "symbol": "TEST"}]
        # spot 101 with $1 div in window prices like spot 100 without
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            snapshooter._sanity_check_spot(101.0, self._chain(100.0), divs, ASOF)
