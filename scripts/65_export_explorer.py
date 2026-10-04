"""
Step 10b (map explorer): export everything the single-map explorer (web/index.html) needs.

Sites:
  hay          Hay River: 2022 (flood year, positive control) and 2023 (no flood,
               negative control); stages Before peak / Peak / After peak (same
               images as the judges' page); estimated flooded land from the
               elevation model (same rules as the judges' page).
  fort_simpson, albany
               Blind-test sites: one entry per spring 2021-2026 from the LOCKED
               image list (read only). Stages come only from that list:
               Before melt (last image before melt), Breakup (melt image with the
               most rubble ice before the ice cleared), After (first image with
               the river mostly open). Predictions are the locked yearly ones.
               No flooded-land layer (no elevation model there).

Map layers (each class a separate transparent picture so it can be switched off):
  open water #2F6FE4, smooth sheet ice #BFEFFF, rubble / jammed ice #FF9F1C,
  flooded land #FF5A36. Ice classes use the same angle-corrected brightness rule
  everywhere (HH35 >= -13 dB rubble; < -20 dB open water once melt has started).

Basemap (drawn by the page, no map server needed): river and lake water, main
and minor roads, and a few labels, from OpenStreetMap and the project's own data.

Output: web/data/explorer.js, web/data/img/x_*.png

Run from the project folder:
    venv\\Scripts\\python.exe scripts\\65_export_explorer.py
"""

import importlib.util
import json
import time
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import requests
from PIL import Image
from rasterio.features import shapes as raster_shapes
from rasterio.warp import reproject, Resampling, transform_bounds
from scipy.ndimage import distance_transform_edt, label
from shapely.geometry import box, mapping, shape

PROJECT_DIR = Path(__file__).resolve().parent.parent
PROC = PROJECT_DIR / "data" / "processed"
RAW = PROJECT_DIR / "data" / "raw"
BT = PROJECT_DIR / "outputs" / "blind_test"
DATA = PROJECT_DIR / "web" / "data"
IMG = DATA / "img"
WEB_CRS = "EPSG:3857"
PIXEL = 8

COLOURS = {1: (47, 111, 228, 235), 2: (191, 239, 255, 225), 3: (255, 159, 28, 240)}
CLASS_KEYS = {1: "water", 2: "smooth", 3: "rubble"}
FLOOD_RGBA = (255, 90, 54, 185)
REF_ANGLE, ANGLE_SLOPE, RUBBLE_DB, DARK_DB = 35.0, 0.18, -13.0, -20.0
FLOOD_LEVEL_M, LAKE_TO_CGVD2013, NEAR_WATER_M = 166.4, -0.28, 1500

SITES = {
    "hay": {"name": "Hay River", "where": "NT", "view": (-115.885, 60.772, -115.685, 60.878),
            "center": [60.82, -115.79], "zoom": 12.5},
    "fort_simpson": {"name": "Fort Simpson", "where": "NT",
                     "view": (-121.56, 61.80, -121.13, 61.935), "center": [61.862, -121.34], "zoom": 12,
                     "community": "Fort Simpson"},
    "albany": {"name": "Albany River", "where": "ON",
               "view": (-81.86, 52.165, -81.44, 52.335), "center": [52.25, -81.65], "zoom": 12,
               "community": "Fort Albany and Kashechewan"},
}
LABELS = {
    "hay": [("Hay River", 60.8150, -115.7920, "town"), ("Vale Island", 60.8530, -115.7600, "place"),
            ("Great Slave Lake", 60.8735, -115.8050, "water")],
    "fort_simpson": [("Fort Simpson", 61.8580, -121.3500, "town"), ("Mackenzie River", 61.8950, -121.4400, "water"),
                     ("Liard River", 61.8250, -121.2900, "water")],
    "albany": [("Fort Albany", 52.2130, -81.6825, "town"), ("Kashechewan", 52.2935, -81.6394, "town"),
               ("Albany River", 52.2400, -81.8000, "water"), ("James Bay", 52.2700, -81.4800, "water")],
}
MAIN_ROADS = {"motorway", "trunk", "primary", "secondary", "tertiary"}
MINOR_ROADS = {"residential", "unclassified", "living_street"}
URLS = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter",
        "https://overpass.private.coffee/api/interpreter"]


