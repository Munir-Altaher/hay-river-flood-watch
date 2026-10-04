"""
Step 3a (new plan): Prepare every RCM scene over the river corridor.

1. River pixel map (made once): which pixels are river, how far each is from
   the lake (km, measured along the East Channel + main river) and which
   channel it is in. The river outline is shrunk by RIVER_EDGE_M so pixels
   that mix water/ice with the riverbank are left out.

2. For each 16M RCM zip in data/rcm/ (any sub-folder, including the new
   corridor downloads): calibrate, smooth speckle, put on the corridor map
   grid (10 m pixels), and keep only the corridor area. Three bands:
       1 HH (dB)   2 HV (dB)   3 incidence angle (degrees)
   The incidence angle is the satellite's viewing angle at that pixel; ice
   and water look brighter at steep angles and darker at shallow ones, so
   the classifier needs it.
   Scenes already processed are skipped, so this can be re-run as new
   downloads arrive.

Outputs:
    data/processed/corridor/river_pixels.tif     band 1 km from lake, band 2 channel code
    data/processed/corridor/scenes/<YYYYMMDD_HHMMSS>_<beam>.tif
    data/processed/corridor/scenes.csv           list of processed scenes

Run from the project folder:
    venv\\Scripts\\python.exe scripts\\30_corridor_scenes.py
"""

import re
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import shapely
from rasterio.features import geometry_mask
from rasterio.transform import from_origin

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rcm_utils import read_scene  # noqa: E402

PROJECT_DIR = Path(__file__).resolve().parent.parent
CORRIDOR_FILE = PROJECT_DIR / "data" / "processed" / "corridor" / "corridor.gpkg"
OUT_DIR = PROJECT_DIR / "data" / "processed" / "corridor"
SCENE_DIR = OUT_DIR / "scenes"
RIVER_PIXELS = OUT_DIR / "river_pixels.tif"

MAP_CRS = "EPSG:32611"
PIXEL = 10
RIVER_EDGE_M = 15          # shrink the river outline by this much (skip bank pixels)
BEAM_PREFIX = "16M"        # only the 16 m beams (same detail everywhere)
CHANNEL_CODES = {"Hay River": 1, "Hay River - East Channel": 1,
                 "Hay River - West Channel": 2, "Hay River - Rudd Channel": 3}
CHANNEL_NAMES = {1: "Main / East Channel", 2: "West Channel", 3: "Rudd Channel"}


def corridor_grid():
    corridor = gpd.read_file(CORRIDOR_FILE, layer="corridor")
    left, bottom, right, top = corridor.total_bounds
    left, top = np.floor(left / PIXEL) * PIXEL, np.ceil(top / PIXEL) * PIXEL
    width = int(np.ceil((right - left) / PIXEL))
    height = int(np.ceil((top - bottom) / PIXEL))
    transform = from_origin(left, top, PIXEL, PIXEL)
    inside = ~geometry_mask(corridor.geometry, (height, width), transform)
    return transform, (height, width), inside


def make_river_pixels(transform, shape):
    river = gpd.read_file(CORRIDOR_FILE, layer="river_mask").union_all().buffer(-RIVER_EDGE_M)
    centre = gpd.read_file(CORRIDOR_FILE, layer="centreline").geometry.iloc[0]
    lines = gpd.read_file(CORRIDOR_FILE, layer="channel_lines")
    is_river = ~geometry_mask([river], shape, transform)
    rows, cols = np.nonzero(is_river)
    xs, ys = rasterio.transform.xy(transform, rows, cols)
    pts = shapely.points(np.array(xs), np.array(ys))

    km = np.full(shape, np.nan, dtype=np.float32)
    km[rows, cols] = shapely.line_locate_point(centre, pts) / 1000

    # Nearest named channel line for each river pixel.
    codes = np.array([CHANNEL_CODES.get(n, 1) for n in lines["name"]])
    dists = np.stack([shapely.distance(g, pts) for g in lines.geometry])
    channel = np.zeros(shape, dtype=np.float32)
    channel[rows, cols] = codes[np.argmin(dists, axis=0)]

    profile = dict(driver="GTiff", width=shape[1], height=shape[0], count=2, dtype="float32",
                   crs=MAP_CRS, transform=transform, nodata=np.nan, compress="deflate")
    with rasterio.open(RIVER_PIXELS, "w", **profile) as dst:
        dst.write(km, 1)
        dst.write(channel, 2)
        dst.set_band_description(1, "km_from_lake")
        dst.set_band_description(2, "channel_code")
    counts = {CHANNEL_NAMES[c]: int((channel == c).sum()) for c in CHANNEL_NAMES}
    print(f"River pixels: {len(rows):,} ({counts}); km 0-{np.nanmax(km):.0f}")


