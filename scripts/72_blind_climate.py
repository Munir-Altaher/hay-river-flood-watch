"""
Blind test, step 3: daily air temperatures and thawing degree-days for each site.

Station choice (approved): the NEAREST Environment and Climate Change Canada
station location whose daily mean temperature is complete enough for every
spring 2021-2026 (March 1 to June 30: at most MAX_MISSING missing days per
spring). As for Hay River (script 13), several station IDs at the same place
are joined into one record (most complete first, gaps filled from the others).
Short gaps (up to 3 days) are filled with a straight line, like Hay River.

Thawing degree-days use EXACTLY the Hay River rule (script 20): sum of daily
mean temperatures above 0 C, counted from March 1. Melt has started once this
reaches 20 (MELT_TDD in scripts 31 and 41). Nothing is adjusted for the new sites.

Output: data/processed/blind/<site>/thaw.csv (date, tmean_c, tdd, station)

Run from the project folder:
    venv\\Scripts\\python.exe scripts\\72_blind_climate.py
"""

import math
from pathlib import Path

import numpy as np
import pandas as pd
import requests

PROJECT_DIR = Path(__file__).resolve().parent.parent
OUT = PROJECT_DIR / "data" / "processed" / "blind"
API = "https://api.weather.gc.ca/collections"
SITES = {"fort_simpson": (-121.3543, 61.8631), "albany": (-81.66, 52.25)}
YEARS = range(2021, 2027)
MAX_MISSING = 5
SEARCH_DEG = 3.0
GROUP_KM = 5             # stations this close together count as one place (e.g. an airport)


def km(a, b):
    lon1, lat1, lon2, lat2 = map(math.radians, [a[0], a[1], b[0], b[1]])
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


def daily(climate_id):
    rows, offset = [], 0
    while True:
        r = requests.get(f"{API}/climate-daily/items", params={
            "CLIMATE_IDENTIFIER": climate_id, "datetime": "2021-03-01/2026-06-30",
            "limit": 10000, "offset": offset, "f": "json"}, timeout=300)
        r.raise_for_status()
        f = r.json()["features"]
        rows += [x["properties"] for x in f]
        if len(f) < 10000:
            break
        offset += 10000
    if not rows:
        return None
    d = pd.DataFrame(rows)
    d["date"] = pd.to_datetime(d["LOCAL_DATE"]).dt.normalize()
    d["tmean_c"] = d["MEAN_TEMPERATURE"].fillna((d["MIN_TEMPERATURE"] + d["MAX_TEMPERATURE"]) / 2)
    return d[["date", "tmean_c"]].drop_duplicates("date").set_index("date")["tmean_c"]


if __name__ == "__main__":
    for site, (lon, lat) in SITES.items():
        st = requests.get(f"{API}/climate-stations/items", params={
            "bbox": f"{lon - SEARCH_DEG},{lat - SEARCH_DEG / 2},{lon + SEARCH_DEG},{lat + SEARCH_DEG / 2}",
            "limit": 200, "f": "json"}, timeout=120).json()["features"]
        cands = []
        for f in st:
            p = f["properties"]
            last = p.get("DLY_LAST_DATE")
            if not last or last[:4] < "2026":
                continue
            c = f["geometry"]["coordinates"]
            cands.append((km((lon, lat), c), p["CLIMATE_IDENTIFIER"], p["STATION_NAME"]))
        cands.sort()
        print(f"\n===== {site}: {len(cands)} stations with daily data into 2026")
        # Group stations at the same place (within GROUP_KM of each other), nearest place first.
        # Like Hay River (script 13), stations at one place are joined into one record:
        # the most complete station first, its gaps filled from the others.
        groups = []
        for c in cands:
            for g in groups:
                if abs(g[0][0] - c[0]) <= GROUP_KM:
                    g.append(c)
                    break
            else:
                groups.append([c])
        chosen = None
        for g in groups:
            series = []
            for dist, cid, name in g:
                t = daily(cid)
                if t is not None:
                    miss = sum(int(t.reindex(pd.date_range(f"{y}-03-01", f"{y}-06-30")).isna().sum()) for y in YEARS)
                    series.append((miss, cid, name, dist, t))
            if not series:
                continue
            series.sort()
            merged = series[0][4]
            for s_ in series[1:]:
                merged = merged.combine_first(s_[4])
            missing = {y: int(merged.reindex(pd.date_range(f"{y}-03-01", f"{y}-06-30")).isna().sum()) for y in YEARS}
            ok = all(m <= MAX_MISSING for m in missing.values())
            label = " + ".join(f"{n} ({c})" for _, c, n, _, _ in series)
            print(f"  {label}, {g[0][0]:.0f} km: missing days per spring {missing} -> {'OK' if ok else 'gaps'}")
            if ok:
                chosen = (" + ".join(c for _, c, _, _, _ in series), series[0][2], g[0][0], merged)
                break
        if not chosen:
            print("  no station with a complete record found")
            continue
        cid, name, dist, t = chosen
        rows = []
        for y in YEARS:
            days = pd.date_range(f"{y}-03-01", f"{y}-06-30")
            s = t.reindex(days).interpolate(limit=3, limit_area="inside")
            tdd = np.cumsum(np.clip(s.fillna(0).to_numpy(), 0, None))
            rows.append(pd.DataFrame({"date": days, "tmean_c": s.to_numpy(), "tdd": tdd}))
        out = pd.concat(rows, ignore_index=True)
        out["station"] = f"{name} ({cid}), {dist:.0f} km away"
        (OUT / site).mkdir(parents=True, exist_ok=True)
        out.to_csv(OUT / site / "thaw.csv", index=False)
        hit = out[out["tdd"] >= 20]
        melt = hit.groupby(hit["date"].dt.year)["date"].min().dt.strftime("%m-%d").to_dict()
        print(f"  using {name}; melt (20 thawing degree-days) reached on: {melt}")
