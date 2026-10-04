"""
Step 3c (new plan): River ice classification VERSION 2 - change since late winter.

Why: version 1 (script 31) judged each scene on brightness alone, so
  * a winter ice cover that froze in rough looked the same as a breakup jam,
  * scenes taken from different satellite beams/directions disagreed.
Version 2 compares every spring scene with what the same river pixel looked
like in LATE WINTER (before melt), so rough-but-stationary ice is not
mistaken for a jam, and look-direction effects mostly cancel out.

Late-winter reference (per spring, per pixel)
---------------------------------------------
Candidates: scenes from the same spring taken before melt really started
(thawing degree-days since March 1 below REF_MAX_TDD) and before the scene
being classified. Each pixel takes its value from the best candidate that
covers it, in this order:
    quality 1  same beam AND same pass direction (identical geometry)
    quality 2  same pass direction, viewing angle within ANGLE_MATCH_DEG
    quality 3  any other pre-melt scene that spring (switched off by default:
               USE_OTHER_PASS = False, see below)
Brightness is compared after the viewing-angle correction from version 1
(HH_35 = HH + ANGLE_SLOPE * (angle - 35)); for quality 1 that correction
cancels out exactly.

Classes
-------
  1 open water        - melt has started and the pixel is now dark and at
                        least CHANGE_DB darker than in late winter (ice gone),
                        or extremely dark (below VERY_DARK_DB)
  2 smooth ice cover  - no big change; late-winter ice there was smooth
  3 rough ice cover   - no big change; late-winter ice there was rough
  4 new rubble/moving - at least CHANGE_DB brighter than late winter AND bright
                        now: ice has broken up / piled up since winter (jams)
  255 unclassified    - no late-winter reference covers this pixel
Scenes taken before melt (they ARE late winter) get classes 2/3 only.

Known limitation: if the winter ice was smooth (dark) and is replaced by
calm open water (also dark), nothing changes on the radar - that pixel stays
"smooth ice cover". Ice-off is only detected where winter ice was rough.

Outputs
-------
data/processed/ice_classes_v2/<scene>.tif   classes above
data/processed/ice_classes_v2/<scene>_refquality.tif   1/2/3 per pixel (0 = none)
data/processed/ice_profiles_v2.csv          per scene per km
data/processed/ice_scene_summary_v2.csv     per scene (jam-zone numbers)
outputs/ice_maps/v2_profile_<year>.png, v2_map_<scene>.png

Run from the project folder:
    venv\\Scripts\\python.exe scripts\\32_ice_change.py
"""

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap
from matplotlib.patches import Patch
import numpy as np
import pandas as pd
import rasterio
from scipy.ndimage import median_filter

PROJECT_DIR = Path(__file__).resolve().parent.parent
CORRIDOR = PROJECT_DIR / "data" / "processed" / "corridor"
RIVER_PIXELS = CORRIDOR / "river_pixels.tif"
SCENES = CORRIDOR / "scenes"
DEGREE_DAYS = PROJECT_DIR / "data" / "processed" / "ice" / "daily_degree_days.csv"
TOWN_GAUGE = PROJECT_DIR / "data" / "raw" / "hydat" / "07OB001_daily.csv"
OUT_CLASSES = PROJECT_DIR / "data" / "processed" / "ice_classes_v2"
OUT_FIGS = PROJECT_DIR / "outputs" / "ice_maps"

REF_ANGLE, ANGLE_SLOPE = 35.0, 0.18   # same viewing-angle correction as version 1
RUBBLE_DB = -13.0       # angle-corrected HH at/above this = rough ice
DARK_DB = -17.0         # "dark now" for the ice-gone test
VERY_DARK_DB = -22.0    # this dark after melt = open water even without a change
CHANGE_DB = 3.0         # change since late winter that counts as real
MELT_TDD = 20.0         # thawing degree-days since Mar 1: melt has started
REF_MAX_TDD = 35.0      # scenes before this much thaw can be late-winter references
                        # (breakup at the town gauge comes at ~49-87, see step 2)
ANGLE_MATCH_DEG = 10.0
USE_OTHER_PASS = False  # comparing ascending with descending passes proved unreliable
                        # (e.g. 2024-04-18 vs its neighbours), so those pixels stay unclassified
