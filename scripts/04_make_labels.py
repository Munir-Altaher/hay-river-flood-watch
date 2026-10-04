"""
Step 4: Turn flood polygons (shapes) into label images on our map grid.

Inputs:
  - NRCan EGS flood product (May 14, 2022, from a Capella radar image):
      class 1 = permanent water (normal river / lake)
      class 2 = open-water flood
    Only valid inside the Capella image footprint.
  - Your hand-drawn polygons, data/labels/hand_labels.gpkg (optional), with an
    integer field "label":  1 = flooded,  0 = dry (definitely not flooded).
    Hand labels win wherever they overlap the NRCan shapes.

Outputs (all on the same 10 m grid as the radar images):
  data/processed/labels/permanent_water.tif   1 = normal water, 0 = not
      NRCan class 1 inside the Capella footprint; outside it, we fall back
      to water seen in the reference scene.
  data/processed/labels/training_labels.tif
      0 = dry, 1 = flood, 2 = permanent water, 255 = unknown (not labelled)
  data/processed/labels/label_source.tif
      where each label came from: 0 = none, 1 = NRCan, 2 = hand-drawn

It also prepares files for hand-labelling in QGIS (see docs/hand_labeling_guide.md):
  data/labels/qgis/flood_20220512_view.tif   colour picture of the May 12 scene
  data/labels/qgis/egs_20220514.gpkg         NRCan shapes in map coordinates
  data/labels/hand_labels.gpkg               empty layer ready to draw in
                                             (only created if it doesn't exist)

Run from the project folder:
    venv\\Scripts\\python.exe scripts\\04_make_labels.py
"""

from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.features import rasterize

PROJECT_DIR = Path(__file__).resolve().parent.parent
PROCESSED = PROJECT_DIR / "data" / "processed"
LABEL_DIR = PROJECT_DIR / "data" / "labels"
EGS_DIR = LABEL_DIR / "Flood_CAN_NT_Hay_20220514_182929"
EGS_FLOOD = EGS_DIR / "Flood_CAN_NT_Hay_20220514_182929.shp"
EGS_FOOTPRINT = EGS_DIR / "Footprint_CAN_NT_Hay_20220514_182929.shp"
HAND_LABELS = LABEL_DIR / "hand_labels.gpkg"

REFERENCE = PROCESSED / "reference_2022" / "20210417_012845_16M17.tif"
# Scenes to make colour pictures of for hand-labelling. Both are from May 12;
# the 14:21 one also covers the east side of town that the 01:13 one misses.
LABEL_SCENES = {
    "flood_20220512_view.tif": PROCESSED / "flood_2022" / "20220512_011316_16M7.tif",
    "flood_20220512_1421_view.tif": PROCESSED / "flood_2022" / "20220512_142109_16M4.tif",
}
REF_WATER_DB = -16.0   # reference pixels darker than this count as water

OUT_DIR = PROCESSED / "labels"
QGIS_DIR = LABEL_DIR / "qgis"

DRY, FLOOD, PERMANENT, UNKNOWN = 0, 1, 2, 255


def burn(shapes, values, grid):
    """Paint shapes onto a blank image of the grid; 0 where there's no shape."""
    pairs = [(geom, int(v)) for geom, v in zip(shapes, values) if geom is not None]
    if not pairs:
        return np.zeros(grid.shape, dtype=np.uint8)
    return rasterize(pairs, out_shape=grid.shape, transform=grid.transform,
                     fill=0, dtype=np.uint8)