def load(name):
    spec = importlib.util.spec_from_file_location(name[:-3], PROJECT_DIR / "scripts" / name)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def overpass(q):
    for attempt in range(4):
        for u in URLS:
            try:
                r = requests.post(u, data={"data": q}, timeout=300,
                                  headers={"User-Agent": "hay-river-flood-watch (hackathon project)"})
                r.raise_for_status()
                return r.json()["elements"]
            except Exception as e:
                print("   ", u.split("/")[2], "failed:", str(e)[:50])
            time.sleep(10)
    raise SystemExit("Overpass failed")


def to_png(codes, src_transform, src_crs, path, view, palette):
    """Reproject class codes to the web map projection over `view` and save a transparent PNG."""
    vx0, vy0, vx1, vy1 = transform_bounds("EPSG:4326", WEB_CRS, *view)
    w, h = int((vx1 - vx0) / PIXEL), int((vy1 - vy0) / PIXEL)
    dst_t = rasterio.transform.from_bounds(vx0, vy0, vx1, vy1, w, h)
    out = np.zeros((h, w), dtype=np.uint8)
    reproject(codes.astype(np.uint8), out, src_transform=src_transform, src_crs=src_crs, dst_transform=dst_t,
              dst_crs=WEB_CRS, resampling=Resampling.nearest, src_nodata=0, dst_nodata=0)
    rgba = np.zeros(out.shape + (4,), dtype=np.uint8)
    for code, colour in palette.items():
        rgba[out == code] = colour
    if not rgba[..., 3].any():
        return False
    Image.fromarray(rgba, "RGBA").save(path, optimize=True)
    return True


def class_layers(codes, transform, crs, stem, view):
    out = {}
    for code, key in CLASS_KEYS.items():
        p = IMG / f"x_{stem}_{key}.png"
        if to_png(np.where(codes == code, code, 0), transform, crs, p, view, {code: COLOURS[code]}):
            out[key] = f"data/img/{p.name}"
    return out


def gj(geoms_wgs84, tol):
    feats = []
    for g in geoms_wgs84:
        if g is None or g.is_empty:
            continue
        g = g.simplify(tol)
        if not g.is_empty:
            feats.append({"type": "Feature", "properties": {}, "geometry": mapping(g)})
    return {"type": "FeatureCollection", "features": feats}


def round_coords(obj):
    if isinstance(obj, float):
        return round(obj, 5)
    if isinstance(obj, (list, tuple)):
        return [round_coords(x) for x in obj]
    if isinstance(obj, dict):
        return {k: round_coords(v) for k, v in obj.items()}
    return obj


def road_layers(roads_wgs, view):
    clip = box(*view).buffer(0.02)
    r = roads_wgs[roads_wgs.intersects(clip)]
    main = r[r["highway"].isin(MAIN_ROADS)]
    minor = r[r["highway"].isin(MINOR_ROADS)]
    labels = []
    for name, g in main[main["name"].notna()].groupby("name"):
        line = g.geometry.union_all().intersection(box(*view))
        if line.is_empty or line.length < 0.01:
            continue
        p = line.interpolate(0.5, normalized=True)
        labels.append([name, round(p.y, 5), round(p.x, 5), "road"])
    return gj(list(main.geometry.intersection(clip)), 0.00005), gj(list(minor.geometry.intersection(clip)), 0.00005), labels