JAM_ZONE_KM = 15
MIN_BIN_COVERAGE = 0.5

NO_DATA, WATER, SMOOTH, ROUGH, RUBBLE, UNCLASSIFIED = 0, 1, 2, 3, 4, 255
CLASS_NAMES = {WATER: "open water", SMOOTH: "smooth ice cover", ROUGH: "rough ice cover",
               RUBBLE: "new rubble / moving ice"}
# Reference palette in fixed order: blue, aqua, violet, orange (orange = the jam signal).
CLASS_COLOURS = {WATER: "#2a78d6", SMOOTH: "#1baf7a", ROUGH: "#4a3aa7", RUBBLE: "#eb6834"}
INK, MUTED, GRID, AXIS = "#0b0b0b", "#898781", "#e1e0d9", "#c3c2b7"


def load_scene(path):
    with rasterio.open(path) as src:
        hh, hv, inc = src.read(1), src.read(2), src.read(3)
        tags = src.tags()
    hh = np.where(np.isfinite(hv), hh, np.nan)
    return hh + ANGLE_SLOPE * (inc - REF_ANGLE), np.nanmedian(inc), tags


def build_reference(scene, candidates, cache):
    """Per-pixel late-winter HH_35 and the quality of the match (1 best)."""
    ref = np.full(cache[scene["name"]].shape, np.nan, dtype=np.float32)
    quality = np.zeros(ref.shape, dtype=np.uint8)
    ordered = []
    for _, c in candidates.iterrows():
        if c["beam"] == scene["beam"] and c["pass"] == scene["pass"]:
            q = 1
        elif c["pass"] == scene["pass"] and abs(c["angle"] - scene["angle"]) <= ANGLE_MATCH_DEG:
            q = 2
        else:
            q = 3
            if not USE_OTHER_PASS:
                continue
        ordered.append((q, -c["time"].value, c["name"]))   # best quality, then latest
    for q, _, name in sorted(ordered):
        fill = np.isnan(ref) & np.isfinite(cache[name])
        ref[fill] = cache[name][fill]
        quality[fill] = q
    return ref, quality


def classify(now, ref, melt):
    out = np.full(now.shape, NO_DATA, dtype=np.uint8)
    seen = np.isfinite(now)
    if not melt and np.isnan(ref).all():
        # This scene is itself late winter: describe the winter cover.
        out[seen] = np.where(now[seen] >= RUBBLE_DB, ROUGH, SMOOTH)
        return out
    has_ref = seen & np.isfinite(ref)
    out[seen & ~has_ref] = UNCLASSIFIED
    change = median_filter(np.where(has_ref, now - ref, 0), size=3)
    winter_rough = ref >= RUBBLE_DB
    out[has_ref] = np.where(winter_rough[has_ref], ROUGH, SMOOTH)
    new_rubble = has_ref & (change >= CHANGE_DB) & (now >= RUBBLE_DB)
    out[new_rubble] = RUBBLE
    if melt:
        gone = has_ref & (((change <= -CHANGE_DB) & (now < DARK_DB)) | (now < VERY_DARK_DB))
        out[gone] = WATER
    return out


def style(ax):
    for side in ["top", "right"]:
        ax.spines[side].set_visible(False)
    for side in ["left", "bottom"]:
        ax.spines[side].set_color(AXIS)
    ax.tick_params(colors=MUTED)


def legend(ax, loc):
    ax.legend(handles=[Patch(color=CLASS_COLOURS[c], label=CLASS_NAMES[c]) for c in CLASS_NAMES],
              frameon=False, loc=loc, fontsize=9, ncol=2)