def save(path, array, grid, nodata=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    profile = grid.profile.copy()
    profile.update(count=1, dtype="uint8", nodata=nodata, compress="deflate")
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(array, 1)


def to_byte(values, low, high):
    """Stretch values between low and high to 1..255 (0 = no data)."""
    scaled = np.clip((values - low) / (high - low), 0, 1) * 254 + 1
    return np.where(np.isfinite(values), scaled, 0).astype(np.uint8)


if __name__ == "__main__":
    grid = rasterio.open(REFERENCE)   # every processed image shares this grid

    # --- NRCan shapes -------------------------------------------------------
    egs = gpd.read_file(EGS_FLOOD).to_crs(grid.crs)
    footprint = gpd.read_file(EGS_FOOTPRINT).to_crs(grid.crs)
    egs_class = burn(egs.geometry, egs["class"], grid)
    inside = burn(footprint.geometry, [1] * len(footprint), grid) == 1

    # --- Permanent (normal) water -------------------------------------------
    ref_hh = grid.read(1)
    ref_water = np.isfinite(ref_hh) & (ref_hh < REF_WATER_DB)
    permanent = np.where(inside, egs_class == 1, ref_water).astype(np.uint8)
    save(OUT_DIR / "permanent_water.tif", permanent, grid)

    # --- Training labels ----------------------------------------------------
    labels = np.full(grid.shape, UNKNOWN, dtype=np.uint8)
    labels[inside] = DRY
    labels[inside & (egs_class == 2)] = FLOOD
    labels[inside & (egs_class == 1)] = PERMANENT

    # Where each label came from: 0 = none, 1 = NRCan, 2 = hand-drawn.
    source = np.where(inside, 1, 0).astype(np.uint8)

    if HAND_LABELS.exists():
        hand = gpd.read_file(HAND_LABELS)
        hand = hand[hand.geometry.notna() & hand["label"].isin([0, 1])]
        if len(hand):
            hand = hand.to_crs(grid.crs)
            # burn() uses 0 for "no shape", so shift labels by 1 while painting.
            hand["geometry"] = hand.geometry.make_valid()   # fix self-crossing outlines
            painted = burn(hand.geometry, hand["label"] + 1, grid)
            labels[painted == 1] = DRY
            labels[painted == 2] = FLOOD
            source[painted > 0] = 2
        print(f"Hand labels: {(hand['label'] == 1).sum()} flood shapes, "
              f"{(hand['label'] == 0).sum()} dry shapes")
    else:
        print("No hand labels yet (data/labels/hand_labels.gpkg) - using NRCan only.")

    save(OUT_DIR / "training_labels.tif", labels, grid, nodata=UNKNOWN)
    save(OUT_DIR / "label_source.tif", source, grid)
    km2 = lambda n: n * 100 / 1e6
    print(f"Labelled pixels: dry {km2((labels == DRY).sum()):.1f} km2, "
          f"flood {km2((labels == FLOOD).sum()):.2f} km2, "
          f"permanent water {km2((labels == PERMANENT).sum()):.1f} km2")

    # --- Files for drawing labels in QGIS -----------------------------------
    QGIS_DIR.mkdir(parents=True, exist_ok=True)
    profile = grid.profile.copy()
    profile.update(count=3, dtype="uint8", nodata=0, compress="deflate", photometric="RGB")
    for view_name, scene in LABEL_SCENES.items():
        with rasterio.open(scene) as src:
            hh, hv = src.read(1), src.read(2)
        change = hh - ref_hh
        # Red = HH brightness, green = HV brightness, blue = got darker since reference.
        # Open water shows up dark; newly darkened ground shows up blue.
        rgb = np.stack([to_byte(hh, -25, 0), to_byte(hv, -32, -8), to_byte(-change, -6, 10)])
        rgb[:, ~np.isfinite(hh)] = 0
        with rasterio.open(QGIS_DIR / view_name, "w", **profile) as dst:
            dst.write(rgb)

    egs[["class", "geometry"]].to_file(QGIS_DIR / "egs_20220514.gpkg", layer="egs_flood")

    if not HAND_LABELS.exists():
        empty = gpd.GeoDataFrame({"label": np.array([], dtype="int32"),
                                  "note": np.array([], dtype="str")},
                                 geometry=gpd.GeoSeries([], crs=grid.crs))
        empty.to_file(HAND_LABELS, layer="hand_labels", geometry_type="Polygon")
        print(f"Created empty drawing layer: {HAND_LABELS}")

    print(f"Label images in {OUT_DIR}\nQGIS files in {QGIS_DIR}")
