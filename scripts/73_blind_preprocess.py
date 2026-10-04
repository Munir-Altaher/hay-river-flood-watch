"""
Blind test, step 4: preprocess downloaded RCM scenes for a blind-test site.

Exactly the Hay River steps (scripts/rcm_utils.py, same settings as script 30):
calibrate to sigma nought with the scene's own gain table, 5x5 speckle
smoothing, warp through the scene's control points onto a 10 m grid (here the
site's local UTM grid), keep HH dB, HV dB and the viewing angle. Only the river
area is kept. No classification and no prediction happens here.

After a scene is saved and re-opened successfully, its raw zip is DELETED
(requested, to save disk space). The scene list keeps the zip name and size.

Output: data/processed/blind/<site>/scenes/<YYYYMMDD_HHMMSS>_<beam>.tif
        data/processed/blind/<site>/scenes.csv

Run from the project folder:
    venv\\Scripts\\python.exe scripts\\73_blind_preprocess.py <site>
"""

import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rcm_utils import read_scene  # noqa: E402

PROJECT_DIR = Path(__file__).resolve().parent.parent
WINDOW = 5                       # same speckle window as Hay River


if __name__ == "__main__":
    site = sys.argv[1]
    raw = PROJECT_DIR / "data" / "rcm" / "blind" / site
    base = PROJECT_DIR / "data" / "processed" / "blind" / site
    out_dir = base / "scenes"
    out_dir.mkdir(parents=True, exist_ok=True)
    with rasterio.open(base / "river_pixels.tif") as src:
        km = src.read(1)
        transform, crs, shape = src.transform, src.crs, km.shape
    is_river = np.isfinite(km)
    log_path = base / "scenes.csv"
    log = pd.read_csv(log_path) if log_path.exists() else pd.DataFrame()

    profile = dict(driver="GTiff", width=shape[1], height=shape[0], count=3, dtype="float32", crs=crs,
                   transform=transform, nodata=np.nan, compress="deflate", tiled=True, predictor=3)
    new_rows = []
    for zip_path in sorted(raw.glob("*.zip")):
        m = re.search(r"_([A-Z0-9]+)_(\d{8}_\d{6})_", zip_path.name)
        beam, stamp = m.group(1), m.group(2)
        out_path = out_dir / f"{stamp}_{beam}.tif"
        size_mb = zip_path.stat().st_size / 1e6
        print(f"{zip_path.name} ({size_mb:.0f} MB) ...", flush=True)
        try:
            hh, hv, inc, meta = read_scene(zip_path, transform, shape, crs, window=WINDOW)
        except Exception as e:
            print(f"    FAILED: {e} (zip kept)")
            continue
        for band in (hh, hv, inc):
            band[~is_river] = np.nan
        seen = int((np.isfinite(hh) & is_river).sum())
        with rasterio.open(out_path, "w", **profile) as dst:
            for i, (b, nm) in enumerate([(hh, "HH_dB"), (hv, "HV_dB"), (inc, "incidence_deg")], 1):
                dst.write(b.astype(np.float32), i)
                dst.set_band_description(i, nm)
            dst.update_tags(source_zip=zip_path.name, **meta)
        with rasterio.open(out_path) as chk:          # make sure it saved before deleting the zip
            ok = chk.read(1).shape == shape
        new_rows.append({"scene": out_path.stem, "source_zip": zip_path.name, "zip_mb": round(size_mb),
                         "beam": meta["beam"], "pass": meta["pass"], "acquired_utc": meta["acquired_utc"],
                         "pixel_spacing_m": meta["pixel_spacing_m"], "river_pixels_seen": seen,
                         "river_seen_pct": round(100 * seen / is_river.sum(), 1)})
        if ok:
            zip_path.unlink()
            print(f"    -> {out_path.name}: {100 * seen / is_river.sum():.0f}% of the river seen; zip deleted")
    if new_rows:
        log = pd.concat([log, pd.DataFrame(new_rows)], ignore_index=True).drop_duplicates("scene", keep="last")
        log.to_csv(log_path, index=False)
    print(f"{site}: {len(log)} scenes preprocessed in total")
