"""
Blind test, step 2: site geometry and jam zones (river geometry only).

Jam-zone rule (the same for every site, derived from Hay River's training zone):
  * Community extent along the river = from the 5th to the 95th percentile of the
    community's OpenStreetMap buildings, measured as distance along the river
    centre line (so a few outlying buildings do not stretch it).
  * Downstream end = the river mouth (where the river meets a lake or the sea)
    if it is within 5 km downstream of the community; otherwise 5 km downstream
    of the community's downstream edge.
  * Upstream end = 5 km upstream of the community's upstream edge, on EVERY river
    that flows past the community (both rivers at a confluence).
  * All water between those ends is included: every channel, around every island,
    as long as it is part of the connected river network (separate small creeks,
    under MIN_ZONE_PART_KM2, are left out).
  Check on Hay River: buildings run from km 0.6 to km 10.4 above Great Slave Lake;
  the mouth (km 0) is within 5 km, so the rule gives km 0 to 15.4, matching the
  km 0-15 zone the model was trained with.
  No information about past floods is used.

Also builds, for each site, the same "river pixel" map as Hay River (10 m grid in
the local UTM zone): distance along the river, which river, and in/out of jam zone.

Outputs: data/processed/blind/<site>/river_pixels.tif (bands: km, river id, jam zone)
         data/processed/blind/<site>/site_info.json, jam_zone.gpkg

Run from the project folder:
    venv\\Scripts\\python.exe scripts\\71_blind_sites_setup.py
"""

import json
import time
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
import requests
import shapely
from rasterio.features import geometry_mask
from rasterio.transform import from_origin
from shapely.geometry import LineString, Point
from shapely.ops import linemerge

PROJECT_DIR = Path(__file__).resolve().parent.parent
BLIND = PROJECT_DIR / "outputs" / "blind_test"
OUT = PROJECT_DIR / "data" / "processed" / "blind"
PIXEL = 10
EDGE_KM = 5.0
MIN_ZONE_PART_KM2 = 0.2      # zone water must be part of a connected river body at least this big
URLS = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter",
        "https://overpass.private.coffee/api/interpreter"]

SITES = {
    "fort_simpson": {
        "crs": "EPSG:32610", "box": (-121.8, 61.70, -120.9, 62.05),
        "rivers": {"Mackenzie": "Deh-Cho / Mackenzie River", "Liard": "Liard River"},
        "main": "Mackenzie", "mouth": None,
        "communities": {"Fort Simpson": (-121.3543, 61.8631)},
    },
    "albany": {
        "crs": "EPSG:32617", "box": (-82.2, 52.05, -81.3, 52.45),
        "rivers": {"Albany": "Albany River"},
        "main": "Albany", "mouth": "coast",
        "communities": {"Fort Albany": (-81.6825, 52.213), "Kashechewan": (-81.6394, 52.2935)},
    },
}


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


def line(el):
    return LineString([(p["lon"], p["lat"]) for p in el["geometry"]])


