"""
Step 6a (new plan): Export everything the dashboard needs into web/data/.

The website (web/index.html) is opened straight from disk, so data is saved
as small JavaScript files (window.HRFW.<name> = {...}) instead of JSON - web
browsers won't let a page opened from disk read JSON files.

What gets exported
------------------
seasons.js     ice thickness + thawing degree-days for every winter, plus the
               typical range across all winters
forecasts.js   day-by-day forecast for every spring 1976-2024 (each made by a
               model that never saw that spring), risk level, the factors
               driving it, RCM note, observed level
scenes.js      every RCM scene: date, beam, jam-zone numbers, ice profile by km,
               and the picture file for the map
flood.js       projected flood pictures for gauge levels 164-172 m (two lake
               levels) and the building/road counts
map.js         river km markers, jam zone, gauge, places
meta.js        thresholds, model skill, flood history, method notes
img/ice_<scene>.png, img/flood_<level>_<mouth>.png   map pictures (web map projection)

Run from the project folder (takes a few minutes):
    venv\\Scripts\\python.exe scripts\\60_export_dashboard.py
"""

import importlib.util
import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from PIL import Image
from rasterio.warp import calculate_default_transform, reproject, Resampling, transform_bounds

PROJECT_DIR = Path(__file__).resolve().parent.parent
SCRIPTS = PROJECT_DIR / "scripts"
PROC = PROJECT_DIR / "data" / "processed"
WEB = PROJECT_DIR / "web"
DATA = WEB / "data"
IMG = DATA / "img"

WEB_CRS = "EPSG:3857"          # the projection web maps use
ICE_PIXEL_M = 15               # ice pictures: 15 m pixels on the web map
FLOOD_PIXEL_M = 10
FLOOD_LEVELS = np.round(np.arange(164.0, 172.01, 0.5), 2)
HIGH_LAKE_ANOM = 0.3           # lake this far above average -> use the high-lake flood curve
FORECAST_START, FORECAST_END = "04-01", "06-10"
RCM_YEARS = range(2021, 2027)

# Colours (reference palette): ice classes and the brightness-only fallback.
ICE_RGB = {1: (42, 120, 214), 2: (27, 175, 122), 3: (74, 58, 167), 4: (235, 104, 52)}
FLOOD_RGB = (232, 123, 164)    # magenta: kept apart from the orange "new rubble" ice class
DAYS_AFTER_PEAK = 3            # forecasts stop this many days after the spring's actual peak


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace(".py", ""), SCRIPTS / name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_js(name, obj):
    DATA.mkdir(parents=True, exist_ok=True)
    text = json.dumps(obj, separators=(",", ":"), default=lambda o: None if pd.isna(o) else str(o))
    (DATA / f"{name}.js").write_text(f"window.HRFW = window.HRFW || {{}};\nwindow.HRFW.{name} = {text};\n",
                                     encoding="utf-8")
    print(f"  {name}.js: {len(text) / 1024:.0f} KB")


def to_web_png(array, src_transform, src_crs, path, pixel, colour_fn):
    """Reproject a class array to the web map projection and save a transparent PNG."""
    h, w = array.shape
    left, top = src_transform.c, src_transform.f
    right, bottom = left + src_transform.a * w, top + src_transform.e * h
    dst_transform, dw, dh = calculate_default_transform(src_crs, WEB_CRS, w, h, left, bottom, right, top,
                                                        resolution=pixel)
    out = np.zeros((dh, dw), dtype=np.uint8)
    reproject(array, out, src_transform=src_transform, src_crs=src_crs, dst_transform=dst_transform,
              dst_crs=WEB_CRS, resampling=Resampling.nearest, src_nodata=0, dst_nodata=0)
    rows, cols = np.nonzero(out)
    if len(rows) == 0:
        return None
    r0, r1, c0, c1 = rows.min(), rows.max() + 1, cols.min(), cols.max() + 1
    crop = out[r0:r1, c0:c1]
    rgba = colour_fn(crop)
    Image.fromarray(rgba, "RGBA").save(path, optimize=True)
    x0 = dst_transform.c + c0 * dst_transform.a
    y0 = dst_transform.f + r0 * dst_transform.e
    x1 = dst_transform.c + c1 * dst_transform.a
    y1 = dst_transform.f + r1 * dst_transform.e
    west, south, east, north = transform_bounds(WEB_CRS, "EPSG:4326", x0, y1, x1, y0)
    return [[round(south, 6), round(west, 6)], [round(north, 6), round(east, 6)]]


