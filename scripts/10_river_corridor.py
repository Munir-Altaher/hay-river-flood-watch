"""
Step 1a (new plan): Build the Hay River corridor from OpenStreetMap.

Everything later (RCM ice mapping, the ice profile) needs to know where the
river is and how far each spot is from the mouth. This script downloads the
river from OpenStreetMap and builds:

  centreline   one line from Great Slave Lake (km 0) upstream along the
               East Channel and the main river, with distance in km
  km_marks     a point every 1 km along the centreline (for charts/labels)
  river_mask   the river's water area (banks to banks), clipped to the
               first CORRIDOR_KM km
  channel_lines  the named lines of the main river and each channel
  corridor     the river mask plus a margin, used to crop the RCM images

Saved to data/processed/corridor/corridor.gpkg (one layer each).

Why the East Channel? In town the river splits around Vale Island into the
East Channel (main channel) and the West and Rudd channels. Ice jams form in
all of them; we measure distance along the East Channel and label pixels in
the other channels with their own channel name.

Run from the project folder:
    venv\\Scripts\\python.exe scripts\\10_river_corridor.py
"""

import time
from pathlib import Path

import geopandas as gpd
import numpy as np
import requests
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import linemerge, polygonize, unary_union

PROJECT_DIR = Path(__file__).resolve().parent.parent
OUT_FILE = PROJECT_DIR / "data" / "processed" / "corridor" / "corridor.gpkg"

CORRIDOR_KM = 55          # how far upstream from the lake to go
MARGIN_M = 1500           # extra land around the river kept when cropping images
SIDE_CHANNEL_HALF_WIDTH_M = 25   # West/Rudd channels drawn ~50 m wide where OSM has no outline
MAP_CRS = "EPSG:32611"    # UTM zone 11N, metres - same grid as the earlier work
SEARCH_BOX = (60.40, -116.40, 60.92, -115.55)   # south, west, north, east

OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]


def overpass(query):
    """Run a query on the first Overpass server that answers."""
    for attempt in range(2):
        for url in OVERPASS_URLS:
            try:
                r = requests.post(url, data={"data": query}, timeout=300,
                                  headers={"User-Agent": "hay-river-flood-watch (hackathon project)"})
                r.raise_for_status()
                return r.json()["elements"]
            except (requests.RequestException, ValueError) as error:
                print(f"    {url} failed: {error}")
            time.sleep(10)
    raise SystemExit("All Overpass servers failed - try again in a few minutes.")


def line_of(element):
    return LineString([(p["lon"], p["lat"]) for p in element["geometry"]])


def polygon_of_relation(rel):
    """Assemble a multipolygon relation from its outer/inner member lines."""
    outer = [line_of(m) for m in rel["members"] if m.get("role") == "outer" and "geometry" in m]
    inner = [line_of(m) for m in rel["members"] if m.get("role") == "inner" and "geometry" in m]
    shell = unary_union(list(polygonize(linemerge(outer)))) if outer else None
    if shell is None or shell.is_empty:
        return None
    if inner:
        holes = unary_union(list(polygonize(linemerge(inner))))
        shell = shell.difference(holes)
    return shell


