"""
Step 1d (new plan): Download daily weather for Hay River (Environment and
Climate Change Canada historical climate data) and join the stations into
one continuous record.

The Hay River airport weather station has changed ID over the years, so we
combine several, in order of preference:
    2202400  HAY RIVER A        1943-2014
    2202401  HAY RIVER A        2014-today
    2202402  HAY RIVER CLIMATE  2003-today  (automatic; fills gaps)
    2202403  HAY RIVER A        2018-today  (automatic; fills gaps)
For each day we use the first station that has a temperature. If a day has
only a min and max, the mean is (min + max) / 2. Gaps of up to 3 days are
filled by drawing a straight line between neighbouring days; longer gaps
are left empty and reported.

Output: data/raw/climate/hay_river_daily.csv
    date, tmean_c, tmin_c, tmax_c, precip_mm, snow_cm, snow_on_ground_cm,
    source_station, filled (True if the temperature was gap-filled)

Run from the project folder:
    venv\\Scripts\\python.exe scripts\\13_get_climate.py
"""

from pathlib import Path

import pandas as pd
import requests

PROJECT_DIR = Path(__file__).resolve().parent.parent
OUT_DIR = PROJECT_DIR / "data" / "raw" / "climate"
API = "https://api.weather.gc.ca/collections/climate-daily/items"
PAGE = 10000
STATIONS = ["2202400", "2202401", "2202402", "2202403"]   # order of preference
MAX_FILL_DAYS = 3


def download(climate_id):
    rows, offset = [], 0
    while True:
        r = requests.get(API, params={"CLIMATE_IDENTIFIER": climate_id, "limit": PAGE,
                                      "offset": offset, "sortby": "LOCAL_DATE", "f": "json"},
                         timeout=300)
        r.raise_for_status()
        features = r.json()["features"]
        rows += [f["properties"] for f in features]
        if len(features) < PAGE:
            return pd.DataFrame(rows)
        offset += PAGE


if __name__ == "__main__":
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    parts = []
    for cid in STATIONS:
        print(f"Downloading station {cid} ...")
        d = download(cid)
        d = pd.DataFrame({
            "date": pd.to_datetime(d["LOCAL_DATE"]).dt.normalize(),
            "tmean_c": d["MEAN_TEMPERATURE"], "tmin_c": d["MIN_TEMPERATURE"],
            "tmax_c": d["MAX_TEMPERATURE"], "precip_mm": d["TOTAL_PRECIPITATION"],
            "snow_cm": d["TOTAL_SNOW"], "snow_on_ground_cm": d["SNOW_ON_GROUND"],
        })
        d["tmean_c"] = d["tmean_c"].fillna((d["tmin_c"] + d["tmax_c"]) / 2)
        d["source_station"] = cid
        d.to_csv(OUT_DIR / f"station_{cid}_daily.csv", index=False)
        print(f"  {len(d):,} days, {d['date'].min():%Y-%m-%d} to {d['date'].max():%Y-%m-%d}, "
              f"{d['tmean_c'].notna().sum():,} with temperature")
        parts.append(d)

    # Stack the stations, keep the most-preferred one that has a temperature each day.
    stacked = pd.concat(parts)
    stacked["rank"] = stacked["source_station"].map({c: i for i, c in enumerate(STATIONS)})
    stacked = stacked.sort_values(["date", "rank"])
    with_temp = stacked[stacked["tmean_c"].notna()].drop_duplicates("date")
    without = stacked[~stacked["date"].isin(with_temp["date"])].drop_duplicates("date")
    merged = pd.concat([with_temp, without]).drop(columns="rank").sort_values("date")

    # Put every calendar day in, then fill short gaps.
    full = pd.DataFrame({"date": pd.date_range(merged["date"].min(), merged["date"].max())})
    merged = full.merge(merged, on="date", how="left")
    missing = merged["tmean_c"].isna()
    merged["tmean_c"] = merged["tmean_c"].interpolate(limit=MAX_FILL_DAYS, limit_area="inside")
    merged["filled"] = missing & merged["tmean_c"].notna()
    merged.to_csv(OUT_DIR / "hay_river_daily.csv", index=False)

    print(f"\nCombined record: {merged['date'].min():%Y-%m-%d} to {merged['date'].max():%Y-%m-%d}")
    print("Days from each station:", merged["source_station"].value_counts().to_dict())
    print(f"Gap-filled days: {merged['filled'].sum()}, still missing: {merged['tmean_c'].isna().sum()}")

    # Report missing days per winter (Oct 1 - May 31), labelled by the spring year.
    m = merged.assign(season=merged["date"].dt.year + (merged["date"].dt.month >= 10))
    winter = m[(m["date"].dt.month >= 10) | (m["date"].dt.month <= 5)]
    gaps = winter.groupby("season")["tmean_c"].apply(lambda s: s.isna().sum())
    bad = gaps[gaps > 0]
    print("Winters (by spring year) with missing temperature days:",
          bad.to_dict() if len(bad) else "none")
    print(f"Saved to {OUT_DIR / 'hay_river_daily.csv'}")