# --------------------------------------------------------------------------------
def hay_site(demo, fp):
    site = SITES["hay"]
    view = site["view"]
    # Basemap: river (project corridor) + Great Slave Lake (30 m elevation map, water level).
    river = gpd.read_file(PROC / "corridor" / "corridor.gpkg", layer="river_mask").to_crs(4326)
    with rasterio.open(RAW / "dem" / "dem_corridor_30m.tif") as src:
        dem, t, crs = src.read(1), src.transform, src.crs
    low, _ = label(np.isfinite(dem) & (dem <= 157.3))
    top_ids = set(np.unique(low[0, :])) - {0}
    lake = np.isin(low, list(top_ids)) if top_ids else np.zeros_like(low, bool)
    lake_polys = [shape(g) for g, v in raster_shapes(lake.astype(np.uint8), mask=lake, transform=t) if v == 1]
    lake_wgs = list(gpd.GeoSeries(lake_polys, crs=crs).to_crs(4326).buffer(0)) if lake_polys else []
    water = gj(list(river.geometry) + lake_wgs, 0.0001)
    roads = gpd.read_file(RAW / "osm_hay_river.gpkg", layer="roads").to_crs(4326)
    main, minor, road_lbl = road_layers(roads, view)
    lines = gpd.read_file(PROC / "corridor" / "corridor.gpkg", layer="channel_lines").to_crs(4326)
    chan_lbl = []
    for name, short in [("Hay River - East Channel", "East Channel"), ("Hay River - West Channel", "West Channel")]:
        g = lines[lines["name"] == name].geometry.union_all()
        if not g.is_empty:
            p = g.interpolate(0.45, normalized=True)
            chan_lbl.append([short, round(p.y, 5), round(p.x, 5), "water"])
    main_river = lines[lines["name"] == "Hay River"].geometry.union_all().intersection(box(*view))
    if not main_river.is_empty:
        p = main_river.interpolate(0.7, normalized=True)
        chan_lbl.append(["Hay River", round(p.y, 5), round(p.x, 5), "water"])

    # Layers, stages, flood: same scenes and rules as the judges' page (script 61).
    with rasterio.open(PROC / "corridor" / "river_pixels.tif") as src:
        rtf, rcrs = src.transform, src.crs
        km = src.read(1)
    jam = np.isfinite(km) & (km <= 15)
    p = fp.prepare()
    near = distance_transform_edt(~p["is_river"]) * abs(p["transform"].a) <= NEAR_WATER_M
    offset = float((PROC / "risk" / "hydat_datum_offset.txt").read_text())
    town = pd.read_csv(RAW / "hydat" / "07OB001_daily.csv", parse_dates=["date"]).set_index("date")["level_m"]
    lake_lv = pd.read_csv(RAW / "hydat" / "07OB002_daily.csv", parse_dates=["date"]).set_index("date")["level_m"]
    buildings = gpd.read_file(RAW / "osm_hay_river.gpkg", layer="buildings").to_crs(p["crs"])
    from rasterio.features import rasterize
    ids = rasterize(((g, i + 1) for i, g in enumerate(buildings.geometry)), out_shape=p["dem"].shape,
                    transform=p["transform"], fill=0, all_touched=True, dtype="int32")
    watch = json.loads((DATA / "watch.js").read_text(encoding="utf-8").split("window.HRFW.watch = ", 1)[1].rstrip().rstrip(";"))
    stage_names = {"before": "Before peak", "peak": "Peak", "after": "After peak"}
    years, stats = {}, {}
    for year, cfg in demo.YEARS.items():
        st_list = []
        for key, scene in cfg["stages"].items():
            day = pd.Timestamp(scene[:8])
            classes = rasterio.open(PROC / "ice_classes" / f"{scene}.tif").read(1)
            layers = class_layers(classes, rtf, rcrs, f"hay_{year}_{key}", view)
            seen = jam & (classes > 0)
            pct = {k: round(100 * float((classes[seen] == c).mean())) for c, k in CLASS_KEYS.items()}
            if key == "peak" and "peak_gauge_m" in cfg and day == pd.Timestamp(cfg["peak"]):
                gauge, mouth = cfg["peak_gauge_m"], cfg["peak_mouth_m"]
            else:
                gauge = float(town.get(day, np.nan)) + offset
                mouth = float(lake_lv.get(day, np.nan)) + LAKE_TO_CGVD2013
            if not np.isfinite(mouth):
                mouth = fp.MOUTH_TYPICAL
            flooded, _ = fp.flood_extent(p, gauge, mouth)
            flooded &= near
            if gauge < FLOOD_LEVEL_M:
                flooded[:] = False
            n_bldg = int((np.bincount(ids[flooded], minlength=len(buildings) + 1)[1:] > 0).sum())
            fpath = IMG / f"x_hay_{year}_{key}_flood.png"
            if to_png(flooded.astype(np.uint8), p["transform"], p["crs"], fpath, view, {1: FLOOD_RGBA}):
                layers["flood"] = f"data/img/{fpath.name}"
            rec = next((r for r in watch["years"][str(year)]["days"] if r["d"] == day.strftime("%m-%d")), None)
            stats[(year, key)] = {"pct": pct, "gauge": gauge, "bldg": n_bldg}
            st_list.append({"key": key, "label": stage_names[key], "date": day.strftime("%Y-%m-%d"),
                            "days_from_peak": (day - pd.Timestamp(cfg["peak"])).days, "scene": scene,
                            "layers": layers, "river_m": round(gauge, 1), "buildings": n_bldg, "pct": pct,
                            "prediction": hay_prediction(rec, day, watch)})
            print(f"  hay {year} {key}: {pct} river {gauge:.1f} m, {n_bldg} buildings, layers {sorted(layers)}")
        years[str(year)] = {"label": "2022: Flood year" if year == 2022 else "2023: No flood",
                            "role": cfg["role"], "peak": cfg["peak"], "stages": st_list}
    # What we see (max 3 short points for the current view).
    for year, y in years.items():
        other = "2023" if year == "2022" else "2022"
        for s in y["stages"]:
            o = next(x for x in years[other]["stages"] if x["key"] == s["key"])
            pts = [f"Rubble ice covers {s['pct']['rubble']}% of the river from the lake to town"
                   + (f"; {s['pct']['water']}% is open water." if s["pct"]["water"] >= 5 else ".")]
            if s["buildings"]:
                pts.append(f"Estimated flooding reaches about {s['buildings']} buildings, including Vale Island.")
            else:
                pts.append(f"The river stays in its banks ({s['river_m']:.1f} m at the town gauge).")
            pts.append(f"Same stage in {other}: {o['pct']['rubble']}% rubble ice"
                       + (f", about {o['buildings']} buildings flooded." if o["buildings"] else ", no flooding."))
            s["see"] = pts
    return {"name": site["name"], "where": site["where"], "view": view, "center": site["center"], "zoom": site["zoom"],
            "kind": "controls", "default_year": "2022", "years": years,
            "base": {"water": round_coords(water), "main": round_coords(main), "minor": round_coords(minor)},
            "labels": LABELS["hay"] + chan_lbl + road_lbl,
            "has_flood": True}