if __name__ == "__main__":
    s, w, n, e = SEARCH_BOX
    print("Downloading the Hay River and its channels from OpenStreetMap ...")
    lines = overpass(f"""[out:json][timeout:180];
        way["waterway"="river"]["name"~"^Hay River"]({s},{w},{n},{e}); out geom;""")
    print("Downloading river water areas ...")
    areas = overpass(f"""[out:json][timeout:180];
        (way["natural"="water"]["water"="river"]({s},{w},{n},{e});
         relation["natural"="water"]["water"="river"]({s},{w},{n},{e});
         way["waterway"="riverbank"]({s},{w},{n},{e}););
        out geom;""")

    # --- Centreline: East Channel + main river, oriented from the lake -------
    named = gpd.GeoDataFrame(
        [{"name": el["tags"]["name"], "geometry": line_of(el)} for el in lines],
        crs="EPSG:4326").to_crs(MAP_CRS)
    print("  channel lines found:", named["name"].value_counts().to_dict())
    main = named[named["name"].isin(["Hay River", "Hay River - East Channel"])]
    centre = linemerge(list(main.geometry))
    if centre.geom_type == "MultiLineString":
        # Join the pieces end to end if they don't quite touch.
        centre = max(centre.geoms, key=lambda g: g.length)
        print("  warning: channel and main river did not join; using the longest piece")
    # km 0 = the end nearest the lake = the northernmost end.
    start, end = Point(centre.coords[0]), Point(centre.coords[-1])
    if end.y > start.y:
        centre = LineString(centre.coords[::-1])
    print(f"  centreline length: {centre.length / 1000:.1f} km "
          f"(starts at the lake, runs upstream)")
    centre_km = LineString([centre.interpolate(d)
                            for d in np.arange(0, min(CORRIDOR_KM * 1000, centre.length), 50)])

    marks = gpd.GeoDataFrame(
        {"km": np.arange(0, CORRIDOR_KM + 1)},
        geometry=[centre.interpolate(k * 1000) for k in range(CORRIDOR_KM + 1)], crs=MAP_CRS)

    # --- River water area ------------------------------------------------------
    polys = []
    for el in areas:
        if el["type"] == "way" and len(el.get("geometry", [])) >= 4:
            polys.append(Polygon([(p["lon"], p["lat"]) for p in el["geometry"]]))
        elif el["type"] == "relation":
            geom = polygon_of_relation(el)
            if geom is not None:
                polys.append(geom)
    water = gpd.GeoDataFrame(geometry=polys, crs="EPSG:4326").to_crs(MAP_CRS)
    water["geometry"] = water.geometry.make_valid()
    water_all = water.union_all()

    # Keep only the river near our centreline, out to CORRIDOR_KM.
    reach = centre_km.buffer(1500)
    channels = named[named["name"] != "Hay River"].geometry.buffer(1500).union_all()
    keep_zone = reach.union(channels.intersection(centre_km.buffer(6000)))
    river = water_all.intersection(keep_zone)

    # OpenStreetMap has no water-area outline for parts of the West and Rudd
    # channels, only their centre lines. Fill those gaps by widening the lines.
    side = named[named["name"].isin(["Hay River - West Channel", "Hay River - Rudd Channel"])]
    river = river.union(side.geometry.buffer(SIDE_CHANNEL_HALF_WIDTH_M).union_all())

    # The channels are all connected, so the water area is one shape. Which
    # channel each pixel belongs to is worked out later, pixel by pixel
    # (nearest channel line), when the RCM images are cropped.
    pieces = gpd.GeoDataFrame(geometry=[river], crs=MAP_CRS).explode(index_parts=False)
    pieces = pieces[pieces.area > 500].reset_index(drop=True)
    pieces["area_km2"] = pieces.area / 1e6
    print(f"  river water area in corridor: {pieces['area_km2'].sum():.1f} km2 "
          f"in {len(pieces)} piece(s)")

    corridor = gpd.GeoDataFrame(geometry=[river.buffer(MARGIN_M)], crs=MAP_CRS)

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    gpd.GeoDataFrame({"name": ["Hay River (East Channel + main)"]},
                     geometry=[centre], crs=MAP_CRS).to_file(OUT_FILE, layer="centreline")
    marks.to_file(OUT_FILE, layer="km_marks")
    pieces.to_file(OUT_FILE, layer="river_mask")
    corridor.to_file(OUT_FILE, layer="corridor")
    named.to_file(OUT_FILE, layer="channel_lines")

    lonlat = corridor.to_crs("EPSG:4326").total_bounds
    print(f"  corridor box (lon/lat): {np.round(lonlat, 4).tolist()}")
    for k in [0, 5, 10, 13, 20, 30, 40, 50]:
        p = marks[marks.km == k].to_crs("EPSG:4326").geometry.iloc[0]
        print(f"  km {k:2d}: {p.y:.4f}, {p.x:.4f}")
    print(f"Saved to {OUT_FILE}")