def ice_colours(codes):
    """codes 1-4 = change classes (solid); 11-13 = brightness-only fallback (faded)."""
    rgba = np.zeros(codes.shape + (4,), dtype=np.uint8)
    for c, rgb in ICE_RGB.items():
        rgba[codes == c] = (*rgb, 235)
    for c, base in [(11, 1), (12, 2), (13, 4)]:
        rgba[codes == c] = (*ICE_RGB[base], 110)
    return rgba


def flood_colours(codes):
    rgba = np.zeros(codes.shape + (4,), dtype=np.uint8)
    rgba[codes == 1] = (*FLOOD_RGB, 170)
    return rgba


def r1(x, d=2):
    return None if x is None or (isinstance(x, float) and not np.isfinite(x)) else round(float(x), d)


# ---------------------------------------------------------------------------
def export_seasons():
    dd = pd.read_csv(PROC / "ice" / "daily_degree_days.csv", parse_dates=["date"])
    winters = pd.read_csv(PROC / "ice" / "winter_summary.csv")
    ok = set(winters.loc[winters["data_ok"], "season"])
    band = dd[dd["season"].isin(ok)]
    thick = band.groupby("days_since_sep1")["thickness_cm"].quantile([0.1, 0.5, 0.9]).unstack()
    band = band.assign(doy=band["date"].dt.dayofyear)
    spring = band[band["date"].dt.month.isin([3, 4, 5, 6])]
    tdd = spring.groupby("doy")["tdd"].quantile([0.1, 0.5, 0.9]).unstack()
    seasons = {}
    for s, g in dd.groupby("season"):
        g = g[g["days_since_sep1"] <= 320]
        sp = g[g["date"].dt.month.isin([3, 4, 5, 6])]
        seasons[int(s)] = {
            "thickness": [r1(v, 1) for v in g["thickness_cm"]],
            "thickness_low": [r1(v, 1) for v in g["thickness_low_cm"]],
            "thickness_high": [r1(v, 1) for v in g["thickness_high_cm"]],
            "tdd_doy0": int(sp["date"].dt.dayofyear.min()) if len(sp) else None,
            "tdd": [r1(v, 1) for v in sp["tdd"]],
        }
    summary = winters.set_index("season")[["freeze_up", "afdd_winter", "max_thickness_cm", "tdd_may01",
                                           "missing_days", "data_ok"]]
    write_js("seasons", {
        "thickness_band": {"p10": [r1(v, 1) for v in thick[0.1][:321]], "p50": [r1(v, 1) for v in thick[0.5][:321]],
                           "p90": [r1(v, 1) for v in thick[0.9][:321]]},
        "tdd_band": {"doy0": int(tdd.index.min()), "p10": [r1(v, 1) for v in tdd[0.1]],
                     "p50": [r1(v, 1) for v in tdd[0.5]], "p90": [r1(v, 1) for v in tdd[0.9]]},
        "seasons": seasons,
        "summary": {int(k): {c: (v.item() if hasattr(v, "item") else v) for c, v in row.items()}
                    for k, row in summary.iterrows()},
    })


