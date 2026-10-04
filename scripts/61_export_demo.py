"""
Step 7 (demo): Export the data for the simplified Hay River demo page
(web/index.html): 2022 flood year (positive control) vs 2023 no-flood year
(negative control), three stages each, plus five prediction dates.

For each stage and year:
  * RCM river ice from the angle-corrected brightness classes (script 31),
    the SAME method for both years so the maps are comparable:
        open water (blue), smooth sheet ice (white), rubble / jammed ice (amber)
  * estimated flooded land (red): the flood-projection method (script 50) run
    with the river level observed at the town gauge that day and the lake
    level at the mouth - an estimate from elevation, not seen by the radar
  * jam-zone numbers used for the "What we see" points

Prediction cards: risk level from the risk model (script 41, each spring
forecast by a model that never saw it), "confidence" = chance the spring peak
reaches 166.4 m (the lowest documented flood level), estimated from the
model's past errors, and a one-sentence reason built from the actual numbers.

Output: web/data/demo.js and web/data/img/demo_*.png

Run from the project folder:
    venv\\Scripts\\python.exe scripts\\61_export_demo.py
"""

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from PIL import Image
from rasterio.features import rasterize
from rasterio.warp import calculate_default_transform, reproject, Resampling, transform_bounds

PROJECT_DIR = Path(__file__).resolve().parent.parent
PROC = PROJECT_DIR / "data" / "processed"
RAW = PROJECT_DIR / "data" / "raw"
DATA = PROJECT_DIR / "web" / "data"
IMG = DATA / "img"

VIEW = (-115.88, 60.775, -115.69, 60.875)        # west, south, east, north: town, Vale Island, mouth
WEB_CRS = "EPSG:3857"
ICE_PIXEL_M, FLOOD_PIXEL_M = 8, 8
JAM_ZONE_KM = 15
FLOOD_LEVEL_M = 166.4
LAKE_TO_CGVD2013 = -0.28                          # GNWT (2025) conversion for gauge 07OB002
MAX_FLOOD_DISTANCE_M = 1500                       # show estimated flooding only this close to river/lake

YEARS = {
    2022: {"role": "positive", "title": "2022: Flood year", "peak": "2022-05-12",
           "stages": {"before": "20220508_142058_16M4", "peak": "20220512_142109_16M4",
                      "after": "20220516_142046_16M4"},
           # GNWT (2025): instantaneous peak at the gauge and highwater at the mouth on May 12.
           "peak_gauge_m": 170.90, "peak_mouth_m": 158.18},
    2023: {"role": "negative", "title": "2023: No flood", "peak": "2023-04-30",
           "stages": {"before": "20230424_141314_16M8", "peak": "20230428_141251_16M8",
                      "after": "20230502_141302_16M8"}},
}
PREDICTION_DATES = ["2022-04-20", "2022-05-02", "2022-05-08", "2022-05-11", "2023-04-28"]

COLOURS = {1: (31, 111, 191, 235), 2: (255, 255, 255, 245), 3: (242, 169, 0, 240)}  # water, smooth, rubble
FLOOD_RGBA = (235, 45, 55, 140)                    # Canada red, see-through


def load(name):
    spec = importlib.util.spec_from_file_location(name[:-3], PROJECT_DIR / "scripts" / name)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def to_png(codes, src_transform, src_crs, path, pixel, palette):
    """Reproject a small-integer class array to web-map coordinates, crop to VIEW, save as PNG."""
    h, w = codes.shape
    left, top = src_transform.c, src_transform.f
    right, bottom = left + src_transform.a * w, top + src_transform.e * h
    vx0, vy0, vx1, vy1 = transform_bounds("EPSG:4326", WEB_CRS, *VIEW)
    dst_w, dst_h = int((vx1 - vx0) / pixel), int((vy1 - vy0) / pixel)
    dst_transform = rasterio.transform.from_bounds(vx0, vy0, vx1, vy1, dst_w, dst_h)
    out = np.zeros((dst_h, dst_w), dtype=np.uint8)
    reproject(codes.astype(np.uint8), out, src_transform=src_transform, src_crs=src_crs,
              dst_transform=dst_transform, dst_crs=WEB_CRS, resampling=Resampling.nearest,
              src_nodata=0, dst_nodata=0)
    rgba = np.zeros(out.shape + (4,), dtype=np.uint8)
    for code, colour in palette.items():
        rgba[out == code] = colour
    Image.fromarray(rgba, "RGBA").save(path, optimize=True)
    return [[VIEW[1], VIEW[0]], [VIEW[3], VIEW[2]]]


def daily_series(path):
    d = pd.read_csv(path, parse_dates=["date"]).set_index("date")["level_m"]
    return d


