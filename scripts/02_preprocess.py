"""
Step 2: Turn each downloaded RCM zip into a clean, map-aligned image.

For every zip in data/rcm/<window>/ this script:
  1. Reads the HH and HV images straight out of the zip (no unzipping).
  2. Calibrates them: converts raw pixel numbers (DN) into radar brightness
     "sigma nought" using the gain table that comes with each scene:
         sigma0 = DN^2 / gain
  3. Smooths out "speckle" (the grainy salt-and-pepper noise all radar
     images have) with a small 5x5 averaging window.
  4. Lays the image onto a regular map grid (UTM zone 11N, 10 m pixels)
     cropped to the study area, so every scene lines up pixel-for-pixel.
  5. Converts brightness to decibels (dB), the usual radar scale. Water is
     very dark: roughly -18 dB or lower in HH.
  6. Saves a 2-band GeoTIFF (band 1 = HH dB, band 2 = HV dB) to
     data/processed/<window>/ and a summary table to outputs/scenes.csv.

Run from the project folder:
    venv\\Scripts\\python.exe scripts\\02_preprocess.py
"""

import re
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from rasterio.transform import from_origin
from rasterio.warp import reproject, transform_bounds, Resampling
from scipy.ndimage import uniform_filter

# --- Settings ---------------------------------------------------------------

PROJECT_DIR = Path(__file__).resolve().parent.parent
RAW_DIR = PROJECT_DIR / "data" / "rcm"
OUT_DIR = PROJECT_DIR / "data" / "processed"

# Study area corners in longitude/latitude. South edge moved from 60.75 to
# 60.715 to include the flood patches mapped by NRCan just south of town.
WEST, SOUTH, EAST, NORTH = -115.95, 60.715, -115.60, 60.92

MAP_CRS = "EPSG:32611"   # UTM zone 11N - a flat map grid measured in metres
PIXEL_SIZE = 10          # metres per output pixel
SPECKLE_WINDOW = 5       # size of the smoothing window (pixels)

# Build the output map grid once, so every scene uses exactly the same one.
left, bottom, right, top = transform_bounds("EPSG:4326", MAP_CRS,
                                            WEST, SOUTH, EAST, NORTH)
left, top = np.floor(left / PIXEL_SIZE) * PIXEL_SIZE, np.ceil(top / PIXEL_SIZE) * PIXEL_SIZE
GRID_WIDTH = int(np.ceil((right - left) / PIXEL_SIZE))
GRID_HEIGHT = int(np.ceil((top - bottom) / PIXEL_SIZE))
GRID_TRANSFORM = from_origin(left, top, PIXEL_SIZE, PIXEL_SIZE)


# --- Helper functions -------------------------------------------------------

def read_text(zf, name_ending):
    """Read a text file from inside the zip, found by the end of its name."""
    name = next(n for n in zf.namelist() if n.endswith(name_ending))
    return zf.read(name).decode()


def xml_value(xml, tag):
    """Pull the text between <tag ...> and </tag> from an XML string."""
    match = re.search(rf"<{tag}[^>]*>([^<]+)</{tag}>", xml)
    return match.group(1) if match else None


def gain_per_column(lut_xml, width):
    """
    The calibration table lists a gain for some image columns.
    It says which column the first value belongs to and how far apart the
    values are (this can be negative when the image is stored right-to-left).
    We fill in a gain for every column by interpolating between them.
    """
    gains = np.array(xml_value(lut_xml, "gains").split(), dtype=float)
    first = float(xml_value(lut_xml, "pixelFirstLutValue"))
    step = float(xml_value(lut_xml, "stepSize"))
    columns = first + step * np.arange(len(gains))
    order = np.argsort(columns)
    return np.interp(np.arange(width), columns[order], gains[order])


def calibrate(dn, gain):
    """Raw DN -> smoothed sigma0 (linear). Pixels with DN = 0 are 'no data'."""
    valid = dn > 0
    sigma0 = (dn.astype(np.float32) ** 2) / gain[np.newaxis, :].astype(np.float32)

    # Average over a small window, ignoring no-data pixels.
    sigma0[~valid] = 0
    total = uniform_filter(sigma0, SPECKLE_WINDOW)
    count = uniform_filter(valid.astype(np.float32), SPECKLE_WINDOW)
    with np.errstate(invalid="ignore", divide="ignore"):
        smooth = total / count
    smooth[~valid] = np.nan
    return smooth


