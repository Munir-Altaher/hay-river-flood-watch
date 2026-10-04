"""
Step 1c (new plan): Download daily river gauge data (Water Survey of Canada,
HYDAT) for the Hay River gauges you confirmed.

Source: Environment and Climate Change Canada's public data API
(api.weather.gc.ca), collection "hydrometric-daily-mean", which serves the
official HYDAT daily values together with their data flags.

Stations:
    07OB001  Hay River near Hay River       - town gauge (level + discharge)
    07OB003  Hay River near Meander River   - upstream discharge (Alberta)
    07OB008  Hay River near Alta/NWT border - upstream discharge (recent years)
    07OB002  Great Slave Lake at Hay River  - lake level at the river mouth

About the flags (HYDAT "symbols"):
    Ice Conditions - the flow was ESTIMATED because ice was on the river
                     (common in winter and at breakup)
    Estimated      - estimated for another reason
    Partial Day    - the daily value uses less than a full day of readings
Water levels at 07OB001 are measured even under ice; flows at breakup are
mostly estimated. Levels are in each station's own local datum ("assumed
datum"), not height above sea level.

Output: data/raw/hydat/<station>_daily.csv
        columns: date, level_m, discharge_m3s, level_flag, discharge_flag

Run from the project folder:
    venv\\Scripts\\python.exe scripts\\12_get_gauges.py
"""

from pathlib import Path

import pandas as pd
import requests

PROJECT_DIR = Path(__file__).resolve().parent.parent
OUT_DIR = PROJECT_DIR / "data" / "raw" / "hydat"
API = "https://api.weather.gc.ca/collections/hydrometric-daily-mean/items"
PAGE = 10000

STATIONS = {
    "07OB001": "Hay River near Hay River (town)",
    "07OB003": "Hay River near Meander River (upstream)",
    "07OB008": "Hay River near Alta/NWT boundary (upstream)",
    "07OB002": "Great Slave Lake at Hay River (lake)",
}


def download(station):
    rows, offset = [], 0
    while True:
        r = requests.get(API, params={"STATION_NUMBER": station, "limit": PAGE, "offset": offset,
                                      "sortby": "DATE", "f": "json"}, timeout=300)
        r.raise_for_status()
        features = r.json()["features"]
        rows += [f["properties"] for f in features]
        if len(features) < PAGE:
            return rows
        offset += PAGE


if __name__ == "__main__":
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for station, label in STATIONS.items():
        print(f"Downloading {station} {label} ...")
        df = pd.DataFrame(download(station))
        df = df.rename(columns={"DATE": "date", "LEVEL": "level_m", "DISCHARGE": "discharge_m3s",
                                "LEVEL_SYMBOL_EN": "level_flag",
                                "DISCHARGE_SYMBOL_EN": "discharge_flag"})
        df = df[["date", "level_m", "discharge_m3s", "level_flag", "discharge_flag"]]
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date")
        df.to_csv(OUT_DIR / f"{station}_daily.csv", index=False)
        lvl = df.dropna(subset=["level_m"])["date"]
        q = df.dropna(subset=["discharge_m3s"])["date"]
        print(f"  {len(df):,} days | level {lvl.min():%Y}-{lvl.max():%Y} ({len(lvl):,} days)"
              if len(lvl) else f"  {len(df):,} days | no level data", end="")
        print(f" | discharge {q.min():%Y}-{q.max():%Y} ({len(q):,} days)" if len(q) else " | no discharge")
    print(f"Saved to {OUT_DIR}")
