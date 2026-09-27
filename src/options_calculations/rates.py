"""US Treasury daily par yield curve -> interpolated continuously-compounded risk-free rates.

Exact-date match only: raises if no curve is published for the requested date
(e.g. weekends/holidays, or today's curve not out yet before ~18:00 ET).
No fallback — on a weekend, pass the last weekday's date explicitly.
Fetched curves are archived as one JSON per date under `treasury_archive/`
(past curves are immutable, so archived files never expire).
"""
import csv
import io
import json
import os
import urllib.request
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from functools import lru_cache
import numpy as np
from scipy.interpolate import CubicSpline


LOCAL_DIR = Path(__file__).parent.resolve()
ARCHIVE_DIR = LOCAL_DIR / "../../data" / "treasury"


URL = (
    "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
    "daily-treasury-rates.csv/all/{value_month}?type=daily_treasury_yield_curve&"
    "field_tdr_date_value_month={value_month}&page&_format=csv"
)

# CSV column header -> tenor in years
TENORS = {
    "1 Mo": 1 / 12, "1.5 Month": 1.5 / 12, "2 Mo": 2 / 12, "3 Mo": 3 / 12,
    "4 Mo": 4 / 12, "6 Mo": 6 / 12, "1 Yr": 1, "2 Yr": 2, "3 Yr": 3,
    "5 Yr": 5, "7 Yr": 7, "10 Yr": 10, "20 Yr": 20, "30 Yr": 30,
}


class TreasuryYieldRatesManager:
    def __init__(self):
        self.asof = None
        self.tenors = None
        self.yields_cc = None
        self.yields_pct = None

    @staticmethod
    def _download_curves(month: str) -> list[dict]:
        with urllib.request.urlopen(URL.format(value_month=month), timeout=30) as resp:
            return list(csv.DictReader(io.StringIO(resp.read().decode())))

    @lru_cache(maxsize=None)  # one resolved curve per day per process
    def extract_curve(self, request_date: date | None = None) -> tuple[date, list, list]:
        request_date = request_date or datetime.now(ZoneInfo("US/Eastern")).date()
        archive = ARCHIVE_DIR / f"{request_date}.json"
        if archive.exists():
            try:  # corrupt file -> treat as miss, re-fetch overwrites it
                data = json.loads(archive.read_text())
                return request_date, data["tenors"], data["yields_pct"]
            except (json.JSONDecodeError, KeyError):
                pass
        curves = self._download_curves(month=request_date.strftime("%Y%m"))
        if not curves:
            raise ValueError(f"No Treasury curve for {request_date.month}, {request_date.year} yet.")
        for curve in curves:
            asof = datetime.strptime(curve["Date"], "%m/%d/%Y").date()
            if asof == request_date:
                tenors, yields_pct = self._parse_row(curve)
                ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
                archive.write_text(json.dumps({"tenors": tenors, "yields_pct": yields_pct}))
                return asof, tenors, yields_pct
        raise ValueError(f"No treasury curve is yet available for {request_date.strftime('%m-%d-%Y')}.")

    @staticmethod
    def _parse_row(curve: dict) -> tuple[list, list]:
        tenors, yields_pct = zip(*(
            (tenor, float(curve[maturity])) for maturity, tenor in TENORS.items() if curve.get(maturity)
        ))
        return list(tenors), list(yields_pct)

    @staticmethod
    def parse_curve(tenors: list, yields_pct: list):
        # par yield (semiannual) -> continuously compounded
        yields_cc = 2 * np.log1p(np.array(yields_pct) / 200)
        return np.array(tenors), np.array(yields_pct), yields_cc

    def fetch_curve(self, request_date: date | None = None):
        self.asof, tenors, yields_pct = self.extract_curve(request_date)
        self.tenors, self.yields_pct, self.yields_cc = self.parse_curve(tenors, yields_pct)
        self.cs = CubicSpline(self.tenors, self.yields_cc)
        return self.tenors, self.yields_pct, self.yields_cc

    def interpolate_rate(self, t_years: float) -> float:
        """Cubic-spline interpolated cc risk-free rate for tenor `t_years` (as a decimal)."""
        return self.cs(t_years)


if __name__ == "__main__":
    d = "20260923"
    request_date = date.strptime(d, "%Y%m%d")
    treasury_yield_mgr = TreasuryYieldRatesManager()
    tenors, rates, yields_cc = treasury_yield_mgr.fetch_curve(request_date)
    print(f"Curve as of {asof}")
    for dte in (7, 14, 30, 50, 70, 90, 180):
        r = treasury_yield_mgr.interpolate_rate(dte / 365)
        print(f"  DTE {dte:>3}: {r * 100:.3f}%")
        assert 0 < r < 0.2, "rate out of sane range"
    assert np.all(np.diff(tenors) > 0) and len(tenors) >= 10
    print("OK")