def export_forecasts(rm):
    history = pd.read_csv(PROC / "risk" / "breakup_history.csv", index_col="year")
    history["peak_date"] = pd.to_datetime(history["peak_time"], errors="coerce")
    town = pd.read_csv(rm.TOWN, parse_dates=["date"]).dropna(subset=["level_m"])
    for year in history.index[history["peak_date"].isna()]:
        s = town[(town["date"].dt.year == year) & town["date"].dt.month.isin([4, 5, 6])]
        if len(s):
            history.loc[year, "peak_date"] = s.loc[s["level_m"].idxmax(), "date"]
    offset = float((PROC / "risk" / "hydat_datum_offset.txt").read_text())
    daily = rm.daily_inputs()
    rows = pd.read_csv(PROC / "risk" / "training_rows.csv", parse_dates=["date"])
    bundle = __import__("joblib").load(PROC / "risk" / "risk_model.joblib")
    spread = bundle["spread"]
    v1 = pd.read_csv(rm.ICE_V1, parse_dates=["time"])
    v2 = pd.read_csv(rm.ICE_V2, parse_dates=["time"])
    names = {"q_up": "Upstream flow (Meander River)", "q_up_rise7": "Rise in upstream flow (7 days)",
             "lake_anom": "Great Slave Lake level", "thickness_cm": "Ice thickness"}

    out = {}
    for year in sorted(rows["year"].unique()):
        model = rm.fit(rows[rows["year"] != year], rm.FEATURES)
        scaler, ridge = model.named_steps["standardscaler"], model.named_steps["ridge"]
        end = pd.Timestamp(f"{year}-{FORECAST_END}")
        if year in history.index and pd.notna(history.loc[year, "peak_date"]):
            # The model forecasts the COMING peak; after it has passed that is meaningless.
            end = min(end, history.loc[year, "peak_date"].normalize() + pd.Timedelta(days=DAYS_AFTER_PEAK))
        days = daily[(daily["date"] >= f"{year}-{FORECAST_START}") & (daily["date"] <= end)].copy()
        days["lake_anom"] = days["lake_anom"].fillna(0.0)
        days = days.dropna(subset=rm.FEATURES)
        if days.empty:
            continue
        X = days[rm.FEATURES]
        med = model.predict(X)
        contrib = (scaler.transform(X) * ridge.coef_)
        series = []
        for i, (_, d) in enumerate(days.iterrows()):
            p10, p90 = med[i] + spread[0.1], med[i] + spread[0.9]
            level = rm.model_level(med[i], p90)
            status = rm.rcm_status(d["date"], v1, v2) if year in RCM_YEARS else None
            final, why = rm.rcm_adjust(level, status) if year in RCM_YEARS else (level, None)
            obs = town[town["date"] == d["date"]]["level_m"]
            series.append({
                "date": d["date"].strftime("%Y-%m-%d"), "median": r1(med[i]), "p10": r1(p10), "p90": r1(p90),
                "model_level": level, "level": final, "rcm_note": why,
                "observed": r1(float(obs.iloc[0]) + offset) if len(obs) else None,
                "lake_high": bool(d["lake_anom"] >= HIGH_LAKE_ANOM),
                "drivers": [{"name": names[f], "value": r1(float(d[f]), 2), "effect_m": r1(float(c), 2)}
                            for f, c in sorted(zip(rm.FEATURES, contrib[i]), key=lambda t: -abs(t[1]))],
                "tdd": r1(float(d["tdd"]), 1),
            })
        h = history.loc[year] if year in history.index else None
        out[int(year)] = {
            "series": series,
            "peak_level": r1(h["peak_level_m"]) if h is not None else None,
            "peak_date": h["peak_date"].strftime("%Y-%m-%d") if h is not None and pd.notna(h["peak_date"]) else None,
            "documented_flood": bool(h["documented_flood"]) if h is not None else False,
            "breakup_type": h["breakup_type"] if h is not None and isinstance(h["breakup_type"], str) else None,
            "intercept": r1(float(ridge.intercept_)),
        }
    write_js("forecasts", out)
    return history


def export_scenes():
    with rasterio.open(PROC / "corridor" / "river_pixels.tif") as src:
        river_km = src.read(1)
        transform, crs = src.transform, src.crs
    is_river = np.isfinite(river_km)
    km_bin = np.where(is_river, np.floor(river_km), -1).astype(int)
    bin_total = np.bincount(km_bin[is_river], minlength=60)
    s1 = pd.read_csv(PROC / "ice_scene_summary.csv").set_index("scene")
    s2 = pd.read_csv(PROC / "ice_scene_summary_v2.csv").set_index("scene")
    IMG.mkdir(parents=True, exist_ok=True)
    scenes = []
    for name in sorted(s2.index):
        c2 = rasterio.open(PROC / "ice_classes_v2" / f"{name}.tif").read(1)
        c1 = rasterio.open(PROC / "ice_classes" / f"{name}.tif").read(1)
        combined = np.where((c2 >= 1) & (c2 <= 4), c2, 0).astype(np.uint8)
        fallback = (c2 == 255) & (c1 > 0)
        combined[fallback] = np.select([c1 == 1, c1 == 2, c1 == 3], [11, 12, 13], 0)[fallback]
        combined[~is_river] = 0
        bounds = to_web_png(combined, transform, crs, IMG / f"ice_{name}.png", ICE_PIXEL_M, ice_colours)
        if bounds is None:
            continue
        profile = []
        for k in range(0, 56):
            m = (km_bin == k) & (combined > 0)
            n = int(m.sum())
            if n == 0 or n < 0.3 * bin_total[k]:
                continue
            vals, counts = np.unique(combined[m], return_counts=True)
            profile.append([k, int(vals[np.argmax(counts)]), round(n / bin_total[k], 2)])
        r2, r_1 = s2.loc[name], s1.loc[name] if name in s1.index else None
        scenes.append({
            "id": name, "time": pd.Timestamp(r2["time"]).strftime("%Y-%m-%d %H:%M"), "year": int(r2["year"]),
            "beam": r2["beam"], "pass": r2["pass"], "tdd": r1(r2["tdd_since_mar1"], 1),
            "late_winter": bool(r2["is_late_winter_reference"]),
            "jam_classified_pct": r1(r2["jam_zone_classified_pct"], 0),
            "jam_new_rubble_pct": r1(r2.get("jam_zone_pct_new"), 0),
            "jam_open_water_pct": r1(r2.get("jam_zone_pct_open"), 0),
            "jam_rough_pct": r1(r2.get("jam_zone_pct_rough"), 0),
            "jam_bright_v1_pct": r1(r_1["jam_zone_pct_rubble"], 0) if r_1 is not None else None,
            "img": f"data/img/ice_{name}.png", "bounds": bounds, "profile": profile,
        })
    write_js("scenes", scenes)
    print(f"  {len(scenes)} RCM scene pictures")


