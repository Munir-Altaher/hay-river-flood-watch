"""
Step 4a (new plan): Breakup history - one row per spring at the town gauge.

Source: GNWT (2025) "Kátł'odeh (Hay River) Flood Hazard Mapping Study -
Summary Report", Table 16 (peak spring breakup at WSC #07OB001 Hay River
near Hay River): date, INSTANTANEOUS peak water level in metres above sea
level (Geodetic Survey of Canada datum, local 1985 adjustment, ~CGVD28),
peak discharge and breakup type, 1964-2023. Its flood-event table (Section
4.x) lists the years with documented flooding/evacuations in the town.

This script:
  1. reads Table 16 from the report text (data/raw/docs/...txt),
  2. works out the offset between HYDAT's daily "assumed datum" levels and
     the report's sea-level elevations (needed to use daily HYDAT data,
     e.g. for 2024 and for the day-by-day 2022 replay),
  3. writes data/processed/risk/breakup_history.csv.

Run from the project folder:
    venv\\Scripts\\python.exe scripts\\40_breakup_history.py
"""

import re
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_DIR = Path(__file__).resolve().parent.parent
REPORT_TXT = PROJECT_DIR / "data" / "raw" / "docs" / "gnwt_hay_river_flood_hazard_summary_2025.txt"
TOWN_GAUGE = PROJECT_DIR / "data" / "raw" / "hydat" / "07OB001_daily.csv"
OUT = PROJECT_DIR / "data" / "processed" / "risk" / "breakup_history.csv"

# Years with documented flooding / evacuations in the town (GNWT 2025, flood
# history table): 1951, 1963, 1974, 1985, 1992, 2003, 2008, 2022.
GNWT_FLOOD_YEARS = [1951, 1963, 1974, 1985, 1992, 2003, 2008, 2022]
ROW = re.compile(
    r"^(?P<year>(19|20)\d\d) (?P<date>\d{4}-\d\d-\d\d \d{1,2}:\d\d|ND) (?P<level>\d{3}\.\d+|ND) "
    r"(?P<q>[\d,]+|ND) (?P<type>Ice Run|Ice Jam|Thermal|ND)")

if __name__ == "__main__":
    text = REPORT_TXT.read_text(encoding="utf-8")
    start = text.index("Table 16 Peak Spring Breakup Summary – #07OB001")
    end = text.index("Table 17 # 07OB002")
    rows = []
    for line in text[start:end].splitlines():
        m = ROW.match(line.strip())
        if m:
            rows.append({
                "year": int(m["year"]),
                "peak_time": None if m["date"] == "ND" else m["date"],
                "peak_level_m": None if m["level"] == "ND" else float(m["level"]),
                "peak_q_m3s": None if m["q"] == "ND" else float(m["q"].replace(",", "")),
                "breakup_type": None if m["type"] == "ND" else m["type"],
            })
    table = pd.DataFrame(rows).drop_duplicates("year").set_index("year").sort_index()
    print(f"Table 16: {len(table)} springs ({table.index.min()}-{table.index.max()}), "
          f"{table['peak_level_m'].notna().sum()} with a peak level")

    # --- HYDAT daily (assumed datum) vs report (sea level) -------------------
    g = pd.read_csv(TOWN_GAUGE, parse_dates=["date"]).dropna(subset=["level_m"])
    spring = g[g["date"].dt.month.isin([4, 5, 6])]
    daily_max = spring.groupby(spring["date"].dt.year)["level_m"].max()
    both = table.join(daily_max.rename("hydat_daily_max"), how="inner").dropna(
        subset=["peak_level_m", "hydat_daily_max"])
    diff = both["peak_level_m"] - both["hydat_daily_max"]
    # The instantaneous peak is always a bit above the daily mean (jams peak
    # fast), so the smallest differences are closest to the true datum offset.
    offset = float(diff.quantile(0.1))
    print(f"Report peak minus HYDAT daily max, {len(diff)} years: "
          f"min {diff.min():.2f}, 10th pct {offset:.2f}, median {diff.median():.2f}, max {diff.max():.2f} m")
    print(f"Using HYDAT-to-sea-level offset of {offset:.2f} m "
          "(daily levels converted this way are slightly LOW at sharp ice-jam peaks)")

    # 2024 is not in Table 16: use HYDAT daily max + offset, flagged.
    for year in daily_max.index:
        if year not in table.index or pd.isna(table.loc[year, "peak_level_m"]):
            table.loc[year, "peak_level_m"] = round(daily_max[year] + offset, 3)
            table.loc[year, "level_source"] = "HYDAT daily max + offset"
    table["level_source"] = table["level_source"].fillna("GNWT Table 16 (instantaneous)")
    table["hydat_daily_max"] = daily_max
    table["documented_flood"] = table.index.isin(GNWT_FLOOD_YEARS)
    table.attrs["offset"] = offset

    OUT.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(OUT)
    (OUT.parent / "hydat_datum_offset.txt").write_text(f"{offset:.3f}\n")

    lv = table.dropna(subset=["peak_level_m"])
    print(f"\nPeak levels: median {lv['peak_level_m'].median():.2f} m, "
          f"range {lv['peak_level_m'].min():.2f}-{lv['peak_level_m'].max():.2f} m")
    print("Documented flood years and their peak level at the gauge:")
    for y in GNWT_FLOOD_YEARS:
        lvl = table.loc[y, "peak_level_m"] if y in table.index else None
        rank = (lv["peak_level_m"] > lvl).sum() + 1 if lvl and not pd.isna(lvl) else None
        print(f"  {y}: {lvl if lvl and not pd.isna(lvl) else 'no gauge peak'}"
              + (f" (rank {rank} of {len(lv)})" if rank else "")
              + (f", {table.loc[y, 'breakup_type']}" if y in table.index else ""))
    top = lv.sort_values("peak_level_m", ascending=False).head(12)
    print("\nHighest 12 peaks:", ", ".join(f"{y} {r.peak_level_m:.2f}{'*' if r.documented_flood else ''}"
                                         for y, r in top.iterrows()), "(* = documented flood)")
    print(f"Saved {OUT}")
