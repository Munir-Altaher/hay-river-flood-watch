"""
Step 6: Download buildings, roads and place names from OpenStreetMap.

Uses the free Overpass API (a public service for querying OpenStreetMap).
Only the study-area box is sent. Run this once; the results are saved to
data/raw/osm_hay_river.gpkg with three layers:
    buildings  - building outlines
    roads      - roads and streets (with names where known)
    places     - named neighbourhoods/areas (e.g. Vale Island, Old Town)

Run from the project folder:
    venv\\Scripts\\python.exe scripts\\06_get_osm.py
"""

import time
from pathlib import Path

import geopandas as gpd
import requests
from shapely.geometry import LineString, Point, Polygon

PROJECT_DIR = Path(__file__).resolve().parent.parent
OUT_FILE = PROJECT_DIR / "data" / "raw" / "osm_hay_river.gpkg"

SOUTH, WEST, NORTH, EAST = 60.715, -115.95, 60.92, -115.60
# Public Overpass servers, tried in order (they are sometimes busy).
OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]

QUERY = f"""
[out:json][timeout:180];
(
  way["building"]({SOUTH},{WEST},{NORTH},{EAST});
  way["highway"]({SOUTH},{WEST},{NORTH},{EAST});
  node["place"]({SOUTH},{WEST},{NORTH},{EAST});
  way["place"]({SOUTH},{WEST},{NORTH},{EAST});
);
out geom;
"""

ROAD_TYPES = {"motorway", "trunk", "primary", "secondary", "tertiary", "unclassified",
              "residential", "service", "living_street", "track", "road"}


def download():
    """Try each server (twice) until one answers."""
    for attempt in range(2):
        for url in OVERPASS_URLS:
            try:
                print(f"  trying {url} ...")
                response = requests.post(url, data={"data": QUERY}, timeout=300,
                                         headers={"User-Agent": "hay-river-flood-watch (hackathon project)"})
                response.raise_for_status()
                return response.json()["elements"]
            except (requests.RequestException, ValueError) as error:
                print(f"    failed: {error}")
            time.sleep(10)
    raise SystemExit("All Overpass servers failed - try again in a few minutes.")


def coords(element):
    return [(p["lon"], p["lat"]) for p in element.get("geometry", [])]


if __name__ == "__main__":
    print("Asking OpenStreetMap (Overpass API) for buildings, roads and places ...")
    elements = download()
    print(f"  received {len(elements):,} map features")

    buildings, roads, places = [], [], []
    for el in elements:
        tags = el.get("tags", {})
        if el["type"] == "way" and "building" in tags:
            pts = coords(el)
            if len(pts) >= 4:
                buildings.append({"osm_id": el["id"], "building": tags["building"],
                                  "name": tags.get("name"),
                                  "addr_street": tags.get("addr:street"),
                                  "addr_housenumber": tags.get("addr:housenumber"),
                                  "geometry": Polygon(pts)})
        elif el["type"] == "way" and tags.get("highway") in ROAD_TYPES:
            pts = coords(el)
            if len(pts) >= 2:
                roads.append({"osm_id": el["id"], "highway": tags["highway"],
                              "name": tags.get("name") or tags.get("ref"),
                              "geometry": LineString(pts)})
        elif "place" in tags and tags.get("name"):
            if el["type"] == "node":
                geom = Point(el["lon"], el["lat"])
            else:
                pts = coords(el)
                geom = Polygon(pts).centroid if len(pts) >= 4 else None
            if geom is not None:
                places.append({"osm_id": el["id"], "place": tags["place"],
                               "name": tags["name"], "geometry": geom})

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    for layer, rows in [("buildings", buildings), ("roads", roads), ("places", places)]:
        gdf = gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")
        gdf.to_file(OUT_FILE, layer=layer)
        print(f"  {layer}: {len(gdf):,}")
    print(f"Saved to {OUT_FILE}")
