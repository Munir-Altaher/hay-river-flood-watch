"""
Step 9 (first-responder view): important places in Hay River and the river level
at which each one starts to flood.

Places (OpenStreetMap):
  * critical facilities: hospital, emergency measures / fire hall, RCMP, schools,
    community centre, airport, seaplane base, fuel stations
  * neighbourhoods: Vale Island, Old Town, New Town (buildings grouped by the
    nearest neighbourhood point) and K'atlodeeche First Nation lands (buildings
    inside the First Nation boundary)
  * evacuation routes: named main roads, and road bridges

Method: the flood-projection model (script 50, same water-surface shape and the
same display rule as the website: within 1.5 km of the river or lake) is run for
river levels at the town gauge from 164.0 to 172.0 m in 0.1 m steps, for a
typical lake and a high lake. For every 5 m pixel this gives the LOWEST gauge
level at which it floods. A place's "flood level" is the lowest level reached
anywhere on it (buildings: the building plus 10 m; points without a building:
30 m around the point; roads: the road plus 8 m, not counting where it crosses
the river; bridges: their approach roads, since the ground model has no bridge
decks). Neighbourhoods get the levels at which 10% and 50% of their buildings
flood. No place gets a level below 166.4 m, the lowest gauge level with
documented flooding in town (DOCUMENTED_FLOOR_M).

This is an estimate from elevation data and a simplified ice-jam water surface;
real floods also depend on where the jam forms.

Outputs: data/processed/flood_projection/first_flood_level_<mouth>.tif
         web/data/places.js

Run from the project folder (about 10 minutes):
    venv\\Scripts\\python.exe scripts\\63_places.py
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
from rasterio.features import rasterize
from scipy.ndimage import distance_transform_edt
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import linemerge, polygonize, unary_union

PROJECT_DIR = Path(__file__).resolve().parent.parent
PROC = PROJECT_DIR / "data" / "processed"
OSM = PROJECT_DIR / "data" / "raw" / "osm_hay_river.gpkg"
OUT_JS = PROJECT_DIR / "web" / "data" / "places.js"
LEVELS = np.round(np.arange(164.0, 172.01, 0.1), 1)
NEAR_WATER_M = 1500
NEVER = 999.0
# No flooding in the town has been documented below 166.4 m at the gauge (GNWT 2025
# flood history). At low river levels the elevation model overestimates (its water-
# surface shape was tuned to the extreme 2022 jam), so no place is given a flood level
# below this. The elevation model still decides the ORDER in which places flood.
DOCUMENTED_FLOOR_M = 166.4
BRIDGE_APPROACH_M = 150      # bridges are judged by their approach roads (the lidar removes bridge decks)
URLS = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter",
        "https://overpass.private.coffee/api/interpreter"]
BOX = "60.76,-115.92,60.89,-115.66"
NEIGHBOURHOODS = {"Vale Island": (-115.7670, 60.8546), "Old Town": (-115.7409, 60.8569),
                  "New Town": (-115.7817, 60.8144)}
MAIN_ROADS = {"trunk", "primary", "secondary", "tertiary"}
FACILITY_TAGS = [
    ("emergency", "yes", "Hospital"), ("amenity", "hospital", "Hospital"), ("amenity", "clinic", "Health centre"),
    ("amenity", "fire_station", "Emergency services"), ("amenity", "police", "Emergency services"),
    ("amenity", "school", "School"), ("amenity", "community_centre", "Community centre"),
    ("amenity", "townhall", "Town hall"), ("aeroway", "aerodrome", "Airport"), ("amenity", "fuel", "Fuel"),
]


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
                print("   ", u.split("/")[2], "failed:", str(e)[:60])
            time.sleep(10)
    raise SystemExit("Overpass failed - try again later")


def first_flood_levels(fp, p, mouth):
    """Lowest gauge level at which each pixel floods (NEVER if not by 172 m)."""
    path = PROC / "flood_projection" / f"first_flood_level_{mouth:.2f}.tif"
    if path.exists():
        return rasterio.open(path).read(1)
    near = distance_transform_edt(~p["is_river"]) * abs(p["transform"].a) <= NEAR_WATER_M
    first = np.full(p["dem"].shape, NEVER, dtype=np.float32)
    for lv in LEVELS:
        flooded, _ = fp.flood_extent(p, float(lv), mouth)
        new = flooded & near & (first == NEVER)
        first[new] = lv
    prof = p["profile"].copy()
    prof.update(dtype="float32", nodata=None, compress="deflate")
    with rasterio.open(path, "w", **prof) as dst:
        dst.write(first, 1)
    return first


def min_level(first, geoms, transform, exclude=None):
    out = []
    for g in geoms:
        m = rasterize([(g, 1)], out_shape=first.shape, transform=transform, all_touched=True).astype(bool)
        if exclude is not None:
            m &= ~exclude
        out.append(float(first[m].min()) if m.any() else NEVER)
    return out


if __name__ == "__main__":
    fp = load("50_flood_projection.py")
    print("Preparing the elevation model ...")
    p = fp.prepare()
    crs, transform = p["crs"], p["transform"]
    firsts = {}
    for mouth in fp.MOUTH_LEVELS:
        print(f"First-flood levels for river mouth at {mouth} m (81 river levels) ...")
        firsts[mouth] = first_flood_levels(fp, p, mouth)

    buildings = gpd.read_file(OSM, layer="buildings").to_crs(crs).reset_index(drop=True)
    roads = gpd.read_file(OSM, layer="roads").to_crs(crs)

    # --- Facilities ---
    els = overpass(f"""[out:json][timeout:180];
        (nwr["amenity"~"hospital|clinic|school|fire_station|police|townhall|community_centre|fuel"]({BOX});
         nwr["emergency"="yes"]({BOX}); nwr["aeroway"="aerodrome"]({BOX});
         way["highway"]["bridge"="yes"]({BOX}););
        out center tags;""")
    places = []
    for el in els:
        t = el.get("tags", {})
        c = el.get("center") or {"lat": el.get("lat"), "lon": el.get("lon")}
        if c["lat"] is None:
            continue
        if t.get("bridge") == "yes":
            if t.get("highway") in ("footway", "path", "cycleway", "track"):
                continue
            places.append({"name": f"{t.get('name') or 'Road'} bridge", "cat": "Evacuation route", "kind": "bridge",
                           "lat": c["lat"], "lon": c["lon"], "osm": el["id"]})
            continue
        cat = next((label for k, v, label in FACILITY_TAGS if t.get(k) == v), None)
        name = t.get("name")
        if cat is None or (not name and cat not in ("Community centre",)):
            continue
        places.append({"name": name or "Community centre", "cat": cat, "kind": "point",
                       "lat": c["lat"], "lon": c["lon"], "osm": el["id"]})
    fac = gpd.GeoDataFrame(places, geometry=gpd.points_from_xy([x["lon"] for x in places],
                                                               [x["lat"] for x in places]), crs=4326).to_crs(crs)
    fac = fac.drop_duplicates(subset=["name", "cat"])
    # Footprint: the building under the point (+10 m), else 30 m around the point; bridges: 30 m.
    hits = gpd.sjoin(fac[["geometry"]], buildings[["geometry"]], how="left", predicate="within")
    hits = hits[~hits.index.duplicated()]
    foot = []
    road_union = roads.geometry.union_all()
    for i, row in fac.iterrows():
        bi = hits.loc[i, "index_right"]
        if row["kind"] == "bridge":
            # The road on either side of the bridge (the deck itself is not in the ground model).
            foot.append(road_union.intersection(row.geometry.buffer(BRIDGE_APPROACH_M)).buffer(8))
        elif pd.notna(bi):
            foot.append(buildings.geometry[int(bi)].buffer(10))
        else:
            foot.append(row.geometry.buffer(30))

    # --- Neighbourhoods ---
    kfn_el = overpass(f"""[out:json][timeout:180];
        relation["boundary"="aboriginal_lands"]["name"="K'atlodeeche First Nation"]; out geom;""")
    kfn = None
    for rel in kfn_el:
        outer = [LineString([(q["lon"], q["lat"]) for q in m["geometry"]])
                 for m in rel.get("members", []) if m.get("role") == "outer" and "geometry" in m]
        if outer:
            kfn = gpd.GeoSeries([unary_union(list(polygonize(linemerge(outer))))], crs=4326).to_crs(crs).iloc[0]
    bc = buildings.centroid
    group = pd.Series(index=buildings.index, dtype=object)
    if kfn is not None:
        group[bc.within(kfn)] = "K'atlodeeche First Nation"
    pts = gpd.GeoSeries(gpd.points_from_xy([v[0] for v in NEIGHBOURHOODS.values()],
                                           [v[1] for v in NEIGHBOURHOODS.values()]), crs=4326).to_crs(crs)
    names = list(NEIGHBOURHOODS)
    d = np.stack([bc.distance(pt) for pt in pts])
    nearest = np.array(names)[d.argmin(axis=0)]
    free = group.isna() & (d.min(axis=0) <= 2500)
    group[free] = nearest[free.to_numpy()]

    out_places = []
    for mouth_key, mouth in [("typical", fp.MOUTH_LEVELS[0]), ("high", fp.MOUTH_LEVELS[1])]:
        fac[f"level_{mouth_key}"] = min_level(firsts[mouth], foot, transform, exclude=p["is_river"])
        bl = min_level(firsts[mouth], list(buildings.geometry.buffer(10)), transform)
        buildings[f"level_{mouth_key}"] = bl
    for _, r in fac.iterrows():
        ll = gpd.GeoSeries([r.geometry], crs=crs).to_crs(4326).iloc[0]
        out_places.append({"name": r["name"], "cat": r["cat"], "lat": round(ll.y, 5), "lon": round(ll.x, 5),
                           "level": {"typical": r["level_typical"], "high": r["level_high"]}})
    for g in ["Vale Island", "Old Town", "New Town", "K'atlodeeche First Nation"]:
        b = buildings[group == g]
        if b.empty:
            continue
        lv = {}
        for k in ["typical", "high"]:
            v = np.sort(b[f"level_{k}"].to_numpy())
            lv[k] = float(v[int(0.1 * (len(v) - 1))])
            lv[k + "_half"] = float(v[int(0.5 * (len(v) - 1))])
        ctr = gpd.GeoSeries([b.union_all().centroid], crs=crs).to_crs(4326).iloc[0]
        out_places.append({"name": g, "cat": "Neighbourhood", "lat": round(ctr.y, 5), "lon": round(ctr.x, 5),
                           "buildings": int(len(b)), "level": {"typical": lv["typical"], "high": lv["high"]},
                           "level_half": {"typical": lv["typical_half"], "high": lv["high_half"]}})

    # --- Evacuation routes: named main roads ---
    main = roads[roads["highway"].isin(MAIN_ROADS) & roads["name"].notna()]
    for name, g in main.groupby("name"):
        geom = g.geometry.union_all()
        lv, spot = {}, None
        for k, mouth in [("typical", fp.MOUTH_LEVELS[0]), ("high", fp.MOUTH_LEVELS[1])]:
            m = rasterize([(geom.buffer(8), 1)], out_shape=firsts[mouth].shape, transform=transform,
                          all_touched=True).astype(bool) & ~p["is_river"]     # not where it crosses the river
            vals = np.where(m, firsts[mouth], NEVER)
            lv[k] = float(vals.min())
            if k == "typical" or spot is None:
                rr, cc = np.unravel_index(np.argmin(vals), vals.shape)
                x, y = rasterio.transform.xy(transform, rr, cc)
                spot = gpd.GeoSeries([Point(x, y)], crs=crs).to_crs(4326).iloc[0]
        out_places.append({"name": name, "cat": "Evacuation route", "lat": round(spot.y, 5), "lon": round(spot.x, 5),
                           "length_km": round(geom.length / 1000, 1), "level": lv,
                           "note": "marker shows the lowest point on this road"})

    def tidy(v):
        return None if v >= NEVER else round(max(v, DOCUMENTED_FLOOR_M), 1)
    for pl in out_places:
        pl["model_level"] = {k: (None if v >= NEVER else round(v, 1)) for k, v in pl["level"].items()}
        pl["level"] = {k: tidy(v) for k, v in pl["level"].items()}
        if "level_half" in pl:
            pl["level_half"] = {k: tidy(v) for k, v in pl["level_half"].items()}
    OUT_JS.write_text("window.HRFW = window.HRFW || {};\nwindow.HRFW.places = "
                      + json.dumps({"places": out_places, "levels_checked": [164.0, 172.0],
                                    "documented_floor_m": DOCUMENTED_FLOOR_M}, separators=(",", ":"))
                      + ";\n", encoding="utf-8")
    print(f"\n{len(out_places)} places saved to {OUT_JS}")

    # --- Every building (houses etc.) with its flood level, for the map ---
    b4326 = buildings.to_crs(4326)
    feats = []
    for (_, row), geom in zip(buildings.iterrows(), b4326.geometry.simplify(0.000005)):
        if geom is None or geom.is_empty or geom.geom_type != "Polygon":
            continue
        feats.append({"c": [[round(x, 5), round(y, 5)] for x, y in geom.exterior.coords],
                      "t": row.get("building") if isinstance(row.get("building"), str) else "yes",
                      "n": row.get("name") if isinstance(row.get("name"), str) else None,
                      "lt": tidy(row["level_typical"]), "lh": tidy(row["level_high"])})
    (OUT_JS.parent / "buildings.js").write_text(
        "window.HRFW = window.HRFW || {};\nwindow.HRFW.buildings = " + json.dumps(feats, separators=(",", ":")) + ";\n",
        encoding="utf-8")
    print(f"{len(feats)} buildings saved to {OUT_JS.parent / 'buildings.js'} "
          f"({(OUT_JS.parent / 'buildings.js').stat().st_size / 1e3:.0f} KB)")
    for pl in sorted(out_places, key=lambda x: (x["level"]["typical"] or 999)):
        print(f"  {pl['cat']:18s} {pl['name'][:38]:38s} floods from {pl['level']['typical']} m "
              f"(typical lake) / {pl['level']['high']} m (high lake)")
