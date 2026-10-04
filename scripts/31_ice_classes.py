"""
Step 3b (new plan): Classify river ice in every RCM scene and build the
"ice profile" (ice type by km from the lake) for each date.

Simple rule-based classifier (version 1)
----------------------------------------
Radar brightness of river ice depends on how rough it is:
  * rough / rubble ice (jammed blocks, ridged ice) scatters a lot of the
    radar signal back -> BRIGHT
  * smooth sheet ice and calm open water reflect it away -> DARK

1. Viewing-angle correction. The same surface looks brighter when the
   satellite looks more steeply. From the 2022 jam scenes (taken at 25-47
   degrees) the river got about ANGLE_SLOPE dB brighter per degree steeper,
   so every pixel is converted to how it would look at REF_ANGLE degrees:
       HH_35 = HH + ANGLE_SLOPE * (incidence_angle - REF_ANGLE)
2. HH_35 >= RUBBLE_DB                -> rough/rubble ice
3. HH_35 <  DARK_DB                  -> open water OR smooth ice:
       if spring melt has started (thawing degree-days since March 1 >=
       MELT_TDD, from step 2)        -> open water
       otherwise                     -> smooth sheet ice
4. anything in between               -> smooth sheet ice

Known limitation: smooth ice and calm water look alike to the radar (both
dark in HH and HV). The melt rule above is a stand-in; wind-roughened water
can also look like rough ice. The rubble-ice class - the one that matters
most for jam risk - is the most reliable.

Outputs
-------
data/processed/ice_classes/<scene>.tif    0 no data, 1 open water, 2 smooth ice, 3 rubble ice
data/processed/ice_profiles.csv           one row per scene per km of river
data/processed/ice_scene_summary.csv      one row per scene
outputs/ice_maps/profile_<year>.png       ice type by km and date for each spring
outputs/ice_maps/map_<scene>.png          map of the lower river (lake to km 20)

Run from the project folder:
    venv\\Scripts\\python.exe scripts\\31_ice_classes.py
"""

from pathlib import Path

import geopandas as gpd
import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap
from matplotlib.patches import Patch
import numpy as np
import pandas as pd
import rasterio

PROJECT_DIR = Path(__file__).resolve().parent.parent
CORRIDOR = PROJECT_DIR / "data" / "processed" / "corridor"
RIVER_PIXELS = CORRIDOR / "river_pixels.tif"
SCENES = CORRIDOR / "scenes"
DEGREE_DAYS = PROJECT_DIR / "data" / "processed" / "ice" / "daily_degree_days.csv"
TOWN_GAUGE = PROJECT_DIR / "data" / "raw" / "hydat" / "07OB001_daily.csv"
OUT_CLASSES = PROJECT_DIR / "data" / "processed" / "ice_classes"
OUT_FIGS = PROJECT_DIR / "outputs" / "ice_maps"

REF_ANGLE = 35.0       # degrees
ANGLE_SLOPE = 0.18     # dB per degree (measured from the 2022 jam scenes)
RUBBLE_DB = -13.0      # angle-corrected HH at or above this = rough/rubble ice
DARK_DB = -20.0        # angle-corrected HH below this = open water or smooth ice
MELT_TDD = 20.0        # thawing degree-days since March 1 after which dark = open water
JAM_ZONE_KM = 15       # lake up past the town: where jams flood Hay River
MIN_BIN_COVERAGE = 0.5  # a 1 km bin needs half its river pixels visible to count

NO_DATA, WATER, SMOOTH, RUBBLE = 0, 1, 2, 3
CLASS_NAMES = {WATER: "open water", SMOOTH: "smooth ice", RUBBLE: "rough/rubble ice"}
# Reference palette, fixed order: blue = water, aqua = smooth ice, orange = rubble.
CLASS_COLOURS = {WATER: "#2a78d6", SMOOTH: "#1baf7a", RUBBLE: "#eb6834"}
INK, MUTED, GRID, AXIS = "#0b0b0b", "#898781", "#e1e0d9", "#c3c2b7"


def thaw_on(degree_days, when):
    day = degree_days[degree_days["date"] == when.normalize()]
    return float(day["tdd"].iloc[0]) if len(day) else np.nan


def classify(hh, inc, melt_started):
    hh35 = hh + ANGLE_SLOPE * (inc - REF_ANGLE)
    out = np.full(hh.shape, NO_DATA, dtype=np.uint8)
    ok = np.isfinite(hh35)
    out[ok] = SMOOTH
    out[ok & (hh35 >= RUBBLE_DB)] = RUBBLE
    out[ok & (hh35 < DARK_DB)] = WATER if melt_started else SMOOTH
    return out, hh35


