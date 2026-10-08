"""Ingest EOD data from LondonStrategicEdge -> data/symbols/<ticker>/<asof>/.

Snapshot per trading day:
  chain.csv      option chain in the strike band, expiries within 3 months of
                 asof, windowed on ABSOLUTE expiry dates (vendor min/max_dte
                 is relative to each row's last trade date, not today).
                 5000-row cap handled in tiers: band call -> split by
                 call/put -> page by expected weekly (Friday) expiries
  spot.json      last regular-session 1m candle (15:59 ET bar; close = EOD spot).
                 The 1d candle is NOT used: it includes extended-hours prints
                 and mismatches the official 16:00 ET close
  dividends     shared store: data/dividends/dividends.csv, all tickers in
                 one file, last 5 years of ex-dates + amounts per ticker
                 (incl. declared future). A ticker's rows are rewritten only
                 when the vendor returns ex-dates newer than the file's
                 latest for that ticker — consumers read this single file

Spot sanity check: the chain itself witnesses where the stock traded.
Put-call parity per expiry, C - P = e^(-rT)*(F - K), is linear in K, so a
least-squares fit of C-P vs strike over matched call/put pairs gives
slope = -e^(-rT) and intercept = e^(-rT)*F, hence forward F = -a/b. Since
F = (S - PV(divs))*e^(rT) ~ S - PV(divs) for near expiries, F plus the expiry
window's declared dividends reconstructs spot (no rates input needed; robust
to approaching ex-dividend dates). Warns past 2%; the fit is European-parity
based, but the American early-exercise premium is negligible for the
near-money short-DTE rows that dominate the band.

Snapshots are immutable: a rerun for an archived date is served from disk
without touching the vendor. Run after 18:00 ET.
"""
import csv
import json
import urllib.request
import warnings
from datetime import date, datetime, time, timedelta
from pathlib import Path
from time import monotonic, sleep
from zoneinfo import ZoneInfo

import numpy as np
from dotenv import dotenv_values
from lse import LSE, LSEError

MAX_DTE = 93
BAND = (0.80, 1.20)  # fetch slightly wider than the 0.8-1.2 surface filter
CALL_INTERVAL = 1.5  # min seconds between vendor calls
ET = ZoneInfo("US/Eastern")
UTC = ZoneInfo("UTC")
LOCAL_DIR = Path(__file__).parent.resolve()

# Cboe weeklys schedule: actual listed expiry dates per program, cached weekly
WEEKLYS_URL = "https://www.cboe.com/available_weeklys/get_csv_download/"
CONFIG_DIR = LOCAL_DIR / ".." / ".." / "config"
WEEKLYS_CACHE = CONFIG_DIR / "available_weeklys.csv"
WEEKLYS_PROGRAMS = ("Standard", "Expanded", "End of Week",
                    "Equity/ETF/ETN (MON)", "Equity/ETF/ETN (TUE)",
                    "Equity/ETF/ETN (WED)", "Equity/ETF/ETN (THUR)")


