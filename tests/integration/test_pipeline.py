"""Integration test: full EOD pipeline (holidays -> rates -> snapshot ->
surface -> save -> prune -> viz) with only the network boundary stubbed:
LSE client, Treasury download, Cboe calendar files. Data dirs are tmp_path.

The synthetic chain is priced by our own CRR pricer at TRUE_VOL, mirroring
build_surface's dividend handling, so the end-to-end assertion is that the
pipeline recovers TRUE_VOL on the surface grid and in smile.csv.

No network, no real data/ tree (same rule as the unit suite).
"""
import csv
import json
import math
from datetime import date, timedelta

import pytest

from options_calculations import eod_iv_calc, holidays, ingest, rates, viz
from options_calculations.surface import crr_price, forecast_dividends

ASOF = date(2026, 9, 23)  # Wednesday
SPOT = 100.0
TRUE_VOL = 0.30
YIELD_PCT = 4.00  # flat par curve -> cc rate below
R_CC = 2 * math.log1p(YIELD_PCT / 200)  # same par->cc conversion as rates.py
EXPIRIES = ["2026-09-25", "2026-10-02", "2026-10-16", "2026-11-20", "2026-12-18"]
DIVS = [{"symbol": "TEST", "effective_date": "2026-08-15", "dividend_amount": "0.25"}]
ARGS = ["-d", "20260923", "-u", "TEST", "--no-viz"]


def _chain() -> list[dict]:
    """CRR-priced chain at TRUE_VOL over 9 strikes x 5 expiries, both types."""
    fwd_divs = forecast_dividends(DIVS, ASOF, ASOF + timedelta(days=eod_iv_calc.MAX_DTE))
    rows = []
    for expiry in EXPIRIES:
        exp = date.fromisoformat(expiry)
        T = (exp - ASOF).days / 365
        divs_t = [((ex - ASOF).days / 365, amt) for ex, amt in fwd_divs if ex <= exp]
        for K in range(80, 121, 5):
            for cp, name in ((1, "call"), (-1, "put")):
                px = crr_price(cp, SPOT, float(K), T, R_CC, TRUE_VOL, divs_t)
                if px < 0.05:
                    continue  # wing junk: penny prices invert badly (real chains too)
                rows.append({"ticker": "TEST", "expiry": expiry, "strike": str(K),
                             "contract_type": name, "last_price": f"{px:.4f}",
                             "last_trade_at": "2026-09-23T19:00:00Z",
                             "iv": str(TRUE_VOL),
                             "updated_at": "2026-09-23T19:00:00Z"})
    return rows


class FakeLSE:
    """In-memory LSE client; `calls` logs every vendor hit."""
    def __init__(self):
        self.calls = []

    def candles(self, ticker, tf, **kw):
        self.calls.append("candles")
        return [  # newest first: extended-hours print must be skipped
            {"timestamp": "2026-09-23T20:30:00+00:00", "close": SPOT + 1},
            {"timestamp": "2026-09-23T19:59:30+00:00", "close": SPOT},  # 15:59 ET
        ]

    def options(self, **kw):
        self.calls.append("options")
        return _chain()

    def dividends(self, ticker):
        self.calls.append("dividends")
        return DIVS


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Pipeline wired to tmp dirs and stubbed vendor; returns (client, calls, data)."""
    data = tmp_path / "data"
    client = FakeLSE()
    calls = {"treasury": 0}

    def fake_init(self, ticker="AAPL", trading_date=None):
        self.ticker = ticker
        self.data_path = data / "symbols"
        self.divs_path = data / "dividends"
        self.client = client
        self.trading_date = trading_date or ASOF
        self._last_call = 0.0

    def fake_download(month):
        calls["treasury"] += 1
        return [{"Date": "09/23/2026", **{m: str(YIELD_PCT) for m in rates.TENORS}}]

    weeklys = tmp_path / "available_weeklys.csv"  # fresh mtime -> no download
    weeklys.write_text('"Standard","09/25/26"\n')

    monkeypatch.setattr(ingest.SnapShooter, "__init__", fake_init)
    monkeypatch.setattr(ingest, "CALL_INTERVAL", 0)
    monkeypatch.setattr(ingest, "WEEKLYS_CACHE", weeklys)
    monkeypatch.setattr(holidays, "verify_holiday_files", lambda: ([], []))
    monkeypatch.setattr(rates.TreasuryYieldRatesManager, "_download_curves",
                        staticmethod(fake_download))
    monkeypatch.setattr(rates, "ARCHIVE_DIR", data / "treasury")
    monkeypatch.setattr(eod_iv_calc, "SYMBOLS_DIR", data / "symbols")
    return client, calls, data


def test_full_run_recovers_input_vol(env):
    client, calls, data = env
    eod_iv_calc.main(ARGS)
    day = data / "symbols" / "TEST" / "2026-09-23"

    smiles = [r for r in csv.DictReader(open(day / "smile.csv")) if r["crr_iv"]]
    assert len(smiles) >= 20
    for r in smiles:
        assert float(r["crr_iv"]) == pytest.approx(TRUE_VOL, abs=1e-3)
        assert abs(float(r["diff"])) < 1e-3  # CRR IV vs vendor IV reference

    surf = list(csv.reader(open(day / "surface.csv")))
    ivs = [float(v) for row in surf[1:] for v in row[1:] if v]
    assert ivs and all(v == pytest.approx(TRUE_VOL, abs=1e-3) for v in ivs)

    assert json.loads((data / "treasury" / "2026-09-23.json").read_text())
    assert set(client.calls) == {"candles", "options", "dividends"}
    assert calls["treasury"] == 1


def test_rerun_is_served_from_archive(env):
    client, calls, _ = env
    eod_iv_calc.main(ARGS)
    n_client, n_treasury = len(client.calls), calls["treasury"]
    eod_iv_calc.main(ARGS)
    assert len(client.calls) == n_client and calls["treasury"] == n_treasury


def test_viz_regenerates_from_pipeline_outputs(env, tmp_path):
    _, _, data = env
    eod_iv_calc.main(ARGS)
    viz.regenerate(data_dir=data / "symbols", out_dir=tmp_path / "viz")
    assert (tmp_path / "viz" / "surfaces.html").exists()
    assert (tmp_path / "viz" / "smiles.html").exists()


def test_weekend_exits_before_any_vendor_call(env):
    client, calls, _ = env
    with pytest.raises(SystemExit):
        eod_iv_calc.main(["-d", "20260926", "-u", "TEST", "--no-viz"])  # Saturday
    assert not client.calls and calls["treasury"] == 0