def style(ax):
    for side in ["top", "right"]:
        ax.spines[side].set_visible(False)
    for side in ["left", "bottom"]:
        ax.spines[side].set_color(AXIS)
    ax.tick_params(colors=MUTED)


def plot_year(year, profiles, scenes, gauge, path):
    p = profiles[profiles["year"] == year]
    s = scenes[scenes["year"] == year].sort_values("time")
    if s.empty:
        return
    fig, (ax, ax2) = plt.subplots(2, 1, figsize=(13, 8), sharex=True,
                                  gridspec_kw={"height_ratios": [3, 1]})
    width = pd.Timedelta(hours=10)
    for _, sc in s.iterrows():
        rows = p[(p["scene"] == sc["scene"]) & p["usable"]]
        for _, r in rows.iterrows():
            ax.bar(sc["time"], 1, bottom=r["km"], width=width,
                   color=CLASS_COLOURS[int(r["dominant_class"])], linewidth=0)
    ax.axhspan(0, JAM_ZONE_KM, color=GRID, alpha=0.35, zorder=0)
    ax.annotate("jam zone (lake to past town)", (s["time"].min(), JAM_ZONE_KM - 1.2),
                fontsize=9, color=MUTED)
    ax.set_ylim(0, 56)
    ax.set_ylabel("km upstream from Great Slave Lake", color=MUTED)
    ax.set_title(f"River ice from RCM, spring {year}: most common ice type in each km of river",
                 loc="left", color=INK)
    ax.legend(handles=[Patch(color=CLASS_COLOURS[c], label=CLASS_NAMES[c]) for c in CLASS_NAMES],
              frameon=False, loc="upper right", fontsize=9, ncol=3)
    style(ax)

    g = gauge[(gauge["date"] >= s["time"].min() - pd.Timedelta(days=5))
              & (gauge["date"] <= s["time"].max() + pd.Timedelta(days=5))]
    if len(g):
        ax2.plot(g["date"], g["level_m"], color=INK, linewidth=1.5)
        ax2.set_ylabel("town gauge\nlevel (m)", color=MUTED)
    else:
        ax2.text(0.5, 0.5, "no town gauge data for this period (HYDAT ends 2024)",
                 transform=ax2.transAxes, ha="center", color=MUTED)
        ax2.set_yticks([])
    ax2.grid(axis="y", color=GRID)
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    style(ax2)
    plt.tight_layout()
    plt.savefig(path, dpi=100)
    plt.close(fig)


def plot_map(name, classes, transform, path, km_limit=20):
    km = rasterio.open(RIVER_PIXELS).read(1)
    rows, cols = np.nonzero(np.isfinite(km) & (km <= km_limit))
    r0, r1, c0, c1 = rows.min() - 30, rows.max() + 30, cols.min() - 30, cols.max() + 30
    crop = classes[r0:r1, c0:c1].astype(float)
    crop[crop == NO_DATA] = np.nan
    fig, ax = plt.subplots(figsize=(8, 10))
    ax.set_facecolor("#f0efec")
    ax.imshow(crop, cmap=ListedColormap([CLASS_COLOURS[c] for c in (WATER, SMOOTH, RUBBLE)]),
              vmin=1, vmax=3, interpolation="nearest")
    ax.set_xticks([]); ax.set_yticks([])
    ax.set_title(f"River ice classes {name} (lake to km {km_limit})", loc="left", color=INK)
    ax.legend(handles=[Patch(color=CLASS_COLOURS[c], label=CLASS_NAMES[c]) for c in CLASS_NAMES],
              frameon=False, loc="lower left", fontsize=9)
    plt.tight_layout()
    plt.savefig(path, dpi=90)
    plt.close(fig)