def hay_prediction(rec, day, watch):
    if rec is None:
        return {"level": None, "text": "No forecast for this day."}
    if rec.get("over"):
        return {"level": "Low", "confidence": "High", "chance": None,
                "reason": "Breakup is over: the ice has cleared and the river has dropped."}
    if not rec.get("status"):
        return {"level": None, "text": "No forecast yet."}
    img_age = None
    if rec.get("rcm") and rec["rcm"]["id"] in watch["ice"]:
        img_age = (day - pd.Timestamp(watch["ice"][rec["rcm"]["id"]]["time"][:10])).days
    conf = "Low" if rec["d"] < "04-01" else ("High" if img_age is not None and img_age <= 3 else "Medium")
    thr = watch["rcm_threshold"]
    rcm = rec.get("rcm")
    if rcm and rcm["melt"] and rcm["rubble"] >= thr:
        reason = f"RCM shows {rcm['rubble']}% rubble ice from the lake to town while the ice melts."
    elif rcm and rcm["water"] >= 50:
        reason = f"RCM shows the river near town mostly open ({rcm['water']}% open water): the ice is clearing."
    else:
        name, value, effect = max(rec["all"], key=lambda t: abs(t[2]))
        what = {"Great Slave Lake level": f"Great Slave Lake is {abs(value):.2f} m {'above' if value >= 0 else 'below'} normal",
                "Ice thickness": f"the ice is about {value:.0f} cm thick",
                "Upstream flow": f"upstream flow is {value:.0f} m³/s",
                "Rise in upstream flow (7 days)": f"upstream flow rose {value:.0f} m³/s in a week"}.get(name, name)
        reason = f"Biggest factor: {what}."
    return {"level": rec["level"], "confidence": conf, "chance": rec["chance"],
            "forecast_m": rec["median"], "reason": reason}


