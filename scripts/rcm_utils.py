"""
Shared helpers for reading RCM GRD zips (used by the corridor scripts, 30+).

Same method as the earlier 02_preprocess.py: calibrate DN to sigma nought
with the scene's own gain table, smooth speckle with a small averaging
window, and warp from satellite geometry to a map grid through the scene's
ground control points.
"""

import re
import zipfile

import numpy as np
import rasterio
from rasterio.warp import reproject, Resampling
from scipy.ndimage import uniform_filter


def read_text(zf, name_ending):
    """Read a text file from inside the zip, found by the end of its name."""
    name = next(n for n in zf.namelist() if n.endswith(name_ending))
    return zf.read(name).decode()


def xml_value(xml, tag):
    match = re.search(rf"<{tag}[^>]*>([^<]+)</{tag}>", xml)
    return match.group(1) if match else None


def per_column(xml, width, values_tag, first_tag, step_tag):
    """
    RCM tables (calibration gains, incidence angles) give values for some
    image columns, starting at column `first` and `step` apart (negative when
    the image is stored right-to-left). Fill in a value for every column.
    """
    values = np.array(" ".join(re.findall(rf"<{values_tag}[^>]*>([^<]+)</{values_tag}>", xml)).split(),
                      dtype=float)
    first = float(xml_value(xml, first_tag))
    step = float(xml_value(xml, step_tag))
    columns = first + step * np.arange(len(values))
    order = np.argsort(columns)
    return np.interp(np.arange(width), columns[order], values[order])


def calibrate(dn, gain, window):
    """Raw DN -> speckle-smoothed sigma0 (linear). DN = 0 means no data."""
    valid = dn > 0
    sigma0 = (dn.astype(np.float32) ** 2) / gain[np.newaxis, :].astype(np.float32)
    sigma0[~valid] = 0
    total = uniform_filter(sigma0, window)
    count = uniform_filter(valid.astype(np.float32), window)
    with np.errstate(invalid="ignore", divide="ignore"):
        smooth = total / count
    smooth[~valid] = np.nan
    return smooth


def warp(image, gcps, gcp_crs, dst_transform, dst_shape, dst_crs):
    """Warp from satellite geometry onto a map grid, bending through every GCP."""
    out = np.full(dst_shape, np.nan, dtype=np.float32)
    reproject(source=image, destination=out, gcps=gcps, src_crs=gcp_crs, src_nodata=np.nan,
              dst_transform=dst_transform, dst_crs=dst_crs, dst_nodata=np.nan,
              resampling=Resampling.bilinear, SRC_METHOD="GCP_TPS")
    return out


def scene_metadata(zf):
    xml = read_text(zf, "metadata/product.xml")
    return {
        "beam": xml_value(xml, "beamModeMnemonic"),
        "pass": xml_value(xml, "passDirection"),
        "acquired_utc": xml_value(xml, "rawDataStartTime"),
        "pixel_spacing_m": float(xml_value(xml, "sampledPixelSpacing")),
    }


def read_scene(zip_path, dst_transform, dst_shape, dst_crs, window=5):
    """
    Return (hh_db, hv_db, incidence_deg, metadata) on the requested map grid.
    """
    zf = zipfile.ZipFile(zip_path)
    meta = scene_metadata(zf)
    out = {}
    gcps = gcp_crs = None
    width = None
    for pol in ["HH", "HV"]:
        tif = next(n for n in zf.namelist() if "/imagery/" in n and n.endswith(f"_{pol}.tif"))
        with rasterio.open(f"/vsizip/{zip_path}/{tif}") as src:
            dn = src.read(1)
            gcps, gcp_crs = src.gcps
        width = dn.shape[1]
        gain = per_column(read_text(zf, f"calibration/lutSigma_{pol}.xml"), width,
                          "gains", "pixelFirstLutValue", "stepSize")
        sigma0 = calibrate(dn, gain, window)
        if pol == "HH":
            shape = dn.shape
        del dn
        on_map = warp(sigma0, gcps, gcp_crs, dst_transform, dst_shape, dst_crs)
        del sigma0
        with np.errstate(divide="ignore", invalid="ignore"):
            out[pol] = 10 * np.log10(on_map)

    angles = per_column(read_text(zf, "calibration/incidenceAngles.xml"), width,
                        "angles", "pixelFirstAnglesValue", "stepSize")
    angle_img = np.broadcast_to(angles[np.newaxis, :].astype(np.float32), shape).copy()
    incidence = warp(angle_img, gcps, gcp_crs, dst_transform, dst_shape, dst_crs)
    incidence[~np.isfinite(out["HH"])] = np.nan
    return out["HH"], out["HV"], incidence, meta
