"""Cboe US options holiday calendar -> holiday.txt, refreshed once a year.

Downloads the official Cboe options holiday CSV, keeps full closures (early
closes like Thanksgiving Friday are still trading days, just shorter), and
writes holiday.txt. On later runs the file is reused as-is unless the stored
calendar year differs from the current year — i.e. the download runs at most
once a year.
"""
import csv
import sys
import urllib.request
from datetime import date, datetime
from zoneinfo import ZoneInfo
from pathlib import Path


CBOE_URL = "https://www.cboe.com/us/options/holidays/csv/"
LOCAL_DIR = Path(__file__).parent.resolve()
CONFIG_PATH = LOCAL_DIR / ".." / ".." / "config"
HOLIDAYS_PATH = CONFIG_PATH / "holiday.txt"
EARLYCLOSE_PATH = CONFIG_PATH / "earlyclose.txt"


def download_holiday_schedule() -> csv.DictReader:
    req = urllib.request.Request(CBOE_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        lines = resp.read().decode().splitlines()
    rows = csv.DictReader(l for l in lines if not l.startswith("#"))
    return rows

def parse_holidays(holiday_schedule: csv.DictReader) -> tuple[list, list]:
    holiday_all, early_close = [], []
    for holiday in holiday_schedule:
        if holiday["Regular Trading Hours"] == "None":
            holiday_all.append(date.fromisoformat(holiday["Date"]))
        else:
            early_close.append(date.fromisoformat(holiday["Date"]))
    return holiday_all, early_close

def save_holiday_files(schedule: list, path: Path):
    path.write_text("".join(f"{day}\n" for day in schedule))

def read_holiday_file(path: Path) -> tuple[int, list[date]]:
    holidays = path.read_text().splitlines()
    holidays_dt = [datetime.strptime(hols, "%Y-%m-%d").date() for hols in holidays]
    year = datetime.strptime(holidays[0], "%Y-%m-%d").replace(tzinfo=ZoneInfo("US/Eastern")).year
    return year, holidays_dt

def fetch_holidays() -> tuple[list[date], list[date]]:
    Path.mkdir(CONFIG_PATH, exist_ok=True)

    schedule = download_holiday_schedule()
    holiday_all, earlyclose_all = parse_holidays(schedule)
    for days, file_path in zip([holiday_all, earlyclose_all], [HOLIDAYS_PATH, EARLYCLOSE_PATH]):
        save_holiday_files(days, path=file_path)

    return holiday_all, earlyclose_all
    
def verify_holiday_files() -> tuple[list[date], list[date]]:
    """Full-closure holidays for the current year, from cache or Cboe."""
    current_year = datetime.now(tz=ZoneInfo("US/Eastern")).year
    if HOLIDAYS_PATH.exists() and EARLYCLOSE_PATH.exists():
        year, holidays = read_holiday_file(HOLIDAYS_PATH)
        if year == current_year:
            _, early_close = read_holiday_file(EARLYCLOSE_PATH)
            return holidays, early_close
    holidays, earlyclose = fetch_holidays()
    return holidays, earlyclose

def is_holiday(input_date: date):
    holidays, early_close = verify_holiday_files()
    if input_date in holidays:
        print(f"{input_date} is holiday. Exiting...", file=sys.stderr)
        return 1
    if input_date in early_close:
        print(f"{input_date} is early close. Continuing...", file=sys.stderr)
        return 2
    return 0

def is_weekend(input_date: date) -> bool:
    return input_date.weekday() > 4

def holiday_weekend_check(input_date: date):
    if is_weekend(input_date):
        print(f"{input_date} is a weekend. Exiting...", file=sys.stderr)
        sys.exit(1)
    schedule_mark = is_holiday(input_date)
    if schedule_mark == 1:
        sys.exit(1)
    return schedule_mark

if __name__ == "__main__":
    def convert_datetime(input_date: int | str) -> date:
        output_datetime = datetime.strptime(str(input_date), "%Y%m%d"
                                            ).replace(tzinfo=ZoneInfo("US/Eastern"))
        return output_datetime.date()

    d = 20261224
    converted_date = convert_datetime(d)
    print(converted_date)
    schedule_mark = holiday_weekend_check(input_date=converted_date)
    print(schedule_mark)