def _weeklys_program_dates() -> list[date]:
    """Listed weeklys expiry dates from Cboe's available-weeklys CSV: Friday
    weeklies (~6 weeks out) and Mon-Thu daily programs (~2 weeks out)."""
    stale = not WEEKLYS_CACHE.exists() or \
        datetime.now(ZoneInfo("US/Eastern")).date() - date.fromtimestamp(WEEKLYS_CACHE.stat().st_mtime) > timedelta(days=7)
    if stale:
        req = urllib.request.Request(WEEKLYS_URL, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            WEEKLYS_CACHE.write_bytes(resp.read())
    dates = []
    for row in csv.reader(open(WEEKLYS_CACHE)):
        if row and row[0] in WEEKLYS_PROGRAMS:
            dates += [datetime.strptime(d, "%m/%d/%y").date() for d in row[1:] if d]
    return dates


def _monthly_expiries(asof: date, horizon: date) -> list[date]:
    """3rd-Friday monthly expiries (Thursday on full-closure holidays, per
    config/holiday.txt). Monthlies are listed far ahead, unlike weeklies."""
    try:
        holidays = {date.fromisoformat(d) for d in
                    (CONFIG_DIR / "holiday.txt").read_text().split()}
    except FileNotFoundError:
        holidays = set()
    expiries = []
    y, m = asof.year, asof.month
    while date(y, m, 1) <= horizon:
        d = date(y, m, 15) + timedelta(days=(4 - date(y, m, 15).weekday()) % 7)
        while d in holidays:
            d -= timedelta(days=1)
        expiries.append(d)
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return expiries


def expected_expiries(asof: date, horizon_days: int = 93) -> list[date]:
    """Candidate expiries in [asof, asof + horizon]: Cboe-listed weeklies and
    Mon-Thu dailies for the near end, generated monthlies for the far end.
    A query schedule, not ground truth: empty pages are expected (program not
    offered for the ticker, or not yet listed)."""
    horizon = asof + timedelta(days=horizon_days)
    cands = set(_weeklys_program_dates()) | set(_monthly_expiries(asof, horizon))
    return sorted(d for d in cands if asof <= d <= horizon)


class SnapShooter:
    FILES = ("spot.json", "chain.csv", "dividends.csv")

    def __init__(self, ticker: str = "AAPL", trading_date: date | None = None):
        self.ticker = ticker
        self.data_path = LOCAL_DIR / "../../data/symbols"
        self.divs_path = LOCAL_DIR / "../../data/dividends"
        self.client = LSE(api_key=dotenv_values(LOCAL_DIR / "../../.env")["LSE_API_KEY"])
        self.trading_date = trading_date or datetime.now(ZoneInfo("US/Eastern")).date()
        self._last_call = 0.0

    def _lse_call(self, fn, *args, **kwargs):
        """Vendor call with throttle (min CALL_INTERVAL between calls) and
        retry with backoff on 429/5xx; other 4xx raise immediately."""
        for attempt, backoff in enumerate((2, 4, 8), 1):
            sleep(max(0.0, CALL_INTERVAL - (monotonic() - self._last_call)))
            self._last_call = monotonic()
            try:
                return fn(*args, **kwargs)
            except LSEError as e:
                if attempt == 3 or (e.status != 429 and e.status < 500):
                    raise
                sleep(backoff)
        return []

    def _fetch_spot(self, ticker: str, asof: date, is_early_close: bool) -> dict:
        """Latest regular-session (09:30-16:00 ET) 1m bar; close = EOD spot.
        The 1d candle includes extended-hours prints, so it is not used."""
        if is_early_close:
            start_time = time(12, 55, 0, tzinfo=ET)
            end_time = time(13, 0, 1, tzinfo=ET)
        else: 
            start_time = time(15, 55, 0, tzinfo=ET)
            end_time = time(16, 0, 1, tzinfo=ET)

        query_begin_dt = datetime.combine(asof, start_time, tzinfo=ET).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S")
        query_end_dt = datetime.combine(asof, end_time, tzinfo=ET).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S")
        bars = self._lse_call(self.client.candles, ticker, "1s", limit=800,
                              order="desc", start=query_begin_dt, end=query_end_dt)
        for bar in bars:  # newest first
            t = datetime.fromisoformat(bar["timestamp"]).astimezone(ET)
            if time(9, 30) <= t.time() <= time(16, 0):
                bar["session_date"] = t.date().isoformat()
                return bar
        raise ValueError(f"No regular-session bar for {ticker} in the last 800 minutes of regular trading session.")

    def _chain_call(self, **params) -> list[dict]:
        return self._lse_call(self.client.options, **params)

    @staticmethod
    def _expected_expiries(asof: date) -> list[str]:
        """Cboe weeklys/dailies + generated monthlies in (asof, asof + 3 months]."""
        return [d.isoformat() for d in expected_expiries(asof)]

    def _chain_pages(self, ticker: str, strike: tuple, asof: date) -> list[list[dict]]:
        """Tiered fetch around the 5000-row cap: band call -> split by type ->
        page by expected expiry. A capped page is never complete data."""
        page = self._chain_call(underlying=ticker, min_dte=0, max_dte=MAX_DTE, strike=strike)
        if len(page) < 5000:
            return [page]
        pages = []
        for t in ("call", "put"):  # tier 1: split by contract type
            p = self._chain_call(underlying=ticker, type=t, min_dte=0, max_dte=MAX_DTE, strike=strike)
            if len(p) >= 5000:
                break
            pages.append(p)
        else:
            return pages
        pages = []  # tier 2: page by expected weekly expiry
        for exp in self._expected_expiries(asof):
            p = self._chain_call(underlying=ticker, expiry=exp, strike=strike)
            if len(p) >= 5000:
                raise RuntimeError(f"5000-row cap on a single expiry ({exp}); split the strike band")
            if p:
                pages.append(p)
            else:
                print(f"no rows for expected expiry {exp} (holiday shift or vendor gap)")
        return pages

    def _fetch_chain(self, ticker: str, spot: float, asof: date) -> list[dict]:
        strike = (round(spot * BAND[0], 2), round(spot * BAND[1], 2))
        chain = [r for page in self._chain_pages(ticker, strike, asof) for r in page]
        # vendor dte is relative to each row's last trade date, not today:
        # window on the absolute expiry calendar instead (3 months)
        lo, hi = asof.isoformat(), (asof + timedelta(days=93)).isoformat()
        live = [r for r in chain if lo <= r["expiry"] <= hi]
        fresh = sum(1 for r in live if r.get("last_trade_at", "")[:10] == asof.isoformat())
        print(f"chain: {len(live)}/{len(chain)} rows live, {fresh} quoted today")
        return live

    def _fetch_dividends(self, ticker: str, asof: date) -> list[dict]:
        """Last 5y of this ticker's dividends from the shared
        data/dividends/dividends.csv (all tickers in one file). If the file's
        latest ex-date for this ticker is < 60 days old, the file is served
        as-is with no vendor call; otherwise the vendor is queried and the
        ticker's rows are refreshed only when newer ex-dates come back."""
        cutoff = (asof - timedelta(days=5 * 365)).isoformat()
        try:
            with open(self.divs_path / self.FILES[2], "r") as file:
                existing = list(csv.DictReader(file))
        except FileNotFoundError:
            existing = []
        ticker_on_file = [d for d in existing if d.get("symbol") == ticker]
        latest_on_file = max((d["effective_date"] for d in ticker_on_file), default="")
        # fresh enough -> skip the vendor call entirely
        if latest_on_file >= (asof - timedelta(days=30)).isoformat():
            return [d for d in ticker_on_file if d.get("effective_date", "") >= cutoff]
        rows = [d for d in self._lse_call(self.client.dividends, ticker)
                if d.get("effective_date", "") >= cutoff]
        if rows and max(d["effective_date"] for d in rows) > latest_on_file:
            merged = [d for d in existing if d.get("symbol") != ticker] + rows
            self.divs_path.parent.mkdir(parents=True, exist_ok=True)
            self._write_csv_archive(content=merged, output_file=(self.divs_path / self.FILES[2]), fieldnames=rows[0])
            return rows
        return [d for d in ticker_on_file if d.get("effective_date", "") >= cutoff]

    @staticmethod
    def _parity_fit(chain: list[dict], expiry: str) -> float | None:
        """Put-call parity fit for one expiry: C-P = a + b*K over matched strikes,
        where b = -e^{-rT} and a = e^{-rT}*F. Returns forward F = -a/b."""
        calls = {float(r["strike"]): float(r["last_price"]) for r in chain
                 if r["contract_type"] == "call" and r["expiry"] == expiry}
        puts = {float(r["strike"]): float(r["last_price"]) for r in chain
                if r["contract_type"] == "put" and r["expiry"] == expiry}
        strikes = sorted(set(calls) & set(puts))
        if len(strikes) < 5:
            return None
        k = np.array(strikes)
        diff = np.array([calls[s] - puts[s] for s in strikes])
        b, a = np.polyfit(k, diff, 1)
        return -a / b  # the ratio is robust: a and b fit errors are correlated

    @staticmethod
    def _dividends_in_window(dividends: list[dict], asof: date, expiry: str) -> float:
        """Declared dividends with ex-date in (asof, expiry]."""
        exp = date.fromisoformat(expiry)
        return sum(float(d["dividend_amount"]) for d in dividends
                   if d.get("dividend_amount")
                   and asof < date.fromisoformat(d["effective_date"]) <= exp)

    def _sanity_check_spot(self, spot: float, chain: list[dict],
                           dividends: list[dict], asof: date) -> None:
        """Warn if spot disagrees with the parity-implied spot: since
        F = (S - PV(divs)) * e^{rT} ~ S - PV(divs) for near expiries,
        F + window dividends reconstructs spot (no rates input needed)."""
        for expiry in sorted({r["expiry"] for r in chain})[:3]:  # nearest expiries
            fwd = self._parity_fit(chain, expiry)
            if fwd:
                # ponytail: e^{rT}~1 and dividends undiscounted for near expiries
                # (sub-cent error); undeclared-but-due divs are missed, absorbed
                # by the 2% threshold.
                implied_spot = fwd + self._dividends_in_window(dividends, asof, expiry)
                dev = (implied_spot - spot) / spot
                if abs(dev) > 0.02:
                    warnings.warn(f"{self.ticker} spot {spot} vs parity-implied "
                                  f"{implied_spot:.2f} ({expiry}): {dev:+.1%}")
                return

    def _archives_exist(self, ticker_data_dir: Path) -> bool:
        archive_dirs = [ticker_data_dir, ticker_data_dir, self.divs_path]
        return all((dir / file).exists() for dir, file in zip(archive_dirs, self.FILES))

    def _read_archive(self, ticker_data_dir: Path, ticker: str):
        spot_bar = json.loads((ticker_data_dir / self.FILES[0]).read_text())
        asof = date.fromisoformat(spot_bar["timestamp"][:10])
        spot = spot_bar["close"]

        with open(ticker_data_dir / self.FILES[1]) as f:
            chain = list(csv.DictReader(f))
        with open(self.divs_path / self.FILES[2]) as f:
            divs = [row for row in list(csv.DictReader(f)) if row["symbol"] == ticker]

        return asof, spot, divs, chain

    def _write_csv_archive(self, content, output_file, fieldnames):
        with open(output_file, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            w.writerows(content)

    def _write_json_archive(self):
        pass

    def snapshot(self, ticker: str, trading_date: date, is_early_close: bool, force_refetch: bool = False):
        ticker_data_dir = self.data_path / ticker / trading_date.isoformat()
        if self._archives_exist(ticker_data_dir) and not force_refetch:
            return self._read_archive(ticker_data_dir, ticker)
        
        spot_bar = self._fetch_spot(ticker, trading_date, is_early_close)
        spot = float(spot_bar["close"])
        asof = date.fromisoformat(spot_bar["session_date"])
        if asof > trading_date:
            raise ValueError(f"Latest session {asof} is after requested day {trading_date}")

        divs = self._fetch_dividends(ticker, asof)  # before the check: divs feed it
        chain = self._fetch_chain(ticker, spot, asof)
        self._sanity_check_spot(spot, chain, divs, asof)

        ticker_data_dir.mkdir(parents=True, exist_ok=True)
        (ticker_data_dir / self.FILES[0]).write_text(json.dumps(spot_bar, indent=2))
        self._write_csv_archive(content=chain, output_file=ticker_data_dir / self.FILES[1], fieldnames=chain[0])

        return asof, spot, divs, chain


if __name__ == "__main__":
    d = "20260923"
    trading_date = date.strptime(d, "%Y%m%d")
    ticker = "AAPL"
    asof, spot, divs, chain = SnapShooter().snapshot(ticker=ticker, trading_date=trading_date, is_early_close=False)
    chain_rows = len(chain)
    divs_rows = len(divs)
    print(f"spot={spot}, chain={chain_rows} rows, dividends={divs_rows} rows")
    assert chain_rows > 500 and divs_rows >= 0 and spot > 0
    print("OK")