def export_flood(fp):
    p = fp.prepare()
    curve = pd.read_csv(PROC / "flood_projection" / "impact_curve.csv")
    layers = {}
    for mouth in fp.MOUTH_LEVELS:
        for level in FLOOD_LEVELS:
            flooded, _ = fp.flood_extent(p, float(level), mouth)
            name = f"flood_{level:.2f}_{mouth:.2f}"
            bounds = to_web_png(flooded.astype(np.uint8), p["transform"], p["crs"], IMG / f"{name}.png",
                                FLOOD_PIXEL_M, flood_colours)
            c = curve[(curve["mouth_level_m"] == mouth) & (np.isclose(curve["gauge_level_m"], level))]
            areas = {k.replace("bldg_", "").replace("_", " "): int(v) for k, v in c.iloc[0].items()
                     if k.startswith("bldg_") and v > 0} if len(c) else {}
            layers[f"{level:.2f}|{mouth:.2f}"] = {
                "img": f"data/img/{name}.png" if bounds else None, "bounds": bounds,
                "buildings": int(c["buildings_flooded"].iloc[0]) if len(c) else None,
                "road_km": r1(c["road_km_flooded"].iloc[0], 1) if len(c) else None,
                "flooded_km2": r1(c["flooded_km2"].iloc[0], 1) if len(c) else None,
                "by_area": areas}
    write_js("flood", {"levels": [float(l) for l in FLOOD_LEVELS], "mouths": fp.MOUTH_LEVELS,
                       "high_lake_anom": HIGH_LAKE_ANOM, "layers": layers})


def export_map():
    corridor = PROC / "corridor" / "corridor.gpkg"
    marks = gpd.read_file(corridor, layer="km_marks").to_crs(4326)
    centre = gpd.read_file(corridor, layer="centreline").to_crs(32611).geometry.iloc[0]
    jam = gpd.GeoSeries([__import__("shapely").ops.substring(centre, 0, 15000)], crs=32611).to_crs(4326).iloc[0]
    places = gpd.read_file(PROJECT_DIR / "data" / "raw" / "osm_hay_river.gpkg", layer="places").to_crs(4326)
    places = places[~places["name"].str.fullmatch(r"Island [A-Z]")]
    write_js("map", {
        "km_marks": [[r1(g.y, 5), r1(g.x, 5), int(k)] for k, g in zip(marks["km"], marks.geometry) if k % 5 == 0],
        "jam_zone": [[r1(y, 5), r1(x, 5)] for x, y in jam.coords],
        "gauges": [{"id": "07OB001", "name": "Hay River near Hay River (town gauge)", "lat": 60.743, "lon": -115.860},
                   {"id": "07OB002", "name": "Great Slave Lake at Hay River", "lat": 60.860, "lon": -115.734}],
        "places": [{"name": n, "lat": r1(g.y, 5), "lon": r1(g.x, 5)} for n, g in zip(places["name"], places.geometry)],
    })


def export_meta(rm, history):
    skill = pd.read_csv(PROC / "risk" / "model_skill.csv")
    val = pd.read_csv(PROC / "flood_projection" / "validation_2022.csv")
    hist = history.dropna(subset=["peak_level_m"])
    write_js("meta", {
        "watch_m": rm.WATCH_M, "warning_m": rm.WARNING_M,
        "levels": rm.LEVELS,
        "skill": skill.to_dict(orient="records"),
        "validation_2022": val[val["profile_exponent"] == 0.6].to_dict(orient="records"),
        "history": [{"year": int(y), "level": r1(r["peak_level_m"]), "flood": bool(r["documented_flood"]),
                     "type": r["breakup_type"] if isinstance(r["breakup_type"], str) else None}
                    for y, r in hist.iterrows()],
        "flood_years": [1951, 1963, 1974, 1985, 1992, 2003, 2008, 2022],
        "rcm_years": list(RCM_YEARS),
    })


if __name__ == "__main__":
    print("Exporting dashboard data to web/data/ ...")
    rm = load("41_risk_model.py")
    fp = load("50_flood_projection.py")
    export_seasons()
    history = export_forecasts(rm)
    export_scenes()
    export_flood(fp)
    export_map()
    export_meta(rm, history)
    size = sum(f.stat().st_size for f in DATA.rglob("*") if f.is_file())
    print(f"Done: {size / 1e6:.1f} MB in {DATA}")
