"""
Step 3: First, simplest water map - a brightness cut-off (threshold).

Water is smooth, so it reflects the radar signal away from the satellite and
looks very dark. Land, buildings and trees look brighter. So:

    water  =  HH brightness darker than a cut-off

The cut-off is picked automatically for each scene with "Otsu's method":
it looks at the histogram of brightness values (which usually has a dark
"water" hump and a bright "land" hump) and finds the dip between them.

Flooding = water in the flood scene that is NOT water in the reference scene
(so the lake and normal river channel are not counted as flood).

Outputs:
    data/processed/water/<scene>_water.tif   1 = water, 0 = dry, 255 = no data
    outputs/water_maps/<scene>.png           picture: radar | water | new water
    outputs/threshold_summary.csv            cut-off and flooded area per scene

Run from the project folder:
    venv\\Scripts\\python.exe scripts\\03_threshold_water.py
"""

from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # draw pictures to files, no pop-up windows
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import rasterio
from rasterio.warp import transform

PROJECT_DIR = Path(__file__).resolve().parent.parent
PROCESSED = PROJECT_DIR / "data" / "processed"
WATER_DIR = PROCESSED / "water"
PIC_DIR = PROJECT_DIR / "outputs" / "water_maps"

REFERENCE = PROCESSED / "reference_2022" / "20210417_012845_16M17.tif"

# Rough box around the town and Vale Island (lon/lat), used to zoom the
# pictures and to report how much of the town area is newly wet.
TOWN_BOX = (-115.84, 60.78, -115.72, 60.87)   # west, south, east, north

PIXEL_AREA_KM2 = 10 * 10 / 1e6


def otsu_threshold(values, bins=256):
    """Find the brightness that best splits the values into two groups."""
    hist, edges = np.histogram(values, bins=bins)
    centres = (edges[:-1] + edges[1:]) / 2
    weight_dark = np.cumsum(hist)
    weight_bright = weight_dark[-1] - weight_dark
    mean_dark = np.cumsum(hist * centres) / np.maximum(weight_dark, 1)
    mean_bright = ((hist * centres).sum() - np.cumsum(hist * centres)) / np.maximum(weight_bright, 1)
    between = weight_dark * weight_bright * (mean_dark - mean_bright) ** 2
    return float(centres[np.argmax(between)])


def water_map(hh_db):
    """Return (water array: 1/0/255, cut-off used)."""
    valid = np.isfinite(hh_db)
    cutoff = otsu_threshold(hh_db[valid])
    water = np.full(hh_db.shape, 255, dtype=np.uint8)
    water[valid] = (hh_db[valid] < cutoff).astype(np.uint8)
    return water, cutoff


def town_window(src):
    """Row/column ranges of the town box in the image."""
    xs, ys = transform("EPSG:4326", src.crs, TOWN_BOX[::2], TOWN_BOX[1::2])
    (r0, c0), (r1, c1) = src.index(xs[0], ys[1]), src.index(xs[1], ys[0])
    return slice(r0, r1), slice(c0, c1)


def save_tif(path, array, profile):
    path.parent.mkdir(parents=True, exist_ok=True)
    p = profile.copy()
    p.update(count=1, dtype="uint8", nodata=255)
    with rasterio.open(path, "w", **p) as dst:
        dst.write(array, 1)


if __name__ == "__main__":
    WATER_DIR.mkdir(parents=True, exist_ok=True)
    PIC_DIR.mkdir(parents=True, exist_ok=True)

    # Normal water extent from the reference scene.
    with rasterio.open(REFERENCE) as src:
        ref_water, ref_cutoff = water_map(src.read(1))
        save_tif(WATER_DIR / f"{REFERENCE.stem}_water.tif", ref_water, src.profile)
    print(f"Reference {REFERENCE.stem}: cut-off {ref_cutoff:.1f} dB")

    rows = []
    for tif in sorted((PROCESSED / "flood_2022").glob("*.tif")):
        with rasterio.open(tif) as src:
            hh = src.read(1)
            profile = src.profile
            rows_sl, cols_sl = town_window(src)

        water, cutoff = water_map(hh)
        save_tif(WATER_DIR / f"{tif.stem}_water.tif", water, profile)

        # New water: wet now, dry in the reference (both must have data).
        new_water = (water == 1) & (ref_water == 0)

        town_valid = water[rows_sl, cols_sl] != 255
        town_cover = 100 * town_valid.mean()
        row = {
            "scene": tif.stem,
            "cutoff_dB": round(cutoff, 1),
            "water_km2": round((water == 1).sum() * PIXEL_AREA_KM2, 2),
            "new_water_km2": round(new_water.sum() * PIXEL_AREA_KM2, 2),
            "town_box_covered_pct": round(town_cover, 0),
            "new_water_in_town_box_km2": round(new_water[rows_sl, cols_sl].sum() * PIXEL_AREA_KM2, 2),
        }
        rows.append(row)
        print(f"{tif.stem}: cut-off {cutoff:.1f} dB, new water {row['new_water_km2']} km2 "
              f"({row['new_water_in_town_box_km2']} km2 in town box, "
              f"town box {town_cover:.0f}% covered)")

        # Picture zoomed on the town: radar | water | new water.
        fig, axes = plt.subplots(1, 3, figsize=(18, 7))
        axes[0].imshow(hh[rows_sl, cols_sl], cmap="gray", vmin=-25, vmax=0)
        axes[0].set_title("Radar HH (dark = smooth / water)")
        w = water[rows_sl, cols_sl].astype(float)
        w[w == 255] = np.nan
        axes[1].imshow(w, cmap="Blues", vmin=0, vmax=1.2)
        axes[1].set_title(f"Water (HH < {cutoff:.1f} dB)")
        axes[2].imshow(hh[rows_sl, cols_sl], cmap="gray", vmin=-25, vmax=0)
        overlay = np.where(new_water[rows_sl, cols_sl], 1.0, np.nan)
        axes[2].imshow(overlay, cmap="autumn", alpha=0.8)
        axes[2].set_title("New water vs reference (red)")
        for ax in axes:
            ax.set_xticks([]); ax.set_yticks([])
        fig.suptitle(f"Hay River - {tif.stem}", fontsize=14)
        plt.tight_layout()
        plt.savefig(PIC_DIR / f"{tif.stem}.png", dpi=80)
        plt.close(fig)

    out_csv = PROJECT_DIR / "outputs" / "threshold_summary.csv"
    pd.DataFrame(rows).to_csv(out_csv, index=False)
    print(f"\nPictures in {PIC_DIR}\nSummary in {out_csv}")