def plot_year(year, profiles, scenes, gauge, path):
    s = scenes[scenes["year"] == year].sort_values("time")
    p = profiles[(profiles["year"] == year) & profiles["usable"]]
    if s.empty:
        return
    fig, (ax, ax2) = plt.subplots(2, 1, figsize=(13, 8), sharex=True,
                                  gridspec_kw={"height_ratios": [3, 1]})
    width = pd.Timedelta(hours=10)
    for _, r in p.iterrows():
        ax.bar(r["time"], 1, bottom=r["km"], width=width,
               color=CLASS_COLOURS[int(r["dominant_class"])], linewidth=0)
    ax.axhspan(0, JAM_ZONE_KM, color=GRID, alpha=0.35, zorder=0)
    ax.text(0.005, JAM_ZONE_KM / 56 - 0.03, "jam zone (lake to past town)", transform=ax.transAxes,
            fontsize=9, color=MUTED)
    ax.set_ylim(0, 56)
    ax.set_ylabel("km upstream from Great Slave Lake", color=MUTED)
    ax.set_title(f"River ice change since late winter (RCM), spring {year}", loc="left", color=INK)
    legend(ax, "upper right")
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


def plot_map(name, classes, river_km, path, km_limit=20):
    rows, cols = np.nonzero(np.isfinite(river_km) & (river_km <= km_limit))
    r0, r1, c0, c1 = rows.min() - 30, rows.max() + 30, cols.min() - 30, cols.max() + 30
    crop = classes[r0:r1, c0:c1].astype(float)
    crop[(crop == NO_DATA)] = np.nan
    unclassified = crop == UNCLASSIFIED
    crop[unclassified] = np.nan
    fig, ax = plt.subplots(figsize=(8, 10))
    ax.set_facecolor("#f0efec")
    ax.imshow(np.where(unclassified, 1.0, np.nan), cmap=ListedColormap([AXIS]), vmin=0, vmax=1,
              interpolation="nearest")
    ax.imshow(crop, cmap=ListedColormap([CLASS_COLOURS[c] for c in (WATER, SMOOTH, ROUGH, RUBBLE)]),
              vmin=1, vmax=4, interpolation="nearest")
    ax.set_xticks([]); ax.set_yticks([])
    ax.set_title(f"River ice change since late winter, {name} (lake to km {km_limit})",
                 loc="left", color=INK, fontsize=11)
    legend(ax, "lower left")
    plt.tight_layout()
    plt.savefig(path, dpi=90)
    plt.close(fig)