def to_map_grid(image, gcps, gcp_crs):
    """Warp an image from satellite geometry onto our shared map grid."""
    out = np.full((GRID_HEIGHT, GRID_WIDTH), np.nan, dtype=np.float32)
    reproject(
        source=image, destination=out,
        gcps=gcps, src_crs=gcp_crs, src_nodata=np.nan,
        dst_transform=GRID_TRANSFORM, dst_crs=MAP_CRS, dst_nodata=np.nan,
        resampling=Resampling.bilinear,
        SRC_METHOD="GCP_TPS",   # bend the image smoothly through every control point
    )
    return out


def process_scene(zip_path, window):
    zf = zipfile.ZipFile(zip_path)
    product_xml = read_text(zf, "metadata/product.xml")
    info = {
        "window": window,
        "file": zip_path.name,
        "beam": xml_value(product_xml, "beamModeMnemonic"),
        "pass": xml_value(product_xml, "passDirection"),
        "acquired_utc": xml_value(product_xml, "rawDataStartTime"),
        "pixel_spacing_m": float(xml_value(product_xml, "sampledPixelSpacing")),
    }

    bands_db = []
    for pol in ["HH", "HV"]:
        tif = next(n for n in zf.namelist()
                   if "/imagery/" in n and n.endswith(f"_{pol}.tif"))
        with rasterio.open(f"/vsizip/{zip_path}/{tif}") as src:
            dn = src.read(1)
            gcps, gcp_crs = src.gcps
        gain = gain_per_column(read_text(zf, f"calibration/lutSigma_{pol}.xml"), dn.shape[1])
        sigma0 = calibrate(dn, gain)
        del dn
        on_map = to_map_grid(sigma0, gcps, gcp_crs)
        del sigma0
        with np.errstate(divide="ignore", invalid="ignore"):
            bands_db.append(10 * np.log10(on_map))

    hh_db, hv_db = bands_db
    info["study_area_covered_pct"] = round(100 * np.isfinite(hh_db).mean(), 1)
    info["median_HH_dB"] = round(float(np.nanmedian(hh_db)), 1) if np.isfinite(hh_db).any() else None

    # Name the output after its date/time and beam, e.g. 20220512_011316_16M7.tif
    stamp = re.search(r"_(\d{8}_\d{6})_", zip_path.name).group(1)
    out_path = OUT_DIR / window / f"{stamp}_{info['beam']}.tif"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    profile = dict(driver="GTiff", width=GRID_WIDTH, height=GRID_HEIGHT, count=2,
                   dtype="float32", crs=MAP_CRS, transform=GRID_TRANSFORM,
                   nodata=np.nan, compress="deflate")
    with rasterio.open(out_path, "w", **profile) as dst:
        dst.write(hh_db, 1)
        dst.write(hv_db, 2)
        dst.set_band_description(1, "HH_dB")
        dst.set_band_description(2, "HV_dB")
    info["output"] = str(out_path.relative_to(PROJECT_DIR))
    return info


# --- Main -------------------------------------------------------------------

if __name__ == "__main__":
    print(f"Output grid: {GRID_WIDTH} x {GRID_HEIGHT} pixels of {PIXEL_SIZE} m")
    rows = []
    for zip_path in sorted(RAW_DIR.glob("*/*.zip")):
        window = zip_path.parent.name
        print(f"[{window}] {zip_path.name} ...", flush=True)
        info = process_scene(zip_path, window)
        print(f"    -> {info['output']}  covers {info['study_area_covered_pct']}% "
              f"of study area, median HH {info['median_HH_dB']} dB")
        rows.append(info)

    table = pd.DataFrame(rows)
    out_csv = PROJECT_DIR / "outputs" / "scenes.csv"
    table.to_csv(out_csv, index=False)
    print(f"\nSummary saved to {out_csv}")