if __name__ == "__main__":
    SCENE_DIR.mkdir(parents=True, exist_ok=True)
    transform, shape, inside = corridor_grid()
    print(f"Corridor grid: {shape[1]} x {shape[0]} pixels of {PIXEL} m")
    if not RIVER_PIXELS.exists():
        make_river_pixels(transform, shape)
    with rasterio.open(RIVER_PIXELS) as src:
        river_km = src.read(1)
    is_river = np.isfinite(river_km)

    zips = sorted((PROJECT_DIR / "data" / "rcm").rglob("*.zip"))
    profile = dict(driver="GTiff", width=shape[1], height=shape[0], count=3, dtype="float32",
                   crs=MAP_CRS, transform=transform, nodata=np.nan, compress="deflate",
                   tiled=True, predictor=3)
    for zip_path in zips:
        m = re.search(r"_(\w+?)_(\d{8}_\d{6})_", zip_path.name)
        if not m or not m.group(1).split("_")[-1].startswith(BEAM_PREFIX):
            continue
        beam, stamp = m.group(1).split("_")[-1], m.group(2)
        out_path = SCENE_DIR / f"{stamp}_{beam}.tif"
        if out_path.exists():
            continue
        print(f"{zip_path.parent.name}/{zip_path.name} ...", flush=True)
        hh, hv, inc, meta = read_scene(zip_path, transform, shape, MAP_CRS)
        for band in (hh, hv, inc):
            band[~inside] = np.nan
        seen = np.isfinite(hh) & is_river
        if not seen.any():
            print("    does not cover the river - skipped")
            continue
        with rasterio.open(out_path, "w", **profile) as dst:
            for i, (band, name) in enumerate([(hh, "HH_dB"), (hv, "HV_dB"), (inc, "incidence_deg")], 1):
                dst.write(band.astype(np.float32), i)
                dst.set_band_description(i, name)
            dst.update_tags(source_zip=zip_path.name, **meta)
        print(f"    -> {out_path.name}: river km {np.nanmin(river_km[seen]):.0f}-"
              f"{np.nanmax(river_km[seen]):.0f} visible, angle {np.nanmin(inc[seen]):.0f}-"
              f"{np.nanmax(inc[seen]):.0f} deg")

    # Rebuild the list of processed scenes from the files themselves.
    rows = []
    for tif in sorted(SCENE_DIR.glob("*.tif")):
        with rasterio.open(tif) as src:
            hh = src.read(1)
            tags = src.tags()
        seen = np.isfinite(hh) & is_river
        rows.append({"scene": tif.stem, "acquired_utc": tags.get("acquired_utc"),
                     "beam": tags.get("beam"), "pass": tags.get("pass"),
                     "source_zip": tags.get("source_zip"),
                     "km_min": round(float(np.nanmin(river_km[seen])), 1),
                     "km_max": round(float(np.nanmax(river_km[seen])), 1),
                     "river_pixels_seen": int(seen.sum())})
    pd.DataFrame(rows).to_csv(OUT_DIR / "scenes.csv", index=False)
    print(f"\n{len(rows)} corridor scenes ready in {SCENE_DIR}")