if __name__ == "__main__":
    OUT_CLASSES.mkdir(parents=True, exist_ok=True)
    OUT_FIGS.mkdir(parents=True, exist_ok=True)
    with rasterio.open(RIVER_PIXELS) as src:
        river_km, channel = src.read(1), src.read(2)
        profile = src.profile
    is_river = np.isfinite(river_km)
    main = is_river & (channel == 1)
    km_bin = np.where(is_river, np.floor(river_km), -1).astype(int)
    bin_total = np.bincount(km_bin[main], minlength=60)
    degree_days = pd.read_csv(DEGREE_DAYS, parse_dates=["date"])
    gauge = pd.read_csv(TOWN_GAUGE, parse_dates=["date"]).dropna(subset=["level_m"])

    # Load every scene (river pixels only) once.
    cache, meta = {}, []
    for tif in sorted(SCENES.glob("*.tif")):
        hh35, angle, tags = load_scene(tif)
        hh35[~is_river] = np.nan
        cache[tif.stem] = hh35
        when = pd.to_datetime(tif.stem[:15], format="%Y%m%d_%H%M%S")
        day = degree_days[degree_days["date"] == when.normalize()]
        tdd = float(day["tdd"].iloc[0]) if len(day) else np.nan
        meta.append({"name": tif.stem, "time": when, "year": when.year, "beam": tags.get("beam"),
                     "pass": tags.get("pass"), "angle": float(angle), "tdd": tdd})
    meta = pd.DataFrame(meta)

    profile.update(count=1, dtype="uint8", nodata=NO_DATA)
    prof_rows, scene_rows = [], []
    for _, sc in meta.iterrows():
        melt = bool(sc["tdd"] >= MELT_TDD)
        candidates = meta[(meta["year"] == sc["year"]) & (meta["tdd"] < REF_MAX_TDD)
                          & (meta["time"] < sc["time"])]
        is_reference_scene = sc["tdd"] < REF_MAX_TDD and not melt
        if is_reference_scene:
            ref = np.full(cache[sc["name"]].shape, np.nan, dtype=np.float32)
            quality = np.zeros(ref.shape, dtype=np.uint8)
        else:
            ref, quality = build_reference(sc, candidates, cache)
        classes = classify(cache[sc["name"]], ref, melt)
        classes[~is_river] = NO_DATA
        with rasterio.open(OUT_CLASSES / f"{sc['name']}.tif", "w", **profile) as dst:
            dst.write(classes, 1)
        with rasterio.open(OUT_CLASSES / f"{sc['name']}_refquality.tif", "w", **profile) as dst:
            dst.write(quality, 1)

        seen = main & (classes != NO_DATA)
        for k in range(0, int(np.nanmax(river_km)) + 1):
            in_bin = seen & (km_bin == k)
            n = int(in_bin.sum())
            if n == 0 or bin_total[k] == 0:
                continue
            c = classes[in_bin]
            classified = c[c != UNCLASSIFIED]
            counts = {cl: int((classified == cl).sum()) for cl in CLASS_NAMES}
            nc = len(classified)
            prof_rows.append({
                "scene": sc["name"], "time": sc["time"], "year": sc["year"], "km": k,
                "pixels": n, "classified_pixels": nc,
                "coverage": round(nc / bin_total[k], 2),
                "usable": nc / bin_total[k] >= MIN_BIN_COVERAGE,
                **{f"pct_{CLASS_NAMES[cl].split()[0].replace('/', '')}": round(100 * counts[cl] / max(nc, 1), 1)
                   for cl in CLASS_NAMES},
                "dominant_class": max(counts, key=counts.get) if nc else UNCLASSIFIED,
                "ref_quality_median": float(np.median(quality[in_bin])) if quality[in_bin].any() else None,
            })

        jam_all = main & (river_km <= JAM_ZONE_KM)
        jam = seen & (river_km <= JAM_ZONE_KM) & (classes != UNCLASSIFIED)
        jc = classes[jam]
        q = quality[jam]
        row = {
            "scene": sc["name"], "time": sc["time"], "year": sc["year"], "beam": sc["beam"],
            "pass": sc["pass"], "tdd_since_mar1": round(sc["tdd"], 1), "melt_started": melt,
            "is_late_winter_reference": is_reference_scene,
            "jam_zone_classified_pct": round(100 * jam.sum() / max(jam_all.sum(), 1), 0),
            "jam_zone_ref_quality_1_pct": round(100 * (q == 1).mean(), 0) if len(q) and q.any() else None,
            **{f"jam_zone_pct_{CLASS_NAMES[cl].split()[0].replace('/', '')}":
               round(100 * float((jc == cl).mean()), 1) if len(jc) else None for cl in CLASS_NAMES},
        }
        scene_rows.append(row)
        if len(jc):
            print(f"{sc['name']} TDD {sc['tdd']:5.1f}{' (late-winter ref)' if is_reference_scene else ''}: "
                  f"jam zone {row['jam_zone_classified_pct']:.0f}% classified -> "
                  + ", ".join(f"{CLASS_NAMES[cl]} {100 * (jc == cl).mean():.0f}%" for cl in CLASS_NAMES)
                  + (f" | same-geometry ref {row['jam_zone_ref_quality_1_pct']:.0f}%"
                     if row["jam_zone_ref_quality_1_pct"] is not None else ""))
        else:
            print(f"{sc['name']} TDD {sc['tdd']:5.1f}: jam zone not classified")

    profiles = pd.DataFrame(prof_rows)
    scenes = pd.DataFrame(scene_rows)
    profiles.to_csv(PROJECT_DIR / "data" / "processed" / "ice_profiles_v2.csv", index=False)
    scenes.to_csv(PROJECT_DIR / "data" / "processed" / "ice_scene_summary_v2.csv", index=False)
    for year in sorted(scenes["year"].unique()):
        plot_year(year, profiles, scenes, gauge, OUT_FIGS / f"v2_profile_{year}.png")
    for _, r in scenes[scenes["jam_zone_classified_pct"] >= 80].iterrows():
        cls = rasterio.open(OUT_CLASSES / f"{r['scene']}.tif").read(1)
        plot_map(r["scene"], cls, river_km, OUT_FIGS / f"v2_map_{r['scene']}.png")
    print(f"\nVersion 2 outputs in {OUT_CLASSES} and {OUT_FIGS}")
