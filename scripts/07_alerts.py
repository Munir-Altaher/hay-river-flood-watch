"""
Step 7: Turn a flood map into plain-language alerts.

For each flood scene this script:
  1. Cleans the flood map: removes tiny specks of "flood" smaller than
     MIN_FLOOD_PATCH_M2 (these are usually radar noise, not real flooding).
  2. Finds buildings with flooding on or right next to them (at least
     MIN_FLOOD_PIXELS flood pixels within BUILDING_BUFFER_M metres).
     These two settings were tightened after the first run flagged
     hundreds of buildings from scattered noise even before the flood.
  3. Measures how much of each street runs through flooded areas.
  4. Names the area (Vale Island, Old Town, ...) and nearest street for each
     affected building.
  5. Writes an alert message, a map picture, and GIS files of the affected
     buildings/roads.

Outputs (in outputs/alerts/):
    <scene>.txt                       the alert message
    <scene>.png                       map of flooding + affected buildings
    <scene>_buildings.geojson         affected buildings (open in QGIS)
    <scene>_roads.geojson             flooded road sections
    alert_timeline.csv                one row per scene - how things changed

Run from the project folder (all flood scenes):
    venv\\Scripts\\python.exe scripts\\07_alerts.py
or for one scene:
    venv\\Scripts\\python.exe scripts\\07_alerts.py 20220512_011316_16M7
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path

import geopandas as gpd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import rasterio
from rasterio.features import rasterize, shapes
from scipy.ndimage import label as find_patches
from shapely.geometry import shape

PROJECT_DIR = Path(__file__).resolve().parent.parent
FLOOD_MAP_DIR = PROJECT_DIR / "data" / "processed" / "flood_maps"
OSM_FILE = PROJECT_DIR / "data" / "raw" / "osm_hay_river.gpkg"
OUT_DIR = PROJECT_DIR / "outputs" / "alerts"

MIN_FLOOD_PATCH_M2 = 2000    # ignore flood patches smaller than this (20 pixels)
BUILDING_BUFFER_M = 10       # flooding this close to a building counts...
MIN_FLOOD_PIXELS = 3         # ...if at least this many flood pixels (300 m2) are there
STREET_SEARCH_M = 80         # how far to look for the nearest named street
AREA_SEARCH_M = 1500         # how far to look for the nearest named area
MIN_ROAD_FLOOD_M = 30        # only report streets with at least this much flooded
UTC_TO_LOCAL = timedelta(hours=-6)   # Hay River in May = Mountain Daylight Time

FLOOD, NO_DATA = 1, 255
TOWN_BOX = (-115.84, 60.74, -115.72, 60.87)   # west, south, east, north (for the map)


def clean_flood(flood_map):
    """Keep only flood patches at least MIN_FLOOD_PATCH_M2 in size."""
    flooded = flood_map == FLOOD
    patches, _ = find_patches(flooded, structure=np.ones((3, 3)))
    sizes = np.bincount(patches.ravel())
    min_pixels = MIN_FLOOD_PATCH_M2 / 100
    keep = sizes >= min_pixels
    keep[0] = False
    return keep[patches]


def scene_time(stem):
    """'20220512_011316_16M7' -> (UTC datetime, local datetime)."""
    utc = datetime.strptime(stem[:15], "%Y%m%d_%H%M%S")
    return utc, utc + UTC_TO_LOCAL


def load_osm(crs):
    buildings = gpd.read_file(OSM_FILE, layer="buildings").to_crs(crs)
    roads = gpd.read_file(OSM_FILE, layer="roads").to_crs(crs)
    places = gpd.read_file(OSM_FILE, layer="places").to_crs(crs)
    # Use neighbourhoods and Vale Island - not the whole town ("Hay River"), and not
    # the tiny river islets ("Island A".."Island D"), which would mislabel buildings
    # that merely happen to be closest to them.
    places = places[(places["place"] != "town") &
                    ~places["name"].str.fullmatch(r"Island [A-Z]")]
    buildings = buildings.reset_index(drop=True)

    # Name the nearest street and area for every building, once.
    named = roads[roads["name"].notna()][["name", "geometry"]]
    near_street = gpd.sjoin_nearest(buildings[["geometry"]], named, how="left",
                                    max_distance=STREET_SEARCH_M)
    near_street = near_street[~near_street.index.duplicated()]
    buildings["street"] = near_street["name"].fillna(buildings["addr_street"]).fillna("unnamed road")
    near_area = gpd.sjoin_nearest(buildings[["geometry"]], places[["name", "geometry"]],
                                  how="left", max_distance=AREA_SEARCH_M)
    near_area = near_area[~near_area.index.duplicated()]
    buildings["area"] = near_area["name"].fillna("Hay River (other areas)")
    return buildings, roads


def check_buildings(buildings, flooded, visible, grid):
    """Count flood pixels and visible pixels around each building."""
    zones = buildings.geometry.buffer(BUILDING_BUFFER_M)
    ids = rasterize(((geom, i + 1) for i, geom in enumerate(zones)), out_shape=grid.shape,
                    transform=grid.transform, fill=0, all_touched=True, dtype="int32")
    n = len(buildings) + 1
    flood_px = np.bincount(ids[flooded], minlength=n)[1:]
    visible_px = np.bincount(ids[visible], minlength=n)[1:]
    out = buildings.copy()
    out["flood_pixels"] = flood_px
    out["visible"] = visible_px > 0
    out["affected"] = flood_px >= MIN_FLOOD_PIXELS
    return out


def flooded_roads(roads, flooded, grid):
    """Cut roads to the parts that run through flood patches."""
    polys = [shape(geom) for geom, value in
             shapes(flooded.astype(np.uint8), mask=flooded, transform=grid.transform) if value == 1]
    if not polys:
        return roads.iloc[0:0].assign(flooded_m=[])
    flood_area = gpd.GeoDataFrame(geometry=polys, crs=grid.crs).union_all()
    cut = roads.copy()
    cut["geometry"] = roads.geometry.intersection(flood_area)
    cut = cut[~cut.geometry.is_empty]
    cut["flooded_m"] = cut.geometry.length
    return cut


def write_alert(stem, bld, road_cut, flooded_km2, visible_pct):
    utc, local = scene_time(stem)
    affected = bld[bld["affected"]]
    n_visible = int(bld["visible"].sum())
    n_hidden = len(bld) - n_visible

    if len(affected) >= 10:
        level = "FLOOD WARNING"
    elif len(affected) >= 1:
        level = "FLOOD ADVISORY"
    else:
        level = "NO FLOODED BUILDINGS DETECTED"

    lines = [
        f"{level} - Hay River, NWT",
        f"Satellite radar image: {local:%A %B %d, %Y at %I:%M %p} local time "
        f"({utc:%Y-%m-%d %H:%M} UTC)",
        "",
        f"About {flooded_km2:.1f} km2 of flooding was detected outside the normal river channel.",
        f"{len(affected)} of the {n_visible} buildings visible in this image may have "
        f"water on or next to them.",
    ]
    if n_hidden:
        lines.append(f"({n_hidden} buildings were outside this image and could not be checked.)")

    if len(affected):
        lines += ["", "Areas affected:"]
        for area, count in affected["area"].value_counts().items():
            lines.append(f"  - {area}: {count} building{'s' if count != 1 else ''}")
        on_named = affected[affected["street"] != "unnamed road"]
        lines += ["", "Streets with the most affected buildings:"]
        for street, count in on_named["street"].value_counts().head(10).items():
            lines.append(f"  - {street}: {count}")
        unnamed = len(affected) - len(on_named)
        if unnamed:
            lines.append(f"  - (plus {unnamed} near roads without a name on the map)")

    named_roads = road_cut[road_cut["name"].notna()]
    by_street = named_roads.groupby("name")["flooded_m"].sum().sort_values(ascending=False)
    by_street = by_street[by_street >= MIN_ROAD_FLOOD_M]
    if len(by_street):
        lines += ["", "Roads with water on them (may be impassable):"]
        for street, metres in by_street.head(10).items():
            lines.append(f"  - {street}: about {metres:,.0f} m")

    if len(affected):
        lines += ["", "What to do: if you are in these areas, move to higher ground, avoid driving "
                      "through water, and follow instructions from the Town of Hay River and "
                      "NWT emergency officials."]
    lines += ["", "This is an automated estimate from satellite radar and can miss flooding or "
                  "flag dry areas. Always follow official emergency instructions."]
    return "\n".join(lines), level, len(affected), by_street


def save_map(path, stem, flooded, flood_map, bld, roads, grid, level):
    from rasterio.warp import transform
    xs, ys = transform("EPSG:4326", grid.crs, TOWN_BOX[::2], TOWN_BOX[1::2])
    fig, ax = plt.subplots(figsize=(11, 13))
    ext = [grid.bounds.left, grid.bounds.right, grid.bounds.bottom, grid.bounds.top]
    background = np.full(grid.shape, np.nan)
    background[flood_map == 2] = 0          # normal water
    background[flood_map == NO_DATA] = 1    # outside image
    ax.imshow(background, extent=ext, cmap=matplotlib.colors.ListedColormap(["#9ecae1", "#dddddd"]),
              vmin=0, vmax=1, interpolation="nearest")
    ax.imshow(np.where(flooded, 1.0, np.nan), extent=ext, cmap="autumn", alpha=0.6,
              interpolation="nearest")
    roads.plot(ax=ax, color="#555555", linewidth=0.6)
    bld[~bld["affected"]].plot(ax=ax, color="#888888")
    if bld["affected"].any():
        bld[bld["affected"]].plot(ax=ax, color="darkred", edgecolor="black", linewidth=0.4)
    ax.set_xlim(xs[0], xs[1]); ax.set_ylim(ys[0], ys[1])
    ax.set_xticks([]); ax.set_yticks([])
    _, local = scene_time(stem)
    ax.set_title(f"{level}\n{local:%b %d %Y %I:%M %p} local - red = flooding, dark red = "
                 f"affected buildings,\nblue = normal river, grey = outside image", fontsize=11)
    plt.tight_layout()
    plt.savefig(path, dpi=90)
    plt.close(fig)


if __name__ == "__main__":
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    wanted = sys.argv[1:]
    maps = sorted(FLOOD_MAP_DIR.glob("*_flood.tif"))
    if wanted:
        maps = [m for m in maps if m.stem.replace("_flood", "") in wanted]

    grid = rasterio.open(maps[0])
    buildings, roads = load_osm(grid.crs)
    print(f"Loaded {len(buildings):,} buildings and {len(roads):,} road sections")

    timeline = []
    for map_path in maps:
        stem = map_path.stem.replace("_flood", "")
        with rasterio.open(map_path) as src:
            flood_map = src.read(1)
        flooded = clean_flood(flood_map)
        visible = flood_map != NO_DATA
        flooded_km2 = flooded.sum() * 100 / 1e6

        bld = check_buildings(buildings, flooded, visible, grid)
        road_cut = flooded_roads(roads, flooded, grid)
        text, level, n_affected, by_street = write_alert(stem, bld, road_cut, flooded_km2,
                                                         100 * visible.mean())

        (OUT_DIR / f"{stem}.txt").write_text(text, encoding="utf-8")
        cols = ["osm_id", "building", "street", "area", "flood_pixels", "geometry"]
        bld[bld["affected"]][cols].to_crs("EPSG:4326").to_file(
            OUT_DIR / f"{stem}_buildings.geojson", driver="GeoJSON")
        road_cut[["osm_id", "name", "highway", "flooded_m", "geometry"]].to_crs("EPSG:4326").to_file(
            OUT_DIR / f"{stem}_roads.geojson", driver="GeoJSON")
        save_map(OUT_DIR / f"{stem}.png", stem, flooded, flood_map, bld, roads, grid, level)

        utc, local = scene_time(stem)
        timeline.append({"scene": stem, "local_time": f"{local:%Y-%m-%d %H:%M}", "alert": level,
                         "buildings_visible": int(bld["visible"].sum()),
                         "buildings_affected": n_affected,
                         "flood_km2": round(flooded_km2, 2),
                         "streets_with_water": len(by_street)})
        print(f"{stem}: {level} - {n_affected} buildings affected "
              f"({int(bld['visible'].sum())} visible), {flooded_km2:.2f} km2 flooding")

    pd.DataFrame(timeline).to_csv(OUT_DIR / "alert_timeline.csv", index=False)
    print(f"\nAlerts, maps and GIS files in {OUT_DIR}")
