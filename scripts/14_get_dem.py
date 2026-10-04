"""
Step 1e (new plan): Download ground-elevation maps (DEMs) from NRCan.

Two maps, both bare-earth "DTM" (ground surface with buildings and trees
removed), read straight from NRCan's cloud copies without downloading the
huge full files:

  dem_town_5m.tif      NRCan HRDEM lidar survey "NWT-Enterprise_Hwy_Hay_River_2020"
                       (1 m), averaged to 5 m pixels, over the town area.
                       Used for the flood-extent projection (part 4).
  dem_corridor_30m.tif NRCan MRDEM (30 m, all of Canada) over the whole river
                       corridor - coarser, for context upstream.

Both are put on the UTM 11N grid used everywhere else. Heights are metres
above sea level (Canadian Geodetic Vertical Datum 2013, CGVD2013).

Output: data/raw/dem/

Run from the project folder:
    venv\\Scripts\\python.exe scripts\\14_get_dem.py
"""

import os
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.transform import from_origin
from rasterio.warp import reproject, transform_bounds, Resampling

PROJECT_DIR = Path(__file__).resolve().parent.parent
OUT_DIR = PROJECT_DIR / "data" / "raw" / "dem"
CORRIDOR_FILE = PROJECT_DIR / "data" / "processed" / "corridor" / "corridor.gpkg"
MAP_CRS = "EPSG:32611"

LIDAR_DTM = ("https://canelevation-dem.s3.ca-central-1.amazonaws.com/hrdem-lidar/"
             "NWT-Enterprise_Hwy_Hay_River_2020-1m-dtm.tif")
MRDEM_DTM = "https://canelevation-dem.s3.ca-central-1.amazonaws.com/mrdem-30/mrdem-30-dtm.tif"

# Town area (same box as the earlier flood-mapping work), lon/lat.
TOWN_BOX = (-115.95, 60.715, -115.60, 60.92)

# Faster, quieter reading of cloud files.
os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
os.environ.setdefault("GDAL_HTTP_MULTIRANGE", "YES")


def make_grid(bounds_utm, pixel):
    left, bottom, right, top = bounds_utm
    left, top = np.floor(left / pixel) * pixel, np.ceil(top / pixel) * pixel
    width = int(np.ceil((right - left) / pixel))
    height = int(np.ceil((top - bottom) / pixel))
    return from_origin(left, top, pixel, pixel), width, height


def fetch(url, bounds_utm, pixel, out_path):
    transform, width, height = make_grid(bounds_utm, pixel)
    out = np.full((height, width), np.nan, dtype=np.float32)
    with rasterio.open("/vsicurl/" + url) as src:
        print(f"  source: {src.res[0]} m pixels, CRS EPSG:{src.crs.to_epsg()}")
        reproject(source=rasterio.band(src, 1), destination=out,
                  src_nodata=src.nodata, dst_nodata=np.nan,
                  dst_transform=transform, dst_crs=MAP_CRS,
                  resampling=Resampling.average)
        tags = src.tags()
    profile = dict(driver="GTiff", width=width, height=height, count=1, dtype="float32",
                   crs=MAP_CRS, transform=transform, nodata=np.nan, compress="deflate",
                   tiled=True)
    with rasterio.open(out_path, "w", **profile) as dst:
        dst.write(out, 1)
        dst.update_tags(source=url, **{k: v for k, v in tags.items() if "VERT" in k.upper()})
    valid = np.isfinite(out)
    print(f"  saved {out_path.name}: {width} x {height} pixels of {pixel} m, "
          f"{100 * valid.mean():.0f}% with data, heights {np.nanmin(out):.1f}-{np.nanmax(out):.1f} m")


if __name__ == "__main__":
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("Town lidar DTM (5 m) ...")
    town_utm = transform_bounds("EPSG:4326", MAP_CRS, *TOWN_BOX)
    fetch(LIDAR_DTM, town_utm, 5, OUT_DIR / "dem_town_5m.tif")

    print("Corridor MRDEM DTM (30 m) ...")
    corridor_utm = gpd.read_file(CORRIDOR_FILE, layer="corridor").total_bounds
    fetch(MRDEM_DTM, corridor_utm, 30, OUT_DIR / "dem_corridor_30m.tif")
    print(f"Saved to {OUT_DIR}")
