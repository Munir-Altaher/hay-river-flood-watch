"""
Step 1g: Download recent gauge data that is not yet in HYDAT (2025 onward).

HYDAT (script 12) ends in 2024. The Water Office keeps about 18 months of
real-time readings (every 5 minutes, marked "Provisional" or "Final"); this
script downloads them for our three gauges and turns them into daily averages
in the same format as script 12, so the dashboard can show 2025 and 2026.

Note: provisional data can still be corrected by the Water Survey of Canada.

Output: data/raw/hydat/<station>_daily_recent.csv
    date, level_m, discharge_m3s, level_flag, discharge_flag

Run from the project folder:
    venv\\Scripts\\python.exe scripts\\16_get_gauges_recent.py
"""

import io
from pathlib import Path

import pandas as pd
import requests

PROJECT_DIR = Path(__file__).resolve().parent.parent
OUT_DIR = PROJECT_DIR / "data" / "raw" / "hydat"
URL = "https://wateroffice.ec.gc.ca/services/real_time_data/csv/inline"
STATIONS = ["07OB001", "07OB002", "07OB003"]
START = pd.Timestamp("2025-01-01")
CHUNK_DAYS = 60          # the service is happier with smaller requests


def download(station, start, end):
    r = requests.get(URL, params={"stations[]": station, "parameters[]": ["46", "47"],
                                  "start_date": f"{start:%Y-%m-%d} 00:00:00",
                                  "end_date": f"{end:%Y-%m-%d} 23:59:59"}, timeout=300)
    r.raise_for_status()
    if not r.text.strip():
        return pd.DataFrame()
    df = pd.read_csv(io.StringIO(r.text))
    df.columns = [c.strip().split("/")[0].strip() for c in df.columns]
    return df


if __name__ == "__main__":
    end = pd.Timestamp.today().normalize()
    for station in STATIONS:
        parts = []
        t = START
        while t <= end:
            parts.append(download(station, t, min(t + pd.Timedelta(days=CHUNK_DAYS - 1), end)))
            t += pd.Timedelta(days=CHUNK_DAYS)
        raw = pd.concat([p for p in parts if len(p)])
        cols = {c.lower(): c for c in raw.columns}
        date_col = next(c for c in raw.columns if "date" in c.lower())
        param_col = next(c for c in raw.columns if "parameter" in c.lower())
        value_col = next(c for c in raw.columns if "value" in c.lower() and "qualifier" not in c.lower())
        raw["date"] = pd.to_datetime(raw[date_col], utc=True).dt.tz_convert(None).dt.normalize()
        daily = raw.pivot_table(index="date", columns=param_col, values=value_col, aggfunc="mean")
        out = pd.DataFrame({
            "date": daily.index,
            "level_m": daily.get(46),
            "discharge_m3s": daily.get(47),
            "level_flag": "Provisional (real-time)",
            "discharge_flag": "Provisional (real-time)",
        })
        out.to_csv(OUT_DIR / f"{station}_daily_recent.csv", index=False)
        lv, q = out["level_m"].notna().sum(), out["discharge_m3s"].notna().sum() if "discharge_m3s" in out else 0
        print(f"{station}: {len(out)} days {out['date'].min():%Y-%m-%d} to {out['date'].max():%Y-%m-%d} "
              f"({lv} with level, {q} with flow)")