if __name__ == "__main__":
    IMG.mkdir(parents=True, exist_ok=True)
    fp = load("50_flood_projection.py")
    rm = load("41_risk_model.py")
    print("Preparing the elevation model (about 30 s) ...")
    p = fp.prepare()
    from scipy.ndimage import distance_transform_edt
    near_water = distance_transform_edt(~p["is_river"]) * abs(p["transform"].a) <= MAX_FLOOD_DISTANCE_M

    with rasterio.open(PROC / "corridor" / "river_pixels.tif") as src:
        river_km = src.read(1)
        river_tf, river_crs = src.transform, src.crs
    jam = np.isfinite(river_km) & (river_km <= JAM_ZONE_KM)
    offset = float((PROC / "risk" / "hydat_datum_offset.txt").read_text())
    town = daily_series(RAW / "hydat" / "07OB001_daily.csv")
    lake = daily_series(RAW / "hydat" / "07OB002_daily.csv")

    import geopandas as gpd
    buildings = gpd.read_file(RAW / "osm_hay_river.gpkg", layer="buildings").to_crs(p["crs"])
    ids = rasterize(((g, i + 1) for i, g in enumerate(buildings.geometry)), out_shape=p["dem"].shape,
                    transform=p["transform"], fill=0, all_touched=True, dtype="int32")

    years_out, stats = {}, {}
    for year, cfg in YEARS.items():
        years_out[year] = {"title": cfg["title"], "role": cfg["role"], "peak_date": cfg["peak"], "stages": {}}
        for stage, scene in cfg["stages"].items():
            day = pd.Timestamp(scene[:8])
            classes = rasterio.open(PROC / "ice_classes" / f"{scene}.tif").read(1)
            ice_bounds = to_png(classes, river_tf, river_crs, IMG / f"demo_ice_{year}_{stage}.png",
                                ICE_PIXEL_M, COLOURS)
            seen = jam & (classes > 0)
            pct = {k: round(100 * float((classes[seen] == c).mean()), 0) if seen.any() else None
                   for k, c in [("water", 1), ("smooth", 2), ("rubble", 3)]}

            # River level that day: the documented instantaneous peak on peak day, else daily mean.
            if stage == "peak" and "peak_gauge_m" in cfg and day == pd.Timestamp(cfg["peak"]):
                gauge, mouth = cfg["peak_gauge_m"], cfg["peak_mouth_m"]
                level_note = "instantaneous peak"
            else:
                gauge = float(town.get(day, np.nan)) + offset
                mouth = float(lake.get(day, np.nan)) + LAKE_TO_CGVD2013
                level_note = "daily average"
            if not np.isfinite(mouth):
                mouth = fp.MOUTH_TYPICAL
            flooded, _ = fp.flood_extent(p, gauge, mouth)
            # Display rules for the demo:
            #  * only near the river/lake (MAX_FLOOD_DISTANCE_M), where the estimate is most
            #    reliable - farther out it reaches the edge of the lidar and overestimates;
            #  * only when the river is at/above the lowest documented flood level.
            flooded &= near_water
            if gauge < FLOOD_LEVEL_M:
                flooded[:] = False
            n_bldg = int((np.bincount(ids[flooded], minlength=len(buildings) + 1)[1:] > 0).sum())
            flood_bounds = to_png(flooded.astype(np.uint8), p["transform"], p["crs"],
                                  IMG / f"demo_flood_{year}_{stage}.png", FLOOD_PIXEL_M, {1: FLOOD_RGBA})
            days_from_peak = (day - pd.Timestamp(cfg["peak"])).days
            years_out[year]["stages"][stage] = {
                "date": day.strftime("%Y-%m-%d"), "days_from_peak": days_from_peak,
                "scene": scene, "beam": scene.split("_")[-1],
                "ice_img": f"data/img/demo_ice_{year}_{stage}.png", "ice_bounds": ice_bounds,
                "flood_img": f"data/img/demo_flood_{year}_{stage}.png", "flood_bounds": flood_bounds,
                "river_level_m": round(gauge, 1), "level_note": level_note,
                "buildings_flooded": n_bldg, "jam_zone_pct": pct,
            }
            stats[(year, stage)] = years_out[year]["stages"][stage]
            print(f"{year} {stage:6s} {day:%Y-%m-%d} ({days_from_peak:+d} d): river {gauge:.1f} m, "
                  f"jam zone water/smooth/rubble {pct}, est. buildings flooded {n_bldg}")

    # --- "What we see": at most 3 short points per stage ---------------------------
    def s(y, st):
        return stats[(y, st)]
    see = {}
    for stage in ["before", "peak", "after"]:
        a, b = s(2022, stage), s(2023, stage)
        ra, rb = a["jam_zone_pct"]["rubble"], b["jam_zone_pct"]["rubble"]
        wa, wb = a["jam_zone_pct"]["water"], b["jam_zone_pct"]["water"]
        pts = []
        if stage == "before":
            pts.append(f"Rubble ice fills {ra:.0f}% of the river from the lake to town in 2022, vs {rb:.0f}% in 2023.")
            pts.append(f"The river at town is already {a['river_level_m']:.1f} m in 2022, vs {b['river_level_m']:.1f} m in 2023.")
        elif stage == "peak":
            pts.append(f"2022: the jam holds, with {ra:.0f}% rubble ice near the mouth. 2023: ice is breaking up ({wb:.0f}% open water).")
            pts.append(f"2022: water spreads onto Vale Island, about {a['buildings_flooded']} buildings in the estimated flood area.")
            pts.append(f"2023 stays in its banks ({b['river_level_m']:.1f} m at town).")
        else:
            pts.append(f"2022: the river has dropped to {a['river_level_m']:.1f} m, but rubble ice still fills "
                       f"{ra:.0f}% of the channel.")
            pts.append(f"2023: the river is opening up ({wb:.0f}% open water) with no flooding.")
        if stage == "before":
            fl = a["buildings_flooded"]
            pts.append(f"Low ground is already flooding in 2022 (about {fl} buildings); nothing in 2023." if fl
                       else "No flooding yet in either year.")
        see[stage] = pts[:3]

    # --- Prediction cards -------------------------------------------------------------
    fc = json.loads((DATA / "forecasts.js").read_text(encoding="utf-8").split("window.HRFW.forecasts = ", 1)[1]
                    .rstrip().rstrip(";"))
    loyo = pd.read_csv(PROC / "risk" / "loyo_predictions.csv")
    resid = (loyo["peak_level_m"] - loyo["pred_model"]).to_numpy()
    wts = 1.0 / loyo.groupby("year")["year"].transform("size").to_numpy()
    v1 = pd.read_csv(PROC / "ice_scene_summary.csv", parse_dates=["time"])

    def chance(median):
        return float((wts * ((median + resid) >= FLOOD_LEVEL_M)).sum() / wts.sum())

    def latest_rcm(day):
        d = pd.Timestamp(day)
        # Same rule as the risk model: RCM rubble only counts once melt has started.
        r = v1[(v1["time"] <= d + pd.Timedelta(hours=23)) & (v1["time"] >= d - pd.Timedelta(days=3))
               & (v1["jam_zone_coverage"] >= 0.3) & v1["melt_started"]].sort_values("time")
        return r.iloc[-1] if len(r) else None

    preds = []
    for day in PREDICTION_DATES:
        year = int(day[:4])
        series = fc[str(year)]["series"]
        i = next(k for k, r in enumerate(series) if r["date"] == day)
        r, prev = series[i], series[i - 1]
        drv = {d["name"]: d["value"] for d in r["drivers"]}
        q, q_prev = drv["Upstream flow (Meander River)"], next(
            d["value"] for d in prev["drivers"] if d["name"] == "Upstream flow (Meander River)")
        lake_a, thick = drv["Great Slave Lake level"], drv["Ice thickness"]
        rcm = latest_rcm(day)
        if year == 2023:
            water = rcm["jam_zone_pct_water"] if rcm is not None else None
            reason = (f"Lake and river flow are near normal, and RCM shows the ice breaking up"
                      + (f" ({water:.0f}% open water)." if water else "."))
        elif rcm is not None and rcm["jam_zone_pct_rubble"] >= rm.RCM_BRIGHT_UP and day >= "2022-05-10":
            reason = (f"Rubble ice still jams the river from the lake to town ({rcm['jam_zone_pct_rubble']:.0f}%) "
                      f"while the river at town is {r['observed']:.1f} m.")
        elif rcm is not None and rcm["jam_zone_pct_rubble"] >= rm.RCM_BRIGHT_UP:
            reason = (f"RCM sees {rcm['jam_zone_pct_rubble']:.0f}% rubble ice from the lake to town "
                      f"while upstream flow keeps rising ({q:.0f} m³/s).")
        elif q_prev and q / q_prev >= 2:
            reason = f"Upstream flow jumped from {q_prev:.0f} to {q:.0f} m³/s in one day."
        else:
            reason = (f"Great Slave Lake is {lake_a:.2f} m above normal and the ice is about "
                      f"{thick:.0f} cm thick. Both raise the risk.")
        c = chance(r["median"])
        preds.append({"date": day, "year": year, "level": r["level"],
                      "confidence": round(c * 100), "confidence_text": "over 95%" if c > 0.95 else f"{c:.0%}",
                      "forecast_peak_m": r["median"], "reason": reason,
                      "control": "negative control" if year == 2023 else "flood year"})
        print(f"{day}: {r['level']:8s} chance {c:.0%} | {reason}")

    out = {"view": {"center": [60.82, -115.79], "zoom": 12,
                    "bounds": [[VIEW[1], VIEW[0]], [VIEW[3], VIEW[2]]]},
           "years": years_out, "see": see, "predictions": preds,
           "flood_level_m": FLOOD_LEVEL_M, "rcm_threshold": rm.RCM_BRIGHT_UP,
           "outcome": "2022 flooded (peak 170.9 m on May 12). 2023 did not (peak 162.3 m on Apr 30)."}
    (DATA / "demo.js").write_text("window.HRFW = window.HRFW || {};\nwindow.HRFW.demo = "
                                  + json.dumps(out, separators=(",", ":")) + ";\n", encoding="utf-8")
    print(f"\nSaved {DATA / 'demo.js'}")
    for stage, pts in see.items():
        print(f"  {stage}: " + " | ".join(pts))