if __name__ == "__main__":
    OUT_CLASSES.mkdir(parents=True, exist_ok=True)
    OUT_FIGS.mkdir(parents=True, exist_ok=True)
    with rasterio.open(RIVER_PIXELS) as src:
        river_km = src.read(1)
        channel = src.read(2)
        profile = src.profile
    is_river = np.isfinite(river_km)
    main = is_river & (channel == 1)
    km_bin = np.where(is_river, np.floor(river_km), -1).astype(int)
    bin_total = np.bincount(km_bin[main], minlength=60)
    degree_days = pd.read_csv(DEGREE_DAYS, parse_dates=["date"])
    gauge = pd.read_csv(TOWN_GAUGE, parse_dates=["date"]).dropna(subset=["level_m"])

    profile.update(count=1, dtype="uint8", nodata=NO_DATA)
    prof_rows, scene_rows = [], []
    for tif in sorted(SCENES.glob("*.tif")):
        with rasterio.open(tif) as src:
            hh, hv, inc = src.read(1), src.read(2), src.read(3)
            transform = src.transform
        when = pd.to_datetime(tif.stem[:15], format="%Y%m%d_%H%M%S")
        tdd = thaw_on(degree_days, when)
        melt_started = bool(tdd >= MELT_TDD) if np.isfinite(tdd) else when.month >= 5
        hh = np.where(np.isfinite(hv), hh, np.nan)          # need both channels
        classes, hh35 = classify(hh, inc, melt_started)
        classes[~is_river] = NO_DATA
        with rasterio.open(OUT_CLASSES / f"{tif.stem}.tif", "w", **profile) as dst:
            dst.write(classes, 1)

        seen = main & (classes != NO_DATA)
        for k in range(0, int(np.nanmax(river_km)) + 1):
            in_bin = seen & (km_bin == k)
            n = int(in_bin.sum())
            if n == 0 or bin_total[k] == 0:
                continue
            counts = {c: int((classes[in_bin] == c).sum()) for c in CLASS_NAMES}
            prof_rows.append({
                "scene": tif.stem, "time": when, "year": when.year, "km": k, "pixels": n,
                "coverage": round(n / bin_total[k], 2),
                "usable": n / bin_total[k] >= MIN_BIN_COVERAGE,
                "pct_water": round(100 * counts[WATER] / n, 1),
                "pct_smooth": round(100 * counts[SMOOTH] / n, 1),
                "pct_rubble": round(100 * counts[RUBBLE] / n, 1),
                "dominant_class": max(counts, key=counts.get),
                "median_hh35_db": round(float(np.median(hh35[in_bin])), 1),
            })

        jam = seen & (river_km <= JAM_ZONE_KM)
        all_seen = is_river & (classes != NO_DATA)
        jam_cov = jam.sum() / max((main & (river_km <= JAM_ZONE_KM)).sum(), 1)
        scene_rows.append({
            "scene": tif.stem, "time": when, "year": when.year,
            "tdd_since_mar1": round(tdd, 1) if np.isfinite(tdd) else None,
            "melt_started": melt_started,
            "km_visible_min": float(np.nanmin(river_km[all_seen])) if all_seen.any() else None,
            "km_visible_max": float(np.nanmax(river_km[all_seen])) if all_seen.any() else None,
            "jam_zone_coverage": round(float(jam_cov), 2),
            "jam_zone_pct_rubble": round(100 * float((classes[jam] == RUBBLE).mean()), 1) if jam.any() else None,
            "jam_zone_pct_water": round(100 * float((classes[jam] == WATER).mean()), 1) if jam.any() else None,
            **{f"pct_{CLASS_NAMES[c].split('/')[-1].split()[0]}": round(100 * float((classes[all_seen] == c).mean()), 1)
               for c in CLASS_NAMES},
        })
        print(f"{tif.stem}: TDD {tdd:5.1f} -> "
              + ", ".join(f"{CLASS_NAMES[c]} {100 * (classes[all_seen] == c).mean():4.1f}%" for c in CLASS_NAMES)
              + (f" | jam zone rubble {scene_rows[-1]['jam_zone_pct_rubble']}% "
                 f"(zone {100 * jam_cov:.0f}% visible)" if jam.any() else ""))

    profiles = pd.DataFrame(prof_rows)
    scenes = pd.DataFrame(scene_rows)
    profiles.to_csv(PROJECT_DIR / "data" / "processed" / "ice_profiles.csv", index=False)
    scenes.to_csv(PROJECT_DIR / "data" / "processed" / "ice_scene_summary.csv", index=False)

    for year in sorted(scenes["year"].unique()):
        plot_year(year, profiles, scenes, gauge, OUT_FIGS / f"profile_{year}.png")
    best = scenes[scenes["jam_zone_coverage"] >= 0.8]
    for name in best["scene"]:
        cls = rasterio.open(OUT_CLASSES / f"{name}.tif").read(1)
        plot_map(name, cls, None, OUT_FIGS / f"map_{name}.png")
    print(f"\nProfiles: data/processed/ice_profiles.csv; charts in {OUT_FIGS}")