def blind_site(site_id):
    site = SITES[site_id]
    view = site["view"]
    water_g = gpd.read_file(BT / f"{site_id}_water.gpkg").to_crs(4326)
    water = gj(list(water_g.geometry.intersection(box(*view).buffer(0.05))), 0.0001)
    cache = RAW / f"osm_blind_{site_id}.json"
    w, s, e, n = view
    if not cache.exists():
        els = overpass(f"""[out:json][timeout:180];
            (way["highway"~"motorway|trunk|primary|secondary|tertiary|residential|unclassified"]({s - .02},{w - .02},{n + .02},{e + .02});
             way["natural"="coastline"]({s - .02},{w - .02},{n + .02},{e + .02}););
            out geom;""")
        cache.write_text(json.dumps(els))
    els = json.loads(cache.read_text())
    from shapely.geometry import LineString
    rows, coast = [], []
    for el in els:
        if "geometry" not in el:
            continue
        g = LineString([(q["lon"], q["lat"]) for q in el["geometry"]])
        t = el.get("tags", {})
        if t.get("natural") == "coastline":
            coast.append(g)
        else:
            rows.append({"highway": t.get("highway"), "name": t.get("name") or t.get("ref"), "geometry": g})
    roads = gpd.GeoDataFrame(rows, geometry="geometry", crs=4326) if rows else \
        gpd.GeoDataFrame({"highway": [], "name": []}, geometry=[], crs=4326)
    main, minor, road_lbl = road_layers(roads, view)
    coast_gj = gj(coast, 0.0001)

    # Locked predictions and image list (read only).
    tag = "albany" if site_id == "albany" else "hay_river_fort_simpson"
    preds = pd.read_csv(sorted(BT.glob(f"predictions_{tag}_*.csv"))[-1])
    imgs = pd.read_csv(sorted(BT.glob(f"prediction_images_{tag}_*.csv"))[-1], parse_dates=["time_utc"])
    preds, imgs = preds[preds["site"] == site_id], imgs[(imgs["site"] == site_id) & imgs["counts"]]
    with rasterio.open(PROC / "blind" / site_id / "river_pixels.tif") as src:
        river, rtf, rcrs = np.isfinite(src.read(1)), src.transform, src.crs
    years = {}
    for _, pr in preds.sort_values("year").iterrows():
        y = int(pr["year"])
        yi = imgs[imgs["year"] == y].sort_values("time_utc")
        melt = yi[yi["melt_started"]]
        cleared = melt[melt["open_water_pct"] >= 50]
        counted = melt if cleared.empty else melt[melt["time_utc"] < cleared["time_utc"].iloc[0]]
        picks = []
        pre = yi[~yi["melt_started"]]
        if len(pre):
            picks.append(("before", "Before melt", pre.iloc[-1]))
        if len(counted):
            picks.append(("breakup", "Breakup", counted.loc[counted["rubble_pct"].idxmax()]))
        if len(cleared):
            picks.append(("after", "Ice cleared", cleared.iloc[0]))
        elif len(melt) and (not len(counted) or melt.iloc[-1]["image"] != counted.loc[counted["rubble_pct"].idxmax()]["image"]):
            picks.append(("after", "Latest image", melt.iloc[-1]))
        st_list = []
        for key, lbl, im in picks:
            with rasterio.open(PROC / "blind" / site_id / "scenes" / f"{im['image']}.tif") as src:
                hh, hv, inc = src.read(1), src.read(2), src.read(3)
            hh = np.where(np.isfinite(hv), hh, np.nan)
            hh35 = hh + ANGLE_SLOPE * (inc - REF_ANGLE)
            ok = river & np.isfinite(hh35)
            codes = np.zeros(hh.shape, np.uint8)
            codes[ok] = 2
            codes[ok & (hh35 >= RUBBLE_DB)] = 3
            if im["melt_started"]:
                codes[ok & (hh35 < DARK_DB)] = 1
            layers = class_layers(codes, rtf, rcrs, f"{site_id}_{y}_{key}", view)
            see = [f"Rubble ice covers {im['rubble_pct']:.0f}% of the river near {site['community']}"
                   + (f"; {im['open_water_pct']:.0f}% is open water." if im["open_water_pct"] >= 5 else ".")]
            see.append({"before": "Winter ice cover, before melt: not counted in the prediction.",
                        "breakup": "Highest rubble ice before the ice cleared." + (
                            " Above the jam threshold (83.7%)." if im["rubble_pct"] >= 83.7 else ""),
                        "after": "The river is mostly open water: the ice has cleared." if lbl == "Ice cleared"
                        else "Latest image of the melt season."}[key])
            st_list.append({"key": key, "label": lbl, "date": im["time_utc"].strftime("%Y-%m-%d"),
                            "beam": im["beam"], "scene": im["image"], "layers": layers, "see": see[:3]})
        years[str(y)] = {"label": str(y), "stages": st_list, "separate": not bool(pr["main_scoring"]),
                         "prediction": {"level": pr["risk_level"], "confidence": pr["confidence"],
                                        "chance": None if pd.isna(pr["flood_likelihood_pct"]) else int(pr["flood_likelihood_pct"]),
                                        "reason": pr["explanation"], "outcome": "Not checked yet",
                                        "flags": pr["confidence_flags"]}}
        print(f"  {site_id} {y}: stages {[s['label'] + ' ' + s['date'] for s in st_list]}")
    default = next((k for k, v in years.items() if v["prediction"]["level"] in ("Critical", "Warning")), "2024")
    return {"name": site["name"], "where": site["where"], "view": view, "center": site["center"], "zoom": site["zoom"],
            "kind": "years", "default_year": default, "years": years,
            "base": {"water": round_coords(water), "main": round_coords(main), "minor": round_coords(minor),
                     "coast": round_coords(coast_gj)},
            "labels": LABELS[site_id] + road_lbl, "has_flood": False}


if __name__ == "__main__":
    IMG.mkdir(parents=True, exist_ok=True)
    demo = load("61_export_demo.py")
    fp = load("50_flood_projection.py")
    print("Hay River ...")
    out = {"hay": hay_site(demo, fp)}
    for sid in ["fort_simpson", "albany"]:
        print(f"{SITES[sid]['name']} ...")
        out[sid] = blind_site(sid)
    blind = json.loads((DATA / "blind.js").read_text(encoding="utf-8").split("window.HRFW.blind = ", 1)[1].rstrip().rstrip(";"))
    out["_meta"] = {"locks": blind["locks"], "rules": blind["rules"],
                    "colours": {"water": "#2F6FE4", "smooth": "#BFEFFF", "rubble": "#FF9F1C", "flood": "#FF5A36"}}
    text = json.dumps(out, separators=(",", ":"))
    (DATA / "explorer.js").write_text("window.HRFW = window.HRFW || {};\nwindow.HRFW.explorer = " + text + ";\n",
                                      encoding="utf-8")
    print(f"Saved web/data/explorer.js ({len(text) / 1e3:.0f} KB)")