if __name__ == "__main__":
    for site, s in SITES.items():
        print(f"\n===== {site}")
        w, so, e, n = s["box"]
        bb = f"{so - 0.3},{w - 0.3},{n + 0.3},{e + 0.3}"
        names = "|".join(s["rivers"].values()).replace("/", "\\/")
        els = overpass(f"""[out:json][timeout:180];
            (way["waterway"="river"]["name"~"^({names})$"]({bb}); way["natural"="coastline"]({so},{w},{n},{e}););
            out geom;""")
        crs = s["crs"]
        lines = {k: [] for k in s["rivers"]}
        coast = []
        for el in els:
            t = el.get("tags", {})
            if t.get("natural") == "coastline":
                coast.append(line(el))
            for k, full in s["rivers"].items():
                if t.get("name") == full:
                    lines[k].append(line(el))
        centre = {}
        for k, ls in lines.items():
            g = gpd.GeoSeries(ls, crs=4326).to_crs(crs)
            merged = linemerge(list(g))
            if merged.geom_type == "MultiLineString":
                merged = max(merged.geoms, key=lambda x: x.length)
            centre[k] = merged
            print(f"  {k} centre line: {merged.length / 1000:.0f} km")

        water = gpd.read_file(BLIND / f"{site}_water.gpkg").to_crs(crs).union_all()
        comm = {c: gpd.GeoSeries([Point(*xy)], crs=4326).to_crs(crs).iloc[0] for c, xy in s["communities"].items()}

        # Buildings near each community (within 4 km of its centre point).
        bl = []
        for c, (lon, lat) in s["communities"].items():
            els_b = overpass(f"""[out:json][timeout:180];
                way["building"](around:4000,{lat},{lon}); out center;""")
            pts = [Point(el["center"]["lon"], el["center"]["lat"]) for el in els_b if "center" in el]
            bl.append((c, gpd.GeoSeries(pts, crs=4326).to_crs(crs)))
            print(f"  {c}: {len(pts)} buildings in OpenStreetMap within 4 km")

        main = centre[s["main"]]
        # Direction: distance along the main line, measured from its DOWNSTREAM end.
        if s["mouth"] == "coast":
            cl = gpd.GeoSeries(coast, crs=4326).to_crs(crs).union_all()
            ends = [Point(main.coords[0]), Point(main.coords[-1])]
            mouth_end = min(ends, key=lambda p: p.distance(cl))
            if mouth_end.equals(ends[-1]):
                main = LineString(main.coords[::-1])
            mouth_km = 0.0
            mouth_pt = Point(main.coords[0])
            print(f"  river mouth at the coast: {mouth_pt.distance(cl):.0f} m from mapped coastline")
        else:
            mouth_km = None
            # Mackenzie flows north-west: the downstream end is the northern end.
            if Point(main.coords[-1]).y > Point(main.coords[0]).y:
                main = LineString(main.coords[::-1])
        centre[s["main"]] = main

        # Community extent along the main river.
        km_all = []
        for c, pts in bl:
            km = shapely.line_locate_point(main, pts.values) / 1000
            lo, hi = np.percentile(km, [5, 95])
            km_all.append((c, lo, hi))
            print(f"  {c}: buildings from km {lo:.1f} to km {hi:.1f} along the {s['main']}")
        down_edge = min(lo for _, lo, _ in km_all)
        up_edge = max(hi for _, _, hi in km_all)
        start = mouth_km if (mouth_km is not None and down_edge - mouth_km <= EDGE_KM) else max(0.0, down_edge - EDGE_KM)
        end = up_edge + EDGE_KM
        print(f"  jam zone on the {s['main']}: km {start:.1f} to km {end:.1f}"
              f" ({'starts at the mouth' if start == mouth_km else 'starts 5 km below the community'})")

        # Other rivers at a confluence: from the confluence up to 5 km above the community.
        extra = {}
        for k, ln in centre.items():
            if k == s["main"]:
                continue
            conf = ln.interpolate(ln.project(main.interpolate(main.project(ln.centroid))))
            # Orient the tributary so km 0 is where it meets the main river.
            near_end = min([Point(ln.coords[0]), Point(ln.coords[-1])], key=lambda p: p.distance(main))
            if near_end.equals(Point(ln.coords[-1])):
                ln = LineString(ln.coords[::-1])
            centre[k] = ln
            conf_pt = Point(ln.coords[0])
            kms = []
            for c, pts in bl:
                kms += list(shapely.line_locate_point(ln, pts.values[pts.distance(ln).values < 3000]) / 1000)
            hi = np.percentile(kms, 95) if kms else 0.0
            extra[k] = (0.0, hi + EDGE_KM)
            print(f"  {k}: meets the {s['main']} at km {main.project(conf_pt) / 1000:.1f}; "
                  f"jam zone on the {k}: km 0 to {hi + EDGE_KM:.1f} from the confluence")

        # --- River pixel map (10 m grid, local UTM) ---
        corridor = gpd.read_file(BLIND / f"{site}_corridor.gpkg").to_crs(crs)
        l, b, r_, t = corridor.total_bounds
        l, t = np.floor(l / PIXEL) * PIXEL, np.ceil(t / PIXEL) * PIXEL
        width, height = int(np.ceil((r_ - l) / PIXEL)), int(np.ceil((t - b) / PIXEL))
        transform = from_origin(l, t, PIXEL, PIXEL)
        is_water = ~geometry_mask([water.buffer(-15)], (height, width), transform)
        rows, cols = np.nonzero(is_water)
        xs, ys = rasterio.transform.xy(transform, rows, cols)
        pts = shapely.points(np.array(xs), np.array(ys))
        river_names = list(centre)
        dists = np.stack([shapely.distance(centre[k], pts) for k in river_names])
        which = np.argmin(dists, axis=0)
        km = np.empty(len(rows), dtype=np.float32)
        for i, k in enumerate(river_names):
            sel = which == i
            km[sel] = shapely.line_locate_point(centre[k], pts[sel]) / 1000
        zone = np.zeros(len(rows), dtype=bool)
        for i, k in enumerate(river_names):
            lo, hi = (start, end) if k == s["main"] else extra[k]
            zone |= (which == i) & (km >= lo) & (km <= hi)
        band_km = np.full((height, width), np.nan, np.float32)
        band_riv = np.zeros((height, width), np.float32)
        band_zone = np.zeros((height, width), np.float32)
        band_km[rows, cols] = km
        band_riv[rows, cols] = which + 1
        band_zone[rows, cols] = zone
        # Keep only zone water connected to the main river network: drop small separate
        # creeks that happen to sit at the right distance along the river.
        from scipy.ndimage import label as label_parts
        parts, _ = label_parts(band_zone == 1, structure=np.ones((3, 3)))
        sizes = np.bincount(parts.ravel()) * PIXEL * PIXEL / 1e6
        keep = sizes >= MIN_ZONE_PART_KM2
        keep[0] = False
        dropped = int(((sizes < MIN_ZONE_PART_KM2) & (np.arange(len(sizes)) > 0)).sum())
        band_zone = keep[parts].astype(np.float32)
        zone = band_zone[rows, cols] == 1
        print(f"  dropped {dropped} small separate water bodies from the zone")
        d = OUT / site
        d.mkdir(parents=True, exist_ok=True)
        prof = dict(driver="GTiff", width=width, height=height, count=3, dtype="float32", crs=crs,
                    transform=transform, nodata=np.nan, compress="deflate")
        with rasterio.open(d / "river_pixels.tif", "w", **prof) as dst:
            dst.write(band_km, 1); dst.write(band_riv, 2); dst.write(band_zone, 3)
            for i, nm in enumerate(["km_along_river", "river_id", "jam_zone"], 1):
                dst.set_band_description(i, nm)

        # Geometry description of the zone (for the explanation).
        zpix = zone.sum()
        zone_poly = gpd.GeoSeries([water], crs=crs)
        widths = []
        for k_ in np.arange(start, end, 1.0):
            sl = (which == river_names.index(s["main"])) & (km >= k_) & (km < k_ + 1)
            widths.append(sl.sum() * PIXEL * PIXEL / 1000)          # m of width per 1 km of river
        holes = sum(len(p.interiors) for p in (water.geoms if water.geom_type == "MultiPolygon" else [water]))
        info = {"site": site, "crs": crs, "main_river": s["main"], "zone_main_km": [round(start, 1), round(end, 1)],
                "zone_other_rivers_km": {k: [round(a, 1), round(b_, 1)] for k, (a, b_) in extra.items()},
                "community_km": {c: [round(lo, 1), round(hi, 1)] for c, lo, hi in km_all},
                "zone_water_km2": round(zpix * PIXEL * PIXEL / 1e6, 1),
                "main_width_m_in_zone": {"min": round(min(widths)), "median": round(float(np.median(widths))),
                                         "max": round(max(widths))},
                "islands_in_water_area": int(holes), "grid": [width, height, PIXEL]}
        (d / "site_info.json").write_text(json.dumps(info, indent=1))
        print("  ", json.dumps(info))
